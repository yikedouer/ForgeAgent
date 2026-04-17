"""Tiered context-window compaction.

Problem: The model has a finite context window, but a complex task may
span dozens of rounds producing large tool outputs. Without compaction
the conversation will eventually exceed the budget and fail.

Solution: A three-tier compaction pipeline, each tier more aggressive
than the last. The engine invokes `maybe_compact()` after every round;
it applies the lightest sufficient tier and stops.

  Tier 1 — DISTILL:  Replace verbose tool outputs older than N turns
           with a one-line digest. Cheap and lossless for recent work.

  Tier 2 — CONDENSE: Ask the LLM to summarise the entire conversation
           so far into a compact paragraph, then drop all messages
           older than the summary. Moderate cost, some information loss.

  Tier 3 — PRUNE:    Emergency fallback. Keep only the system message,
           the most recent K messages, and a brief header. Used when
           even a condensed summary would push past the budget.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..core.providers import Provider


def _estimate_tokens(text: str) -> int:
    """Rough heuristic — ~3.5 chars per token for mixed content."""
    return max(1, len(text) // 4)


def _msg_tokens(msg: dict) -> int:
    total = 0
    if msg.get("content"):
        total += _estimate_tokens(str(msg["content"]))
    if msg.get("tool_calls"):
        total += _estimate_tokens(str(msg["tool_calls"]))
    return total


def _conversation_tokens(messages: list[dict]) -> int:
    return sum(_msg_tokens(m) for m in messages)


# ── Tier 1: Distill old tool outputs ────────────────────────

def _distill(messages: list[dict], keep_recent: int = 6) -> bool:
    """Trim tool-result messages older than `keep_recent` to a short tag."""
    changed = False
    cutoff = len(messages) - keep_recent

    for i in range(cutoff):
        m = messages[i]
        if m.get("role") == "tool" and len(str(m.get("content", ""))) > 200:
            original = str(m["content"])
            lines = original.splitlines()
            if len(lines) > 3:
                digest = f"{lines[0]}  ... [{len(lines)} lines distilled] ...  {lines[-1]}"
                messages[i] = {**m, "content": digest}
                changed = True
    return changed


# ── Boundary safety ────────────────────────────────────────

def _safe_split_point(messages: list[dict], desired: int) -> int:
    """Adjust a split point so we don't cut between tool_use and tool_result.

    The API requires that every assistant message containing tool_calls
    is immediately followed by corresponding tool-role messages.  Splitting
    between them causes an error.

    Walk *backward* from `desired` until we find a point that is NOT
    inside a tool_use→tool_result pair.
    """
    idx = min(desired, len(messages))
    # walk back: if the message at idx is a tool result, keep going back
    # until we've passed the matching assistant message with tool_calls.
    while idx > 1:
        msg = messages[idx - 1] if idx <= len(messages) else None
        if msg is None:
            break
        # if we'd start right after a tool-result, we're mid-pair
        if msg.get("role") == "tool":
            idx -= 1
            continue
        # if we'd start right after an assistant with tool_calls,
        # the tool results following it haven't been included yet
        if (msg.get("role") == "assistant" and msg.get("tool_calls")):
            idx -= 1
            continue
        break
    return max(idx, 1)  # never go before index 1 (keep system msg)


# ── Tier 2: LLM-powered condensation ───────────────────────

_CONDENSE_PROMPT = (
    "Summarise the conversation so far into a concise paragraph. "
    "Preserve key decisions, file paths modified, and pending tasks. "
    "Omit tool output details."
)


def _condense(messages: list[dict], provider: Provider, keep_recent: int = 8) -> bool:
    """Replace old messages with an LLM-generated summary."""
    if len(messages) <= keep_recent + 2:
        return False

    # find safe boundary
    split = _safe_split_point(messages, len(messages) - keep_recent)
    old_slice = messages[1:split]
    if not old_slice:
        return False

    summary_input = [
        {"role": "user", "content": _CONDENSE_PROMPT},
        {"role": "user", "content": "\n".join(
            f"[{m.get('role', '?')}] {str(m.get('content', ''))[:300]}"
            for m in old_slice
        )},
    ]
    try:
        result = provider.generate(summary_input)
        summary_text = result.text or "(no summary produced)"
    except Exception:
        return False  # degrade gracefully — skip condensation

    # replace old messages with the summary
    summary_msg = {"role": "user", "content": f"[CONTEXT SUMMARY]\n{summary_text}"}
    messages[1:split] = [summary_msg]
    return True


# ── Tier 3: Emergency prune ─────────────────────────────────

def _prune(messages: list[dict], keep_recent: int = 4) -> bool:
    """Last resort — drop everything except system + recent tail."""
    if len(messages) <= keep_recent + 1:
        return False

    # find safe boundary
    split = _safe_split_point(messages, len(messages) - keep_recent)
    tail = messages[split:]

    header = {"role": "user", "content": "[CONTEXT PRUNED — earlier messages removed to fit budget]"}

    # check if first message is system
    if messages and messages[0].get("role") == "system":
        messages[:] = [messages[0], header] + tail
    else:
        messages[:] = [header] + tail
    return True


# ── Public entry point ──────────────────────────────────────

def maybe_compact(
    messages: list[dict],
    budget: int,
    provider: Provider | None = None,
) -> bool:
    """Apply the lightest compaction tier that brings the conversation
    under budget. Returns True if any compaction was performed."""

    current = _conversation_tokens(messages)
    if current <= budget * 0.55:
        return False  # well within budget — do nothing

    # Tier 1: distill old tool outputs
    if current > budget * 0.55:
        if _distill(messages):
            current = _conversation_tokens(messages)
            if current <= budget * 0.70:
                return True

    # Tier 2: LLM condensation
    if current > budget * 0.70 and provider is not None and len(messages) > 12:
        if _condense(messages, provider):
            current = _conversation_tokens(messages)
            if current <= budget * 0.90:
                return True

    # Tier 3: emergency prune
    if current > budget * 0.90:
        _prune(messages)
        return True

    return False
