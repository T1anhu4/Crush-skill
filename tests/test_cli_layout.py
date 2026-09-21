"""Terminal presentation contracts, using public output and disposable state."""

import os
import re
import select
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from crush_cli import app
from crush_cli.motion import display_width


SGR = re.compile(r"\x1b\[[0-9;]*m")


@pytest.fixture
def cli():
    instance = app.CrushCLI.__new__(app.CrushCLI)
    instance.plain = True
    instance.lang = "zh-Hans"
    instance.data_dir = Path("/tmp/crush-layout-demo/中文/e\u0301/long-memory-location")
    instance.extract_media_tokens = lambda text, turn: (text, [])
    return instance


@pytest.fixture(params=[24, 40, 80])
def columns(request, monkeypatch):
    monkeypatch.setenv("COLUMNS", str(request.param))
    monkeypatch.setenv("LINES", "48")
    monkeypatch.setattr(os, "get_terminal_size", lambda *args: os.terminal_size((request.param, 48)))
    return request.param


def assert_fits(output, columns):
    for line in SGR.sub("", output).splitlines():
        assert display_width(line) < columns, repr(line)


def test_panel_wraps_cjk_and_combining_without_delays(columns, monkeypatch, capsys):
    monkeypatch.setattr(app.time, "sleep", lambda *_: pytest.fail("Presentation must not delay text"))
    app.animated_panel("模型配置 / e\u0301", ["你好世界 " * 18, "https://example.test/" + "path" * 20], plain=False)
    assert_fits(capsys.readouterr().out, columns)


def test_banner_preserves_terminal_history_and_fits(columns, cli, monkeypatch, capsys):
    cli.plain = False
    monkeypatch.setattr(app.os, "system", lambda *_: pytest.fail("Banner must not clear terminal"))
    monkeypatch.setattr(app.time, "sleep", lambda *_: pytest.fail("Banner must not delay text"))
    cli.intro()
    assert_fits(capsys.readouterr().out, columns)


def test_help_fits_and_keeps_commands_discoverable(columns, cli, capsys):
    cli.help()
    output = capsys.readouterr().out
    assert "/import-weflow" in output and "/quit" in output
    assert_fits(output, columns)


def test_reply_wraps_body_and_coaching_and_removes_terminal_controls(columns, cli, capsys):
    reply = "你好 e\u0301 " * 20 + "\n\nsecond paragraph\x1b[2J\x1b]0;injected title\x07end\rhidden"
    cli.print_reply(reply, {"sent_at": 1, "coach": {"interest_read": "关系判断 " * 20, "next_move": "x" * 140}})
    output = capsys.readouterr().out
    assert "second paragraph" in output and "end" in output
    assert "\x1b" not in output and "\r" not in output and "\x07" not in output
    assert "injected title" not in output
    assert_fits(output, columns)


def test_wrap_preserves_paragraphs_and_combining_clusters():
    wrapped = app.wrap("你好e\u0301世界\n\nnext paragraph", width=5)
    assert "\n\n" in wrapped
    assert "e\u0301" in wrapped
    assert "".join(wrapped.split()) == "你好e\u0301世界nextparagraph"
    assert all(display_width(line) <= 5 for line in wrapped.splitlines())


def test_numbered_selector_fits(columns, monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda *_: "2")
    options = [{"name": "English"}, {"name": "Simplified Chinese", "native": "简体中文"}]
    assert app.choose_option("界面语言", "Choose interface language", options, plain=True, lang="en") == options[1]
    assert_fits(capsys.readouterr().out, columns)


def test_arrow_selector_redraws_only_owned_region(columns, monkeypatch, capsys):
    monkeypatch.setenv("TERM", "xterm")
    monkeypatch.delenv("CRUSH_REDUCED_MOTION", raising=False)
    monkeypatch.setattr(app, "supports_arrow_select", lambda: True)
    keys = iter(["\x1b[B", "\n"])
    monkeypatch.setattr(app, "read_key", lambda: next(keys))
    options = [{"name": "English"}, {"name": "中文"}]
    assert app.choose_option("Language", "Choose language", options, plain=False, lang="en") == options[1]
    output = capsys.readouterr().out
    assert "\x1b[2J" not in output and "\x1b[H" not in output and "\x1b[3J" not in output
    assert "\x1b[2K" in output


@pytest.mark.parametrize("kind", ["reduced", "dumb", "short"])
def test_selector_static_fallback(kind, monkeypatch, capsys):
    monkeypatch.setenv("TERM", "dumb" if kind == "dumb" else "xterm")
    monkeypatch.setenv("CRUSH_REDUCED_MOTION", "1" if kind == "reduced" else "0")
    monkeypatch.setenv("LINES", "4" if kind == "short" else "48")
    monkeypatch.setattr(app, "supports_arrow_select", lambda: True)
    monkeypatch.setattr(app, "read_key", lambda: pytest.fail("Must use static input"))
    monkeypatch.setattr("builtins.input", lambda *_: "1")
    app.choose_option("Language", "Choose language", [{"name": "English"}], plain=False, lang="en")
    assert "\x1b[2K" not in capsys.readouterr().out


