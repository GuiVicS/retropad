"""Túnel ngrok opcional (RETROPAD_NGROK=1).

Dá ao Raspberry um endereço HTTPS público, o que permite instalar o RetroPad como
PWA completo (service worker exige HTTPS) e jogar fora da rede local.

ATENÇÃO: isso expõe o servidor na internet. Por isso este módulo:
  - exige PINs de pelo menos 6 caracteres;
  - bloqueia /admin e /api pelo túnel, a menos que RETROPAD_NGROK_ADMIN=1;
  - faz o limite de tentativas de PIN contar pelo IP real do visitante.
"""
import atexit
import os

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
        if request.path == "/admin" or request.path.startswith("/api/"):
            return ("O gerenciador de ROMs só está disponível na rede local.", 403)
        return None


def start(cfg, ngrok=None):
    """Abre o túnel e devolve a URL pública. `ngrok` é injetável para testes."""
    if ngrok is None:
        try:
            from pyngrok import ngrok
        except ImportError:
            raise TunnelError("pyngrok não está instalado (pip install pyngrok)")
    if cfg.ngrok_authtoken:
        ngrok.set_auth_token(cfg.ngrok_authtoken)
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
