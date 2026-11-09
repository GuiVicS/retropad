"""Túnel ngrok opcional (RETROPAD_NGROK=1).

Dá ao Raspberry um endereço HTTPS público, o que permite instalar o RetroPad como
PWA completo (service worker exige HTTPS) e jogar fora da rede local.

ATENÇÃO: isso expõe o servidor na internet. Por isso este módulo:
  - exige PINs de pelo menos 6 caracteres;
  - bloqueia /admin, /roms e /api pelo túnel, a menos que RETROPAD_NGROK_ADMIN=1;
  - faz o limite de tentativas de PIN contar pelo IP real do visitante.
"""
import atexit
import os
import time

from flask import request

MIN_PIN_LEN = 6
LOOPBACK = ("127.0.0.1", "::1")


class TunnelError(Exception):
    pass


def check_settings(cfg):
    """Lista os motivos pelos quais o túnel não deve subir com esta configuração."""
    if not cfg.ngrok:
        return []
    problems = []
    if len(cfg.pin) < MIN_PIN_LEN:
        problems.append(f"defina RETROPAD_PIN com pelo menos {MIN_PIN_LEN} caracteres (o controle ficará público)")
    if cfg.ngrok_allow_admin and (len(cfg.admin_pin) < MIN_PIN_LEN or cfg.admin_pin == cfg.pin):
        problems.append(f"com RETROPAD_NGROK_ADMIN=1, defina um RETROPAD_ADMIN_PIN diferente do PIN do controle "
                        f"e com pelo menos {MIN_PIN_LEN} caracteres")
    return problems


def is_admin_path(path):
    """Páginas e API do gerenciador de ROMs (nunca expostas pelo túnel, salvo RETROPAD_NGROK_ADMIN=1)."""
    return path in ("/admin", "/roms") or path.startswith(("/roms/", "/api/"))


class TunnelMiddleware:
    """Marca requisições vindas do ngrok e usa o IP real do visitante.

    O agente do ngrok conecta de 127.0.0.1 e acrescenta X-Forwarded-For. Só confiamos
    nesse cabeçalho quando a conexão vem do próprio Raspberry; assim, alguém na rede
    local não consegue forjar o IP para driblar o limite de tentativas.
    """

    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app

    def __call__(self, environ, start_response):
        forwarded = environ.get("HTTP_X_FORWARDED_FOR", "")
        if forwarded and environ.get("REMOTE_ADDR") in LOOPBACK:
            environ["retropad.tunnel"] = True
            environ["REMOTE_ADDR"] = forwarded.split(",")[-1].strip()
        return self.wsgi_app(environ, start_response)


def install_guard(app, cfg):
    app.wsgi_app = TunnelMiddleware(app.wsgi_app)

    @app.before_request
    def keep_admin_local():
        if cfg.ngrok_allow_admin or not request.environ.get("retropad.tunnel"):
            return None
        if is_admin_path(request.path):
            return ("O gerenciador de ROMs só está disponível na rede local.", 403)
        return None


def _apply_token(ngrok, token):
    """Entrega o authtoken ao ngrok.

    Se o token já estiver salvo no arquivo de configuração do ngrok (por exemplo, configurado antes
    pelo terminal), o ngrok responde "Authtoken already set" e o pyngrok trata isso como erro. Isso
    não é problema: seguimos em frente e ainda passamos o token pelo ambiente (NGROK_AUTHTOKEN).
    """
    try:
        ngrok.set_auth_token(token)
    except Exception as exc:
        text = str(exc)
        if "already set" in text.lower():
            os.environ["NGROK_AUTHTOKEN"] = token
            return
        raise TunnelError("não consegui salvar o authtoken do ngrok: " + text[:300])


def start(cfg, ngrok=None):
    """Abre o túnel e devolve a URL pública. `ngrok` é injetável para testes."""
    if ngrok is None:
        try:
            from pyngrok import ngrok
        except ImportError:
            raise TunnelError("pyngrok não está instalado (pip install pyngrok)")
    if cfg.ngrok_authtoken:
        _apply_token(ngrok, cfg.ngrok_authtoken)
    options = {}
    if cfg.ngrok_domain:
        options["url"] = f"https://{cfg.ngrok_domain}"
    try:
        tunnel = ngrok.connect(cfg.port, "http", **options)
    except Exception as exc:   # pyngrok levanta vários tipos (token ausente, sem rede, domínio inválido)
        raise TunnelError(str(exc))
    url = tunnel.public_url
    if url.startswith("http://"):
        url = "https://" + url[len("http://"):]
    atexit.register(stop, ngrok, cfg)
    _write_url(cfg, url)
    return url


def open_forever(cfg, on_ready, log=print, sleep=time.sleep, start_fn=None, max_wait=300):
    """Abre o túnel, tentando de novo enquanto falhar (ex.: o Pi ligou antes do Wi-Fi).

    Roda em uma thread à parte: o servidor já atende na rede local enquanto isso, então um problema
    com o ngrok nunca derruba o controle. Devolve a URL quando consegue.
    """
    start_fn = start_fn or start
    attempt = 0
    while True:
        attempt += 1
        try:
            url = start_fn(cfg)
        except Exception as exc:       # TunnelError e qualquer erro inesperado do pyngrok
            wait = min(30 * attempt, max_wait)
            log(f"[RetroPad] AVISO: ngrok falhou ({exc}). Nova tentativa em {wait}s; o controle segue na rede local.")
            sleep(wait)
            continue
        on_ready(url)
        return url


def stop(ngrok, cfg):
    try:
        ngrok.kill()
    except Exception:
        pass
    try:
        os.remove(cfg.url_file)
    except OSError:
        pass


def _write_url(cfg, url):
    try:
        os.makedirs(os.path.dirname(cfg.url_file), exist_ok=True)
        with open(cfg.url_file, "w", encoding="utf-8") as fh:
            fh.write(url + "\n")
    except OSError:
        pass   # só serve para o menu do EmulationStation mostrar o endereço
