"""Configuração do RetroPad, lida de variáveis de ambiente."""
import os
from dataclasses import dataclass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _int(env, key, default):
    try:
        return int(env.get(key, default))
    except (TypeError, ValueError):
        return default


def _flag(env, key):
    return str(env.get(key, "")).strip().lower() in ("1", "true", "yes", "sim", "on")


@dataclass(frozen=True)
class Settings:
    host: str = "0.0.0.0"
    port: int = 8080
    pin: str = ""                 # PIN do controle (WebSocket)
    admin_pin: str = ""           # PIN do gerenciador de ROMs
    roms_dir: str = ""
    systems_file: str = os.path.join(BASE_DIR, "systems.json")
    max_upload_mb: int = 4096     # limite por arquivo
    min_free_mb: int = 200        # margem mínima que deve sobrar no cartão
    max_attempts: int = 5         # erros de PIN antes do bloqueio
    lock_seconds: int = 60
    log_file: str = os.path.join(BASE_DIR, "logs", "retropad.log")
    # Túnel ngrok (HTTPS público, necessário para instalar o PWA fora de localhost)
    ngrok: bool = False
    ngrok_authtoken: str = ""
    ngrok_domain: str = ""        # domínio fixo (ex.: meu-retropad.ngrok-free.app); vazio = aleatório
    ngrok_allow_admin: bool = False   # False: /admin e /api só na rede local
    url_file: str = os.path.join(BASE_DIR, "logs", "tunnel_url.txt")
    # Transmissão da tela do Raspberry para o celular
    stream: bool = True
    stream_fps: int = 12
    stream_width: int = 854       # largura da imagem enviada (altura proporcional)
    stream_quality: int = 6       # JPEG do ffmpeg: 2 (melhor) a 31 (pior)
    stream_source: str = "auto"   # auto | x11 | dispmanx | fbdev (auto escolhe pelo que o Pi tem)
    stream_input: str = ""        # opções de entrada do ffmpeg; vazio = detecta (x11grab ou fbdev)
    stream_filter: str = ""       # filtro ffmpeg antes do redimensionamento (ex.: para kmsgrab)

    @property
    def max_upload_bytes(self):
        return self.max_upload_mb * 1024 * 1024

    @property
    def min_free_bytes(self):
        return self.min_free_mb * 1024 * 1024


def load_settings(env=None):
    env = os.environ if env is None else env
    pin = env.get("RETROPAD_PIN", "")
    return Settings(
        host=env.get("RETROPAD_HOST", "0.0.0.0"),
        port=_int(env, "RETROPAD_PORT", 8080),
        pin=pin,
        # Sem PIN de admin separado, usa o PIN do controle.
        admin_pin=env.get("RETROPAD_ADMIN_PIN", "") or pin,
        roms_dir=os.path.expanduser(env.get("RETROPAD_ROMS", "~/RetroPie/roms")),
        systems_file=env.get("RETROPAD_SYSTEMS", os.path.join(BASE_DIR, "systems.json")),
        max_upload_mb=_int(env, "RETROPAD_MAX_UPLOAD_MB", 4096),
        min_free_mb=_int(env, "RETROPAD_MIN_FREE_MB", 200),
        max_attempts=_int(env, "RETROPAD_PIN_ATTEMPTS", 5),
        lock_seconds=_int(env, "RETROPAD_PIN_LOCK_SECONDS", 60),
        log_file=env.get("RETROPAD_LOG", os.path.join(BASE_DIR, "logs", "retropad.log")),
        ngrok=_flag(env, "RETROPAD_NGROK"),
        ngrok_authtoken=env.get("RETROPAD_NGROK_AUTHTOKEN", "") or env.get("NGROK_AUTHTOKEN", ""),
        ngrok_domain=env.get("RETROPAD_NGROK_DOMAIN", "").strip().replace("https://", "").rstrip("/"),
        ngrok_allow_admin=_flag(env, "RETROPAD_NGROK_ADMIN"),
        url_file=env.get("RETROPAD_URL_FILE", os.path.join(BASE_DIR, "logs", "tunnel_url.txt")),
        stream=str(env.get("RETROPAD_STREAM", "1")).strip().lower() not in ("0", "false", "no", "nao", "não", "off"),
        stream_fps=max(1, min(30, _int(env, "RETROPAD_STREAM_FPS", 12))),
        stream_width=max(160, min(1920, _int(env, "RETROPAD_STREAM_WIDTH", 854))),
        stream_quality=max(2, min(31, _int(env, "RETROPAD_STREAM_QUALITY", 6))),
        stream_source=(env.get("RETROPAD_STREAM_SOURCE", "auto").strip().lower() or "auto"),
        stream_input=env.get("RETROPAD_STREAM_INPUT", "").strip(),
        stream_filter=env.get("RETROPAD_STREAM_FILTER", "").strip(),
    )


settings = load_settings()
