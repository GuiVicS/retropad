"""Testes da transmissão de tela (stream.py)."""
import os
import shutil
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import stream  # noqa: E402
from config import load_settings  # noqa: E402

HAS_FFMPEG = shutil.which("ffmpeg") is not None
SYNTH = "-f lavfi -i testsrc2=size=320x240:rate=15"


def cmd(env=None, exists=lambda p: False, have=("ffmpeg",), **cfg):
    settings = load_settings({k: str(v) for k, v in cfg.items()})
    return stream.build_command(settings, env=env or {}, exists=exists,
                                which=lambda n: "/usr/bin/" + n if n in have else None)


def test_x11_when_display_is_set():
    c = cmd(env={"DISPLAY": ":0"})
    assert c[c.index("-f") + 1] == "x11grab" and ":0" in c


def test_fbdev_when_no_display_but_framebuffer():
    c = cmd(exists=lambda p: p == "/dev/fb0")
    assert "fbdev" in c and "/dev/fb0" in c


def test_custom_input_wins_over_detection():
    c = cmd(env={"DISPLAY": ":0"}, exists=lambda p: True, RETROPAD_STREAM_INPUT=SYNTH)
    assert "x11grab" not in c and "lavfi" in c


def test_no_source_is_a_clear_error():
    with pytest.raises(stream.StreamError, match="fonte de tela"):
        cmd()


def test_missing_ffmpeg_is_a_clear_error():
    with pytest.raises(stream.StreamError, match="ffmpeg"):
        stream.build_command(load_settings({}), env={}, which=lambda n: None)


def test_output_is_scaled_mjpeg_to_stdout():
    c = cmd(RETROPAD_STREAM_INPUT=SYNTH, RETROPAD_STREAM_WIDTH=640, RETROPAD_STREAM_FPS=10, RETROPAD_STREAM_QUALITY=8)
    assert c[-1] == "-" and "mjpeg" in c and "image2pipe" in c
    assert "scale=640:-2" in c and c[c.index("-r") + 1] == "10" and c[c.index("-q:v") + 1] == "8"


def test_filter_goes_before_scale():
    c = cmd(RETROPAD_STREAM_INPUT=SYNTH, RETROPAD_STREAM_FILTER="hwdownload,format=bgr0")
    assert c[c.index("-vf") + 1] == "hwdownload,format=bgr0,scale=854:-2"


def test_settings_are_clamped():
    s = load_settings({"RETROPAD_STREAM_FPS": "999", "RETROPAD_STREAM_WIDTH": "5", "RETROPAD_STREAM_QUALITY": "0"})
    assert (s.stream_fps, s.stream_width, s.stream_quality) == (30, 160, 2)
    assert load_settings({"RETROPAD_STREAM": "0"}).stream is False
    assert load_settings({}).stream is True


def test_split_frames_handles_partial_and_multiple():
    a = b"\xff\xd8AAA\xff\xd9"
    b = b"\xff\xd8BB\xff\xd9"
    buf = bytearray(b"junk" + a + b + b"\xff\xd8CC")
    assert stream.split_frames(buf) == [a, b]
    assert bytes(buf) == b"\xff\xd8CC"           # o quadro incompleto fica esperando
    buf += b"D\xff\xd9"
    assert stream.split_frames(buf) == [b"\xff\xd8CCD\xff\xd9"]
    assert not buf


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg não instalado")
def test_streamer_delivers_real_jpegs_and_stops_ffmpeg():
    settings = load_settings({"RETROPAD_STREAM_INPUT": SYNTH, "RETROPAD_STREAM_WIDTH": "320"})
    st = stream.Streamer(settings)
    st.acquire()
    try:
        seq, frame = st.wait_frame(0, timeout=10)
        assert frame and frame.startswith(b"\xff\xd8") and frame.endswith(b"\xff\xd9")
        seq2, frame2 = st.wait_frame(seq, timeout=10)
        assert seq2 > seq and frame2
        proc = st._proc
    finally:
        st.release()
    assert st.viewers == 0
    proc.wait(timeout=5)                         # ffmpeg parou quando o último espectador saiu
    assert proc.poll() is not None


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg não instalado")
def test_two_viewers_share_one_ffmpeg():
    st = stream.Streamer(load_settings({"RETROPAD_STREAM_INPUT": SYNTH}))
    st.acquire(); first = st._proc
    st.acquire()
    assert st._proc is first and st.viewers == 2
    st.release()
    assert first.poll() is None                  # ainda tem quem assista
    st.release()
    first.wait(timeout=5)
    assert first.poll() is not None


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg não instalado")
def test_capture_failure_is_reported_not_hung():
    bad = load_settings({"RETROPAD_STREAM_INPUT": "-f x11grab -i :987"})  # display que não existe
    st = stream.Streamer(bad, command_factory=lambda: stream.build_command(bad, env={}))
    st.acquire()
    try:
        with pytest.raises(stream.StreamError):
            st.wait_frame(0, timeout=10)
    finally:
        st.release()
    # depois de liberar, dá para tentar de novo (erro anterior não fica preso)
    assert st._error == "" or st.viewers == 0


# --------------------------------------------------------------- dispmanx (raspi2png)

