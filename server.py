"""
RetroPad - servidor que transforma celulares em controles para o RetroPie.

Serve uma página de controle (static/index.html) e recebe o estado dos botões
por WebSocket. Para cada jogador (1 ou 2) cria um gamepad virtual via uinput,
que aparece no sistema como um controle USB Xbox 360.

Também oferece o modo "touchpad": um mouse e um teclado virtuais (uinput), usados
pelo celular como trackpad + teclado nativo.
"""
import hmac
import json
import os
import threading
import time

from evdev import AbsInfo, UInput, ecodes as e
from flask import Flask, request, send_from_directory
from flask_sock import Sock

import api
import inputmap
import stream
import tunnel
from config import settings

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

PIN = settings.pin          # PIN do controle (separado do PIN de admin)
HOST = settings.host
PORT = settings.port

# Botões do gamepad virtual (layout Xbox 360/XInput: A embaixo, B à direita, X em cima, Y à esquerda).
BUTTONS = {
    "a": e.BTN_SOUTH, "b": e.BTN_EAST, "x": e.BTN_NORTH, "y": e.BTN_WEST,
    "l": e.BTN_TL, "r": e.BTN_TR,        # L1 / R1
    "l2": e.BTN_TL2, "r2": e.BTN_TR2,    # gatilhos digitais
    "select": e.BTN_SELECT, "start": e.BTN_START,
    "l3": e.BTN_THUMBL, "r3": e.BTN_THUMBR,
    "mode": e.BTN_MODE,                  # Hotkey / Menu
}
# Analógicos enviados pelo celular, de -1.0 a 1.0.
AXES = {"x": e.ABS_X, "y": e.ABS_Y, "rx": e.ABS_RX, "ry": e.ABS_RY}
AXIS_MAX = 32767
MAX_REL = 200          # maior deslocamento aceito por mensagem de mouse
MAX_TEXT = 200         # maior trecho de texto aceito por mensagem

app = Flask(__name__)
sock = Sock(app)
api.init_app(app, settings)   # gerenciador de ROMs: /admin e /api/*
if settings.ngrok:
    tunnel.install_guard(app, settings)
# Limite de tentativas de PIN do controle (separado do limite do admin).
ctrl_limiter = api.PinLimiter(settings.max_attempts, settings.lock_seconds)


@app.after_request
def mark_response(resp):
    # O service worker só guarda respostas com esta marca (ignora a página de aviso do ngrok).
    resp.headers["X-RetroPad"] = "1"
    return resp

lock = threading.Lock()
pads = {}     # jogador -> UInput
owners = {}   # jogador -> id da conexão WebSocket que o controla
state = {}    # jogador -> {"buttons": set(), "hat": (x, y), "axes": {nome: valor}}
touchpad = {}  # "mouse" / "kbd" -> UInput (criados na primeira vez que alguém usa)
streamer = stream.Streamer(settings)   # captura da tela, só roda com espectadores


def _abs(lo, hi):
    return AbsInfo(value=0, min=lo, max=hi, fuzz=0, flat=0, resolution=0)


def get_pad(player):
    """Cria o gamepad virtual do jogador na primeira vez. Chamar com o lock preso."""
    if player not in pads:
        caps = {
            e.EV_KEY: list(BUTTONS.values()),
            e.EV_ABS: [
                (e.ABS_HAT0X, _abs(-1, 1)), (e.ABS_HAT0Y, _abs(-1, 1)),
                (e.ABS_X, _abs(-32768, 32767)), (e.ABS_Y, _abs(-32768, 32767)),
                (e.ABS_RX, _abs(-32768, 32767)), (e.ABS_RY, _abs(-32768, 32767)),
                (e.ABS_Z, _abs(0, 255)), (e.ABS_RZ, _abs(0, 255)),
            ],
        }
        # VID/PID de Xbox 360 para o RetroArch reconhecer pelo autoconfig.
        pads[player] = UInput(caps, name=f"RetroPad P{player}", vendor=0x045E, product=0x028E, version=0x0110)
        state[player] = {"buttons": set(), "hat": (0, 0), "axes": {}}
    return pads[player]


