"""
LLM-powered Dialogue Analyzer — semantic understanding instead of keyword matching.

Supports two backends:
1. local — regex + heuristic fallback (no API needed, works offline)
2. llm   — semantic analysis via any OpenAI-compatible API (much better accuracy)

The local backend is enhanced from the original keyword approach with:
- Negation detection ("我不开心" != "开心")
- Context-aware scoring
- Combined signal analysis
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from urllib.request import Request, HTTPRedirectHandler, build_opener
from urllib.error import URLError

from .pragmatics_engine import interpret_message
from .types import TurnAnalysis, clamp


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Keep the standalone legacy Skill safe even without the v3 package.
        raise URLError('Model redirects are disabled; configure the final API endpoint.')


def urlopen(request, timeout):
    return build_opener(_NoRedirect()).open(request, timeout=timeout)

# ── Enhanced Local Analyzer ──────────────────────────────────────

# Negation patterns that flip meaning
NEGATION_PATTERNS = [
    r"不\w{0,3}(开心|喜欢|想|舒服|信任|期待|确定)",
    r"没\w{0,3}(兴趣|感觉|那么|什么|意思|所谓)",
    r"(不是|不算|并没有|压根不|完全不|一点也不)",
]

POSITIVE_WORDS = {
    "开心", "想你", "喜欢", "欣赏", "有趣", "放松", "舒服", "信任", "温柔", "理解",
    "期待", "见面", "甜甜", "陪伴", "耐心", "用心", "真诚", "可爱",
}
NEGATIVE_WORDS = {
    "烦", "失望", "冷淡", "生气", "讨厌", "难受", "压抑", "算了", "无语",
    "随便", "不在乎", "懒得", "别烦我", "走开",
}
NEEDINESS_CUES = {
    "你为什么不回", "你在吗", "求你", "一定要", "马上回", "想我了吗",
    "是不是不爱", "别离开", "只有你", "求回复", "等你好久了", "怎么不理我",
}
PRESSURE_CUES = {
    "给我答案", "现在就", "你必须", "你应该", "你得", "立刻", "确定关系",
    "我们今天就", "逼", "承诺", "到底什么意思",
}
AUTHENTIC_CUES = {
    "我真实想法", "我会尊重", "你可以拒绝", "我理解", "我愿意慢一点",
    "坦白", "真诚", "边界", "尊重", "说实话", "不勉强",
}
PLAYFUL_CUES = {
    "哈哈", "开玩笑", "逗你", "轻松", "好玩", "调皮", "笑死",
    "hhhh", "233", "笑不活", "绝了",
}
STABILITY_CUES = {
    "计划", "长期", "稳定", "负责", "节奏", "边界", "一致",
    "可预期", "明天", "下周", "安排", "慢慢来",
}
VALUE_SIGNAL_CUES = {
    "成长", "目标", "事业", "学习", "自律", "价值", "资源", "能力",
    "担当", "执行", "进步", "努力",
}
ATTACHMENT_TRIGGER_CUES = {
    "消失", "突然", "安全感", "忽冷忽热", "不确定", "被抛弃",
    "失控", "不安", "焦虑", "好几天没回", "冷淡了",
}


def _has_negation(text: str) -> bool:
    for pat in NEGATION_PATTERNS:
        if re.search(pat, text):
            return True
    return False


def _cue_score(text: str, cues: set[str], max_hits: int = 4) -> float:
    hits = 0
    for cue in cues:
        if cue in text:
            hits += 1
    return min(1.0, hits / max_hits)


def analyze_local(message: str) -> TurnAnalysis:
    """Enhanced local analysis with negation awareness and richer signals."""
    text = message.strip()
    pragmatic = interpret_message(text)

    # Negation detection
    negated = _has_negation(text)

    # Valence
    pos_hits = sum(1 for w in POSITIVE_WORDS if w in text)
    neg_hits = sum(1 for w in NEGATIVE_WORDS if w in text)
    if pos_hits or neg_hits:
        valence = (pos_hits - neg_hits) / max(1, pos_hits + neg_hits)
    else:
        valence = 0.0

    # Flip valence if negation detected
    if negated and valence > 0:
        valence = -valence * 0.6

    analysis = TurnAnalysis(
        valence=valence,
        neediness_score=_cue_score(text, NEEDINESS_CUES),
        pressure_score=_cue_score(text, PRESSURE_CUES),
        authenticity_score=_cue_score(text, AUTHENTIC_CUES),
        playfulness_score=_cue_score(text, PLAYFUL_CUES),
        stability_score=_cue_score(text, STABILITY_CUES),
        value_signal_score=_cue_score(text, VALUE_SIGNAL_CUES),
        attachment_trigger_score=_cue_score(text, ATTACHMENT_TRIGGER_CUES),
        surface_intent=pragmatic.surface_intent,
        deep_need=pragmatic.deep_need,
        emotional_state=pragmatic.emotional_state,
        test_flag=pragmatic.test_flag,
        test_type=pragmatic.test_type,
        subtext=pragmatic.subtext,
        reply_strategy=pragmatic.reply_strategy,
        register_tags=pragmatic.register_tags,
        slang_hits=pragmatic.slang_hits,
        implied_boundary=pragmatic.implied_boundary,
        confidence=pragmatic.confidence,
    ).bounded()

    if "playful" in pragmatic.register_tags:
        analysis.playfulness_score = max(analysis.playfulness_score, 0.55)
    if "boundary" in pragmatic.register_tags:
        analysis.pressure_score = max(analysis.pressure_score, 0.35)
        analysis.attachment_trigger_score = max(analysis.attachment_trigger_score, 0.25)
    if "soft_decline" in pragmatic.register_tags:
        analysis.valence = min(analysis.valence, -0.15)
    if pragmatic.test_flag:
        analysis.attachment_trigger_score = max(analysis.attachment_trigger_score, 0.35)

    # Notes
    if negated:
        analysis.notes.append("检测到否定/反向表达")
    if analysis.neediness_score > 0.45:
        analysis.notes.append("需求感偏高")
    if analysis.pressure_score > 0.45:
        analysis.notes.append("推进压力偏高")
    if analysis.authenticity_score > 0.35:
        analysis.notes.append("真实性表达")
    if analysis.playfulness_score > 0.35:
        analysis.notes.append("轻松互动信号")
    if analysis.attachment_trigger_score > 0.35:
        analysis.notes.append("依恋焦虑触发")
    if pragmatic.slang_hits:
        analysis.notes.append("识别到梗/口语: " + ", ".join(pragmatic.slang_hits[:4]))
    if pragmatic.subtext != "没有明显潜台词":
        analysis.notes.append("潜台词: " + pragmatic.subtext)

    return analysis.bounded()


# ── LLM-powered Analyzer ──────────────────────────────────────────

ANALYZER_PROMPT = """Analyze this message in a romantic/dating context. Output ONLY valid JSON.

