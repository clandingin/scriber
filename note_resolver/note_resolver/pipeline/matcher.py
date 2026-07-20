"""Stage 3 — Mention matcher.

Input: TranscriptIndex + item/tag name + keyword hints
Output: MentionMatch (matched, span, turn_index, polarity, score, method)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Literal

import numpy as np

from .indexer import TranscriptIndex
from .parser import Turn

logger = logging.getLogger(__name__)

Polarity = Literal["affirmed", "negated", "unknown"]

NEGATION_CUES = (
    r"\b(?:no|not|never|none|deny|denies|denied|denying|negative|"
    r"without|hasn't|haven't|didn't|does(?:n't| not)|do(?:n't| not)|"
    r"isn't|aren't|wasn't|weren't|no history of|denies any)\b"
)
AFFIRM_CUES = (
    r"\b(?:yes|yeah|yep|yup|endorses?|positive for|still use|still using|"
    r"currently use|currently using|i drink|i smoke|i use|i used|"
    r"sometimes|often|daily|weekly|a few times|occasionally)\b"
)

NEG_RE = re.compile(NEGATION_CUES, re.IGNORECASE)
AFF_RE = re.compile(AFFIRM_CUES, re.IGNORECASE)


@dataclass(frozen=True)
class MentionMatch:
    matched: bool
    span_text: str | None
    turn_index: int | None
    polarity: Polarity
    score: float
    method: str  # "keyword" | "embedding" | "none"
    matched_keyword: str | None = None


def _keyword_hit(text: str, keywords: list[str]) -> str | None:
    lower = text.lower()
    # Longer keywords first so "crystal meth" beats "meth"
    for kw in sorted((k for k in keywords if k.strip()), key=len, reverse=True):
        pattern = re.compile(rf"\b{re.escape(kw.lower())}\b", re.IGNORECASE)
        if pattern.search(lower):
            return kw
    return None


def _window_around(text: str, keyword: str, radius: int = 60) -> str:
    lower = text.lower()
    idx = lower.find(keyword.lower())
    if idx < 0:
        return text
    start = max(0, idx - radius)
    end = min(len(text), idx + len(keyword) + radius)
    return text[start:end]


def _patient_text(span_text: str) -> str:
    """Extract patient (B:) utterances only, stopping before the next A:."""
    matches = re.findall(
        r"\bB\s*[:\-–—]\s*(.*?)(?=\s+\bA\s*[:\-–—]|\s*$)",
        span_text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return " ".join(m.strip() for m in matches if m.strip())


def detect_polarity(text: str, keyword: str | None = None) -> Polarity:
    """Lightweight local negation/affirmation heuristic around a hit.

    Prefer the patient (B:) portion of a Q/A span when present, since the
    clinician question often lists the keyword without asserting use.
    """
    patient_text = _patient_text(text)
    focus = patient_text if patient_text else text
    if keyword and keyword.lower() in focus.lower():
        snippet = _window_around(focus, keyword, radius=40)
    else:
        snippet = focus

    neg = bool(NEG_RE.search(snippet))
    aff = bool(AFF_RE.search(snippet))
    if neg and not aff:
        return "negated"
    if aff and not neg:
        return "affirmed"
    if neg and aff:
        neg_pos = max((m.end() for m in NEG_RE.finditer(snippet)), default=-1)
        aff_pos = max((m.end() for m in AFF_RE.finditer(snippet)), default=-1)
        return "negated" if neg_pos >= aff_pos else "affirmed"
    # Only use whole-reply denial when the keyword itself wasn't in the patient text
    # (typical for clinician-listed items answered with a blanket "no").
    if (
        patient_text
        and keyword
        and keyword.lower() not in patient_text.lower()
        and re.search(r"\bdeny(?:\s+all|\s+any)?\b|\bno\b", patient_text, re.I)
    ):
        return "negated"
    return "unknown"


def _primary_turn_index(index: TranscriptIndex, turn_indices: list[int]) -> int:
    """Prefer a patient (B) turn when the span covers both speakers."""
    turns_by_i = {t.index: t for t in index.turns}
    for ti in reversed(turn_indices):
        t = turns_by_i.get(ti)
        if t and t.speaker == "B":
            return ti
    return turn_indices[-1]


def _embedding_search(
    index: TranscriptIndex,
    query: str,
    *,
    top_k: int = 3,
    min_score: float = 0.42,
) -> tuple[int, float] | None:
    q = index.embed_query(query)
    if q is None or index.embeddings is None:
        return None
    scores = index.embeddings @ q
    best_i = int(np.argmax(scores))
    best = float(scores[best_i])
    if best < min_score:
        return None
    # Optionally inspect top_k for logging
    order = np.argsort(-scores)[:top_k]
    logger.debug(
        "Embedding top hits for %r: %s",
        query,
        [(int(i), float(scores[i])) for i in order],
    )
    return best_i, best


GLOBAL_DENIAL_KEYWORDS = {
    "no drugs",
    "deny all",
    "denies all",
    "no drug use",
    "don't do drugs",
    "do not use drugs",
}


def match_mention(
    index: TranscriptIndex,
    *,
    name: str,
    keywords: list[str],
    require_polarity: bool = False,
    skip_negated: bool = False,
    embedding_threshold: float = 0.42,
) -> MentionMatch:
    """Keyword-first mention detection with embedding fallback.

    Contract:
      in  — TranscriptIndex, field/tag name, synonym/keyword hints
      out — MentionMatch
    """
    if not index.spans:
        return MentionMatch(
            matched=False,
            span_text=None,
            turn_index=None,
            polarity="unknown",
            score=0.0,
            method="none",
        )

    # 1) Keyword pass — collect candidates, prefer clear patient polarity
    candidates: list[MentionMatch] = []
    for span in index.spans:
        hit = _keyword_hit(span.text, keywords)
        if not hit:
            continue
        polarity = detect_polarity(span.text, hit) if require_polarity else "unknown"
        turn_index = _primary_turn_index(index, span.turn_indices)
        candidates.append(
            MentionMatch(
                matched=True,
                span_text=span.text,
                turn_index=turn_index,
                polarity=polarity,
                score=1.0,
                method="keyword",
                matched_keyword=hit,
            )
        )

    if candidates:
        if skip_negated:
            candidates = [m for m in candidates if m.polarity != "negated"]
        if not candidates:
            logger.info("NO match for %-20s (only negated keyword hits)", name)
            return MentionMatch(
                matched=False,
                span_text=None,
                turn_index=None,
                polarity="unknown",
                score=0.0,
                method="none",
            )
        ranked = sorted(
            candidates,
            key=lambda m: (
                # Prefer item-specific keywords over global denial phrases
                1
                if (m.matched_keyword or "").lower() in GLOBAL_DENIAL_KEYWORDS
                else 0,
                0 if m.polarity in ("negated", "affirmed") else 1,
                -len(m.matched_keyword or ""),
                # Prefer classic A→B question/answer spans
                0 if (m.span_text or "").lstrip().upper().startswith("A") else 1,
                m.turn_index or 0,
            ),
        )
        match = ranked[0]
        logger.info(
            "KEYWORD match %-20s kw=%-16s turn=%s polarity=%s | %s",
            name,
            match.matched_keyword,
            match.turn_index,
            match.polarity,
            (match.span_text or "")[:120],
        )
        return match

    # 2) Embedding fallback — query from name + keywords
    query = " ".join([name, *keywords[:6]])
    hit = _embedding_search(index, query, min_score=embedding_threshold)
    if hit is None:
        logger.info("NO match for %-20s", name)
        return MentionMatch(
            matched=False,
            span_text=None,
            turn_index=None,
            polarity="unknown",
            score=0.0,
            method="none",
        )

    span_i, score = hit
    span = index.spans[span_i]
    kw = _keyword_hit(span.text, keywords) or _keyword_hit(span.text, [name])
    polarity = detect_polarity(span.text, kw or name) if require_polarity else "unknown"
    turn_index = _primary_turn_index(index, span.turn_indices)
    match = MentionMatch(
        matched=True,
        span_text=span.text,
        turn_index=turn_index,
        polarity=polarity,
        score=score,
        method="embedding",
        matched_keyword=kw,
    )
    logger.info(
        "EMBED  match %-20s score=%.3f turn=%s polarity=%s | %s",
        name,
        score,
        turn_index,
        polarity,
        span.text[:120],
    )
    return match


def turn_citation(turns: list[Turn], turn_index: int | None) -> dict | None:
    if turn_index is None:
        return None
    for t in turns:
        if t.index == turn_index:
            return {
                "turn_index": t.index,
                "speaker": t.speaker,
                "text": t.text,
            }
    return None