def test_color_sanitizes_untrusted_text_even_when_disabled(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    assert app.color("safe\x1b[31mred\x1b[0m\x1b]0;bad\x07!", app.C.gold) == "safered!"


def test_dashboard_wraps_labels_and_preserves_values(columns, cli, capsys):
    cli.session_id = "layout"
    cli.runtime = SimpleNamespace(run=lambda *_: {"dashboard": {"cards": {
        "favorability": 65.5, "中文关系状态 e\u0301 / long_metric_label": 100,
    }}})
    cli.dashboard()
    output = capsys.readouterr().out
    assert "65.5" in output and "100" in output and "█" in output
    assert_fits(output, columns)


def test_sessions_wrap_long_ids_and_keep_active_marker(columns, cli, capsys):
    cli.session_id = "current-session-with-a-long-name"
    cli.runtime = SimpleNamespace(run=lambda *_: {"sessions": [{
        "session_id": cli.session_id, "canonical_archetype": "关系类型 e\u0301",
        "updated_at": "2026-09-21 12:00:00",
    }]})
    cli.sessions()
    output = capsys.readouterr().out
    assert "*" in output
    assert cli.session_id in "".join(output.split())
    assert "2026-09-21" in output
    assert_fits(output, columns)


def test_media_list_wraps_paths_and_counts(columns, cli, capsys):
    cli.session_id = "layout"
    path = "/tmp/中文/e\u0301/long-demo-fixture-image-name.png"
    ctx = {"media_assets": [{"payload": {
        "kind": "image", "mediaKey": "fixture-key", "localPath": path,
        "speakerCounts": {"target": 120, "me": 3},
    }}]}
    cli.runtime = SimpleNamespace(memory=SimpleNamespace(sqlite=SimpleNamespace(build_memory_context=lambda *_a, **_kw: ctx)))
    cli.media_show()
    output = capsys.readouterr().out
    assert path in "".join(output.split())
    assert "target=" in output and "120" in output
    assert_fits(output, columns)


def test_media_fallback_wraps_long_asset_paths(columns, cli, capsys):
    cli.render_media_ref({"kind": "image", "mediaKey": "demo-fixture", "localPath": "/tmp/不存在/" + "long-image-name" * 10})
    assert_fits(capsys.readouterr().out, columns)


def test_media_preview_respects_no_color(cli, tmp_path, monkeypatch, capsys):
    asset = tmp_path / "demo-image"
    asset.write_bytes(b"disposable fixture")
    cli.plain = False
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setenv("TERM_PROGRAM", "iTerm.app")
    monkeypatch.setattr(app.sys.stdout, "isatty", lambda: True)
    cli.render_media_ref({"kind": "image", "localPath": str(asset)})
    assert "\x1b" not in capsys.readouterr().out


@pytest.mark.parametrize("columns", [3, 8])
def test_tiny_terminal_uses_contained_banner_panel_and_reply(columns, cli, monkeypatch, capsys):
    monkeypatch.setenv("COLUMNS", str(columns))
    cli.intro()
    app.animated_panel("模型配置 e\u0301", ["中文面板正文"], plain=True)
    cli.print_reply("你好 e\u0301", {"sent_at": 1})
    output = capsys.readouterr().out
    assert "你好" in "".join(output.split())
    assert_fits(output, columns)


@pytest.mark.skipif(os.name == "nt", reason="POSIX PTY regression")
@pytest.mark.parametrize("key", [b"\x1b", b"\x03", b"\x1b[B"])
def test_selector_in_disposable_pty_exits_and_restores_input(key):
    import fcntl
    import pty
    import struct
    import termios

    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 24, 0, 0))
    original = termios.tcgetattr(slave)
    source = (
        "from crush_cli.app import choose_option\n"
        "try:\n"
        " choice = choose_option('Language', 'Choose language', "
        "[{'name':'English'}, {'name':'中文'}], plain=False, lang='en')\n"
        " print('SELECTED:' + choice['name'])\n"
        "except KeyboardInterrupt:\n"
        " print('CANCELLED')\n"
    )
    env = {**os.environ, "TERM": "xterm", "NO_COLOR": "1", "CRUSH_REDUCED_MOTION": "0", "COLUMNS": "24", "LINES": "30"}
    process = subprocess.Popen([sys.executable, "-c", source], stdin=slave, stdout=slave, stderr=slave, env=env)
    output = b""

    def drain():
        nonlocal output
        if select.select([master], [], [], 0.01)[0]:
            output += os.read(master, 65536)

    def wait_raw():
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            drain()
            if not termios.tcgetattr(slave)[3] & termios.ICANON:
                return
        pytest.fail("Selector did not enter raw input")

    try:
        wait_raw()
        os.write(master, key)
        if key == b"\x1b[B":
            deadline = time.monotonic() + 3
            while output.count(b"Choose language") < 2 and time.monotonic() < deadline:
                drain()
            wait_raw()
            os.write(master, b"\r")
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            pytest.fail("Selector blocked after cancel/selection")
        drain()
        assert process.returncode == 0, output.decode(errors="replace")
        assert b"SELECTED:" in output if key == b"\x1b[B" else b"CANCELLED" in output
        assert b"\x1b[2J" not in output and b"\x1b[3J" not in output
        assert not SGR.search(output.decode(errors="replace"))
        restored = termios.tcgetattr(slave)
        # macOS sets the kernel-managed pending-input flag after processing keys.
        restored[3] &= ~getattr(termios, "PENDIN", 0)
        original[3] &= ~getattr(termios, "PENDIN", 0)
        assert restored == original
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        os.close(master)
        os.close(slave)
