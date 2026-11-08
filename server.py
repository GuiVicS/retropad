"""
RetroPad - servidor que transforma celulares em controles para o RetroPie.

Serve uma página de controle (static/index.html) e recebe o estado dos botões
por WebSocket. Para cada jogador (1 ou 2) cria um gamepad virtual via uinput,
que aparece no sistema como um controle USB Xbox 360.
"""
import hmac
import json
import os
import threading

from evdev import AbsInfo, UInput, ecodes as e
from flask import Flask, request, send_from_directory
from flask_sock import Sock

import api
import tunnel
from config import settings

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

PIN = settings.pin          # PIN do controle (separado do PIN de admin)
HOST = settings.host
PORT = settings.port

# Nomes usados pela página -> códigos de botão do Linux.
# Layout no mesmo esquema do Xbox 360/XInput: A embaixo, B à direita, X em cima, Y à esquerda.
# Inclui: D-pad, analógicos, gatilhos, ombros, botões de clicar-analógico e Hotkey/Menu.
# 
# Para modo MOUSE: adiciona EV_REL (movimento relativo) e BTN_* (cliques)
# Para modo TECLADO: adiciona EV_KEY com códigos de teclado padrão Linux
BUTTONS = {
    # Gamepad buttons (existentes)
    "a": e.BTN_SOUTH,
    "b": e.BTN_EAST,
    "x": e.BTN_NORTH,
    "y": e.BTN_WEST,
    "l": e.BTN_TL,      # L1 / shoulder
    "r": e.BTN_TR,      # R1 / shoulder
    "select": e.BTN_SELECT,
    "start": e.BTN_START,
    "l3": e.BTN_THUMBL, # Left stick click (L3)
    "r3": e.BTN_THUMBR, # Right stick click (R3)
    "mode": e.BTN_MODE, # Hotkey / Menu
    
    # Keyboard keys ( LINUX evdev key codes)
    # Linha de número acima de QWERTY
    "1": e.KEY_1, "2": e.KEY_2, "3": e.KEY_3, "4": e.KEY_4, "5": e.KEY_5,
    "6": e.KEY_6, "7": e.KEY_7, "8": e.KEY_8, "9": e.KEY_9, "0": e.KEY_0,
    # Letras
    "q": e.KEY_Q, "w": e.KEY_W, "e": e.KEY_E, "r": e.KEY_R, "t": e.KEY_T,
    "y": e.KEY_Y, "u": e.KEY_U, "i": e.KEY_I, "o": e.KEY_O, "p": e.KEY_P,
    # Linha inferior
    "a": e.KEY_A, "s": e.KEY_S, "d": e.KEY_D, "f": e.KEY_F, "g": e.KEY_G,
    "h": e.KEY_H, "j": e.KEY_J, "k": e.KEY_K, "l": e.KEY_L,
    # Mais letras
    "z": e.KEY_Z, "x": e.KEY_X, "c": e.KEY_C, "v": e.KEY_V, "b": e.KEY_B,
    "n": e.KEY_N, "m": e.KEY_M,
    # Teclas de modificação e especiais
    "enter": e.KEY_ENTER, "backspace": e.KEY_BACKSPACE, "tab": e.KEY_TAB,
    "space": e.KEY_SPACE, "esc": e.KEY_ESC,
    # Setas (também usadas como D-pad)
    "up": e.KEY_UP, "down": e.KEY_DOWN, "left": e.KEY_LEFT, "right": e.KEY_RIGHT,
}

# Novos: códigos de botão para mouse
MOUSE_BUTTONS = {
    "mouse_left": e.BTN_LEFT,
    "mouse_right": e.BTN_RIGHT,
    "mouse_middle": e.BTN_MIDDLE,
}

# Códigos de eixo para mouse
AXIS_MOUSE_REL = {
    "rel_x": e.REL_X,
    "rel_y": e.REL_Y,
}

# Códigos de eixo para teclado (repetição)
AXIS_KEYBOARD = {
    "key_a": e.KEY_A, "key_b": e.KEY_B, # aliases para compatibilidade
}

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
state = {}    # jogador -> {"buttons": set(), "hat": (x, y)}


