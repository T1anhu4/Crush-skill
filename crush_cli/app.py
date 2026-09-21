from __future__ import annotations

import argparse
import getpass
import json
import os
import random
import re
import select
import shlex
import shutil
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
import base64
from typing import Any, Dict, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse, urlunparse
from urllib.request import Request

from crush_core.provider import ProviderError, urlopen

from crush_cli.motion import Spinner
from crush_cli.presentation import display_width, panel_lines, safe_text, terminal_width, wrap_lines

try:
    import termios
    import tty
except ImportError:  # pragma: no cover - Windows fallback
    termios = None  # type: ignore
    tty = None  # type: ignore


ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / "Crush.skill"
DEFAULT_HOME = Path(os.environ.get("CRUSH_HOME", "~/.crush")).expanduser()


SUPPORTED_LANGUAGES: list[dict[str, str]] = [
    {"code": "en", "name": "English", "native": "English"},
    {"code": "zh-Hans", "name": "Simplified Chinese", "native": "简体中文"},
    {"code": "zh-Hant", "name": "Traditional Chinese", "native": "繁體中文"},
    {"code": "ru", "name": "Russian", "native": "Русский"},
    {"code": "ja", "name": "Japanese", "native": "日本語"},
]

LANG: dict[str, dict[str, str]] = {
    "en": {
        "tagline": "Relationship Persona Simulation Engine",
        "memory": "Local memory: {path}",
        "hint": "Type /help for commands. Type naturally to chat.",
        "no_model": "No chat model configured yet. Starting model setup wizard...",
        "bye": "Session saved locally. Keep practicing with care.",
        "unknown": "Unknown command: {cmd}. Try /help.",
        "commands": "Commands",
        "setup": "configure chat model with guided picker",
        "language_cmd": "change interface language",
        "model_cmd": "change model provider, model, base URL, and API key",
        "start_cmd": "create/reset current persona session",
        "import_cmd": "import chat records; omit file to paste multiline text",
        "sessions_cmd": "list local sessions",
        "use_cmd": "switch session",
        "dashboard_cmd": "show relationship state",
        "postmortem_cmd": "relationship replay report",
        "distill_cmd": "evidence-first persona and relationship distillation report",
        "stop_cmd": "pause timeline and proactive messages",
        "continue_cmd": "resume timeline and proactive messages",
        "config_cmd": "advanced raw config editing",
        "where_cmd": "show local config and memory paths",
        "quit_cmd": "exit",
        "model_title": "Model Setup",
        "language_title": "Language",
        "select_provider": "Choose a model provider",
        "select_language": "Choose interface language",
        "custom_base": "Custom OpenAI-compatible base URL",
        "model_name_prompt": "Model name [{default}]: ",
        "base_prompt": "API base URL [{default}]: ",
        "key_prompt": "API key: ",
        "model_saved": "Model config saved: {provider} / {model}",
        "language_saved": "Language saved: {language}",
        "arrow_hint": "Use ↑/↓ and Enter. Press Esc to cancel.",
        "number_hint": "Enter a number and press Enter.",
        "provider_note": "Provider: {name}\nBase URL: {base}\nTip: {tip}",
        "custom_tip": "Paste the provider's OpenAI-compatible endpoint, usually ending with /v1.",
        "model_tip": "Enter the exact model id from your provider dashboard, for example gpt-4o-mini or deepseek-chat.",
        "key_tip": "Paste your API key. Input is hidden when your terminal supports it.",
        "model_missing_once": "Model not configured. Run /model to configure a provider.",
        "runtime_preview": "Hidden runtime prompt preview:",
        "spinner_state": "Reading memory, updating state, sensing subtext...",
        "spinner_reply": "Letting the persona answer...",
        "turn_saved_after_error": "This user message was saved locally; fix model config and keep going.",
        "timeline_paused": "Timeline paused. Use /continue to resume time progression.",
        "timeline_resumed": "Timeline resumed. She may message proactively when it feels natural.",
        "readout": "Readout",
        "risk": "risk",
        "judgment": "Signal",
        "next_line": "Next move",
        "time_passes": "time passes",
        "timeline_waiting": "Waiting for your reply",
    },
    "zh-Hans": {
        "tagline": "关系人格模拟与聊天训练引擎",
        "memory": "本地记忆: {path}",
        "hint": "输入 /help 查看命令。也可以直接自然聊天。",
        "no_model": "还没有配置聊天模型，正在进入模型配置向导...",
        "bye": "会话已保存。愿你把学到的东西带回现实。",
        "unknown": "未知命令: {cmd}。试试 /help。",
        "commands": "命令",
        "setup": "使用向导配置聊天模型",
        "language_cmd": "切换界面语言",
        "model_cmd": "修改模型厂商、模型名、Base URL 和 API Key",
        "start_cmd": "创建/重置当前人格会话",
        "import_cmd": "导入聊天记录；不传文件则粘贴多行文本",
        "sessions_cmd": "列出本地会话",
        "use_cmd": "切换会话",
        "dashboard_cmd": "查看关系状态",
        "postmortem_cmd": "关系复盘报告",
        "distill_cmd": "基于证据的人格与关系蒸馏报告",
        "stop_cmd": "暂停时间线和主动消息",
        "continue_cmd": "继续时间线和主动消息",
        "config_cmd": "高级原始配置编辑",
        "where_cmd": "显示本地配置和记忆路径",
        "quit_cmd": "退出",
        "model_title": "模型配置",
        "language_title": "语言",
        "select_provider": "选择模型厂商",
        "select_language": "选择界面语言",
        "custom_base": "自定义 OpenAI-compatible Base URL",
        "model_name_prompt": "模型名称 [{default}]: ",
        "base_prompt": "API Base URL [{default}]: ",
        "key_prompt": "API Key: ",
        "model_saved": "模型配置已保存: {provider} / {model}",
        "language_saved": "语言已保存: {language}",
        "arrow_hint": "使用 ↑/↓ 和 Enter 选择，Esc 取消。",
        "number_hint": "输入数字后回车。",
        "provider_note": "厂商: {name}\nBase URL: {base}\n提示: {tip}",
        "custom_tip": "粘贴服务商提供的 OpenAI-compatible endpoint，通常以 /v1 结尾。",
        "model_tip": "填写服务商后台的准确模型 id，比如 gpt-4o-mini 或 deepseek-chat。",
        "key_tip": "粘贴 API Key；终端支持时会隐藏输入。",
        "model_missing_once": "还没有配置模型。请运行 /model 配置厂商。",
        "runtime_preview": "隐藏 runtime prompt 预览:",
        "spinner_state": "读取记忆、更新状态、感知潜台词...",
        "spinner_reply": "让人格自然回应...",
        "turn_saved_after_error": "这次用户消息已写入本地记忆；修好模型配置后可以继续聊。",
        "timeline_paused": "时间线已暂停。使用 /continue 恢复。",
        "timeline_resumed": "时间线已继续。她会在自然时机主动发消息。",
        "readout": "读秒",
        "risk": "风险",
        "judgment": "判断",
        "next_line": "下一句",
        "time_passes": "时间流逝",
        "timeline_waiting": "正在等你回复",
    },
    "zh-Hant": {
        "tagline": "關係人格模擬與聊天訓練引擎",
        "memory": "本地記憶: {path}",
        "hint": "輸入 /help 查看命令。也可以直接自然聊天。",
        "no_model": "尚未配置聊天模型，正在進入模型配置嚮導...",
        "bye": "會話已保存。願你把學到的東西帶回現實。",
        "unknown": "未知命令: {cmd}。試試 /help。",
        "commands": "命令",
        "setup": "使用嚮導配置聊天模型",
        "language_cmd": "切換介面語言",
        "model_cmd": "修改模型廠商、模型名、Base URL 和 API Key",
        "start_cmd": "建立/重置目前人格會話",
        "import_cmd": "匯入聊天記錄；不傳文件則貼上多行文本",
        "sessions_cmd": "列出本地會話",
        "use_cmd": "切換會話",
        "dashboard_cmd": "查看關係狀態",
        "postmortem_cmd": "關係復盤報告",
        "distill_cmd": "基於證據的人格與關係蒸餾報告",
        "stop_cmd": "暫停時間線和主動消息",
        "continue_cmd": "繼續時間線和主動消息",
        "config_cmd": "進階原始配置編輯",
        "where_cmd": "顯示本地配置和記憶路徑",
        "quit_cmd": "退出",
        "model_title": "模型配置",
        "language_title": "語言",
        "select_provider": "選擇模型廠商",
        "select_language": "選擇介面語言",
        "custom_base": "自訂 OpenAI-compatible Base URL",
        "model_name_prompt": "模型名稱 [{default}]: ",
        "base_prompt": "API Base URL [{default}]: ",
        "key_prompt": "API Key: ",
        "model_saved": "模型配置已保存: {provider} / {model}",
        "language_saved": "語言已保存: {language}",
        "arrow_hint": "使用 ↑/↓ 和 Enter 選擇，Esc 取消。",
        "number_hint": "輸入數字後回車。",
        "provider_note": "廠商: {name}\nBase URL: {base}\n提示: {tip}",
        "custom_tip": "貼上服務商提供的 OpenAI-compatible endpoint，通常以 /v1 結尾。",
        "model_tip": "填寫服務商後台的準確模型 id，比如 gpt-4o-mini 或 deepseek-chat。",
        "key_tip": "貼上 API Key；終端支援時會隱藏輸入。",
        "model_missing_once": "尚未配置模型。請執行 /model 配置廠商。",
        "runtime_preview": "隱藏 runtime prompt 預覽:",
        "spinner_state": "讀取記憶、更新狀態、感知潛台詞...",
        "spinner_reply": "讓人格自然回應...",
        "turn_saved_after_error": "這次用戶消息已寫入本地記憶；修好模型配置後可以繼續聊。",
        "timeline_paused": "時間線已暫停。使用 /continue 恢復。",
        "timeline_resumed": "時間線已繼續。她會在自然時機主動發消息。",
        "readout": "讀秒",
        "risk": "風險",
        "judgment": "判斷",
        "next_line": "下一句",
        "time_passes": "時間流逝",
        "timeline_waiting": "正在等你回覆",
    },
    "ru": {
        "tagline": "Engine for Relationship Persona Simulation",
        "memory": "Local memory: {path}",
        "hint": "Type /help for commands. Chat naturally.",
        "no_model": "No chat model configured. Starting model setup wizard...",
        "bye": "Session saved locally. Practice kindly.",
        "unknown": "Unknown command: {cmd}. Try /help.",
        "commands": "Commands",
        "setup": "configure chat model with guided picker",
        "language_cmd": "change interface language",
        "model_cmd": "change model provider, model, base URL, and API key",
        "start_cmd": "create/reset current persona session",
        "import_cmd": "import chat records",
        "sessions_cmd": "list local sessions",
        "use_cmd": "switch session",
        "dashboard_cmd": "show relationship state",
        "postmortem_cmd": "relationship replay report",
        "distill_cmd": "evidence-first relationship distillation report",
        "stop_cmd": "pause timeline",
        "continue_cmd": "resume timeline",
        "config_cmd": "advanced raw config editing",
        "where_cmd": "show local paths",
        "quit_cmd": "exit",
        "model_title": "Model Setup",
        "language_title": "Language",
        "select_provider": "Choose a model provider",
        "select_language": "Choose interface language",
        "custom_base": "Custom OpenAI-compatible base URL",
        "model_name_prompt": "Model name [{default}]: ",
        "base_prompt": "API base URL [{default}]: ",
        "key_prompt": "API key: ",
        "model_saved": "Model config saved: {provider} / {model}",
        "language_saved": "Language saved: {language}",
        "arrow_hint": "Use ↑/↓ and Enter. Esc cancels.",
        "number_hint": "Enter a number and press Enter.",
        "provider_note": "Provider: {name}\nBase URL: {base}\nTip: {tip}",
        "custom_tip": "Paste an OpenAI-compatible endpoint, usually ending with /v1.",
        "model_tip": "Enter the exact model id from your provider dashboard.",
        "key_tip": "Paste your API key. Input is hidden when supported.",
        "model_missing_once": "Model not configured. Run /model.",
        "runtime_preview": "Hidden runtime prompt preview:",
        "spinner_state": "Reading memory and subtext...",
        "spinner_reply": "Letting the persona answer...",
        "turn_saved_after_error": "Message saved locally; fix model config and continue.",
        "timeline_paused": "Timeline paused. Use /continue to resume.",
        "timeline_resumed": "Timeline resumed.",
        "readout": "Readout",
        "risk": "risk",
        "judgment": "Signal",
        "next_line": "Next move",
        "time_passes": "time passes",
        "timeline_waiting": "Waiting for your reply",
    },
    "ja": {
        "tagline": "Relationship Persona Simulation Engine",
        "memory": "Local memory: {path}",
        "hint": "/help でコマンド表示。自然に会話できます。",
        "no_model": "チャットモデル未設定です。設定ウィザードを開始します...",
        "bye": "セッションを保存しました。現実でも丁寧に練習していきましょう。",
        "unknown": "不明なコマンド: {cmd}。/help を試してください。",
        "commands": "Commands",
        "setup": "モデル設定ウィザード",
        "language_cmd": "表示言語を変更",
        "model_cmd": "モデルプロバイダー、モデル名、Base URL、API Key を変更",
        "start_cmd": "現在の人格セッションを作成/リセット",
        "import_cmd": "チャット履歴をインポート",
        "sessions_cmd": "ローカルセッション一覧",
        "use_cmd": "セッション切替",
        "dashboard_cmd": "関係状態を表示",
        "postmortem_cmd": "関係リプレイレポート",
        "distill_cmd": "根拠ベースの関係蒸留レポート",
        "stop_cmd": "タイムライン停止",
        "continue_cmd": "タイムライン再開",
        "config_cmd": "高度な直接設定",
        "where_cmd": "ローカルパス表示",
        "quit_cmd": "終了",
        "model_title": "Model Setup",
        "language_title": "Language",
        "select_provider": "モデルプロバイダーを選択",
        "select_language": "表示言語を選択",
        "custom_base": "Custom OpenAI-compatible Base URL",
        "model_name_prompt": "Model name [{default}]: ",
        "base_prompt": "API base URL [{default}]: ",
        "key_prompt": "API key: ",
        "model_saved": "モデル設定を保存しました: {provider} / {model}",
        "language_saved": "言語を保存しました: {language}",
        "arrow_hint": "↑/↓ と Enter で選択。Esc でキャンセル。",
        "number_hint": "番号を入力して Enter。",
        "provider_note": "Provider: {name}\nBase URL: {base}\nTip: {tip}",
        "custom_tip": "OpenAI-compatible endpoint を貼り付けてください。通常 /v1 で終わります。",
        "model_tip": "プロバイダー画面の正確な model id を入力してください。",
        "key_tip": "API Key を貼り付けてください。対応端末では入力は非表示です。",
        "model_missing_once": "モデル未設定です。/model を実行してください。",
        "runtime_preview": "Hidden runtime prompt preview:",
        "spinner_state": "記憶とサブテキストを読み取り中...",
        "spinner_reply": "人格に返信させています...",
        "turn_saved_after_error": "メッセージは保存されました。設定を直して続行できます。",
        "timeline_paused": "タイムラインを停止しました。/continue で再開。",
        "timeline_resumed": "タイムラインを再開しました。",
        "readout": "Readout",
        "risk": "risk",
        "judgment": "Signal",
        "next_line": "Next move",
        "time_passes": "time passes",
        "timeline_waiting": "Waiting for your reply",
    },
}