def get_mouse():
    """Mouse virtual. Chamar com o lock preso."""
    if "mouse" not in touchpad:
        caps = {
            e.EV_KEY: list(inputmap.MOUSE_BUTTONS.values()),
            e.EV_REL: [e.REL_X, e.REL_Y, e.REL_WHEEL, e.REL_HWHEEL],
        }
        touchpad["mouse"] = UInput(caps, name="RetroPad Mouse", vendor=0x1209, product=0x0001, version=0x0100)
    return touchpad["mouse"]


def get_keyboard():
    """Teclado virtual. Chamar com o lock preso."""
    if "kbd" not in touchpad:
        caps = {e.EV_KEY: inputmap.all_keyboard_codes()}
        touchpad["kbd"] = UInput(caps, name="RetroPad Teclado", vendor=0x1209, product=0x0002, version=0x0100)
    return touchpad["kbd"]


def apply_state(player, buttons, hat, axes=None):
    """Envia só o que mudou desde o último estado do gamepad, depois um SYN."""
    with lock:
        pad = get_pad(player)
        cur = state[player]
        new_buttons = {b for b in buttons if b in BUTTONS}
        for name in cur["buttons"] ^ new_buttons:
            pad.write(e.EV_KEY, BUTTONS[name], 1 if name in new_buttons else 0)
        if hat != cur["hat"]:
            pad.write(e.EV_ABS, e.ABS_HAT0X, hat[0])
            pad.write(e.EV_ABS, e.ABS_HAT0Y, hat[1])
        if axes is not None:
            for name, code in AXES.items():
                value = int(max(-1.0, min(1.0, float(axes.get(name, 0)))) * AXIS_MAX)
                if value != cur["axes"].get(name, 0):
                    pad.write(e.EV_ABS, code, value)
                    cur["axes"][name] = value
        pad.syn()
        cur["buttons"] = new_buttons
        cur["hat"] = hat


def release(player):
    """Solta todos os botões e analógicos do jogador (usado ao desconectar)."""
    apply_state(player, [], (0, 0), {})


def _clamp(value, limit):
    return max(-limit, min(limit, int(value)))


def mouse_move(dx, dy):
    with lock:
        m = get_mouse()
        if dx:
            m.write(e.EV_REL, e.REL_X, _clamp(dx, MAX_REL))
        if dy:
            m.write(e.EV_REL, e.REL_Y, _clamp(dy, MAX_REL))
        m.syn()


def mouse_scroll(v, h=0):
    with lock:
        m = get_mouse()
        if v:
            m.write(e.EV_REL, e.REL_WHEEL, _clamp(v, 20))
        if h:
            m.write(e.EV_REL, e.REL_HWHEEL, _clamp(h, 20))
        m.syn()


def mouse_button(name, down):
    code = inputmap.MOUSE_BUTTONS.get(name)
    if code is None:
        return
    with lock:
        m = get_mouse()
        m.write(e.EV_KEY, code, 1 if down else 0)
        m.syn()


def _tap(kb, code, mods):
    """Aperta e solta uma tecla, com os modificadores indicados segurados."""
    for mod in mods:
        kb.write(e.EV_KEY, mod, 1)
    kb.write(e.EV_KEY, code, 1)
    kb.write(e.EV_KEY, code, 0)
    for mod in reversed(mods):
        kb.write(e.EV_KEY, mod, 0)
    kb.syn()


def _mod_codes(names):
    return [inputmap.MODIFIERS[n] for n in names if n in inputmap.MODIFIERS]


def key_tap(name, mods=()):
    code = inputmap.NAMED_KEYS.get(name)
    if code is None:
        return
    with lock:
        _tap(get_keyboard(), code, _mod_codes(mods))


def type_text(back, text, mods=()):
    """Apaga `back` caracteres e digita `text`. Caracteres sem tecla no layout US são ignorados."""
    mods = _mod_codes(mods)
    with lock:
        kb = get_keyboard()
        for _ in range(max(0, min(int(back), MAX_TEXT))):
            _tap(kb, e.KEY_BACKSPACE, [])
        for ch in text[:MAX_TEXT]:
            found = inputmap.char_to_key(ch)
            if found is None:
                continue
            code, shift = found
            _tap(kb, code, mods + ([e.KEY_LEFTSHIFT] if shift and e.KEY_LEFTSHIFT not in mods else []))