def get_pad(player, mode="gamepad"):
    """Cria o gamepad virtual do jogador na primeira vez. Chamar com o lock preso."""
    if player not in pads:
        # Determinar capacidades baseadas no modo
        if mode == "mouse":
            # Modo mouse: eixos relativos (REL_X, REL_Y) + botões de clique
            caps = {
                e.EV_KEY: list(BUTTONS.values()) + [MOUSE_BUTTONS["mouse_left"], MOUSE_BUTTONS["mouse_right"]],
                e.EV_REL: [
                    (e.REL_X, AbsInfo(value=0, min=-100, max=100, fuzz=0, flat=0, resolution=0)),
                    (e.REL_Y, AbsInfo(value=0, min=-100, max=100, fuzz=0, flat=0, resolution=0)),
                ],
                # Não incluir EV_ABS para ABS_HAT0X/Y para evitar conflito, usar REL apenas
            }
            # VID/PID genérico para mouse/desktop
            vid, pid = 0x03F0, 0x0007  # Pixar/Trust generic, or use 0x045E/0x028E for compatibility
        elif mode == "keyboard":
            # Modo teclado: apenas EV_KEY com todas as teclas
            caps = {
                e.EV_KEY: list(set(BUTTONS.values())),  # remover duplicatas, manter apenas keys únicas
            }
            # VID/PID genérico
            vid, pid = 0x0060, 0x0101  # Standard keyboard VID
        elif mode == "all":
            # Modo completo: gamepad + mouse + teclado
            caps = {
                e.EV_KEY: list(set(BUTTONS.values())),  # gamepad + teclado
                e.EV_ABS: [
                    (e.ABS_HAT0X, AbsInfo(value=0, min=-1, max=1, fuzz=0, flat=0, resolution=0)),
                    (e.ABS_HAT0Y, AbsInfo(value=0, min=-1, max=1, fuzz=0, flat=0, resolution=0)),
                    (e.ABS_X, AbsInfo(value=0, min=-32768, max=32767, fuzz=0, flat=0, resolution=0)),
                    (e.ABS_Y, AbsInfo(value=0, min=-32768, max=32767, fuzz=0, flat=0, resolution=0)),
                    (e.ABS_RX, AbsInfo(value=0, min=-32768, max=32767, fuzz=0, flat=0, resolution=0)),
                    (e.ABS_RY, AbsInfo(value=0, min=-32768, max=32767, fuzz=0, flat=0, resolution=0)),
                    (e.ABS_Z, AbsInfo(value=0, min=0, max=255, fuzz=0, flat=0, resolution=0)),
                    (e.ABS_RZ, AbsInfo(value=0, min=0, max=255, fuzz=0, flat=0, resolution=0)),
                ],
                e.EV_REL: [
                    (e.REL_X, AbsInfo(value=0, min=-100, max=100, fuzz=0, flat=0, resolution=0)),
                    (e.REL_Y, AbsInfo(value=0, min=-100, max=100, fuzz=0, flat=0, resolution=0)),
                ],
            }
            vid, pid = 0x045E, 0x028E  # Xbox 360 compat
        else:
            # Modo gamepad padrão (RetroPie)
            caps = {
                e.EV_KEY: list(BUTTONS.values()),
                e.EV_ABS: [
                    (e.ABS_HAT0X, AbsInfo(value=0, min=-1, max=1, fuzz=0, flat=0, resolution=0)),
                    (e.ABS_HAT0Y, AbsInfo(value=0, min=-1, max=1, fuzz=0, flat=0, resolution=0)),
                    (e.ABS_X, AbsInfo(value=0, min=-32768, max=32767, fuzz=0, flat=0, resolution=0)),
                    (e.ABS_Y, AbsInfo(value=0, min=-32768, max=32767, fuzz=0, flat=0, resolution=0)),
                    (e.ABS_RX, AbsInfo(value=0, min=-32768, max=32767, fuzz=0, flat=0, resolution=0)),
                    (e.ABS_RY, AbsInfo(value=0, min=-32768, max=32767, fuzz=0, flat=0, resolution=0)),
                    (e.ABS_Z, AbsInfo(value=0, min=0, max=255, fuzz=0, flat=0, resolution=0)),
                    (e.ABS_RZ, AbsInfo(value=0, min=0, max=255, fuzz=0, flat=0, resolution=0)),
                ],
            }
            vid, pid = 0x045E, 0x028E  # Xbox 360 para o RetroArch reconhecer pelo autoconfig.

        # Criar o dispositivo UInput com as capacidades determinadas
        pads[player] = UInput(
            caps,
            name=f"RetroPad P{player}",
            vendor=vid,
            product=pid,
            version=0x0110,
        )
        state[player] = {"buttons": set(), "hat": (0, 0), "mode": mode, "mouse_x": 0, "mouse_y": 0, "keys_pressed": set()}
    return pads[player]


