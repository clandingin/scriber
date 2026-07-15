"""PCM binary frame helpers shared by tests/tools."""

from __future__ import annotations

import struct

import numpy as np


def encode_float32_pcm(samples: np.ndarray) -> bytes:
    audio = np.asarray(samples, dtype=np.float32).reshape(-1)
    return struct.pack("<" + "f" * audio.size, *audio.tolist())


def decode_float32_pcm(data: bytes) -> np.ndarray:
    if len(data) % 4 != 0:
        raise ValueError("PCM frame length must be multiple of 4 (float32)")
    count = len(data) // 4
    return np.array(struct.unpack("<" + "f" * count, data), dtype=np.float32)