# Uma rota para cada função. Todas as do controle servem a mesma página, que lê o endereço
# para saber qual função abrir; assim o link (ou o atalho do app instalado) já cai na função certa.
CONTROL_ROUTES = ("/", "/gamepad", "/mouse", "/tela", "/config")
ROMS_ROUTES = ("/roms", "/roms/<system>", "/admin")     # /admin continua valendo como apelido


def _control_page(**_):
    return send_from_directory(STATIC_DIR, "index.html")


def _roms_page(**_):
    return send_from_directory(STATIC_DIR, "admin.html")


for _path in CONTROL_ROUTES:
    app.add_url_rule(_path, endpoint="control" + _path.replace("/", "_"), view_func=_control_page)
for _path in ROMS_ROUTES:
    app.add_url_rule(_path, endpoint="roms" + _path.replace("/", "_").replace("<", "").replace(">", ""), view_func=_roms_page)


@app.route("/sw.js")
def service_worker():
    # Na raiz, para o service worker poder controlar "/" e "/admin". Sem cache, para atualizar logo.
    resp = send_from_directory(STATIC_DIR, "sw.js", mimetype="text/javascript")
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["Service-Worker-Allowed"] = "/"
    return resp


class _SafeSock:
    """Envolve o socket do WebSocket: todo envio vira sendall sob lock.

    A biblioteca usa `send` (que pode gravar só parte de um quadro grande) e escreve de mais de uma
    thread (o vídeo e o eco do fechamento). Sem isso, um celular lento recebe bytes embaralhados.
    """
    def __init__(self, sock, lock):
        self._sock, self._lock, self._closed = sock, lock, False

    def send(self, data):
        with self._lock:
            if self._closed:
                return len(data)        # o fechamento já foi enviado: nada pode vir depois dele
            self._sock.sendall(data)
            if data and data[0] & 0x0F == 0x8:   # opcode 8 = frame de fechamento
                self._closed = True
        return len(data)

    def __getattr__(self, name):
        return getattr(self._sock, name)


