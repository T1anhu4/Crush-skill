import importlib
import importlib.util
import io
import re
from types import SimpleNamespace

import pytest


@pytest.fixture
def motion():
    assert importlib.util.find_spec('crush_cli.motion'), 'Reusable terminal motion module is missing'
    return importlib.import_module('crush_cli.motion')


class Terminal(io.StringIO):
    def isatty(self):
        return True


def test_frame_is_deterministic_and_shows_real_elapsed_time(motion):
    first = motion.render_frame('Reading memory', 2.4, 80)
    assert first == motion.render_frame('Reading memory', 2.4, 80)
    assert 'Reading memory' in first and '2.4s' in first
    assert motion.render_frame('Reading memory', 2.5, 80) != first


def test_narrow_cjk_frames_never_reach_terminal_last_column(motion):
    for columns in range(1, 45):
        frame = motion.render_frame('读取记忆，正在回复 e\u0301', 123.4, columns)
        assert motion.display_width(frame) <= columns - 1
        assert '\n' not in frame and '\r' not in frame
    assert motion.display_width('你好e\u0301') == 5


@pytest.mark.parametrize('kind', ['pipe', 'plain', 'dumb', 'reduced'])
def test_static_fallback_has_one_plain_line(motion, monkeypatch, kind):
    monkeypatch.setenv('TERM', 'dumb' if kind == 'dumb' else 'xterm')
    monkeypatch.setenv('CRUSH_REDUCED_MOTION', '1' if kind == 'reduced' else '0')
    stream = io.StringIO() if kind == 'pipe' else Terminal()
    with motion.Spinner('Reading memory', enabled=kind != 'plain', stream=stream) as spinner:
        assert spinner._thread is None
    assert stream.getvalue() == 'Reading memory\n'


def test_static_activity_wraps_and_strips_control_payloads(motion, monkeypatch):
    monkeypatch.setenv('COLUMNS', '24')
    stream = io.StringIO()
    with motion.Spinner('读取记忆 e\u0301 ' * 10 + '\x1b]0;hidden title\x07done', stream=stream):
        pass
    output = stream.getvalue()
    assert 'hidden title' not in output
    assert all(motion.display_width(line) < 24 for line in output.splitlines())


@pytest.mark.parametrize('error', [RuntimeError, KeyboardInterrupt])
def test_cleanup_finishes_before_final_error_output(motion, monkeypatch, error):
    monkeypatch.setenv('TERM', 'xterm')
    monkeypatch.delenv('CRUSH_REDUCED_MOTION', raising=False)
    stream = Terminal()
    with pytest.raises(error):
        with motion.Spinner('Working', stream=stream) as spinner:
            raise error('failed')
    assert not spinner._thread.is_alive()
    print('Final error', file=stream)
    assert stream.getvalue().endswith('\r\x1b[2KFinal error\n')
    assert '\x1b[2J' not in stream.getvalue()


def test_no_color_keeps_motion_without_color_codes(motion, monkeypatch):
    monkeypatch.setenv('TERM', 'xterm')
    monkeypatch.setenv('NO_COLOR', '1')
    monkeypatch.delenv('CRUSH_REDUCED_MOTION', raising=False)
    stream = Terminal()
    with motion.Spinner('Working', stream=stream) as spinner:
        assert spinner._thread is not None
    assert not re.search(r'\x1b\[[0-9;]*m', stream.getvalue())


def test_model_error_prints_after_spinner_exits(monkeypatch, capsys):
    from crush_cli import app

    active = []
    class TrackingSpinner:
        def __init__(self, *args, **kwargs):
            pass
        def __enter__(self):
            active.append(True)
        def __exit__(self, *args):
            active.pop()
            assert not capsys.readouterr().out, 'Error printed inside active spinner'

    def failed_reply(*args):
        raise app.ModelError('model failed')

    monkeypatch.setattr(app, 'Spinner', TrackingSpinner)
    cli = app.CrushCLI.__new__(app.CrushCLI)
    cli.plain = True
    cli.session_id = 'test'
    cli.timeline_state = lambda: {}
    cli.resolve_pending_proactive = lambda *args: None
    cli.save_timeline_state = lambda *args: None
    cli.t = lambda key: key
    cli.runtime = SimpleNamespace(run=lambda *args: {'runtime_prompt': 'test'})
    cli.client = SimpleNamespace(ready=True, reply=failed_reply)
    cli.chat('hello')
    assert not active
    assert 'model failed' in capsys.readouterr().out


def test_help_exposes_existing_entry_points_and_motion_controls():
    from crush_cli.app import build_parser

    help_text = build_parser().format_help()
    for entry in ('crush web', 'crush v3 --help', '--plain', 'CRUSH_REDUCED_MOTION=1'):
        assert entry in help_text


@pytest.mark.parametrize('environment', ['NO_COLOR', 'TERM'])
def test_app_color_respects_terminal_preferences(monkeypatch, environment):
    from crush_cli.app import C, color

    monkeypatch.setenv('TERM', 'xterm')
    monkeypatch.delenv('NO_COLOR', raising=False)
    monkeypatch.setenv(environment, '' if environment == 'NO_COLOR' else 'dumb')
    assert color('model failed', C.red) == 'model failed'


@pytest.mark.parametrize('kind,plain', [('pipe', True), ('dumb', True), ('tty', False), ('no_color', False)])
def test_cli_constructor_uses_static_mode_for_pipe_and_dumb_terminal(monkeypatch, tmp_path, kind, plain):
    from crush_cli import app

    monkeypatch.setenv('TERM', 'dumb' if kind == 'dumb' else 'xterm')
    monkeypatch.delenv('NO_COLOR', raising=False)
    if kind == 'no_color':
        monkeypatch.setenv('NO_COLOR', '1')
    monkeypatch.setattr(app.sys, 'stdout', io.StringIO() if kind == 'pipe' else Terminal())
    monkeypatch.setattr(app, 'import_runtime', lambda path: SimpleNamespace())
    args = app.build_parser().parse_args(['--home', str(tmp_path)])
    assert app.CrushCLI(args).plain is plain
