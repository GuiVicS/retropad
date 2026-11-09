"""Rotas: uma por função, e o gerenciador de ROMs nunca vaza pelo túnel."""
import os
import sys
import tempfile

import pytest
from flask import Flask

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tunnel  # noqa: E402
from config import Settings  # noqa: E402

CONTROL = ["/", "/gamepad", "/mouse", "/tela", "/config"]
ROMS = ["/roms", "/roms/nes", "/roms/snes", "/admin"]


@pytest.fixture(scope="module")
def client():
    tmp = tempfile.mkdtemp()
    os.environ.update(RETROPAD_ROMS=tmp, RETROPAD_LOG=os.path.join(tmp, "l.log"), RETROPAD_ADMIN_PIN="9999")
    import importlib
    import config
    importlib.reload(config)
    import server
    importlib.reload(server)
    return server.app.test_client()


@pytest.mark.parametrize("path", CONTROL)
def test_each_controller_function_has_its_own_route(client, path):
    r = client.get(path)
    assert r.status_code == 200 and b'id="pad"' in r.data
    assert r.headers.get("X-RetroPad") == "1"


@pytest.mark.parametrize("path", ROMS)
def test_rom_manager_routes(client, path):
    r = client.get(path)
    assert r.status_code == 200 and b'id="roms"' in r.data


def test_unknown_route_is_404(client):
    assert client.get("/nada").status_code == 404


@pytest.mark.parametrize("path", ["/admin", "/roms", "/roms/nes", "/api/status", "/api/roms/nes"])
def test_admin_paths_are_recognised_as_admin(path):
    assert tunnel.is_admin_path(path)


@pytest.mark.parametrize("path", CONTROL + ["/ws", "/static/theme.css", "/romsfoo"])
def test_controller_paths_are_not_admin(path):
    assert not tunnel.is_admin_path(path)


def guarded(allow_admin=False):
    app = Flask(__name__)
    for p in CONTROL + ROMS + ["/api/status"]:
        app.add_url_rule(p, endpoint="e" + p.replace("/", "_"), view_func=lambda **_: "ok")
    tunnel.install_guard(app, Settings(ngrok=True, pin="123456", ngrok_allow_admin=allow_admin))
    return app.test_client()


VIA_TUNNEL = {"environ_base": {"REMOTE_ADDR": "127.0.0.1"}, "headers": {"X-Forwarded-For": "203.0.113.9"}}


@pytest.mark.parametrize("path", ROMS + ["/api/status"])
def test_tunnel_blocks_every_rom_manager_route(path):
    assert guarded().get(path, **VIA_TUNNEL).status_code == 403


@pytest.mark.parametrize("path", CONTROL)
def test_tunnel_still_serves_the_controller(path):
    assert guarded().get(path, **VIA_TUNNEL).status_code == 200


@pytest.mark.parametrize("path", ROMS)
def test_rom_manager_open_on_lan_and_when_explicitly_enabled(path):
    assert guarded().get(path, environ_base={"REMOTE_ADDR": "192.168.0.20"}).status_code == 200
    assert guarded(allow_admin=True).get(path, **VIA_TUNNEL).status_code == 200