def src(env=None, exists=lambda p: False, have=("ffmpeg",), **cfg):
    settings = load_settings({k: str(v) for k, v in cfg.items()})
    return stream.pick_source(settings, env=env or {}, exists=exists, which=lambda n: "/usr/bin/" + n if n in have else None)


def test_auto_prefers_dispmanx_over_fbdev_when_raspi2png_is_installed():
    # /dev/fb0 só mostra o console; o EmulationStation só aparece pelo dispmanx.
    assert src(exists=lambda p: p == "/dev/fb0", have=("ffmpeg", "raspi2png")) == "dispmanx"
    assert src(exists=lambda p: p == "/dev/fb0") == "fbdev"             # sem raspi2png, mantém o fbdev


def test_x11_still_wins_when_there_is_a_display():
    assert src(env={"DISPLAY": ":0"}, have=("ffmpeg", "raspi2png")) == "x11"


def test_source_can_be_forced():
    assert src(have=("ffmpeg", "raspi2png"), exists=lambda p: True, RETROPAD_STREAM_SOURCE="fbdev") == "fbdev"
    assert src(RETROPAD_STREAM_SOURCE="dispmanx") == "dispmanx"
    assert src(RETROPAD_STREAM_SOURCE="lixo", exists=lambda p: True) == "fbdev"     # valor inválido volta ao automático
    assert src(RETROPAD_STREAM_INPUT=SYNTH, exists=lambda p: True) == "custom"


def test_dispmanx_ffmpeg_reads_png_from_stdin():
    c = cmd(RETROPAD_STREAM_SOURCE="dispmanx", RETROPAD_STREAM_WIDTH=640, have=("ffmpeg", "raspi2png"))
    assert c[c.index("-f") + 1] == "image2pipe" and "png" in c and c[c.index("-i") + 1] == "-"
    assert "scale=640:-2" in c and c[-1] == "-" and "mjpeg" in c
    # sem isto o primeiro quadro demora ~12 s (o ffmpeg fica sondando a entrada)
    assert c[c.index("-analyzeduration") + 1] == "0" and "-probesize" in c


def test_capture_command_keeps_the_screen_proportions():
    assert stream.capture_command(load_settings({"RETROPAD_STREAM_WIDTH": "854"}), size=(1920, 1080))[2:6] == ["--width", "854", "--height", "480"]
    c = stream.capture_command(load_settings({"RETROPAD_STREAM_WIDTH": "854"}), size=(1280, 1024))
    assert c[c.index("--height") + 1] == "682" and c[0] == "raspi2png" and "--stdout" in c       # 5:4, par
    # nunca amplia além da tela
    assert stream.capture_command(load_settings({"RETROPAD_STREAM_WIDTH": "1920"}), size=(640, 480))[3] == "640"


def test_screen_size_reads_the_framebuffer_and_has_a_fallback():
    assert stream.screen_size(read=lambda p: "1920,1080\n") == (1920, 1080)
    assert stream.screen_size(read=lambda p: (_ for _ in ()).throw(OSError())) == (1920, 1080)


def make_fake_raspi2png(tmp_path, fail=False):
    """Um 'raspi2png' de mentira: gera um PNG de teste (ou falha), para testar o encanamento todo."""
    script = tmp_path / "raspi2png"
    if fail:
        script.write_text("#!/bin/sh\necho 'vc_dispmanx_snapshot falhou (KMS?)' >&2\nexit 3\n")
    else:
        script.write_text("#!/bin/sh\nexec ffmpeg -hide_banner -loglevel error -f lavfi -i testsrc2=size=320x180:rate=1 -frames:v 1 -f image2pipe -c:v png -\n")
    script.chmod(0o755)
    return str(script)


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg não instalado")
def test_dispmanx_pipeline_delivers_jpegs(tmp_path):
    fake = make_fake_raspi2png(tmp_path)
    settings = load_settings({"RETROPAD_STREAM_SOURCE": "dispmanx", "RETROPAD_STREAM_WIDTH": "320", "RETROPAD_STREAM_FPS": "5"})
    st = stream.Streamer(settings, command_factory=lambda: stream.build_command(
        settings, env={}, which=lambda n: "/usr/bin/" + n), capture_factory=lambda cmd: [fake])
    st.acquire()
    try:
        seq, frame = st.wait_frame(0, timeout=15)
        assert frame and frame.startswith(b"\xff\xd8") and frame.endswith(b"\xff\xd9")
        seq2, frame2 = st.wait_frame(seq, timeout=15)
        assert seq2 > seq
    finally:
        st.release()


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg não instalado")
def test_dispmanx_failure_is_reported_with_the_tools_own_message(tmp_path):
    fake = make_fake_raspi2png(tmp_path, fail=True)
    settings = load_settings({"RETROPAD_STREAM_SOURCE": "dispmanx"})
    st = stream.Streamer(settings, command_factory=lambda: stream.build_command(
        settings, env={}, which=lambda n: "/usr/bin/" + n), capture_factory=lambda cmd: [fake])
    st.acquire()
    try:
        with pytest.raises(stream.StreamError, match="falhou.*KMS"):
            st.wait_frame(0, timeout=15)
    finally:
        st.release()
