    # Written by Anju for the Multi-Agent Creative Studio capstone (new file, not part
    # of the original starter).
"""Deterministic guardrails for the Creative Director.

Two ADK callbacks:
  * input_guardrail  (before_model_callback): screens the user's message before
    any model call. Blocks empty or oversized briefs, obvious prompt-injection
    attempts and clearly harmful requests.
  * output_guardrail (after_model_callback): lints the final report for risky
    marketing claims (health or statistical claims with no source) and appends
    a visible "Compliance check" note. It warns; it never deletes content.

These are intentionally simple, rule-based checks. They are a safety net around
the prompt-level rules and the Critic, not a replacement for human review.
"""
import logging
import re
from typing import Optional

from google.genai import types

try:
    from google.adk.models import LlmResponse
except ImportError:  # older import path
    from google.adk.models.llm_response import LlmResponse

logger = logging.getLogger("ai_creative_studio.guardrails")

MAX_BRIEF_CHARS = 2000

# Phrases that try to override the agent's instructions.
_INJECTION_PATTERNS = [
    r"ignore (all |any |your |the )?(previous|prior|above|earlier) (instructions|rules|prompts?)",
    r"disregard (all |any |the |your )?(system|previous|prior) (prompt|instructions|rules)",
    r"(reveal|show|print|repeat) (me )?(your |the )?(system )?(prompt|instructions)",
    r"\byou are now\b",
    r"\bdeveloper mode\b",
    r"\bjailbreak\b",
    r"override (your |the )?(safety|guardrails?|rules)",
]

# Requests the studio will not work on at all.
_HARMFUL_PATTERNS = [
    r"\b(bomb|explosive|detonator|ammunition)s?\b",
    r"\bfake (reviews?|testimonials?|endorsements?)\b",
    r"\bcounterfeit\b",
    r"\bchild (sexual|porn)",
    r"\b(deepfake|impersonat\w+)\b",
    r"\bhate (speech|campaign)\b",
    r"\b(self[- ]harm|suicide) (promotion|campaign)\b",
]

# Unsupported or risky marketing claims.
_CLAIM_PATTERNS = [
    (r"clinically (proven|tested|shown)", "clinical claim"),
    (r"scientifically proven", "scientific claim"),
    (r"\bguarantee[ds]?\b", "guarantee"),
    (r"\bcures?\b", "cure claim"),
    (r"\bFDA[- ](approved|cleared)\b", "regulatory claim"),
    (r"doctor[- ](recommended|approved)", "medical endorsement"),
    (r"\bmiracle\b", "miracle claim"),
    (r"\bdetox\w*\b", "detox claim"),
    (r"\b\d{1,3}% (more|less|better|faster|increase|improvement|boost)\b", "unsourced statistic"),
]

REFUSAL_EMPTY = (
    "I need a campaign brief to start. Please describe the product, the target "
    "audience and how many posts you want."
)
REFUSAL_LONG = (
    "That brief is too long for me to process safely (limit: %d characters). "
    "Please shorten it to the product, audience and number of posts." % MAX_BRIEF_CHARS
)
REFUSAL_INJECTION = (
    "I can't follow instructions that try to change my rules or reveal my "
    "configuration. Please send a normal campaign brief and I'll get started."
)
REFUSAL_HARMFUL = (
    "I can't help with that request. The Creative Studio only creates honest, "
    "lawful marketing campaigns. Please send a different brief."
)


def check_input(text: str):
    """Return (ok, reason, message). reason is None when ok."""
    if text is None or not text.strip():
        return False, "empty", REFUSAL_EMPTY
    if len(text) > MAX_BRIEF_CHARS:
        return False, "too_long", REFUSAL_LONG
    lowered = text.lower()
    for pattern in _INJECTION_PATTERNS:
        if re.search(pattern, lowered):
            return False, "prompt_injection", REFUSAL_INJECTION
    for pattern in _HARMFUL_PATTERNS:
        if re.search(pattern, lowered):
            return False, "harmful_request", REFUSAL_HARMFUL
    return True, None, ""


def scan_claims(text: str):
    """Return a sorted list of (label, matched text) for risky claims."""
    found = []
    for pattern, label in _CLAIM_PATTERNS:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            found.append((label, match.group(0)))
    return sorted(set(found))


def _latest_user_text(llm_request) -> Optional[str]:
    """Text of the newest user message, or None when the last content is a
    tool result or model turn (nothing new from the user to check)."""
    contents = getattr(llm_request, "contents", None) or []
    if not contents:
        return None
    last = contents[-1]
    if getattr(last, "role", None) != "user":
        return None
    parts = getattr(last, "parts", None) or []
    if any(getattr(p, "function_response", None) for p in parts):
        return None
    texts = [p.text for p in parts if getattr(p, "text", None)]
    if not texts:
        return ""
    return "\n".join(texts)


def _text_response(message: str) -> LlmResponse:
    return LlmResponse(
        content=types.Content(role="model", parts=[types.Part(text=message)])
    )


def input_guardrail(callback_context, llm_request) -> Optional[LlmResponse]:
    """before_model_callback: block bad input before the model is called."""
    text = _latest_user_text(llm_request)
    if text is None:
        return None
    ok, reason, message = check_input(text)
    if ok:
        return None
    logger.warning("Input guardrail blocked a request: reason=%s", reason)
    try:
        callback_context.state["guardrail_blocked"] = reason
    except Exception:
        pass
    return _text_response(message)


def output_guardrail(callback_context, llm_response) -> Optional[LlmResponse]:
    """after_model_callback: append a compliance note to risky final reports."""
    content = getattr(llm_response, "content", None)
    if content is None or getattr(llm_response, "partial", False):
        return None
    parts = getattr(content, "parts", None) or []
    if any(getattr(p, "function_call", None) for p in parts):
        return None
    text = "\n".join(p.text for p in parts if getattr(p, "text", None))
    if not text or "Compliance check:" in text:
        return None
    flagged = scan_claims(text)
    if not flagged:
        return None
    logger.warning("Output guardrail flagged %d claim(s)", len(flagged))
    try:
        callback_context.state["guardrail_flags"] = [m for _, m in flagged]
    except Exception:
        pass
    lines = ["", "Compliance check: possible unsupported claims found. "
             "Review before publishing:"]
    for label, matched in flagged:
        lines.append('- %s: "%s"' % (label, matched))
    parts.append(types.Part(text="\n".join(lines)))
    return llm_response
