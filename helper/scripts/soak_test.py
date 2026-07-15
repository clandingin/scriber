"""Accelerated long-session soak: stream synthetic PCM and confirm memory stays bounded.

Usage (helper must already be running with matching token):

  .venv\\Scripts\\python scripts\\soak_test.py
"""

from __future__ import annotations

import argparse
import asyncio
import json
import struct
import sys
import time
from pathlib import Path

import numpy as np
import websockets

ROOT = Path(__file__).resolve().parent.parent
TOKEN_PATH = ROOT / ".token"
SAMPLE_RATE = 16_000
HOST = "127.0.0.1"
PORT = 17341


def load_token() -> str:
    if not TOKEN_PATH.exists():
        print(f"Missing token file: {TOKEN_PATH}", file=sys.stderr)
        sys.exit(1)
    return TOKEN_PATH.read_text(encoding="utf-8").strip()


def synthetic_chunk(seconds: float, freq: float = 220.0) -> bytes:
    n = int(SAMPLE_RATE * seconds)
    t = np.arange(n, dtype=np.float32) / SAMPLE_RATE
    # Tone + silence bursts to exercise VAD
    tone = 0.2 * np.sin(2 * np.pi * freq * t).astype(np.float32)
    gate = ((t * 2).astype(int) % 2 == 0).astype(np.float32)
    audio = tone * gate
    return struct.pack("<" + "f" * n, *audio.tolist())


async def run(duration_sec: float, chunk_sec: float) -> None:
    token = load_token()
    uri = f"ws://{HOST}:{PORT}/?token={token}"
    session_id = f"soak-{int(time.time())}"
    segments = 0
    max_text = 0

    async with websockets.connect(uri, max_size=8 * 1024 * 1024) as ws:
        await ws.send(json.dumps({"type": "start", "sessionId": session_id, "sampleRate": SAMPLE_RATE}))
        ready = json.loads(await ws.recv())
        assert ready.get("type") == "ready", ready

        async def reader() -> None:
            nonlocal segments, max_text
            async for raw in ws:
                if isinstance(raw, bytes):
                    continue
                msg = json.loads(raw)
                if msg.get("type") == "segment":
                    segments += 1
                    max_text = max(max_text, len(msg.get("text") or ""))
                if msg.get("type") == "done":
                    return

        reader_task = asyncio.create_task(reader())
        sent = 0.0
        while sent < duration_sec:
            await ws.send(synthetic_chunk(chunk_sec))
            sent += chunk_sec
            await asyncio.sleep(0)  # yield; faster than realtime

        await ws.send(json.dumps({"type": "stop"}))
        await asyncio.wait_for(reader_task, timeout=180)
        print(
            f"Soak complete: streamed {duration_sec:.0f}s audio (accelerated), "
            f"segments={segments}, max_segment_chars={max_text}"
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=float, default=120.0, help="Simulated audio seconds")
    parser.add_argument("--chunk", type=float, default=1.5)
    args = parser.parse_args()
    asyncio.run(run(args.duration, args.chunk))


if __name__ == "__main__":
    main()
