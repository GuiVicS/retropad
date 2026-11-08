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
# Layout no mesmo esquema do Xbox: A embaixo, B à direita, X em cima, Y à esquerda.
BUTTONS = {
    "a": e.BTN_SOUTH,
    "b": e.BTN_EAST,
    "x": e.BTN_NORTH,
    "y": e.BTN_WEST,
    "l": e.BTN_TL,
    "r": e.BTN_TR,
    "select": e.BTN_SELECT,
    "start": e.BTN_START,
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


def get_pad(player):
    """Cria o gamepad virtual do jogador na primeira vez. Chamar com o lock preso."""
    if player not in pads:
        caps = {
            e.EV_KEY: list(BUTTONS.values()),
            e.EV_ABS: [
                (e.ABS_HAT0X, AbsInfo(value=0, min=-1, max=1, fuzz=0, flat=0, resolution=0)),
                (e.ABS_HAT0Y, AbsInfo(value=0, min=-1, max=1, fuzz=0, flat=0, resolution=0)),
            ],
        }
        # VID/PID do Xbox 360 para o RetroArch reconhecer pelo autoconfig.
        pads[player] = UInput(
            caps,
            name=f"RetroPad P{player}",
            vendor=0x045E,
            product=0x028E,
            version=0x0110,
        )
        state[player] = {"buttons": set(), "hat": (0, 0)}
    return pads[player]


def apply_state(player, buttons, hat):
    """Envia só o que mudou desde o último estado, depois um SYN."""
    with lock:
        pad = get_pad(player)
        cur = state[player]
        new_buttons = {b for b in buttons if b in BUTTONS}

        for name in cur["buttons"] ^ new_buttons:
            pad.write(e.EV_KEY, BUTTONS[name], 1 if name in new_buttons else 0)

        if hat != cur["hat"]:
            pad.write(e.EV_ABS, e.ABS_HAT0X, hat[0])
            pad.write(e.EV_ABS, e.ABS_HAT0Y, hat[1])

        pad.syn()
        cur["buttons"] = new_buttons
        cur["hat"] = hat


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
                apply_state(player, buttons, hat)

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
