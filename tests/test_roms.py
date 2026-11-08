"""Testes da lógica de ROMs e da API. Rodar: pytest -q (na pasta retropad/)."""
import io
import os
import sys
from collections import namedtuple

import pytest
from flask import Flask

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import api  # noqa: E402
import roms  # noqa: E402
from config import Settings  # noqa: E402
from roms import RomError  # noqa: E402

SYSTEMS = {
    "snes": {"name": "Super Nintendo", "extensions": [".sfc", ".smc", ".zip"]},
    "psx": {"name": "PlayStation", "extensions": [".cue", ".bin", ".chd", ".iso", ".zip"]},
}
ZIP = b"PK\x03\x04" + b"\0" * 100


@pytest.fixture
def roms_dir(tmp_path):
    for s in ("snes", "psx"):
        (tmp_path / s).mkdir()
    return str(tmp_path)


def save(roms_dir, name, data=b"x" * 10, system="snes", **kw):
    kw.setdefault("max_bytes", 10 * 2**20)
    kw.setdefault("min_free", 0)
    return roms.save_stream(roms_dir, SYSTEMS, system, name, io.BytesIO(data), len(data), **kw)


# ------------------------------------------------------- sanitização de nomes

@pytest.mark.parametrize("raw,expected", [
    ("Super Mario World (USA).sfc", "Super Mario World (USA).sfc"),
    ("Pokémon [!].sfc", "Pokémon [!].sfc"),
    ("../../etc/passwd.sfc", "passwd.sfc"),
    ("..\\..\\windows\\game.sfc", "game.sfc"),
    ("/abs/path/game.sfc", "game.sfc"),
    (".hidden.sfc", "hidden.sfc"),
    ("a\x00b\nc.sfc", "ab c.sfc"),
    ("a   b.sfc", "a b.sfc"),
    ("jogo<>:\"|?*.sfc", "jogo.sfc"),
])
def test_sanitize_filename(raw, expected):
    assert roms.sanitize_filename(raw) == expected


@pytest.mark.parametrize("raw", ["", ".", "..", "...", "/", "<>|", None, 5])
def test_sanitize_rejects_invalid(raw):
    with pytest.raises(RomError):
        roms.sanitize_filename(raw)


def test_sanitize_limits_length_keeping_extension():
    name = roms.sanitize_filename("a" * 500 + ".sfc")
    assert name.endswith(".sfc") and len(name.encode()) <= roms.MAX_NAME_BYTES


# ------------------------------------------------------------- extensões

def test_extension_accepted_case_insensitive():
    assert roms.check_extension(SYSTEMS, "snes", "Game.SFC") == ".sfc"


@pytest.mark.parametrize("name", ["game.exe", "game", "game.cue", "game.sfc.txt"])
def test_extension_rejected(name):
    with pytest.raises(RomError) as exc:
        roms.check_extension(SYSTEMS, "snes", name)
    assert exc.value.status == 415


def test_unconfigured_system_rejected():
    with pytest.raises(RomError):
        roms.check_extension(SYSTEMS, "ports", "x.sh")


# -------------------------------------------------------- path traversal

@pytest.mark.parametrize("system", ["..", "../x", "snes/..", "a/b", "", "SNES", "snes\x00", ".hidden"])
def test_system_traversal_rejected(roms_dir, system):
    with pytest.raises(RomError):
        roms.system_dir(roms_dir, system)


@pytest.mark.parametrize("name", ["../x.sfc", "..", "a/b.sfc", "..\\x.sfc", "", "x\x00.sfc"])
def test_rom_path_traversal_rejected(roms_dir, name):
    with pytest.raises(RomError):
        roms.rom_path(roms_dir, "snes", name)