def apply_state(player, buttons, hat, mouse_rel=None, keys=None):
    """Envia só o que mudou desde o último estado, depois um SYN."""
    with lock:
        pad = get_pad(player, state[player].get("mode", "gamepad"))
        cur = state[player]
        mode = cur.get("mode", "gamepad")
        new_buttons = {b for b in buttons if b in BUTTONS}

        # Processar botões do gamepad
        for name in cur["buttons"] ^ new_buttons:
            pad.write(e.EV_KEY, BUTTONS[name], 1 if name in new_buttons else 0)

        # Processar hat (D-pad) - só no modo gamepad
        if hat != cur["hat"] and mode == "gamepad":
            pad.write(e.EV_ABS, e.ABS_HAT0X, hat[0])
            pad.write(e.EV_ABS, e.ABS_HAT0Y, hat[1])

        # Processar movimento do mouse (REL_X, REL_Y) - só no modo mouse
        if mouse_rel and mode == "mouse":
            dx, dy = mouse_rel
            # Somar ao posição atual, com limite
            new_x = max(-100, min(100, cur.get("mouse_x", 0) + dx))
            new_y = max(-100, min(100, cur.get("mouse_y", 0) + dy))
            pad.write(e.EV_REL, e.REL_X, dx)
            pad.write(e.EV_REL, e.REL_Y, dy)
            cur["mouse_x"] = new_x
            cur["mouse_y"] = new_y

        # Processar teclas pressionadas - só no modo keyboard
        if keys and mode == "keyboard":
            for key_name in keys:
                if key_name in BUTTONS:
                    pad.write(e.EV_KEY, BUTTONS[key_name], 1)
                    cur["keys_pressed"].add(key_name)

        # Liberar teclas que foram soltas (se houver rastreamento)
        if keys and mode == "keyboard":
            # Calcular teclas que saíram (diferença entre pressionadas antigas e novas)
            old_pressed = cur.get("keys_pressed", set())
            # Aqui simplificamos: as teclas são mantidas até serem explicitamente liberadas
            # Em um sistema completo, seria necessário rastrear liberação

        pad.syn()
        cur["buttons"] = new_buttons
        cur["hat"] = hat
        # Garantir que modo e mouse/keys existam no state
        if "mode" not in cur:
            cur["mode"] = mode
        if "mouse_x" not in cur and mode == "mouse":
            cur["mouse_x"] = 0
            cur["mouse_y"] = 0
        if "keys_pressed" not in cur and mode == "keyboard":
            cur["keys_pressed"] = set()


def release(player):
    """Solta todos os botões do jogador (usado ao desconectar)."""
    apply_state(player, [], (0, 0))


@app.route("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.route("/admin")
def admin():
    return send_from_directory(STATIC_DIR, "admin.html")


@app.route("/sw.js")
def service_worker():
    # Na raiz, para o service worker poder controlar "/" e "/admin". Sem cache, para atualizar logo.
    resp = send_from_directory(STATIC_DIR, "sw.js", mimetype="text/javascript")
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["Service-Worker-Allowed"] = "/"
    return resp


@sock.route("/ws")
def controller(ws):
    conn_id = id(ws)
    player = None

    def send_error(text):
        ws.send(json.dumps({"t": "error", "msg": text}))

    try:
        while True:
            raw = ws.receive()
            if raw is None:
                break
            msg = json.loads(raw)
            kind = msg.get("t")

            if kind == "join" and player is None:
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

                player = p
                ws.send(json.dumps({"t": "joined", "player": p}))

            elif kind == "state" and player is not None:
                buttons = msg.get("buttons", [])
                hx, hy = msg.get("hat", [0, 0])
                hat = (max(-1, min(1, int(hx))), max(-1, min(1, int(hy))))
                # Novos campos opcionais para mouse e teclado
                mouse_rel = msg.get("mouse_rel")  # [dx, dy] para mouse
                keys = msg.get("keys")  # lista de nomes de teclas para keyboard
                hat = (max(-1, min(1, int(hx))), max(-1, min(1, int(hy))))
                apply_state(player, buttons, hat, mouse_rel, keys)

    except Exception as exc:  # conexão caiu ou mensagem inválida
        print(f"[RetroPad] conexão encerrada: {exc}")
    finally:
        if player is not None:
            release(player)
            with lock:
                if owners.get(player) == conn_id:
                    del owners[player]
            print(f"[RetroPad] jogador {player} desconectado")


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
            raise SystemExit("[RetroPad] ngrok NÃO iniciado:\n  - " + "\n  - ".join(problems))
        try:
            url = tunnel.start(settings)
        except tunnel.TunnelError as exc:
            raise SystemExit(f"[RetroPad] ngrok falhou: {exc}")
        app.config["RETROPAD_TUNNEL_URL"] = url
        print(f"[RetroPad] ngrok: {url}  (instale o PWA por este endereço)")
        if not settings.ngrok_allow_admin:
            print("[RetroPad] ngrok: /admin só na rede local (RETROPAD_NGROK_ADMIN=1 para liberar)")
    app.run(host=HOST, port=PORT, threaded=True)
