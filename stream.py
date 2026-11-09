"""Transmissão da tela do Raspberry para o celular.

O ffmpeg captura a tela, reduz e gera JPEGs em sequência (MJPEG) na saída padrão.
Esta classe separa os quadros e guarda sempre o mais recente; cada celular conectado
recebe esse quadro pelo WebSocket. O ffmpeg só roda enquanto houver quem esteja assistindo.
"""
import os
import shlex
import shutil
import subprocess
import threading
import time

SOI, EOI = b"\xff\xd8", b"\xff\xd9"


class StreamError(Exception):
    pass


def build_command(settings, env=None, exists=os.path.exists, which=shutil.which):
    """Monta a linha de comando do ffmpeg. Levanta StreamError se não houver como capturar."""
    env = os.environ if env is None else env
    if not which("ffmpeg"):
        raise StreamError("ffmpeg não está instalado (sudo apt install ffmpeg)")
    fps = settings.stream_fps
    if settings.stream_input:
        source = shlex.split(settings.stream_input)
    elif env.get("DISPLAY"):
        source = ["-f", "x11grab", "-framerate", str(fps), "-i", env["DISPLAY"]]
    elif exists("/dev/fb0"):
        source = ["-f", "fbdev", "-framerate", str(fps), "-i", "/dev/fb0"]
    else:
        raise StreamError(
            "Nenhuma fonte de tela encontrada (sem DISPLAY nem /dev/fb0). "
            "Defina RETROPAD_STREAM_INPUT, veja o README.")
    filters = [f for f in (settings.stream_filter, "scale=%d:-2" % settings.stream_width) if f]
    return (["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-fflags", "nobuffer", "-flags", "low_delay"]
            + source
            + ["-an", "-vf", ",".join(filters), "-r", str(fps),
               "-c:v", "mjpeg", "-q:v", str(settings.stream_quality), "-f", "image2pipe", "-"])


def split_frames(buffer):
    """Tira de `buffer` (bytearray) todos os JPEGs completos e devolve a lista deles."""
    frames = []
    while True:
        start = buffer.find(SOI)
        if start < 0:
            buffer.clear()
            break
        end = buffer.find(EOI, start + 2)
        if end < 0:
            del buffer[:start]
            break
        frames.append(bytes(buffer[start:end + 2]))
        del buffer[:end + 2]
    return frames


class Streamer:
    def __init__(self, settings, command_factory=None):
        self.settings = settings
        self._command = command_factory or (lambda: build_command(settings))
        self._cond = threading.Condition()
        self._viewers = 0
        self._proc = None
        self._seq = 0
        self._frame = None
        self._error = ""
        self._generation = 0

    # --- visualizadores ---
    def acquire(self):
        """Registra um espectador e liga a captura se for o primeiro. Levanta StreamError."""
        with self._cond:
            if self._viewers == 0:
                self._start()
            self._viewers += 1

    def release(self):
        with self._cond:
            self._viewers = max(0, self._viewers - 1)
            if self._viewers == 0:
                self._stop()

    def _start(self):
        cmd = self._command()          # pode levantar StreamError
        self._error, self._frame = "", None
        try:
            self._proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
        except OSError as exc:
            raise StreamError("não consegui iniciar o ffmpeg: %s" % exc)
        self._generation += 1
        threading.Thread(target=self._reader, args=(self._proc, self._generation), daemon=True).start()

    def _stop(self):
        proc, self._proc = self._proc, None
        self._generation += 1
        self._cond.notify_all()
        if proc and proc.poll() is None:
            proc.terminate()
            # Espera o ffmpeg sair em segundo plano: quem chamou (e segura o lock) não pode travar.
            threading.Thread(target=self._reap, args=(proc,), daemon=True).start()

    @staticmethod
    def _reap(proc):
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

    def _reader(self, proc, generation):
        buf = bytearray()
        try:
            while True:
                chunk = proc.stdout.read(65536)
                if not chunk:
                    break
                buf += chunk
                frames = split_frames(buf)
                if frames:
                    with self._cond:
                        if generation != self._generation:
                            continue      # captura antiga: segue drenando para o ffmpeg conseguir sair
                        self._frame = frames[-1]
                        self._seq += 1
                        self._cond.notify_all()
        finally:
            err = b""
            try:
                err = proc.stderr.read() or b""
            except Exception:
                pass
            with self._cond:
                if generation == self._generation:
                    self._error = err.decode("utf-8", "replace").strip()[-300:] or "a captura de tela parou"
                    self._cond.notify_all()

    # --- leitura ---
    def wait_frame(self, last_seq, timeout=5.0):
        """Espera um quadro mais novo que `last_seq`. Devolve (seq, jpeg) ou (last_seq, None) no timeout.
        Levanta StreamError se a captura falhou."""
        deadline = time.monotonic() + timeout
        with self._cond:
            while self._seq == last_seq or self._frame is None:
                if self._error:
                    raise StreamError(self._error)
                left = deadline - time.monotonic()
                if left <= 0 or self._viewers == 0:
                    return last_seq, None
                self._cond.wait(left)
            return self._seq, self._frame

    @property
    def viewers(self):
        return self._viewers