PROVIDERS: list[dict[str, str]] = [
    {"id": "openai", "name": "OpenAI", "base": "https://api.openai.com/v1", "model": "gpt-4o-mini", "mode": "openai", "tip": "Use an OpenAI API key. Base URL is the standard Chat Completions endpoint."},
    {"id": "claude", "name": "Claude / Anthropic", "base": "https://api.anthropic.com/v1", "model": "claude-3-5-haiku-latest", "mode": "anthropic", "tip": "Use an Anthropic API key. Crush will call the Messages API directly."},
    {"id": "gemini", "name": "Gemini / Google", "base": "https://generativelanguage.googleapis.com/v1beta", "model": "gemini-1.5-flash", "mode": "gemini", "tip": "Use a Google AI Studio API key. Crush will call generateContent directly."},
    {"id": "deepseek", "name": "DeepSeek", "base": "https://api.deepseek.com", "model": "deepseek-chat", "mode": "openai", "tip": "Use a DeepSeek API key. deepseek-chat is a safe default; you can type another model id."},
    {"id": "kimi", "name": "Kimi / Moonshot", "base": "https://api.moonshot.cn/v1", "model": "kimi-k2-0711-preview", "mode": "openai", "tip": "Use a Moonshot API key. Change the model name if your account uses another Kimi model."},
    {"id": "qwen", "name": "Qwen / DashScope", "base": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "qwen-plus", "mode": "openai", "tip": "Use a DashScope API key. This endpoint is OpenAI-compatible."},
    {"id": "custom", "name": "Custom", "base": "https://api.openai.com/v1", "model": "gpt-4o-mini", "mode": "openai", "tip": "Use this for OpenAI-compatible proxies or local gateways."},
]


class C:
    reset = "\033[0m"
    dim = "\033[2m"
    bold = "\033[1m"
    rose = "\033[38;5;150m"
    coral = "\033[38;5;180m"
    cyan = "\033[38;5;151m"
    gold = "\033[38;5;180m"
    green = "\033[38;5;150m"
    slate = "\033[38;5;250m"
    red = "\033[38;5;174m"


def color(text: str, code: str, enabled: bool = True) -> str:
    text = safe_text(text)
    enabled = enabled and sys.stdout.isatty() and "NO_COLOR" not in os.environ and os.environ.get("TERM", "").lower() != "dumb"
    return f"{code}{text}{C.reset}" if enabled else text


def visible_len(text: str) -> int:
    return display_width(safe_text(text))


def wrap(text: str, width: int = 78) -> str:
    return "\n".join(wrap_lines(text, min(width, terminal_width())))


def tr(lang: str, key: str, **kwargs: Any) -> str:
    template = LANG.get(lang, LANG["en"]).get(key, LANG["en"].get(key, key))
    return template.format(**kwargs) if kwargs else template


def provider_by_id(provider_id: str) -> dict[str, str]:
    for provider in PROVIDERS:
        if provider["id"] == provider_id:
            return provider
    return PROVIDERS[0]


def supports_arrow_select() -> bool:
    return bool(termios and tty and sys.stdin.isatty() and sys.stdout.isatty() and os.name != "nt")


