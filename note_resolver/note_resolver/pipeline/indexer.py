"""Stage 2 — Chunker / indexer.

Input: list[Turn]
Output: Index with spans + optional sentence-transformer embeddings
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np

from .parser import Turn, format_turn

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


@dataclass
class Span:
    """A searchable chunk over one or more consecutive turns."""

    span_id: int
    turn_indices: list[int]
    text: str
    speaker_hint: str  # dominant / last speaker label for display


@dataclass
class TranscriptIndex:
    turns: list[Turn]
    spans: list[Span]
    embeddings: np.ndarray | None = None  # shape (n_spans, dim) or None
    model_name: str | None = None
    _model: object | None = field(default=None, repr=False, compare=False)

    def embed_query(self, text: str) -> np.ndarray | None:
        if self._model is None or self.embeddings is None:
            return None
        vec = self._model.encode([text], normalize_embeddings=True)
        return np.asarray(vec[0], dtype=np.float32)


def build_spans(turns: list[Turn], window: int = 2) -> list[Span]:
    """Group turns into topical spans for retrieval.

    Prefers doctor→patient (A then B) pairs so a question and its answer
    stay together for polarity detection. Falls back to sliding windows
    for any leftover turns.
    """
    if not turns:
        return []

    spans: list[Span] = []
    used: set[int] = set()

    # Pass 1: A→B adjacency pairs
    i = 0
    while i < len(turns) - 1:
        a, b = turns[i], turns[i + 1]
        if a.speaker == "A" and b.speaker == "B":
            chunk = [a, b]
            spans.append(
                Span(
                    span_id=len(spans),
                    turn_indices=[t.index for t in chunk],
                    text=" ".join(format_turn(t) for t in chunk),
                    speaker_hint="B",
                )
            )
            used.add(a.index)
            used.add(b.index)
            i += 2
            continue
        i += 1

    # Pass 2: leftover single turns (and any non A-B sequences)
    for t in turns:
        if t.index in used:
            continue
        spans.append(
            Span(
                span_id=len(spans),
                turn_indices=[t.index],
                text=format_turn(t),
                speaker_hint=t.speaker,
            )
        )

    # Do not add B→A reverse windows — they attach an answer to the *next*
    # clinician question and poison polarity/citation.
    return spans


def build_index(
    turns: list[Turn],
    *,
    window: int = 2,
    model_name: str = DEFAULT_MODEL,
    enable_embeddings: bool = True,
) -> TranscriptIndex:
    """Build spans and (optionally) embed them with a small ST model."""
    spans = build_spans(turns, window=window)
    index = TranscriptIndex(turns=turns, spans=spans, model_name=None)

    if not enable_embeddings or not spans:
        logger.info("Index built with %d spans (embeddings disabled)", len(spans))
        return index

    try:
        from sentence_transformers import SentenceTransformer

        logger.info("Loading embedding model %s …", model_name)
        model = SentenceTransformer(model_name)
        texts = [s.text for s in spans]
        emb = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        index.embeddings = np.asarray(emb, dtype=np.float32)
        index.model_name = model_name
        index._model = model
        logger.info("Index built with %d spans + embeddings", len(spans))
    except Exception as exc:  # noqa: BLE001 — fall back to keyword-only
        logger.warning(
            "Embedding model unavailable (%s); keyword matching only.",
            exc,
        )
    return index
