"""Cell-aware, control-safe terminal layout without third-party dependencies."""

from __future__ import annotations

import re
import shutil
import unicodedata


# Strip complete and unterminated terminal strings before removing control bytes.
_ESCAPES = re.compile(
    r"(?:\x1b\]|\x9d)[^\x07\x1b\x9c]*(?:\x07|\x1b\\|\x9c|$)"
    r"|(?:\x1b[P^_X]|[\x90\x98\x9e\x9f]).*?(?:\x1b\\|\x9c|$)"
    r"|(?:\x1b\[|\x9b)[0-?]*[ -/]*(?:[@-~]|$)"
    r"|\x1b[ -/]*[@-~]",
    re.DOTALL,
)


def safe_text(text: str) -> str:
    """Keep printable text and paragraphs; never trust incoming ANSI sequences."""
    text = _ESCAPES.sub("", str(text)).replace("\t", "    ")
    return "".join(
        char if char == "\n" or not unicodedata.category(char).startswith("C") else " "
        for char in text
    )


def display_width(text: str) -> int:
    return sum(
        0 if unicodedata.category(char) in {"Mn", "Me"} or unicodedata.category(char).startswith("C")
        else 2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1
        for char in text
    )


def terminal_width(maximum: int = 78) -> int:
    """Leave the last cell unused to prevent terminal autowrap during redraw."""
    return max(1, min(maximum, shutil.get_terminal_size((80, 24)).columns - 1))


def wrap_lines(text: str, width: int) -> list[str]:
    """Wrap words by cells, breaking long tokens while keeping combining marks."""
    width = max(1, width)
    result = []
    for paragraph in safe_text(text).split("\n"):
        line = ""
        for token in re.findall(r"\s+|\S+", paragraph):
            if token.isspace():
                if line:
                    line += " "
                continue
            if line and display_width(line + token) > width:
                result.append(line.rstrip())
                line = ""
            for char in token:
                if line and display_width(line + char) > width:
                    result.append(line.rstrip())
                    line = ""
                line += char
        result.append(line.rstrip())
    return result


def panel_lines(title: str, lines: list[str], width: int) -> list[str]:
    if width < 12:
        return [line for text in [title, *lines] for line in wrap_lines(text, width)]
    body_width = max(1, width - 2)
    headings = wrap_lines(title, max(1, width - 3))
    rows = ["╭─ " + headings[0]] + ["│ " + line for line in headings[1:]]
    rows.extend("│ " + line for text in lines for line in wrap_lines(text, body_width))
    rows.append("╰" + "─" * max(0, width - 1))
    return rows
