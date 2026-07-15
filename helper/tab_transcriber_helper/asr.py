"""faster-whisper ASR with rolling buffer and max-window segmentation."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16_000
MAX_WINDOW_SEC = 28.0
OVERLAP_SEC = 0.75
MIN_SPEECH_SEC = 0.4


@dataclass
class SegmentResult:
    text: str
    t0: float
    t1: float
    rtf: float


def load_model(
    model_size: str = "base.en",
    device: str = "cpu",
    compute_type: str = "int8",
) -> Any:
    from faster_whisper import WhisperModel

    logger.info(
        "Loading Whisper model size=%s device=%s compute_type=%s",
        model_size,
        device,
        compute_type,
    )
    return WhisperModel(model_size, device=device, compute_type=compute_type)


class StreamingASR:
    """Buffers PCM and transcribes when the rolling window fills or on flush."""

    def __init__(self, model: Any) -> None:
        self.model = model
        self._buffer = np.zeros(0, dtype=np.float32)
        self._stream_offset_sec = 0.0
        self._condition_text = ""
        self._last_condition_reset = time.monotonic()
        self._condition_reset_sec = 5 * 60

    def append_pcm(self, pcm: np.ndarray) -> list[SegmentResult]:
        if pcm.size == 0:
            return []
        audio = np.asarray(pcm, dtype=np.float32).reshape(-1)
        self._buffer = np.concatenate([self._buffer, audio])
        results: list[SegmentResult] = []
        max_samples = int(MAX_WINDOW_SEC * SAMPLE_RATE)
        while self._buffer.size >= max_samples:
            results.append(self._transcribe_window(force=False))
        return results

    def flush(self) -> list[SegmentResult]:
        min_samples = int(MIN_SPEECH_SEC * SAMPLE_RATE)
        if self._buffer.size < min_samples:
            self._buffer = np.zeros(0, dtype=np.float32)
            return []
        return [self._transcribe_window(force=True)]

    def _maybe_reset_condition(self) -> None:
        now = time.monotonic()
        if now - self._last_condition_reset >= self._condition_reset_sec:
            self._condition_text = ""
            self._last_condition_reset = now

    def _transcribe_window(self, force: bool) -> SegmentResult:
        self._maybe_reset_condition()
        overlap_samples = 0 if force else int(OVERLAP_SEC * SAMPLE_RATE)
        if force:
            window = self._buffer
            consumed = self._buffer.size
        else:
            max_samples = int(MAX_WINDOW_SEC * SAMPLE_RATE)
            window = self._buffer[:max_samples]
            consumed = max(0, max_samples - overlap_samples)

        duration = window.size / SAMPLE_RATE
        t0 = self._stream_offset_sec
        t1 = t0 + duration

        started = time.perf_counter()
        segments, _info = self.model.transcribe(
            window,
            language="en",
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 400},
            beam_size=3,
            best_of=3,
            condition_on_previous_text=True,
            initial_prompt=self._condition_text or None,
            without_timestamps=False,
        )
        texts: list[str] = []
        for seg in segments:
            part = (seg.text or "").strip()
            if part:
                texts.append(part)
        text = " ".join(texts).strip()
        elapsed = max(time.perf_counter() - started, 1e-6)
        rtf = elapsed / max(duration, 1e-6)

        if text:
            self._condition_text = (self._condition_text + " " + text).strip()[-400:]

        self._stream_offset_sec += consumed / SAMPLE_RATE
        self._buffer = self._buffer[consumed:]

        logger.debug("segment t0=%.2f t1=%.2f rtf=%.2f text_len=%d", t0, t1, rtf, len(text))
        return SegmentResult(text=text, t0=t0, t1=t1, rtf=rtf)
