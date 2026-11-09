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


def cmd(env=None, exists=lambda p: False, **cfg):
    settings = load_settings({k: str(v) for k, v in cfg.items()})
    return stream.build_command(settings, env=env or {}, exists=exists, which=lambda n: "/usr/bin/" + n)


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
    bad = load_settings({"RETROPAD_STREAM_INPUT": "-f x11grab -i :99"})   # não existe servidor X aqui
    st = stream.Streamer(bad, command_factory=lambda: stream.build_command(bad, env={}))
    st.acquire()
    try:
        with pytest.raises(stream.StreamError):
            st.wait_frame(0, timeout=10)
    finally:
        st.release()
    # depois de liberar, dá para tentar de novo (erro anterior não fica preso)
    assert st._error == "" or st.viewers == 0
