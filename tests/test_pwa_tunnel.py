"""Testes do PWA (manifest, service worker) e do túnel ngrok. Rodar: pytest -q"""
import json
import os
import sys
import tempfile

import pytest
from flask import Flask

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tunnel  # noqa: E402
from config import Settings, load_settings  # noqa: E402

STATIC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")


# ------------------------------------------------------------------ config

def test_ngrok_env_parsing():
    cfg = load_settings({"RETROPAD_NGROK": "1", "NGROK_AUTHTOKEN": "tok", "RETROPAD_NGROK_DOMAIN": "https://x.ngrok-free.app/",
                         "RETROPAD_PIN": "123456"})
    assert cfg.ngrok and cfg.ngrok_authtoken == "tok" and cfg.ngrok_domain == "x.ngrok-free.app"
    assert not cfg.ngrok_allow_admin
    assert not load_settings({}).ngrok
    assert load_settings({"RETROPAD_NGROK": "no"}).ngrok is False


def test_ngrok_requires_strong_pin():
    assert tunnel.check_settings(Settings(ngrok=False)) == []
    assert tunnel.check_settings(Settings(ngrok=True, pin="")) != []
    assert tunnel.check_settings(Settings(ngrok=True, pin="1234")) != []          # curto demais
    assert tunnel.check_settings(Settings(ngrok=True, pin="123456", admin_pin="123456")) == []


def test_ngrok_admin_exposure_needs_separate_pin():
    base = dict(ngrok=True, pin="123456", ngrok_allow_admin=True)
    assert tunnel.check_settings(Settings(**base, admin_pin="123456")) != []     # igual ao do controle
    assert tunnel.check_settings(Settings(**base, admin_pin="abc")) != []        # curto
    assert tunnel.check_settings(Settings(**base, admin_pin="s3nha-forte")) == []


# ------------------------------------------------------------ start (mock)

class FakeNgrok:
    def __init__(self, url="http://abc.ngrok-free.app"):
        self.calls, self.url, self.killed = [], url, False

    def set_auth_token(self, tok): self.calls.append(("token", tok))

    def connect(self, port, proto, **opts):
        self.calls.append(("connect", port, proto, opts))
        return type("T", (), {"public_url": self.url})()

    def kill(self): self.killed = True


def test_start_passes_token_domain_and_forces_https(tmp_path):
    cfg = Settings(ngrok=True, port=8080, ngrok_authtoken="tok", ngrok_domain="fixo.ngrok-free.app",
                   url_file=str(tmp_path / "u" / "url.txt"))
    fake = FakeNgrok()
    url = tunnel.start(cfg, ngrok=fake)
    assert url == "https://abc.ngrok-free.app"
    assert fake.calls == [("token", "tok"), ("connect", 8080, "http", {"url": "https://fixo.ngrok-free.app"})]
    assert (tmp_path / "u" / "url.txt").read_text().strip() == url
    tunnel.stop(fake, cfg)
    assert fake.killed and not (tmp_path / "u" / "url.txt").exists()


def test_start_without_domain_or_token(tmp_path):
    fake = FakeNgrok("https://rand.ngrok-free.app")
    tunnel.start(Settings(ngrok=True, url_file=str(tmp_path / "u.txt")), ngrok=fake)
    assert fake.calls == [("connect", 8080, "http", {})]


def test_start_wraps_ngrok_errors(tmp_path):
    class Boom(FakeNgrok):
        def connect(self, *a, **k): raise RuntimeError("authentication failed")
    with pytest.raises(tunnel.TunnelError, match="authentication failed"):
        tunnel.start(Settings(ngrok=True, url_file=str(tmp_path / "u.txt")), ngrok=Boom())


# -------------------------------------------------------------- guard HTTP

def guarded_client(allow_admin=False):
    cfg = Settings(ngrok=True, pin="123456", ngrok_allow_admin=allow_admin)
    app = Flask(__name__)

    @app.route("/admin")
    def admin(): return "admin"

    @app.route("/api/status")
    def st(): return "status"

    @app.route("/")
    def home():
        from flask import request
        return request.remote_addr

    tunnel.install_guard(app, cfg)
    return app.test_client()