def read_key() -> str:
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd, termios.TCSANOW)
        ch = os.read(fd, 1).decode("ascii", errors="ignore")
        if ch in {"\x03", "\x04", ""}:
            raise KeyboardInterrupt
        if ch == "\x1b":
            if not select.select([fd], [], [], 0.1)[0]:
                return "\x1b"
            nxt = os.read(fd, 1).decode("ascii", errors="ignore")
            if nxt == "[" and select.select([fd], [], [], 0.1)[0]:
                return "\x1b[" + os.read(fd, 1).decode("ascii", errors="ignore")
            return "\x1b"
        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def choose_option(title: str, prompt: str, options: list[dict[str, str]], *, plain: bool, lang: str, selected: int = 0) -> dict[str, str]:
    if not options:
        raise ValueError("Choose from at least one option")
    width = terminal_width()
    index = max(0, min(selected, len(options) - 1))

    def option_label(option: dict[str, str]) -> str:
        label = option.get("name", "")
        native = option.get("native", "")
        return label + (f" · {native}" if native and native != label else "")

    def numbered() -> dict[str, str]:
        print(color("\n" + wrap(title), C.bold, not plain))
        print(color(wrap(prompt), C.cyan, not plain))
        for i, option in enumerate(options, start=1):
            print(wrap(f"  {i}. {option_label(option)}"))
        print(color(wrap(tr(lang, "number_hint")), C.dim, not plain))
        while True:
            raw = input("> ").strip()
            if raw.isdigit() and 1 <= int(raw) <= len(options):
                return options[int(raw) - 1]
            print(color("Invalid selection.", C.red, not plain))

    def rows() -> list[str]:
        result = [color(line, C.rose) for line in panel_lines(title, [prompt, tr(lang, "arrow_hint")], width)]
        for i, option in enumerate(options):
            lines = wrap_lines(option_label(option), max(1, width - 3))
            for j, line in enumerate(lines):
                marker = " › " if i == index and j == 0 else "   "
                result.append(color(marker + line, C.bold if i == index else C.slate))
        return result

    if (plain or not supports_arrow_select() or os.environ.get("TERM", "").lower() == "dumb"
            or os.environ.get("CRUSH_REDUCED_MOTION") == "1"
            or len(rows()) >= shutil.get_terminal_size((80, 24)).lines):
        return numbered()

    previous_rows = 0
    while True:
        frame = rows()
        # A resized terminal can reflow old rows; avoid erasing uncertain history.
        if terminal_width() != width or len(frame) >= shutil.get_terminal_size((80, 24)).lines:
            return numbered()
        if previous_rows:
            sys.stdout.write(f"\r\033[{previous_rows}A")
        sys.stdout.write("".join("\r\033[2K" + line + "\n" for line in frame))
        sys.stdout.flush()
        previous_rows = len(frame)
        key = read_key()
        if key in {"\x1b[A", "k"}:
            index = (index - 1) % len(options)
        elif key in {"\x1b[B", "j"}:
            index = (index + 1) % len(options)
        elif key in {"\r", "\n"}:
            return options[index]
        elif key == "\x1b":
            raise KeyboardInterrupt


def animated_panel(title: str, lines: list[str], *, plain: bool) -> None:
    print()
    for row in panel_lines(title, lines, terminal_width()):
        print(color(row[:2], C.rose, not plain) + row[2:])


class ModelError(RuntimeError):
    pass


def normalize_api_base(value: str) -> str:
    base = (value or "").strip().rstrip("/")
    if not base:
        return "https://api.openai.com/v1"
    if "://" not in base:
        base = "https://" + base
    parsed = urlparse(base)
    host = parsed.netloc.lower()
    path = parsed.path.rstrip("/")

    if host == "platform.deepseek.com":
        host = "api.deepseek.com"
        path = ""
    if host == "api.deepseek.com" and path == "/v1":
        path = ""
    if path.endswith("/chat/completions"):
        path = path[: -len("/chat/completions")]

    return urlunparse((parsed.scheme or "https", host or parsed.netloc, path, "", "", "")).rstrip("/")


