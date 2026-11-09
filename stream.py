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


SOURCES = ("auto", "x11", "dispmanx", "fbdev")


def pick_source(settings, env=None, exists=os.path.exists, which=shutil.which):
    """Decide de onde vem a imagem: 'custom', 'x11', 'dispmanx' ou 'fbdev'."""
    env = os.environ if env is None else env
    if settings.stream_input:
        return "custom"
    want = settings.stream_source if settings.stream_source in SOURCES else "auto"
    if want != "auto":
        return want
    if env.get("DISPLAY"):
        return "x11"
    # O /dev/fb0 só mostra o console de texto. O EmulationStation e os jogos do Pi 0 a 3 só aparecem
    # na captura do dispmanx (raspi2png), por isso ele tem prioridade quando está instalado.
    if which("raspi2png"):
        return "dispmanx"
    if exists("/dev/fb0"):
        return "fbdev"
    raise StreamError(
        "Nenhuma fonte de tela encontrada (sem DISPLAY, raspi2png nem /dev/fb0). "
        "Rode scripts/diagnose-screen.sh e veja o README.")


def screen_size(read=lambda p: open(p).read()):
    """Tamanho da tela do Pi (largura, altura), lido do framebuffer; 16:9 se não souber."""
    try:
        w, h = [int(x) for x in read("/sys/class/graphics/fb0/virtual_size").strip().split(",")]
        if w > 0 and h > 0:
            return w, h
    except Exception:
        pass
    return 1920, 1080


def capture_command(settings, size=None):
    """Comando que tira UM retrato da tela do Pi (dispmanx) e escreve o PNG na saída padrão."""
    w0, h0 = size or screen_size()
    w = min(settings.stream_width, w0)
    h = max(2, int(round(w * h0 / float(w0))) // 2 * 2)          # altura proporcional, par
    return ["raspi2png", "--stdout", "--width", str(w), "--height", str(h), "--compression", "1"]


def build_command(settings, env=None, exists=os.path.exists, which=shutil.which):
    """Monta a linha de comando do ffmpeg. Levanta StreamError se não houver como capturar."""
    env = os.environ if env is None else env
    if not which("ffmpeg"):
        raise StreamError("ffmpeg não está instalado (sudo apt install ffmpeg)")
    fps = settings.stream_fps
    kind = pick_source(settings, env, exists, which)
    if kind == "custom":
        source = shlex.split(settings.stream_input)
    elif kind == "x11":
        if not env.get("DISPLAY"):
            raise StreamError("RETROPAD_STREAM_SOURCE=x11 mas não há DISPLAY")
        source = ["-f", "x11grab", "-framerate", str(fps), "-i", env["DISPLAY"]]
    elif kind == "dispmanx":
        if not which("raspi2png"):
            raise StreamError("raspi2png não está instalado (veja o README, seção da tela do sistema)")
        # Os retratos chegam um a um pela entrada padrão (veja Streamer._feed).
        # Sem limitar a sondagem, o ffmpeg espera ~12 s de retratos antes de mostrar o primeiro quadro.
        source = ["-probesize", "32768", "-analyzeduration", "0",
                  "-f", "image2pipe", "-c:v", "png", "-framerate", str(fps), "-i", "-"]
    else:
        if not exists("/dev/fb0"):
            raise StreamError("RETROPAD_STREAM_SOURCE=fbdev mas /dev/fb0 não existe")
        source = ["-f", "fbdev", "-framerate", str(fps), "-i", "/dev/fb0"]
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
    def __init__(self, settings, command_factory=None, capture_factory=None):
        self.settings = settings
        self._capture = capture_factory
        self._default_command = command_factory is None
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
        feeder = self._feeder_command(cmd)
        self._error, self._frame = "", None
        try:
            self._proc = subprocess.Popen(cmd, stdin=subprocess.PIPE if feeder else None,
                                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
        except OSError as exc:
            raise StreamError("não consegui iniciar o ffmpeg: %s" % exc)
        self._generation += 1
        threading.Thread(target=self._reader, args=(self._proc, self._generation), daemon=True).start()
        if feeder:
            threading.Thread(target=self._feed, args=(self._proc, feeder, self._generation), daemon=True).start()

    def _feeder_command(self, cmd):
        """Para o dispmanx, o ffmpeg lê retratos pela entrada padrão; aqui vem o comando que os tira."""
        if self._capture is not None:
            return self._capture(cmd)
        if self._default_command and pick_source(self.settings) == "dispmanx":
            return capture_command(self.settings)
        return None

    def _feed(self, proc, capture, generation):
        """Tira retratos da tela (um processo por quadro) e entrega ao ffmpeg, no ritmo do fps."""
        gap = 1.0 / self.settings.stream_fps
        failure = ""
        try:
            while generation == self._generation and proc.poll() is None:
                started = time.monotonic()
                try:
                    shot = subprocess.run(capture, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
                except Exception as exc:
                    failure = "%s: %s" % (capture[0], exc)
                    break
                if shot.returncode != 0 or not shot.stdout:
                    failure = "%s falhou: %s" % (capture[0], (shot.stderr or b"").decode("utf-8", "replace").strip()[-200:] or "sem imagem")
                    break
                try:
                    proc.stdin.write(shot.stdout)
                    proc.stdin.flush()
                except (BrokenPipeError, OSError, ValueError):
                    break
                left = gap - (time.monotonic() - started)
                if left > 0:
                    time.sleep(left)
        finally:
            try:
                proc.stdin.close()
            except Exception:
                pass
            if failure:
                with self._cond:
                    if generation == self._generation:
                        self._error = failure
                        self._cond.notify_all()

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
                    # Se o alimentador (raspi2png) já explicou a falha, essa explicação vale mais.
                    self._error = self._error or err.decode("utf-8", "replace").strip()[-300:] or "a captura de tela parou"
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
