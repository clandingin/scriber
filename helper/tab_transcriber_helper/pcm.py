"""PCM binary frame helpers shared by tests/tools."""

from __future__ import annotations

import struct

import numpy as np

# Dual-stream speaker ids (extension: A = mic, B = browser tab)
SPEAKER_A = 0
SPEAKER_B = 1
SPEAKER_LABELS = {SPEAKER_A: "A", SPEAKER_B: "B"}


def encode_float32_pcm(samples: np.ndarray) -> bytes:
    audio = np.asarray(samples, dtype=np.float32).reshape(-1)
    return struct.pack("<" + "f" * audio.size, *audio.tolist())


def decode_float32_pcm(data: bytes) -> np.ndarray:
    if len(data) % 4 != 0:
        raise ValueError("PCM frame length must be multiple of 4 (float32)")
    count = len(data) // 4
    return np.array(struct.unpack("<" + "f" * count, data), dtype=np.float32)


def encode_speaker_pcm(speaker: int, samples: np.ndarray) -> bytes:
    """Frame: uint32 LE speaker id + float32 LE PCM samples."""
    if speaker not in SPEAKER_LABELS:
        raise ValueError(f"unsupported speaker id {speaker}")
    return struct.pack("<I", speaker) + encode_float32_pcm(samples)


def decode_speaker_pcm(data: bytes) -> tuple[int, np.ndarray]:
    if len(data) < 4:
        raise ValueError("speaker PCM frame too short")
    (speaker,) = struct.unpack_from("<I", data, 0)
    if speaker not in SPEAKER_LABELS:
        raise ValueError(f"unsupported speaker id {speaker}")
    return speaker, decode_float32_pcm(data[4:])


def format_speaker_line(speaker: str, text: str) -> str:
    cleaned = text.strip()
    if not cleaned:
        return ""
    label = speaker.strip().upper()
    if label in ("A", "B"):
        return f"{label}: {cleaned}"
    return cleaned