VIA_TUNNEL = {"environ_base": {"REMOTE_ADDR": "127.0.0.1"}, "headers": {"X-Forwarded-For": "203.0.113.9"}}


def test_admin_blocked_through_tunnel_by_default():
    c = guarded_client()
    assert c.get("/admin", **VIA_TUNNEL).status_code == 403
    assert c.get("/api/status", **VIA_TUNNEL).status_code == 403
    assert c.get("/", **VIA_TUNNEL).status_code == 200      # o controle continua acessível


def test_admin_allowed_locally_and_on_lan():
    c = guarded_client()
    assert c.get("/admin").status_code == 200                                              # na própria máquina
    assert c.get("/admin", environ_base={"REMOTE_ADDR": "192.168.0.20"}).status_code == 200  # celular na Wi-Fi


def test_admin_allowed_through_tunnel_when_enabled():
    assert guarded_client(allow_admin=True).get("/admin", **VIA_TUNNEL).status_code == 200


def test_real_visitor_ip_used_only_from_loopback():
    c = guarded_client()
    assert c.get("/", **VIA_TUNNEL).get_data(as_text=True) == "203.0.113.9"
    # Alguém na LAN forjando X-Forwarded-For não troca de IP (driblaria o limite de PIN)
    r = c.get("/", environ_base={"REMOTE_ADDR": "192.168.0.20"}, headers={"X-Forwarded-For": "1.2.3.4"})
    assert r.get_data(as_text=True) == "192.168.0.20"
    # ...nem escapa do bloqueio do admin fingindo ser local: sem loopback, a regra não se aplica,
    # mas também não ganha nada além do que a LAN já tem.


# ---------------------------------------------------------------- servidor

@pytest.fixture(scope="module")
def server_client():
    tmp = tempfile.mkdtemp()
    os.environ.update(RETROPAD_ROMS=tmp, RETROPAD_LOG=os.path.join(tmp, "l.log"), RETROPAD_ADMIN_PIN="9999")
    import importlib
    import config
    importlib.reload(config)
    import server
    importlib.reload(server)
    return server.app.test_client()


def test_service_worker_served_from_root(server_client):
    r = server_client.get("/sw.js")
    assert r.status_code == 200
    assert r.headers["Service-Worker-Allowed"] == "/"
    assert "no-cache" in r.headers["Cache-Control"]
    assert "javascript" in r.mimetype


def test_responses_are_marked_for_the_service_worker(server_client):
    for url in ("/", "/admin", "/static/theme.css", "/static/manifest.json"):
        assert server_client.get(url).headers.get("X-RetroPad") == "1", url


def test_service_worker_never_caches_api_or_ws():
    src = open(os.path.join(STATIC, "sw.js"), encoding="utf-8").read()
    assert "'/api/'" in src and "'/ws'" in src
    assert "X-RetroPad" in src


# ---------------------------------------------------------------- manifest

def test_manifest_is_installable():
    m = json.load(open(os.path.join(STATIC, "manifest.json"), encoding="utf-8"))
    assert m["name"] and m["short_name"] and m["start_url"] and m["display"] in ("standalone", "fullscreen")
    assert "orientation" not in m          # o admin precisa funcionar em retrato
    sizes = {(i["sizes"], i["purpose"]) for i in m["icons"]}
    assert ("192x192", "any") in sizes and ("512x512", "any") in sizes and ("512x512", "maskable") in sizes
    for icon in m["icons"]:                # todos os ícones existem em disco
        assert os.path.isfile(os.path.join(STATIC, icon["src"].replace("/static/", "")))


@pytest.mark.parametrize("page", ["index.html", "admin.html"])
def test_pages_link_pwa_assets(page):
    html = open(os.path.join(STATIC, page), encoding="utf-8").read()
    for needle in ('rel="manifest"', 'rel="apple-touch-icon"', "/static/pwa.js", "/static/theme.css", 'data-install'):
        assert needle in html, (page, needle)