@sock.route("/ws")
def controller(ws):
    conn_id = id(ws)
    player = None      # número do jogador (modo gamepad)
    mode = None        # "gamepad" ou "touchpad"
    held = set()       # botões do mouse segurados por esta conexão
    send_lock = threading.RLock()  # texto e quadros de vídeo saem de threads diferentes
    ws.sock = _SafeSock(ws.sock, send_lock)
    watching = threading.Event()   # este celular está assistindo a tela
    stop_push = threading.Event()

    def send(data):
        with send_lock:
            if isinstance(data, bytes) and (stop_push.is_set() or not ws.connected):
                return          # conexão fechando: não manda mais vídeo
            ws.send(data if isinstance(data, bytes) else json.dumps(data))

    def send_error(text):
        send({"t": "error", "msg": text})

    def push_frames():
        seq = 0
        gap = 1.0 / settings.stream_fps      # no máximo `stream_fps` quadros por segundo, qualquer que seja a fonte
        try:
            while not stop_push.is_set():
                started = time.monotonic()
                seq, frame = streamer.wait_frame(seq, 2.0)
                if frame:
                    send(frame)
                    left = gap - (time.monotonic() - started)
                    if left > 0:
                        stop_push.wait(left)
        except stream.StreamError as exc:
            try:
                send({"t": "stream", "state": "error", "msg": str(exc)})
            except Exception:
                pass
        except Exception:   # conexão fechou no meio do envio
            pass

    def start_watching():
        if watching.is_set():
            return
        if not settings.stream:
            send({"t": "stream", "state": "error", "msg": "Transmissão desativada no servidor (RETROPAD_STREAM=0)"})
            return
        try:
            streamer.acquire()
        except stream.StreamError as exc:
            send({"t": "stream", "state": "error", "msg": str(exc)})
            return
        watching.set(); stop_push.clear()
        threading.Thread(target=push_frames, daemon=True).start()
        send({"t": "stream", "state": "on"})

    def stop_watching():
        if watching.is_set():
            watching.clear(); stop_push.set()
            streamer.release()

    try:
        while True:
            raw = ws.receive()
            if raw is None:
                stop_push.set()
                break
            msg = json.loads(raw)
            kind = msg.get("t")

            if kind == "join" and mode is None:
                if PIN:
                    ip = request.remote_addr
                    wait = ctrl_limiter.wait(ip)
                    if wait:
                        send_error(f"Muitas tentativas. Aguarde {wait}s")
                        break
                    if not hmac.compare_digest(str(msg.get("pin", "")).encode(), PIN.encode()):
                        ctrl_limiter.fail(ip)
                        send_error("PIN incorreto")
                        break
                    ctrl_limiter.ok(ip)

                if msg.get("mode", "gamepad") == "touchpad":
                    mode = "touchpad"
                    with lock:
                        get_mouse()
                        get_keyboard()
                    send({"t": "joined", "mode": "touchpad"})
                    continue

                p = msg.get("player")
                if p not in (1, 2):
                    send_error("Jogador inválido")
                    break
                with lock:
                    taken = p in owners
                    if not taken:
                        owners[p] = conn_id
                        get_pad(p)
                if taken:
                    send_error(f"Jogador {p} já está em uso")
                    break
                player, mode = p, "gamepad"
                send({"t": "joined", "player": p, "mode": "gamepad"})

            elif mode is not None and kind == "stream":
                if msg.get("on"):
                    start_watching()
                else:
                    stop_watching()
                    send({"t": "stream", "state": "off"})

            elif mode == "gamepad" and kind == "state":
                hx, hy = msg.get("hat", [0, 0])
                hat = (max(-1, min(1, int(hx))), max(-1, min(1, int(hy))))
                apply_state(player, msg.get("buttons", []), hat, msg.get("axes"))

            elif mode == "touchpad":
                if kind == "move":
                    mouse_move(msg.get("dx", 0), msg.get("dy", 0))
                elif kind == "scroll":
                    mouse_scroll(msg.get("v", 0), msg.get("h", 0))
                elif kind == "click":
                    name, down = str(msg.get("b", "left")), bool(msg.get("down", True))
                    mouse_button(name, down)
                    (held.add if down else held.discard)(name)
                elif kind == "key":
                    key_tap(str(msg.get("key", "")), msg.get("mods", []))
                elif kind == "text":
                    type_text(msg.get("back", 0), str(msg.get("text", "")), msg.get("mods", []))

    except Exception as exc:  # conexão caiu ou mensagem inválida
        print(f"[RetroPad] conexão encerrada: {exc}")
    finally:
        # Primeiro libera o jogador (para ele poder reconectar já), só depois desliga a captura.
        if mode == "gamepad":
            release(player)
            with lock:
                if owners.get(player) == conn_id:
                    del owners[player]
            print(f"[RetroPad] jogador {player} desconectado")
        elif mode == "touchpad":
            for name in held:
                mouse_button(name, False)
            print("[RetroPad] touchpad desconectado")
        stop_watching()


if __name__ == "__main__":
    if not PIN:
        print("[RetroPad] AVISO: RETROPAD_PIN não definido. Qualquer um na rede pode controlar.")
    if not settings.admin_pin:
        print("[RetroPad] AVISO: sem RETROPAD_ADMIN_PIN, o gerenciador de ROMs fica desativado.")
    elif not os.environ.get("RETROPAD_ADMIN_PIN"):
        print("[RetroPad] AVISO: usando RETROPAD_PIN também como PIN de admin. Defina RETROPAD_ADMIN_PIN.")
    print(f"[RetroPad] ROMs em {settings.roms_dir}")
    print(f"[RetroPad] servidor em http://{HOST}:{PORT}")
    if settings.ngrok:
        problems = tunnel.check_settings(settings)
        if problems:
            # Sem túnel (para não expor o controle com configuração fraca), mas a rede local continua funcionando.
            print("[RetroPad] AVISO: ngrok NÃO iniciado, o controle segue só na rede local:\n  - " + "\n  - ".join(problems))
        else:
            def tunnel_ready(url):
                app.config["RETROPAD_TUNNEL_URL"] = url
                print(f"[RetroPad] ngrok: {url}  (instale o PWA por este endereço)")
                if not settings.ngrok_allow_admin:
                    print("[RetroPad] ngrok: /roms e /admin só na rede local (RETROPAD_NGROK_ADMIN=1 para liberar)")
            threading.Thread(target=tunnel.open_forever, args=(settings, tunnel_ready), daemon=True).start()
    app.run(host=HOST, port=PORT, threaded=True)