def load_config(config_file: Path) -> Dict[str, Any]:
    if not config_file.exists():
        return {}
    try:
        return json.loads(config_file.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_config(config_file: Path, config: Dict[str, Any]) -> None:
    config_file.parent.mkdir(parents=True, exist_ok=True)
    import tempfile
    fd, name = tempfile.mkstemp(prefix=".config-", dir=config_file.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        os.replace(name, config_file)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def import_runtime(data_dir: Path):
    os.environ.setdefault("CRUSH_DATA_DIR", str(data_dir))
    sys.path.insert(0, str(SKILL_DIR))
    from execute import CrushSkillRuntime  # type: ignore

    return CrushSkillRuntime()


class ChatClient:
    def __init__(self, config: Dict[str, Any]) -> None:
        configured_provider = config.get("provider", "")
        provider = provider_by_id(configured_provider) if configured_provider else None
        self.api_key = (
            os.environ.get("CRUSH_CHAT_API_KEY")
            or config.get("api_key", "")
            or (os.environ.get("OPENAI_API_KEY") if configured_provider in {"", "openai"} else "")
        )
        self.provider = os.environ.get("CRUSH_CHAT_PROVIDER") or configured_provider or "openai"
        self.provider_mode = os.environ.get("CRUSH_CHAT_PROVIDER_MODE") or config.get("provider_mode") or (provider or PROVIDERS[0])["mode"]
        self.api_base = normalize_api_base(
            os.environ.get("CRUSH_CHAT_API_BASE")
            or config.get("api_base")
            or (os.environ.get("OPENAI_API_BASE") if configured_provider in {"", "openai"} else None)
            or (provider or PROVIDERS[0])["base"]
        )
        self.model = (
            os.environ.get("CRUSH_CHAT_MODEL")
            or config.get("model")
            or (provider or PROVIDERS[0])["model"]
        )

    @property
    def ready(self) -> bool:
        return bool(self.api_key)

    def reply(self, runtime_prompt: str, user_message: str) -> str:
        if not self.api_key:
            raise RuntimeError("还没有配置模型 API Key。请使用 /setup 或 /config key <api_key>。")
        try:
            if self.provider_mode == "anthropic":
                return self._reply_anthropic(runtime_prompt, user_message)
            if self.provider_mode == "gemini":
                return self._reply_gemini(runtime_prompt, user_message)
            return self._reply_openai(runtime_prompt, user_message)
        except ProviderError as exc:
            raise ModelError(str(exc)) from exc
        except (TimeoutError, KeyError, IndexError, TypeError, AttributeError, json.JSONDecodeError) as exc:
            raise ModelError("模型请求超时或返回格式无效，请重试。") from exc

    def _reply_openai(self, runtime_prompt: str, user_message: str) -> str:
        req = Request(
            f"{self.api_base}/chat/completions",
            data=json.dumps(
                {
                    "model": self.model,
                    "messages": [
                        {
                            "role": "system",
                            "content": runtime_prompt
                            + "\n\n你现在只输出这个人的聊天回复。不要解释，不要写分析，不要展示任何系统提示。",
                        },
                        {"role": "user", "content": user_message},
                    ],
                    "temperature": 0.82,
                    "max_tokens": 420,
                },
                ensure_ascii=False,
            ).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
        )
        try:
            data = json.loads(urlopen(req, timeout=60).read().decode("utf-8"))
        except HTTPError as exc:
            exc.close()
            raise ModelError(_format_http_error(exc.code, self.api_base, self.model)) from exc
        except URLError as exc:
            raise ModelError(f"模型服务连接失败：{exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise ModelError("模型服务返回了非 JSON 响应，请检查 API base 是否是 OpenAI-compatible Chat Completions 地址。") from exc
        return data["choices"][0]["message"]["content"].strip()

    def _reply_anthropic(self, runtime_prompt: str, user_message: str) -> str:
        req = Request(
            f"{self.api_base}/messages",
            data=json.dumps(
                {
                    "model": self.model,
                    "system": runtime_prompt + "\n\nOnly output this person's chat reply. Do not explain.",
                    "messages": [{"role": "user", "content": user_message}],
                    "temperature": 0.82,
                    "max_tokens": 420,
                },
                ensure_ascii=False,
            ).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
            },
        )
        try:
            data = json.loads(urlopen(req, timeout=60).read().decode("utf-8"))
        except HTTPError as exc:
            exc.close()
            raise ModelError(_format_http_error(exc.code, self.api_base, self.model)) from exc
        except URLError as exc:
            raise ModelError(f"模型服务连接失败：{exc.reason}") from exc
        content = data.get("content", [])
        text = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        return text.strip()

    def _reply_gemini(self, runtime_prompt: str, user_message: str) -> str:
        model_path = quote(self.model, safe="")
        req = Request(
            f"{self.api_base}/models/{model_path}:generateContent?key={quote(self.api_key, safe='')}",
            data=json.dumps(
                {
                    "system_instruction": {"parts": [{"text": runtime_prompt + "\n\nOnly output this person's chat reply. Do not explain."}]},
                    "contents": [{"role": "user", "parts": [{"text": user_message}]}],
                    "generationConfig": {"temperature": 0.82, "maxOutputTokens": 420},
                },
                ensure_ascii=False,
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            data = json.loads(urlopen(req, timeout=60).read().decode("utf-8"))
        except HTTPError as exc:
            exc.close()
            raise ModelError(_format_http_error(exc.code, self.api_base, self.model)) from exc
        except URLError as exc:
            raise ModelError(f"模型服务连接失败：{exc.reason}") from exc
        candidates = data.get("candidates", [])
        if not candidates:
            return ""
        parts = candidates[0].get("content", {}).get("parts", [])
        return "".join(part.get("text", "") for part in parts if isinstance(part, dict)).strip()


def _format_http_error(code: int, api_base: str, model: str, body: str = "") -> str:
    # Provider error payloads may echo credentials, private chat, or ANSI controls.
    tips = {
        401: "API key 无效或权限不足。请重新运行 /setup 或 /config key <new_key>。",
        404: "接口地址或模型名可能不对。DeepSeek 请用 API base: https://api.deepseek.com。",
        429: "请求过多、额度不足或触发限流。可以稍后重试，或检查服务商余额/并发限制。",
    }
    tip = tips.get(code, "请检查 API base、model、key 和服务商状态。")
    return f"模型服务返回 HTTP {code}。\n{tip}"


class CrushCLI:
    def __init__(self, args: argparse.Namespace) -> None:
        self.home = Path(args.home or DEFAULT_HOME).expanduser()
        self.config_file = self.home / "config.json"
        self.config = load_config(self.config_file)
        if args.session:
            self.config["session_id"] = args.session
        if args.model:
            self.config["model"] = args.model
        if args.api_base:
            self.config["api_base"] = args.api_base
        if args.api_key:
            self.config["api_key"] = args.api_key
        self.data_dir = Path(args.data_dir or self.config.get("data_dir") or self.home / "data").expanduser()
        self.session_id = self.config.get("session_id", "default")
        self.lang = self.config.get("language", "en")
        self.plain = bool(args.plain) or not sys.stdout.isatty() or os.environ.get("TERM", "").lower() == "dumb"
        self.once_message = args.message
        self.runtime = import_runtime(self.data_dir)
        self.client = ChatClient(self.config)
        self.timeline_stop = threading.Event()
        self.timeline_thread: threading.Thread | None = None
        self.print_lock = threading.Lock()

    def t(self, key: str, **kwargs: Any) -> str:
        return tr(self.lang, key, **kwargs)

    def run(self) -> int:
        self.intro()
        self.ensure_session()
        if self.once_message:
            self.chat(self.once_message)
            return 0
        if not self.client.ready and sys.stdin.isatty():
            print(color(self.t("no_model"), C.gold, not self.plain))
            try:
                self.model_wizard(first_run=True)
            except KeyboardInterrupt:
                print(color(self.t("model_missing_once"), C.gold, not self.plain))
        self.start_timeline()
        try:
            while True:
                try:
                    raw = input(color(f"\n{self.session_id} › ", C.rose, not self.plain)).strip()
                except (EOFError, KeyboardInterrupt):
                    print("\n" + color(self.t("bye"), C.dim, not self.plain))
                    return 0
                if not raw:
                    continue
                if raw.startswith("/"):
                    if self.command(raw) is False:
                        return 0
                    continue
                self.chat(raw)
        finally:
            self.stop_timeline()

    def intro(self) -> None:
        logo = [
            "   ______                __        __   _ __ __",
            "  / ____/______  _______/ /_      / /__(_) // /",
            " / /   / ___/ / / / ___/ __ \\    / //_/ / // /_",
            "/ /___/ /  / /_/ (__  ) / / /   / ,< / /__  __/",
            "\\____/_/   \\__,_/____/_/ /_/   /_/|_/_/  /_/   ",
        ]
        if self.plain or max(display_width(line) for line in logo) > terminal_width():
            logo = wrap_lines("Crush.skill / v2", terminal_width())
        for line in logo:
            print(color(line, C.rose, not self.plain))
        print()
        print(color(wrap(self.t("tagline")), C.bold, not self.plain))
        print(color(wrap(self.t("memory", path=self.data_dir)), C.dim, not self.plain))
        print(color(wrap(self.t("hint")), C.dim, not self.plain))

    def ensure_session(self) -> None:
        session = self.runtime.memory.sqlite.load_session(self.session_id)
        if session:
            return
        self.runtime.run(
            "quick_start",
            self.session_id,
            {"config": {"archetype": "experience", "name": "她", "gender": "female", "relationship_stage": "talking"}},
        )

    def command(self, raw: str) -> bool:
        try:
            parts = shlex.split(raw)
        except ValueError:
            print("命令引号未闭合，请检查后重试。")
            return True
        if not parts:
            return True
        cmd = parts[0].lower()
        args = parts[1:]
        try:
            if cmd in {"/q", "/quit", "/exit"}:
                print(color(self.t("bye"), C.dim, not self.plain))
                return False
            if cmd == "/help":
                self.help()
            elif cmd in {"/setup", "/model"}:
                self.model_wizard(first_run=False)
            elif cmd in {"/language", "/laguage"}:
                self.language_wizard()
            elif cmd == "/config":
                self.config_command(args)
            elif cmd == "/start":
                self.start(args)
            elif cmd == "/reset":
                self.reset_current_session()
            elif cmd == "/import":
                self.import_chats(args)
            elif cmd == "/import-weflow":
                self.import_weflow(args)
            elif cmd == "/import-status":
                self.import_status()
            elif cmd == "/delete-import":
                self.delete_import(args)
            elif cmd == "/profile":
                self.profile_show()
            elif cmd == "/media":
                self.media_show()
            elif cmd == "/sessions":
                self.sessions()
            elif cmd == "/use":
                self.use(args)
            elif cmd == "/dashboard":
                self.dashboard()
            elif cmd == "/postmortem":
                self.postmortem()
            elif cmd == "/distill":
                self.distill()
            elif cmd == "/stop":
                self.pause_timeline()
            elif cmd == "/continue":
                self.continue_timeline()
            elif cmd == "/where":
                self.where()
            else:
                print(color(self.t("unknown", cmd=cmd), C.red, not self.plain))
        except Exception as exc:
            print(color(f"Error: {exc}", C.red, not self.plain))
        return True

    def help(self) -> None:
        rows = [
            ("/model", self.t("model_cmd")),
            ("/language", self.t("language_cmd")),
            ("/setup", self.t("setup")),
            ("/start [archetype] [name]", self.t("start_cmd")),
            ("/reset", "clear current session memory and imported records"),
            ("/import [file]", self.t("import_cmd")),
            ("/import-weflow <file>", "import WeFlow JSON and build style memory"),
            ("/import-status", "show imported memory status"),
            ("/delete-import <import_id>", "delete one imported WeFlow memory set"),
            ("/profile", "show imported language style card"),
            ("/media", "show common imported emoji/image assets"),
            ("/sessions", self.t("sessions_cmd")),
            ("/use <session_id>", self.t("use_cmd")),
            ("/dashboard", self.t("dashboard_cmd")),
            ("/postmortem", self.t("postmortem_cmd")),
            ("/distill", self.t("distill_cmd")),
            ("/stop", self.t("stop_cmd")),
            ("/continue", self.t("continue_cmd")),
            ("/config model|base|key <value>", self.t("config_cmd")),
            ("/where", self.t("where_cmd")),
            ("/quit", self.t("quit_cmd")),
        ]
        print(color(f"\n{self.t('commands')}", C.bold, not self.plain))
        width = terminal_width()
        for name, desc in rows:
            if width >= 64:
                for i, line in enumerate(wrap_lines(desc, width - 33)):
                    label = name.ljust(30) if i == 0 else " " * 30
                    print(f"  {color(label, C.cyan, not self.plain)} {line}")
            else:
                print(color(wrap(name), C.cyan, not self.plain))
                for line in wrap_lines(desc, max(1, width - 2)):
                    print("  " + line)
                print()

    def setup(self) -> None:
        self.model_wizard(first_run=False)

    def language_wizard(self) -> None:
        selected = next((i for i, item in enumerate(SUPPORTED_LANGUAGES) if item["code"] == self.lang), 0)
        choice = choose_option(self.t("language_title"), self.t("select_language"), SUPPORTED_LANGUAGES, plain=self.plain, lang=self.lang, selected=selected)
        self.lang = choice["code"]
        self.config["language"] = self.lang
        save_config(self.config_file, self.config)
        print(color(self.t("language_saved", language=choice["native"]), C.green, not self.plain))

    def model_wizard(self, first_run: bool = False) -> None:
        provider_options = [{"id": item["id"], "name": item["name"], "native": ""} for item in PROVIDERS]
        current_provider = self.config.get("provider", "openai")
        selected = next((i for i, item in enumerate(PROVIDERS) if item["id"] == current_provider), 0)
        provider_choice = choose_option(self.t("model_title"), self.t("select_provider"), provider_options, plain=self.plain, lang=self.lang, selected=selected)
        provider = provider_by_id(provider_choice["id"])
        base = provider["base"]
        if provider["id"] == "custom":
            animated_panel(self.t("custom_base"), [self.t("custom_tip")], plain=self.plain)
            base = normalize_api_base(input(self.t("base_prompt", default=self.config.get("api_base", base))).strip() or self.config.get("api_base", base))
        else:
            animated_panel(
                self.t("model_title"),
                [self.t("provider_note", name=provider["name"], base=provider["base"], tip=provider["tip"])],
                plain=self.plain,
            )
        default_model = self.config.get("model") if self.config.get("provider") == provider["id"] else provider["model"]
        print(color(self.t("model_tip"), C.dim, not self.plain))
        model = input(self.t("model_name_prompt", default=default_model)).strip() or default_model
        print(color(self.t("key_tip"), C.dim, not self.plain))
        key = getpass.getpass(self.t("key_prompt")).strip()
        self.config.update({
            "provider": provider["id"],
            "provider_mode": provider["mode"],
            "api_base": normalize_api_base(base),
            "model": model,
            "language": self.lang,
        })
        if key:
            self.config["api_key"] = key
        self.config["session_id"] = self.session_id
        self.config["data_dir"] = str(self.data_dir)
        save_config(self.config_file, self.config)
        self.client = ChatClient(self.config)
        print(color(self.t("model_saved", provider=provider["name"], model=model), C.green, not self.plain))

    def config_command(self, args: list[str]) -> None:
        if not args:
            safe = {k: ("***" if "key" in k else v) for k, v in self.config.items()}
            print(json.dumps(safe, ensure_ascii=False, indent=2))
            return
        if len(args) < 2 or args[0] not in {"model", "base", "key", "session"}:
            raise ValueError("Usage: /config model|base|key|session <value>")
        field_map = {"model": "model", "base": "api_base", "key": "api_key", "session": "session_id"}
        value = normalize_api_base(args[1]) if args[0] == "base" else args[1]
        self.config[field_map[args[0]]] = value
        if args[0] == "session":
            self.session_id = args[1]
            self.ensure_session()
        save_config(self.config_file, self.config)
        self.client = ChatClient(self.config)
        print(color("Config saved.", C.green, not self.plain))

    def start(self, args: list[str]) -> None:
        archetype = args[0] if args else "experience"
        name = args[1] if len(args) > 1 else "她"
        result = self.runtime.run(
            "quick_start",
            self.session_id,
            {"config": {"archetype": archetype, "name": name, "gender": "female", "relationship_stage": "talking"}},
        )
        print(color(f"Started {self.session_id}: {result['canonical_archetype']} / {name}", C.green, not self.plain))

    def reset_current_session(self) -> None:
        self.runtime.run("delete_session", self.session_id, {})
        timeline_all = self.config.setdefault("timeline", {})
        timeline_all.pop(self.session_id, None)
        save_config(self.config_file, self.config)
        print(color(f"Reset session: {self.session_id}", C.green, not self.plain))
        print(color("Now import chats with /import-weflow or start a new practice persona with /start.", C.dim, not self.plain))

    def import_chats(self, args: list[str]) -> None:
        if args:
            text = Path(args[0]).expanduser().read_text(encoding="utf-8")
        else:
            print(color("Paste chat records. End with a single line: /done", C.dim, not self.plain))
            lines = []
            while True:
                line = input()
                if line.strip() == "/done":
                    break
                lines.append(line)
            text = "\n".join(lines)
        with Spinner("Importing chat records and rebuilding persona...", enabled=not self.plain):
            result = self.runtime.run("chat_import", self.session_id, {"source_text": text})
        analysis = result["analysis"]
        print(color("Import complete.", C.green, not self.plain))
        print(f"  messages: {analysis['total_messages']}")
        print(f"  archetype: {analysis['inferred_archetype']} / {analysis['inferred_attachment']} / {analysis['inferred_mbti']}")
        print(f"  phrases: {', '.join(analysis.get('signature_phrases', [])[:6]) or 'none'}")
        print(f"  slang: {', '.join(analysis.get('slang_hits', [])[:6]) or 'none'}")
        distillation = result.get("distillation_report") or {}
        radar = distillation.get("relationship_radar") or {}
        validation = distillation.get("validation") or {}
        if radar:
            print(color("Distillation preview:", C.bold, not self.plain))
            print(f"  confidence: {validation.get('level', 'unknown')} / {validation.get('confidence', 0)}")
            print(f"  active/passive: {radar.get('active_passive', 'unknown')}")
            print(f"  friend/flirt: {radar.get('friend_or_flirt', 'unknown')}")
            print(f"  boundary: {radar.get('warm_guarded', 'unknown')}")
            print(color("  Run /distill for the full evidence map and training playbook.", C.dim, not self.plain))

    def import_weflow(self, args: list[str]) -> None:
        if not args:
            raise ValueError("Usage: /import-weflow [--full] <weflow.json>")
        full = False
        clean_args = []
        for arg in args:
            if arg in {"--full", "--raw", "--private"}:
                full = True
            else:
                clean_args.append(arg)
        if not clean_args:
            raise ValueError("Usage: /import-weflow [--full] <weflow.json>")
        path = str(Path(clean_args[0]).expanduser())
        timeline = self.timeline_state()
        was_paused = bool(timeline.get("paused"))
        timeline["paused"] = True
        self.save_timeline_state(timeline)
        try:
            with Spinner("Importing WeFlow JSON and building style memory...", enabled=not self.plain):
                result = self.runtime.run("weflow_import", self.session_id, {"source_file": path, "privacy_mode": "full" if full else "safe"})
        finally:
            timeline = self.timeline_state()
            timeline["paused"] = was_paused
            self.save_timeline_state(timeline)
        self.print_weflow_import_result(result)

    def print_weflow_import_result(self, result: Dict[str, Any]) -> None:
        stats = result.get("stats", {})
        print(color("WeFlow import complete." if not result.get("already_imported") else "WeFlow file already imported.", C.green, not self.plain))
        print(f"  import_id: {result.get('import_id')}")
        print(f"  mode:      {result.get('privacy_mode') or stats.get('privacy_mode', 'safe')}")
        print(f"  raw messages: {stats.get('raw', 0)}")
        print(f"  normalized:   {stats.get('normalized', 0)}")
        print(f"  me / target:  {stats.get('me', 0)} / {stats.get('target', 0)}")
        print(f"  date range:   {' → '.join(stats.get('date_range', []))}")
        print(f"  chunks:       {stats.get('dialogue_chunks', 0)}")
        print(f"  examples:     {stats.get('target_reply_examples', 0)}")
        print(f"  clusters:     {stats.get('target_reply_clusters', 0)}")
        print(f"  media assets: {stats.get('media_assets', 0)}")
        print(f"  redacted:     {stats.get('redacted', 0)}")
        print(color("  Memory is ready for companion chat and proactive messages.", C.dim, not self.plain))

    def import_status(self) -> None:
        result = self.runtime.run("import_status", self.session_id, {})
        imports = result.get("imports", [])
        if not imports:
            print(color("No imports for this profile.", C.dim, not self.plain))
            return
        for item in imports:
            stats = item.get("stats", {})
            print(f"{item['import_id']}  {item['source_type']}  messages={stats.get('normalized', 0)}  examples={stats.get('target_reply_examples', 0)}")

    def delete_import(self, args: list[str]) -> None:
        if not args:
            raise ValueError("Usage: /delete-import <import_id>")
        result = self.runtime.run("delete_import", self.session_id, {"import_id": args[0]})
        print(color(f"Deleted import: {result['import_id']}", C.green, not self.plain))

    def profile_show(self) -> None:
        ctx = self.runtime.memory.sqlite.build_memory_context(self.session_id, query="persona profile", limit=2)
        text = ctx.get("persona_profile_text") or "No imported persona profile yet."
        print(text)

    def media_show(self) -> None:
        ctx = self.runtime.memory.sqlite.build_memory_context(self.session_id, query="emoji media image", limit=2)
        assets = ctx.get("media_assets", [])
        if not assets:
            print(color(wrap("No imported media assets yet. Re-import with /import-weflow --full <file>."), C.dim, not self.plain))
            return
        print(color("\n" + wrap("Media Assets"), C.bold, not self.plain))
        for item in assets[:12]:
            payload = item.get("payload", {})
            counts = payload.get("speakerCounts", {})
            key = payload.get("mediaKey") or payload.get("md5") or payload.get("artifactId")
            path = payload.get("localPath") or payload.get("cdnUrl") or ""
            print(color(wrap(f"{payload.get('kind', 'media')} · {key}"), C.cyan, not self.plain))
            print(wrap(f"target={counts.get('target', 0)} · me={counts.get('me', 0)}"))
            if path:
                print(wrap(path))
            if not self.plain:
                self.render_media_ref(payload, preview_only=True)

    def sessions(self) -> None:
        result = self.runtime.run("list_sessions", self.session_id, {})
        for item in result["sessions"]:
            marker = "*" if item["session_id"] == self.session_id else " "
            print(wrap(f"{marker} {item['session_id']}  {item['canonical_archetype']}  {item['updated_at']}"))

    def use(self, args: list[str]) -> None:
        if not args:
            raise ValueError("Usage: /use <session_id>")
        self.session_id = args[0]
        self.config["session_id"] = self.session_id
        save_config(self.config_file, self.config)
        self.ensure_session()
        print(color(f"Switched to session: {self.session_id}", C.green, not self.plain))

    def dashboard(self) -> None:
        result = self.runtime.run("dashboard", self.session_id, {})
        cards = result["dashboard"]["cards"]
        print(color("\n" + wrap("Relationship State"), C.bold, not self.plain))
        width = terminal_width()
        for key, value in cards.items():
            print(color(wrap(key), C.slate, not self.plain))
            bar_width = min(24, width - display_width(str(value)) - 3)
            if bar_width >= 4:
                print(f"  {self.bar(float(value), bar_width)} {value}")
            else:
                print(wrap(str(value)))
                print(self.bar(float(value), width))

    def postmortem(self) -> None:
        result = self.runtime.run("postmortem", self.session_id, {})
        print(result["markdown"])

    def distill(self) -> None:
        with Spinner("Distilling evidence map and training playbook...", enabled=not self.plain):
            result = self.runtime.run("distillation_report", self.session_id, {})
        print(result["markdown"])

    def where(self) -> None:
        print(f"config: {self.config_file}")
        print(f"data:   {self.data_dir}")
        print(f"skill:  {SKILL_DIR}")
        timeline = self.timeline_state()
        paused = "yes" if timeline.get("paused") else "no"
        next_at = timeline.get("next_proactive_at", 0)
        next_text = datetime.fromtimestamp(next_at).strftime("%Y-%m-%d %H:%M:%S") if next_at else "not scheduled"
        print(f"timeline paused: {paused}")
        print(f"next proactive:  {next_text}")

    def chat(self, message: str) -> None:
        timeline = self.timeline_state()
        response_read = self.resolve_pending_proactive(timeline, message)
        timeline["last_user_at"] = time.time()
        self.save_timeline_state(timeline)
        with Spinner(self.t("spinner_state"), enabled=not self.plain):
            turn = self.runtime.run("chat_turn", self.session_id, {"message": message})
        if not self.client.ready:
            print(color(self.t("model_missing_once"), C.gold, not self.plain))
            print(color(self.t("runtime_preview"), C.dim, not self.plain))
            print(wrap(turn["runtime_prompt"][:1200]))
            return
        try:
            with Spinner(self.t("spinner_reply"), enabled=not self.plain):
                reply = self.client.reply(turn["runtime_prompt"], message)
        except ModelError as exc:
            print(color(str(exc), C.red, not self.plain))
            print(color(self.t("turn_saved_after_error"), C.dim, not self.plain))
            return
        reply = reply.strip()
        if not reply:
            print(color("Model returned an empty reply. The user message was saved; try again or switch models.", C.gold, not self.plain))
            return
        self.runtime.run(
            "record_reply",
            self.session_id,
            {"message": message, "npc_reply": reply, "tags": turn.get("tags", [])},
        )
        timeline = self.timeline_state()
        timeline["last_npc_at"] = time.time()
        timeline["pending"] = {}
        timeline["next_proactive_at"] = time.time() + self.sample_proactive_delay()
        self.save_timeline_state(timeline)
        if response_read:
            turn.setdefault("coach", {})
            note = response_read.get("note", "")
            if note:
                turn["coach"]["interest_read"] = f"{turn['coach'].get('interest_read', '')}；时间线判断: {note}".strip("；")
        self.adjust_coach_after_reply(turn, reply)
        self.print_reply(reply, turn)

    def start_timeline(self) -> None:
        state = self.timeline_state()
        if not state.get("next_proactive_at"):
            state["next_proactive_at"] = time.time() + self.sample_proactive_delay()
            self.save_timeline_state(state)
        self.timeline_thread = threading.Thread(target=self.timeline_loop, daemon=True)
        self.timeline_thread.start()

    def stop_timeline(self) -> None:
        self.timeline_stop.set()
        if self.timeline_thread:
            self.timeline_thread.join(timeout=0.5)

    def pause_timeline(self) -> None:
        state = self.timeline_state()
        state["paused"] = True
        self.save_timeline_state(state)
        print(color(self.t("timeline_paused"), C.gold, not self.plain))

    def continue_timeline(self) -> None:
        state = self.timeline_state()
        state["paused"] = False
        state["next_proactive_at"] = time.time() + min(900.0, self.sample_proactive_delay())
        self.save_timeline_state(state)
        print(color(self.t("timeline_resumed"), C.green, not self.plain))

    def timeline_state(self) -> Dict[str, Any]:
        all_states = self.config.setdefault("timeline", {})
        state = all_states.setdefault(self.session_id, {})
        now = time.time()
        state.setdefault("paused", False)
        state.setdefault("last_user_at", now)
        state.setdefault("last_npc_at", 0.0)
        state.setdefault("next_proactive_at", 0.0)
        state.setdefault("initiative", 0.55)
        state.setdefault("warmth", 0.55)
        state.setdefault("ignored_streak", 0)
        state.setdefault("low_priority_replies", 0)
        state.setdefault("pending", {})
        return state

    def save_timeline_state(self, state: Dict[str, Any], session_id: str | None = None) -> None:
        self.config.setdefault("timeline", {})[session_id or self.session_id] = state
        self.config["session_id"] = self.session_id
        self.config["data_dir"] = str(self.data_dir)
        save_config(self.config_file, self.config)

    def timeline_loop(self) -> None:
        while not self.timeline_stop.is_set():
            self.timeline_stop.wait(8.0)
            if self.timeline_stop.is_set() or not self.client.ready:
                continue
            try:
                self.maybe_proactive_message()
            except Exception as exc:
                with self.print_lock:
                    print(color(f"\nTimeline skipped: {exc}", C.dim, not self.plain))

    def maybe_proactive_message(self) -> None:
        session_id = self.session_id
        state = self.timeline_state()
        now = time.time()
        if state.get("paused") or now < float(state.get("next_proactive_at", 0)):
            return
        pending = state.get("pending") or {}
        if pending:
            self.maybe_follow_up_pending(state, pending, now)
            return
        probability = self.proactive_probability()
        if random.random() > probability:
            state["next_proactive_at"] = now + self.sample_proactive_delay()
            self.save_timeline_state(state)
            return

        event = self.timeline_event(state)
        timeline_runtime = import_runtime(self.data_dir)
        prompt = timeline_runtime.run("proactive_prompt", session_id, {"event": event, **state})
        reply = self.client.reply(prompt["runtime_prompt"], event).strip()
        if not reply or reply == "__NO_MESSAGE__":
            state["next_proactive_at"] = now + self.sample_proactive_delay()
            self.save_timeline_state(state)
            return
        timeline_runtime.run(
            "record_reply",
            session_id,
            {"message": event, "npc_reply": reply, "tags": ["timeline_proactive"]},
        )
        state["last_npc_at"] = time.time()
        state["pending"] = self.build_pending(reply, event, "initial")
        state["next_proactive_at"] = state["pending"]["followup_due_at"]
        self.save_timeline_state(state, session_id)
        if self.session_id != session_id:
            return
        with self.print_lock:
            print(color(f"\n[{self.t('time_passes')}]", C.dim, not self.plain))
            self.print_reply(reply, {"relationship_vector": self.t("timeline_waiting"), "delta": {}, "sent_at": state["last_npc_at"]})
            sys.stdout.write(color(f"\n{self.session_id} › ", C.rose, not self.plain))
            sys.stdout.flush()

    def sample_proactive_delay(self) -> float:
        session = self._load_session_for_timeline()
        canonical = session.get("canonical_archetype", "experience")
        profile = session.get("profile", {})
        attachment = profile.get("attachment_style", "")
        ranges = {
            "emotional": (1800, 7200),
            "experience": (2700, 10800),
            "security": (7200, 21600),
            "value": (10800, 28800),
            "passive": (21600, 64800),
        }
        low, high = ranges.get(canonical, ranges["experience"])
        if "Anxious" in attachment:
            low *= 0.65
            high *= 0.75
        if "Avoidant" in attachment:
            low *= 1.35
            high *= 1.5
        scale = float(os.environ.get("CRUSH_TIMELINE_SPEED", "1") or "1")
        return max(15.0, random.uniform(low, high) * scale)

    def proactive_probability(self) -> float:
        session = self._load_session_for_timeline()
        profile = session.get("profile", {})
        state = {**session.get("state", {}), **self.timeline_state()}
        canonical = session.get("canonical_archetype", "experience")
        base = {
            "emotional": 0.68,
            "experience": 0.52,
            "security": 0.28,
            "value": 0.2,
            "passive": 0.12,
        }.get(canonical, 0.42)
        attachment = profile.get("attachment_style", "")
        if "Anxious" in attachment:
            base += 0.18
        if "Avoidant" in attachment:
            base -= 0.12
        base *= max(0.15, min(1.15, float(state.get("initiative", 0.55)) + 0.45))
        base *= max(0.25, min(1.2, float(state.get("warmth", 0.55)) + 0.45))
        base -= min(0.35, int(state.get("ignored_streak", 0)) * 0.12)
        base -= min(0.25, int(state.get("low_priority_replies", 0)) * 0.08)
        base += max(0.0, float(state.get("favorability", 0)) - 45) / 180
        base += max(0.0, float(state.get("exploration", 0)) - 35) / 220
        base -= max(0.0, float(state.get("defense_level", 0)) - 35) / 130
        return max(0.05, min(0.82, base))

    def build_pending(self, reply: str, event: str, kind: str) -> Dict[str, Any]:
        now = time.time()
        patience = self.sample_patience_window()
        return {
            "message": reply,
            "event": event,
            "kind": kind,
            "sent_at": now,
            "followup_due_at": now + patience,
            "followup_count": 0,
            "expires_at": now + patience * 3.5,
        }

    def sample_patience_window(self) -> float:
        session = self._load_session_for_timeline()
        canonical = session.get("canonical_archetype", "experience")
        base = {
            "emotional": (2400, 9000),
            "experience": (3600, 12600),
            "security": (7200, 21600),
            "value": (10800, 28800),
            "passive": (21600, 43200),
        }.get(canonical, (5400, 18000))
        scale = float(os.environ.get("CRUSH_TIMELINE_SPEED", "1") or "1")
        return max(20.0, random.uniform(*base) * scale)

    def maybe_follow_up_pending(self, state: Dict[str, Any], pending: Dict[str, Any], now: float) -> None:
        session_id = self.session_id
        followups = int(pending.get("followup_count", 0))
        if followups >= 2 or now >= float(pending.get("expires_at", 0)):
            self.cool_down_after_ignored(state)
            state["pending"] = {}
            state["next_proactive_at"] = now + self.sample_proactive_delay() * (1.6 + min(2, int(state.get("ignored_streak", 0))) * 0.7)
            self.save_timeline_state(state)
            return

        event = self.followup_event(state, pending, followups)
        timeline_runtime = import_runtime(self.data_dir)
        prompt = timeline_runtime.run("proactive_prompt", session_id, {"event": event, **state, "pending": pending})
        reply = self.client.reply(prompt["runtime_prompt"], event).strip()
        if not reply or reply == "__NO_MESSAGE__":
            pending["followup_due_at"] = now + self.sample_patience_window()
            state["next_proactive_at"] = pending["followup_due_at"]
            self.save_timeline_state(state)
            return
        timeline_runtime.run(
            "record_reply",
            session_id,
            {"message": event, "npc_reply": reply, "tags": ["timeline_followup"]},
        )
        pending["message"] = reply
        pending["event"] = event
        pending["kind"] = "followup"
        pending["sent_at"] = now
        pending["followup_count"] = followups + 1
        pending["followup_due_at"] = now + self.sample_patience_window() * (1.8 + followups)
        pending["expires_at"] = now + self.sample_patience_window() * (3.0 + followups)
        state["pending"] = pending
        state["last_npc_at"] = now
        state["next_proactive_at"] = pending["followup_due_at"]
        self.save_timeline_state(state, session_id)
        if self.session_id != session_id:
            return
        with self.print_lock:
            print(color(f"\n[{self.t('time_passes')}]", C.dim, not self.plain))
            self.print_reply(reply, {"relationship_vector": self.t("timeline_waiting"), "delta": {}, "sent_at": now})
            sys.stdout.write(color(f"\n{self.session_id} › ", C.rose, not self.plain))
            sys.stdout.flush()

    def followup_event(self, state: Dict[str, Any], pending: Dict[str, Any], followups: int) -> str:
        now = datetime.now()
        hour = now.hour
        waited_minutes = max(1, int((time.time() - float(pending.get("sent_at", time.time()))) / 60))
        if 22 <= hour or hour < 2:
            natural = "已经很晚了，她会想到你是不是还没到家、是不是还在忙、为什么还没回。"
        elif 7 <= hour < 10:
            natural = "早上了，她不会直接逼问昨晚为什么不回，而是用到公司/早餐/今天安排委婉试探。"
        elif 11 <= hour < 14:
            natural = "中午了，她可能借午饭或午休自然续一下，同时观察你是否还愿意接。"
        elif 17 <= hour < 20:
            natural = "下班/晚饭时间，她可能问你到哪了、吃没吃，带一点关心也带一点试探。"
        else:
            natural = "过了一段时间，她会根据性格轻轻追问，但不会像机器人重复催。"
        mood = "第一次追问，语气可以轻一点。" if followups == 0 else "已经不是第一次未回复了，热情下降，语气更克制或有点不爽。"
        return (
            f"她上一条主动消息发出后，已经等了约 {waited_minutes} 分钟没有得到回复。{natural}{mood}"
            "请只发一条真人会发的追问/试探消息；不要换新话题刷屏，不要显得像定时任务。"
        )

    def cool_down_after_ignored(self, state: Dict[str, Any]) -> None:
        state["ignored_streak"] = int(state.get("ignored_streak", 0)) + 1
        state["initiative"] = max(0.08, float(state.get("initiative", 0.55)) - 0.16)
        state["warmth"] = max(0.12, float(state.get("warmth", 0.55)) - 0.10)

    def resolve_pending_proactive(self, state: Dict[str, Any], message: str) -> Dict[str, Any]:
        pending = state.get("pending") or {}
        if not pending:
            return {}
        quality = self.assess_reply_to_pending(message, pending)
        state["pending"] = {}
        state["last_response_quality"] = quality["quality"]
        state["last_response_note"] = quality["note"]
        if quality["quality"] == "high_care":
            state["ignored_streak"] = 0
            state["initiative"] = min(1.0, float(state.get("initiative", 0.55)) + 0.06)
            state["warmth"] = min(1.0, float(state.get("warmth", 0.55)) + 0.08)
        elif quality["quality"] == "valid_busy":
            state["ignored_streak"] = max(0, int(state.get("ignored_streak", 0)) - 1)
            state["initiative"] = min(1.0, float(state.get("initiative", 0.55)) + 0.02)
            state["warmth"] = min(1.0, float(state.get("warmth", 0.55)) + 0.03)
        elif quality["quality"] == "low_priority":
            state["low_priority_replies"] = int(state.get("low_priority_replies", 0)) + 1
            state["initiative"] = max(0.08, float(state.get("initiative", 0.55)) - 0.10)
            state["warmth"] = max(0.12, float(state.get("warmth", 0.55)) - 0.08)
        else:
            state["initiative"] = max(0.08, float(state.get("initiative", 0.55)) - 0.05)
            state["warmth"] = max(0.12, float(state.get("warmth", 0.55)) - 0.04)
        return quality

    def assess_reply_to_pending(self, message: str, pending: Dict[str, Any]) -> Dict[str, Any]:
        text = message.strip().lower()
        waited = max(0, int((time.time() - float(pending.get("sent_at", time.time()))) / 60))
        apology = any(word in text for word in ["抱歉", "不好意思", "刚看到", "才看到", "sorry", "sry", "ごめん"])
        valid_busy = any(word in text for word in ["睡着", "睡觉", "休息", "加班", "刚下班", "开会", "路上", "到家", "赶 ddl", "赶ddl", "忙完", "手机没电", "信号不好"])
        low_priority = any(word in text for word in ["打游戏", "游戏", "刷视频", "忘了", "懒得", "没看", "在玩", "开黑"])
        care = any(word in text for word in ["想你", "怕你担心", "马上回", "刚忙完就回", "一忙完就回", "没不理你"])
        if care or (apology and valid_busy):
            return {"quality": "high_care", "waited_minutes": waited, "note": "你解释了原因并照顾到她的感受，她会觉得被重视。"}
        if valid_busy or apology:
            return {"quality": "valid_busy", "waited_minutes": waited, "note": "你有合理原因，她会理解，但会观察这种情况是否长期发生。"}
        if low_priority:
            return {"quality": "low_priority", "waited_minutes": waited, "note": "你把她排在游戏/娱乐后面，她会察觉自己优先级不高，主动性会下降。"}
        return {"quality": "unclear", "waited_minutes": waited, "note": "你没有解释为什么晚回，她会保留判断。"}

    def _load_session_for_timeline(self) -> Dict[str, Any]:
        if threading.current_thread() is threading.main_thread():
            return self.runtime.memory.sqlite.load_session(self.session_id) or {}
        return import_runtime(self.data_dir).memory.sqlite.load_session(self.session_id) or {}

    def timeline_event(self, state: Dict[str, Any]) -> str:
        now = datetime.now()
        last_npc = float(state.get("last_npc_at", 0) or 0)
        last_user = float(state.get("last_user_at", 0) or 0)
        idle_after_npc = max(0, int((time.time() - last_npc) / 60)) if last_npc >= last_user and last_npc else 0
        inactive = max(0, int((time.time() - max(last_user, last_npc)) / 60))
        hour = now.hour
        if 7 <= hour < 10:
            slot = "早上/通勤/早餐时间"
        elif 11 <= hour < 14:
            slot = "中午/午饭/午休前后"
        elif 17 <= hour < 20:
            slot = "傍晚/下班/晚饭时间"
        elif 22 <= hour or hour < 1:
            slot = "深夜/睡前/情绪更松的时候"
        else:
            slot = "普通空闲时段"
        initiative = float(state.get("initiative", 0.55))
        warmth = float(state.get("warmth", 0.55))
        ignored = int(state.get("ignored_streak", 0))
        low_priority = int(state.get("low_priority_replies", 0))
        return (
            f"当前本地时间 {now.strftime('%Y-%m-%d %H:%M')}，时间段是{slot}。"
            f"距离你上一条消息后她已经等了约 {idle_after_npc} 分钟；"
            f"距离最近一次互动约 {inactive} 分钟。"
            f"她当前主动性约 {initiative:.2f}，热情约 {warmth:.2f}，连续被忽略 {ignored} 次，低优先级回复累计 {low_priority} 次。"
            "请她根据自己的人格、主动性、好感、防御、最近聊天和这个时间段，决定并发出一条自然主动消息。"
            "如果主动性/热情下降，就不要热情刷屏；可以克制、试探、慢一点，甚至只是低热度开话题。"
            "不要模板化，不要像闹钟，不要在对方未回复时连续换新话题。"
        )

    def print_reply(self, reply: str, turn: Dict[str, Any]) -> None:
        print()
        stamp = datetime.fromtimestamp(float(turn.get("sent_at") or time.time())).strftime("%H:%M")
        header = self.bubble_header("Ta", stamp)
        print(color(header, C.rose, not self.plain))
        display_reply, media_refs = self.extract_media_tokens(reply, turn)
        prefix = "│ " if terminal_width() >= 12 else ""
        for line in wrap_lines(display_reply, max(1, terminal_width() - display_width(prefix))):
            print(color(prefix, C.rose, not self.plain) + line)
        if prefix:
            print(color("╰", C.rose, not self.plain))
        for ref in media_refs:
            self.render_media_ref(ref)
        vector = turn.get("relationship_vector", "")
        delta = turn.get("delta", {})
        coach = turn.get("coach", {})
        if coach:
            flags = coach.get("warning_flags", [])
            flag_text = f" · {'/'.join(flags[:2])}" if flags else ""
            print(color(
                wrap(f"{self.t('readout')}: {coach.get('line_type')} · {self.t('risk')} {coach.get('risk_level')} · {coach.get('should_flirt')}{flag_text}"),
                C.gold,
                not self.plain,
            ))
            print(color(wrap(f"{self.t('judgment')}: {coach.get('interest_read')}"), C.dim, not self.plain))
            print(color(wrap(f"{self.t('next_line')}: {coach.get('next_move')}"), C.dim, not self.plain))
            detail = " · ".join(
                part
                for part in [
                    coach.get("user_neediness"),
                    coach.get("persona_read"),
                    coach.get("pressure_note"),
                ]
                if part
            )
            if detail:
                print(color(wrap(f"细节: {detail}"), C.dim, not self.plain))
        elif vector:
            short = f"{vector} · favorability {delta.get('favorability', 0):+} · defense {delta.get('defense_level', 0):+}"
            print(color(wrap(short), C.dim, not self.plain))

    def adjust_coach_after_reply(self, turn: Dict[str, Any], reply: str) -> None:
        text = re.sub(r"\s+", "", reply.lower())
        if not re.search(r"(眯一会|睡会|睡觉|困|累死|休息|先忙|上课|开会|洗澡|晚点|等会)", text):
            return
        coach = turn.setdefault("coach", {})
        coach["line_type"] = "对方低能量/要休息"
        coach["risk_level"] = "中"
        coach["should_flirt"] = "先别推进：低打扰收尾"
        coach["interest_read"] = "她愿意回应，但此刻身体/注意力不在线；把节奏让给她，比继续暧昧更真实。"
        coach["next_move"] = "短句接住：让她休息，别追问，留一个轻松可回的尾巴。"
        flags = coach.setdefault("warning_flags", [])
        if "休息窗口" not in flags:
            flags.insert(0, "休息窗口")

    def extract_media_tokens(self, reply: str, turn: Dict[str, Any]) -> tuple[str, list[Dict[str, Any]]]:
        assets = {}
        for item in (turn.get("memory_context", {}) or {}).get("media_assets", []):
            payload = item.get("payload", {})
            for key in [payload.get("mediaKey"), payload.get("md5"), payload.get("artifactId")]:
                if key:
                    assets[str(key)] = payload

        refs: list[Dict[str, Any]] = []

        def resolve_asset(kind: str, key: str) -> Dict[str, Any]:
            if key in assets:
                return assets[key]
            for asset_key, payload in assets.items():
                if asset_key.startswith(key) or key.startswith(asset_key):
                    return payload
            return {"kind": kind, "mediaKey": key}

        def replace(match: re.Match[str]) -> str:
            kind, key = match.group(1), match.group(2)
            payload = resolve_asset(kind, key)
            refs.append(payload)
            return f"[{kind}:{key[:10]}]"

        cleaned = re.sub(r"\[\[(emoji|image|video|voice):([A-Za-z0-9_./:-]+)\]\]", replace, reply)
        cleaned = re.sub(r"\[\[(emoji|image|video|voice):([A-Za-z0-9_./:-]{10,})(?!\]\])", replace, cleaned)
        return cleaned, refs

    def render_media_ref(self, media: Dict[str, Any], preview_only: bool = False) -> None:
        path = str(media.get("localPath") or "")
        url = str(media.get("cdnUrl") or "")
        kind = media.get("kind", "media")
        label = media.get("mediaKey") or media.get("md5") or media.get("id") or kind
        inline_supported = os.environ.get("TERM_PROGRAM") in {"iTerm.app", "WezTerm"}
        visual = not self.plain and sys.stdout.isatty() and "NO_COLOR" not in os.environ and os.environ.get("TERM", "").lower() != "dumb"
        if visual and path and Path(path).expanduser().exists() and inline_supported:
            try:
                data = Path(path).expanduser().read_bytes()
                encoded = base64.b64encode(data).decode("ascii")
                name = base64.b64encode(Path(path).name.encode("utf-8")).decode("ascii")
                print(f"\033]1337;File=name={name};inline=1;width={min(24, terminal_width())};height=8;preserveAspectRatio=1:{encoded}\a")
                print(color(wrap(f"[{kind}] {path}"), C.dim, not self.plain))
                return
            except Exception:
                pass
        if visual and path and Path(path).expanduser().exists():
            if self.render_ansi_image(Path(path).expanduser()):
                print(color(wrap(f"[{kind}] {path}"), C.dim, not self.plain))
                return
        if not preview_only:
            print(color(wrap(f"[{kind}] {label}: {path or url or 'media asset not found locally'}"), C.dim, not self.plain))

    def render_ansi_image(self, path: Path, width: int = 24) -> bool:
        try:
            from PIL import Image, ImageSequence

            with Image.open(path) as img:
                frame = next(ImageSequence.Iterator(img)).convert("RGB")
                w, h = frame.size
                if w <= 0 or h <= 0:
                    return False
                target_w = max(1, min(width, w, terminal_width()))
                # Two vertical pixels are packed into one terminal row.
                target_h = max(2, int((h / w) * target_w * 0.5))
                frame = frame.resize((target_w, target_h * 2))
                for y in range(0, frame.height, 2):
                    row = []
                    for x in range(frame.width):
                        upper = frame.getpixel((x, y))
                        lower = frame.getpixel((x, min(y + 1, frame.height - 1)))
                        row.append(
                            f"\033[38;2;{upper[0]};{upper[1]};{upper[2]}m"
                            f"\033[48;2;{lower[0]};{lower[1]};{lower[2]}m▀"
                        )
                    print("".join(row) + C.reset)
                return True
        except Exception:
            return False

    def bar(self, value: float, width: int = 24) -> str:
        normalized = max(0.0, min(100.0, value))
        filled = int((normalized / 100.0) * width)
        return color("█" * filled, C.cyan, not self.plain) + color("░" * (width - filled), C.dim, not self.plain)

    def bubble_header(self, name: str, stamp: str, width: int = 78) -> str:
        width = min(width, terminal_width())
        if width < 12:
            return "\n".join(wrap_lines(f"{name}\n{stamp}", width))
        left = "╭─ " + wrap_lines(name, max(1, width - display_width(stamp) - 4))[0]
        gap = max(1, width - visible_len(left) - visible_len(stamp))
        return left + " " * gap + stamp


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Crush.skill standalone local CLI",
        epilog=(
            "Other entry points: crush web (local web preview); "
            "crush v3 --help (JSON CLI). "
            "Use --plain to disable ANSI animation/colors, or "
            "CRUSH_REDUCED_MOTION=1 for static activity feedback."
        ),
    )
    parser.add_argument("--session", help="Session id to open")
    parser.add_argument("--home", help="Crush local home directory (default: ~/.crush)")
    parser.add_argument("--data-dir", help="Local memory data directory")
    parser.add_argument("--api-key", help="OpenAI-compatible API key")
    parser.add_argument("--api-base", help="OpenAI-compatible API base")
    parser.add_argument("--model", help="Chat model name")
    parser.add_argument("--plain", action="store_true", help="Disable ANSI animation/colors")
    parser.add_argument("--message", help="Send one message and exit")
    parser.add_argument("command", nargs=argparse.REMAINDER, help="Optional headless command, e.g. import weflow ./weflow.json --profile default")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    values = list(argv) if argv is not None else sys.argv[1:]
    if values and values[0] == "web":
        try:
            from crush_core.server import main as web_main
        except ModuleNotFoundError as exc:
            print(f"GUI 依赖尚未安装 ({exc.name})。请从源码目录运行：pip install -r requirements-web.txt")
            return 1
        sys.argv = [sys.argv[0], *values[1:]]
        web_main()
        return 0
    if values and values[0] == "v3":
        from crush_core.__main__ import main as core_main
        sys.argv = [sys.argv[0], *values[1:]]
        return core_main()
    parser = build_parser()
    args = parser.parse_args(values)
    if args.command:
        return run_headless(args)
    return CrushCLI(args).run()


def _take_option(tokens: list[str], name: str, default: str = "") -> str:
    if name not in tokens:
        return default
    idx = tokens.index(name)
    if idx + 1 >= len(tokens):
        return default
    value = tokens[idx + 1]
    del tokens[idx : idx + 2]
    return value


def run_headless(args: argparse.Namespace) -> int:
    tokens = list(args.command)
    profile = _take_option(tokens, "--profile", args.session or "default")
    mode = _take_option(tokens, "--mode", "companion")
    proactive_type = _take_option(tokens, "--type", "daily_checkin")
    import_id = _take_option(tokens, "--import-id", "")
    full = False
    if "--full" in tokens:
        tokens.remove("--full")
        full = True
    args.session = profile
    cli = CrushCLI(args)
    cli.session_id = profile
    cli.ensure_session()
    if tokens[:2] == ["import", "weflow"] and len(tokens) >= 3:
        result = cli.runtime.run("weflow_import", profile, {"source_file": tokens[2], "privacy_mode": "full" if full else "safe"})
        cli.print_weflow_import_result(result)
        return 0
    if tokens[:2] == ["import", "list"] or tokens[:2] == ["import", "status"]:
        cli.import_status()
        return 0
    if tokens[:2] == ["memory", "build"] or tokens[:2] == ["memory", "rebuild"]:
        cli.import_status()
        print("Memory indexes are built during WeFlow import. Re-import to rebuild from source JSON.")
        return 0
    if tokens[:2] == ["profile", "show"]:
        cli.profile_show()
        return 0
    if tokens and tokens[0] == "media":
        cli.media_show()
        return 0
    if tokens[:2] == ["data", "delete"] and import_id:
        cli.delete_import([import_id])
        return 0
    if tokens[:2] == ["proactive", "test"]:
        result = cli.runtime.run("proactive_prompt", profile, {"event": f"proactive test: {proactive_type}", "proactive_type": proactive_type})
        print(result["runtime_prompt"])
        return 0
    if tokens and tokens[0] == "chat":
        message = " ".join(tokens[1:]).strip() or args.message or "你好"
        turn = cli.runtime.run("chat_turn", profile, {"message": message, "mode": mode})
        if cli.client.ready:
            reply = cli.client.reply(turn["runtime_prompt"], message).strip()
            cli.runtime.run("record_reply", profile, {"message": message, "npc_reply": reply, "tags": turn.get("tags", [])})
            print(reply)
        else:
            print(turn["runtime_prompt"])
        return 0
    print("Unknown headless command. Try: import weflow <file>, import status, profile show, chat <message>, proactive test.")
    return 2