Message: "{message}"

Return:
{{
  "valence": <float -1 to 1, overall emotional tone: positive or negative>,
  "neediness_score": <float 0-1, how needy/clingy/desperate the sender sounds>,
  "pressure_score": <float 0-1, how much pressure to progress/commit/decide>,
  "authenticity_score": <float 0-1, how genuine, vulnerable, honest the sender is>,
  "playfulness_score": <float 0-1, humor, teasing, lightness>,
  "stability_score": <float 0-1, reliability, consistency, long-term orientation>,
  "value_signal_score": <float 0-1, demonstrating high-value traits (ambition, competence)>,
  "attachment_trigger_score": <float 0-1, signaling attachment anxiety or fear>,
  "surface_intent": "<string, what they're literally saying>",
  "deep_need": "<string, what they actually want/need emotionally>",
  "emotional_state": "<string, one: warm/neutral/cold/anxious/playful/guarded/frustrated>",
  "test_flag": <bool, is this a relationship test?>,
  "test_type": "<string or null, investment_test/compliance_test/jealousy_test/character_test>",
  "subtext": "<string, what they're really saying between the lines>",
  "reply_strategy": "<string, how the simulated person should answer without sounding like an assistant>",
  "register_tags": [<list of slang/pragmatic tags such as playful, boundary, soft_decline, test>],
  "slang_hits": [<list of detected slang/memes/inside jokes>],
  "implied_boundary": "<string, any implied boundary or pace signal>",
  "confidence": <float 0-1>,
  "notes": [<list of 1-3 key observations in Chinese>]
}}"""


def analyze_llm(message: str, api_base: str | None = None, api_key: str | None = None) -> TurnAnalysis:
    """Use LLM for semantic understanding of the message."""
    api_base = api_base or os.environ.get("OPENAI_API_BASE", "https://api.openai.com/v1")
    api_key = api_key or os.environ.get("OPENAI_API_KEY", "")

    if not api_key:
        return analyze_local(message)

    prompt = ANALYZER_PROMPT.format(message=message.replace('"', '\\"'))

    try:
        req = Request(
            f"{api_base.rstrip('/')}/chat/completions",
            data=json.dumps({
                "model": os.environ.get("CRUSH_ANALYZER_MODEL", "gpt-4o-mini"),
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
                "max_tokens": 400,
            }).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
        )
        resp = json.loads(urlopen(req, timeout=15).read())
        content = resp["choices"][0]["message"]["content"]

        # Parse JSON from response (handle markdown code blocks)
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]

        result = json.loads(content)

        analysis = TurnAnalysis(
            valence=float(result.get("valence", 0)),
            neediness_score=float(result.get("neediness_score", 0)),
            pressure_score=float(result.get("pressure_score", 0)),
            authenticity_score=float(result.get("authenticity_score", 0)),
            playfulness_score=float(result.get("playfulness_score", 0)),
            stability_score=float(result.get("stability_score", 0)),
            value_signal_score=float(result.get("value_signal_score", 0)),
            attachment_trigger_score=float(result.get("attachment_trigger_score", 0)),
            surface_intent=result.get("surface_intent", "普通聊天"),
            deep_need=result.get("deep_need", "保持自然互动"),
            emotional_state=result.get("emotional_state", "neutral"),
            test_flag=bool(result.get("test_flag", False)),
            test_type=result.get("test_type"),
            subtext=result.get("subtext", "没有明显潜台词"),
            reply_strategy=result.get("reply_strategy", "自然接话，不解释，不上价值"),
            register_tags=result.get("register_tags", []),
            slang_hits=result.get("slang_hits", []),
            implied_boundary=result.get("implied_boundary", ""),
            confidence=float(result.get("confidence", 0.7)),
            notes=result.get("notes", []),
        ).bounded()

        return analysis

    except Exception:
        return analyze_local(message)


# ── Public API ────────────────────────────────────────────────────

def analyze_text(message: str) -> TurnAnalysis:
    """Main entry point. Uses LLM if configured, otherwise local."""
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if api_key:
        return analyze_llm(message)
    return analyze_local(message)