def test_symlinked_system_outside_roms_rejected(roms_dir, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside")
    os.symlink(outside, os.path.join(roms_dir, "evil"))
    with pytest.raises(RomError):
        roms.system_dir(roms_dir, "evil")


def test_symlinked_file_cannot_be_deleted_through_link(roms_dir, tmp_path_factory):
    target = tmp_path_factory.mktemp("outside") / "secret.sfc"
    target.write_bytes(b"secret")
    os.symlink(target, os.path.join(roms_dir, "snes", "link.sfc"))
    with pytest.raises(RomError):
        roms.delete_rom(roms_dir, SYSTEMS, "snes", "link.sfc")
    assert target.exists()


def test_upload_traversal_name_stays_inside(roms_dir):
    res = save(roms_dir, "../../evil.sfc")
    assert res["name"] == "evil.sfc"
    assert os.path.isfile(os.path.join(roms_dir, "snes", "evil.sfc"))
    assert not os.path.exists(os.path.join(os.path.dirname(roms_dir), "evil.sfc"))


# ---------------------------------------------------------------- gravação

def test_save_and_list(roms_dir):
    save(roms_dir, "b.sfc", b"12345")
    save(roms_dir, "A.smc", b"1")
    items = roms.list_roms(roms_dir, SYSTEMS, "snes")
    assert [i["name"] for i in items] == ["A.smc", "b.sfc"]
    assert items[1]["size"] == 5
    assert not [f for f in os.listdir(os.path.join(roms_dir, "snes")) if f.endswith(".part")]


def test_overwrite_requires_confirmation(roms_dir):
    save(roms_dir, "g.sfc", b"old")
    with pytest.raises(RomError) as exc:
        save(roms_dir, "g.sfc", b"new")
    assert exc.value.status == 409
    assert open(os.path.join(roms_dir, "snes", "g.sfc"), "rb").read() == b"old"
    assert save(roms_dir, "g.sfc", b"new", overwrite=True)["overwritten"] is True
    assert open(os.path.join(roms_dir, "snes", "g.sfc"), "rb").read() == b"new"


def test_size_limit_declared_and_streamed(roms_dir):
    with pytest.raises(RomError) as exc:
        save(roms_dir, "big.sfc", b"x" * 20, max_bytes=10)
    assert exc.value.status == 413
    # Sem tamanho declarado (chunked): o limite vale durante a leitura e limpa o .part
    with pytest.raises(RomError) as exc:
        roms.save_stream(roms_dir, SYSTEMS, "snes", "big.sfc", io.BytesIO(b"x" * 20), None, 10, 0)
    assert exc.value.status == 413
    assert os.listdir(os.path.join(roms_dir, "snes")) == []


def test_empty_upload_rejected(roms_dir):
    with pytest.raises(RomError):
        save(roms_dir, "e.sfc", b"")
    assert os.listdir(os.path.join(roms_dir, "snes")) == []


def test_upload_is_chunked(roms_dir, monkeypatch):
    monkeypatch.setattr(roms, "CHUNK", 4)
    reads = []

    class Spy(io.BytesIO):
        def read(self, n=-1):
            reads.append(n)
            return super().read(n)

    roms.save_stream(roms_dir, SYSTEMS, "snes", "c.sfc", Spy(b"0123456789"), 10, 2**20, 0)
    assert set(reads) == {4}          # nunca lê o arquivo inteiro de uma vez
    assert len(reads) == 4            # 3 blocos + o final vazio


# ------------------------------------------------------------ espaço livre

def test_disk_space_check(roms_dir, monkeypatch):
    Usage = namedtuple("Usage", "total used free")
    monkeypatch.setattr(roms.shutil, "disk_usage", lambda p: Usage(1000 * 2**20, 0, 500 * 2**20))
    roms.check_space(roms_dir, 100 * 2**20, 200 * 2**20)          # sobra 400 MB: ok
    with pytest.raises(RomError) as exc:
        roms.check_space(roms_dir, 400 * 2**20, 200 * 2**20)      # sobraria 100 MB: recusa
    assert exc.value.status == 507
    with pytest.raises(RomError):
        save(roms_dir, "x.sfc", b"x" * 10, min_free=600 * 2**20)  # margem maior que o livre


def test_failed_upload_leaves_no_file_when_no_space(roms_dir, monkeypatch):
    Usage = namedtuple("Usage", "total used free")
    monkeypatch.setattr(roms.shutil, "disk_usage", lambda p: Usage(10, 10, 0))
    with pytest.raises(RomError):
        save(roms_dir, "x.sfc", min_free=1)
    assert os.listdir(os.path.join(roms_dir, "snes")) == []


# -------------------------------------------------------------- assinaturas

def test_zip_signature(roms_dir):
    save(roms_dir, "ok.zip", ZIP)
    with pytest.raises(RomError) as exc:
        save(roms_dir, "fake.zip", b"not a zip at all")
    assert exc.value.status == 422
    assert not os.path.exists(os.path.join(roms_dir, "snes", "fake.zip"))


def test_iso_signature(roms_dir):
    good = bytearray(0x8100)
    good[0x8001:0x8006] = b"CD001"
    save(roms_dir, "ok.iso", bytes(good), system="psx")
    with pytest.raises(RomError):
        save(roms_dir, "bad.iso", b"\0" * 0x8100, system="psx")


def test_chd_signature(roms_dir):
    save(roms_dir, "ok.chd", b"MComprHD" + b"\0" * 20, system="psx")
    with pytest.raises(RomError):
        save(roms_dir, "bad.chd", b"nope" * 10, system="psx")


# -------------------------------------------------- apagar, renomear, listar

def test_delete_and_rename(roms_dir):
    save(roms_dir, "a.sfc")
    assert roms.rename_rom(roms_dir, SYSTEMS, "snes", "a.sfc", "Novo (BR).sfc") == "Novo (BR).sfc"
    assert os.listdir(os.path.join(roms_dir, "snes")) == ["Novo (BR).sfc"]
    with pytest.raises(RomError):
        roms.rename_rom(roms_dir, SYSTEMS, "snes", "Novo (BR).sfc", "x.exe")
    save(roms_dir, "b.sfc")
    with pytest.raises(RomError) as exc:
        roms.rename_rom(roms_dir, SYSTEMS, "snes", "b.sfc", "Novo (BR).sfc")
    assert exc.value.status == 409
    roms.delete_rom(roms_dir, SYSTEMS, "snes", "b.sfc")
    assert "b.sfc" not in os.listdir(os.path.join(roms_dir, "snes"))
    with pytest.raises(RomError) as exc:
        roms.delete_rom(roms_dir, SYSTEMS, "snes", "b.sfc")
    assert exc.value.status == 404


def test_delete_only_known_extensions(roms_dir):
    p = os.path.join(roms_dir, "snes", "gamelist.xml")
    open(p, "w").write("<x/>")
    with pytest.raises(RomError):
        roms.delete_rom(roms_dir, SYSTEMS, "snes", "gamelist.xml")
    assert os.path.exists(p)


def test_list_systems_counts_and_ignores_non_roms(roms_dir):
    save(roms_dir, "a.sfc", b"123")
    save(roms_dir, "b.zip", ZIP)
    open(os.path.join(roms_dir, "snes", "gamelist.xml"), "w").write("<x/>")
    os.makedirs(os.path.join(roms_dir, ".hidden"))
    os.makedirs(os.path.join(roms_dir, "ports"))
    by_id = {s["id"]: s for s in roms.list_systems(roms_dir, SYSTEMS)}
    assert by_id["snes"]["count"] == 2 and by_id["snes"]["size"] == 3 + len(ZIP)
    assert by_id["psx"]["count"] == 0
    assert by_id["ports"]["configured"] is False
    assert ".hidden" not in by_id


# ================================================================= API HTTP

PIN = "9999"


def make_app(roms_dir, tmp_path, **over):
    cfg = Settings(roms_dir=roms_dir, admin_pin=PIN, pin="", log_file=str(tmp_path / "log" / "r.log"),
                   min_free_mb=0, max_upload_mb=1, max_attempts=3, lock_seconds=60, **over)
    app = Flask(__name__)
    api.init_app(app, cfg)
    app.config["RETROPAD_SYSTEMS"] = SYSTEMS
    return app


@pytest.fixture
def client(roms_dir, tmp_path):
    return make_app(roms_dir, tmp_path).test_client()


H = {"X-Admin-PIN": PIN}


def test_api_requires_pin_on_every_route(client):
    for method, url in [("get", "/api/status"), ("get", "/api/systems"), ("get", "/api/roms/snes"),
                        ("get", "/api/check/snes?name=a.sfc"), ("post", "/api/roms/snes?name=a.sfc"),
                        ("delete", "/api/roms/snes/a.sfc"), ("post", "/api/roms/snes/a.sfc/rename")]:
        assert getattr(client, method)(url).status_code == 401, url


def test_api_disabled_without_admin_pin(roms_dir, tmp_path):
    cfg = Settings(roms_dir=roms_dir, admin_pin="", log_file=str(tmp_path / "l.log"))
    app = Flask(__name__)
    api.init_app(app, cfg)
    r = app.test_client().get("/api/systems", headers=H)
    assert r.status_code == 503


def test_pin_lockout_after_failures(client):
    bad = {"X-Admin-PIN": "0000"}
    assert [client.get("/api/status", headers=bad).status_code for _ in range(3)] == [401, 401, 401]
    # Bloqueado: mesmo o PIN certo é recusado
    assert client.get("/api/status", headers=H).status_code == 429


def test_pin_lockout_expires(roms_dir, tmp_path):
    app = make_app(roms_dir, tmp_path)
    clock = [1000.0]
    app.config["RETROPAD_LIMITER"].clock = lambda: clock[0]
    c = app.test_client()
    for _ in range(3):
        c.get("/api/status", headers={"X-Admin-PIN": "x"})
    assert c.get("/api/status", headers=H).status_code == 429
    clock[0] += 61
    assert c.get("/api/status", headers=H).status_code == 200


def test_correct_pin_resets_counter(client):
    bad = {"X-Admin-PIN": "x"}
    client.get("/api/status", headers=bad)
    client.get("/api/status", headers=bad)
    assert client.get("/api/status", headers=H).status_code == 200
    client.get("/api/status", headers=bad)
    client.get("/api/status", headers=bad)
    assert client.get("/api/status", headers=H).status_code == 200


def test_api_upload_list_rename_delete_flow(client, roms_dir):
    r = client.post("/api/roms/snes?name=Jogo (BR).sfc", data=b"abc", headers=H,
                    content_type="application/octet-stream")
    assert r.status_code == 201 and r.json["name"] == "Jogo (BR).sfc"
    assert client.get("/api/roms/snes", headers=H).json[0]["size"] == 3

    r = client.post("/api/roms/snes?name=Jogo (BR).sfc", data=b"abc", headers=H,
                    content_type="application/octet-stream")
    assert r.status_code == 409
    assert client.post("/api/roms/snes?name=Jogo (BR).sfc&overwrite=1", data=b"abcd", headers=H,
                       content_type="application/octet-stream").status_code == 201

    r = client.post("/api/roms/snes/Jogo (BR).sfc/rename", json={"name": "Novo.sfc"}, headers=H)
    assert r.json["name"] == "Novo.sfc"
    assert client.delete("/api/roms/snes/Novo.sfc", headers=H).status_code == 200
    assert client.get("/api/roms/snes", headers=H).json == []


def test_api_multipart_upload(client, roms_dir):
    r = client.post("/api/roms/snes", headers=H,
                    data={"file": (io.BytesIO(b"rom!"), "m.sfc")}, content_type="multipart/form-data")
    assert r.status_code == 201
    assert os.path.isfile(os.path.join(roms_dir, "snes", "m.sfc"))


def test_api_rejects_bad_extension_traversal_and_size(client, roms_dir):
    assert client.post("/api/roms/snes?name=a.exe", data=b"x", headers=H).status_code == 415
    assert client.post("/api/roms/..?name=a.sfc", data=b"x", headers=H).status_code in (400, 404)
    assert client.post("/api/roms/nope?name=a.sfc", data=b"x", headers=H).status_code == 404
    assert client.delete("/api/roms/snes/..%2F..%2Fetc%2Fpasswd", headers=H).status_code in (400, 404)
    too_big = b"x" * (2 * 2**20)      # limite do teste: 1 MB
    assert client.post("/api/roms/snes?name=big.sfc", data=too_big, headers=H).status_code == 413
    assert os.listdir(os.path.join(roms_dir, "snes")) == []


def test_api_check_endpoint(client):
    assert client.get("/api/check/snes?name=a.sfc&size=10", headers=H).json == {"name": "a.sfc", "exists": False}
    assert client.get("/api/check/snes?name=a.sfc&size=99999999999", headers=H).status_code == 413
    assert client.get("/api/check/snes?name=a.txt&size=1", headers=H).status_code == 415


def test_upload_and_delete_are_logged(client, tmp_path):
    client.post("/api/roms/snes?name=l.sfc", data=b"x", headers=H)
    client.delete("/api/roms/snes/l.sfc", headers=H)
    for h in api.log.handlers:
        h.flush()
    text = (tmp_path / "log" / "r.log").read_text()
    assert "upload" in text and "l.sfc" in text and "exclusão" in text
