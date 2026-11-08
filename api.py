"""Rotas HTTP do gerenciador de ROMs (/api/*), protegidas pelo PIN de admin."""
import hmac
import logging
import os
import time
from functools import wraps
from logging.handlers import RotatingFileHandler

from flask import Blueprint, current_app, jsonify, request

import roms
from roms import RomError

bp = Blueprint("api", __name__)
log = logging.getLogger("retropad.admin")


class PinLimiter:
    """Bloqueia um IP por `lock_seconds` depois de `max_attempts` PINs errados."""

    def __init__(self, max_attempts, lock_seconds, clock=time.monotonic):
        self.max_attempts, self.lock_seconds, self.clock = max_attempts, lock_seconds, clock
        self.fails = {}   # ip -> (erros, bloqueado_até)

    def wait(self, ip):
        _, until = self.fails.get(ip, (0, 0))
        remaining = until - self.clock()
        return int(remaining) + 1 if remaining > 0 else 0

    def fail(self, ip):
        count, until = self.fails.get(ip, (0, 0))
        if until and self.clock() >= until:      # bloqueio anterior já expirou
            count = 0
        count += 1
        until = self.clock() + self.lock_seconds if count >= self.max_attempts else 0
        self.fails[ip] = (count, until)
        if len(self.fails) > 256:                # evita crescer sem limite
            self.fails = {k: v for k, v in self.fails.items() if v[1] > self.clock()}

    def ok(self, ip):
        self.fails.pop(ip, None)


def _cfg():
    return current_app.config["RETROPAD"]


def _systems():
    return current_app.config["RETROPAD_SYSTEMS"]


def _err(message, status):
    return jsonify({"error": message}), status


def require_admin(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        cfg, ip = _cfg(), request.remote_addr
        if not cfg.admin_pin:
            return _err("Gerenciador desativado: defina RETROPAD_ADMIN_PIN (ou RETROPAD_PIN) no servidor.", 503)
        wait = current_app.config["RETROPAD_LIMITER"].wait(ip)
        if wait:
            return _err(f"Muitas tentativas. Aguarde {wait}s.", 429)
        pin = request.headers.get("X-Admin-PIN", "")
        if not pin:
            return _err("Informe o PIN", 401)
        if not hmac.compare_digest(pin.encode(), cfg.admin_pin.encode()):
            current_app.config["RETROPAD_LIMITER"].fail(ip)
            log.warning("PIN de admin incorreto ip=%s", ip)
            return _err("PIN incorreto", 401)
        current_app.config["RETROPAD_LIMITER"].ok(ip)
        return view(*args, **kwargs)
    return wrapper


@bp.errorhandler(RomError)
def _rom_error(exc):
    log.info("recusado ip=%s %s %s: %s", request.remote_addr, request.method, request.path, exc.message)
    return _err(exc.message, exc.status)


@bp.get("/api/status")
@require_admin
def status():
    cfg = _cfg()
    return jsonify({
        "disk": roms.free_space(cfg.roms_dir),
        "roms_dir": cfg.roms_dir,
        "max_upload": cfg.max_upload_bytes,
        "min_free": cfg.min_free_bytes,
        "tunnel_url": current_app.config.get("RETROPAD_TUNNEL_URL", ""),
    })


@bp.get("/api/systems")
@require_admin
def systems():
    return jsonify(roms.list_systems(_cfg().roms_dir, _systems()))


@bp.get("/api/roms/<system>")
@require_admin
def list_roms(system):
    return jsonify(roms.list_roms(_cfg().roms_dir, _systems(), system))


@bp.get("/api/check/<system>")
@require_admin
def check(system):
    """Valida nome, extensão, tamanho e espaço antes de enviar o arquivo."""
    cfg = _cfg()
    size = request.args.get("size", type=int)
    name, _, exists = roms.prepare_upload(
        cfg.roms_dir, _systems(), system, request.args.get("name", ""),
        size, cfg.max_upload_bytes, cfg.min_free_bytes)
    return jsonify({"name": name, "exists": exists})


@bp.post("/api/roms/<system>")
@require_admin
def upload(system):
    """Aceita o corpo cru (?name=arquivo.ext), usado pela página, ou multipart (campo 'file')."""
    cfg = _cfg()
    overwrite = request.args.get("overwrite") == "1"
    if request.mimetype == "multipart/form-data":
        f = request.files.get("file")
        if f is None or not f.filename:
            raise RomError("Nenhum arquivo enviado")
        raw_name, stream = f.filename, f.stream
    else:
        raw_name, stream = request.args.get("name", ""), request.stream
    size = request.content_length

    result = roms.save_stream(
        cfg.roms_dir, _systems(), system, raw_name, stream, size,
        cfg.max_upload_bytes, cfg.min_free_bytes, overwrite)
    log.info("upload ip=%s sistema=%s arquivo=%r bytes=%d sobrescreveu=%s",
             request.remote_addr, system, result["name"], result["size"], result["overwritten"])
    return jsonify(result), 201


@bp.delete("/api/roms/<system>/<path:filename>")
@require_admin
def delete(system, filename):
    roms.delete_rom(_cfg().roms_dir, _systems(), system, filename)
    log.info("exclusão ip=%s sistema=%s arquivo=%r", request.remote_addr, system, filename)
    return jsonify({"ok": True})


@bp.post("/api/roms/<system>/<path:filename>/rename")
@require_admin
def rename(system, filename):
    body = request.get_json(silent=True) or {}
    new_name = roms.rename_rom(_cfg().roms_dir, _systems(), system, filename, body.get("name", ""))
    log.info("renomeado ip=%s sistema=%s %r -> %r", request.remote_addr, system, filename, new_name)
    return jsonify({"name": new_name})


def _setup_logging(path):
    log.setLevel(logging.INFO)
    for h in list(log.handlers):
        log.removeHandler(h)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # Rotação simples: 256 KB x 3 arquivos, pouco desgaste no cartão SD.
        handler = RotatingFileHandler(path, maxBytes=256 * 1024, backupCount=2, encoding="utf-8")
    except OSError as exc:
        print(f"[RetroPad] sem arquivo de log ({exc}); usando só o console")
        handler = logging.StreamHandler()
    handler.setFormatter(fmt)
    log.addHandler(handler)


def init_app(app, cfg):
    """Registra as rotas e as configurações do gerenciador no app Flask."""
    app.config["RETROPAD"] = cfg
    app.config["RETROPAD_SYSTEMS"] = roms.load_systems(cfg.systems_file)
    app.config["RETROPAD_LIMITER"] = PinLimiter(cfg.max_attempts, cfg.lock_seconds)
    # Defesa extra: o Flask corta corpos maiores que o limite (+1 MB de folga do multipart).
    app.config["MAX_CONTENT_LENGTH"] = cfg.max_upload_bytes + 1024 * 1024
    _setup_logging(cfg.log_file)
    app.register_blueprint(bp)

    @app.errorhandler(413)
    def too_large(_exc):
        return _err(f"Arquivo maior que o limite de {cfg.max_upload_mb} MB", 413)
