"""127.0.0.1-only WebSocket server for Tab Transcriber."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import secrets
import sys
from pathlib import Path

import websockets
from websockets.asyncio.server import ServerConnection, serve

from .asr import SAMPLE_RATE, StreamingASR, load_model
from .journal import SessionJournal
from .pcm import (
    SPEAKER_A,
    SPEAKER_B,
    SPEAKER_LABELS,
    decode_float32_pcm,
    decode_speaker_pcm,
)

logger = logging.getLogger(__name__)

HOST = "127.0.0.1"
DEFAULT_PORT = 17341
TOKEN_FILE_NAME = ".token"
MODE_SINGLE = "single"
MODE_AB = "ab"


def _token_path() -> Path:
    return Path(__file__).resolve().parent.parent / TOKEN_FILE_NAME


def generate_or_load_token() -> str:
    path = _token_path()
    if path.exists():
        existing = path.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    token = secrets.token_urlsafe(32)
    path.write_text(token + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return token


class SessionState:
    def __init__(self, session_id: str, mode: str, model) -> None:
        self.session_id = session_id
        self.mode = mode
        self.journal = SessionJournal(session_id)
        self.active = True
        self.lock = asyncio.Lock()
        if mode == MODE_AB:
            self.asr_by_speaker = {
                SPEAKER_A: StreamingASR(model),
                SPEAKER_B: StreamingASR(model),
            }
            self.asr: StreamingASR | None = None
        else:
            self.asr = StreamingASR(model)
            self.asr_by_speaker = {}


class HelperServer:
    def __init__(self, token: str, model_size: str, device: str, compute_type: str) -> None:
        self.token = token
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self._model = None
        self._sessions: dict[str, SessionState] = {}

    def get_model(self):
        if self._model is None:
            self._model = load_model(
                model_size=self.model_size,
                device=self.device,
                compute_type=self.compute_type,
            )
        return self._model

    async def handler(self, websocket: ServerConnection) -> None:
        # websockets 12+: request path may include query
        request = getattr(websocket, "request", None)
        path = getattr(request, "path", None) or getattr(websocket, "path", "/") or "/"
        query = ""
        if "?" in path:
            path, query = path.split("?", 1)
        params = dict(part.split("=", 1) for part in query.split("&") if "=" in part)
        token = params.get("token", "")
        if not secrets.compare_digest(token, self.token):
            await websocket.send(json.dumps({"type": "error", "message": "unauthorized"}))
            await websocket.close(4401, "unauthorized")
            return

        session: SessionState | None = None
        try:
            await websocket.send(
                json.dumps(
                    {
                        "type": "hello",
                        "host": HOST,
                        "sampleRate": SAMPLE_RATE,
                        "model": self.model_size,
                    }
                )
            )
            async for message in websocket:
                if isinstance(message, bytes):
                    if session is None or not session.active:
                        await websocket.send(
                            json.dumps({"type": "error", "message": "start session first"})
                        )
                        continue
                    await self._handle_audio(websocket, session, message)
                    continue

                try:
                    msg = json.loads(message)
                except json.JSONDecodeError:
                    await websocket.send(json.dumps({"type": "error", "message": "invalid json"}))
                    continue

                mtype = msg.get("type")
                if mtype == "ping":
                    await websocket.send(json.dumps({"type": "pong"}))
                    continue

                if mtype == "start":
                    try:
                        session = await self._start_session(msg)
                    except ValueError as exc:
                        await websocket.send(json.dumps({"type": "error", "message": str(exc)}))
                        continue
                    await websocket.send(
                        json.dumps(
                            {
                                "type": "ready",
                                "sessionId": session.session_id,
                                "journalPath": str(session.journal.path),
                                "mode": session.mode,
                            }
                        )
                    )
                    continue

                if mtype == "stop":
                    if session is None:
                        await websocket.send(
                            json.dumps({"type": "error", "message": "no active session"})
                        )
                        continue
                    done_text = await self._stop_session(websocket, session)
                    await websocket.send(
                        json.dumps(
                            {
                                "type": "done",
                                "sessionId": session.session_id,
                                "text": done_text,
                            }
                        )
                    )
                    session = None
                    continue

                await websocket.send(
                    json.dumps({"type": "error", "message": f"unknown type: {mtype}"})
                )
        except websockets.exceptions.ConnectionClosed:
            logger.info("client disconnected")
        finally:
            if session is not None and session.active:
                # Crash / disconnect: keep journal for recovery
                session.active = False
                logger.info("session %s left open journal at %s", session.session_id, session.journal.path)

    async def _start_session(self, msg: dict) -> SessionState:
        session_id = str(msg.get("sessionId") or secrets.token_hex(8))
        sample_rate = int(msg.get("sampleRate") or SAMPLE_RATE)
        if sample_rate != SAMPLE_RATE:
            raise ValueError(f"unsupported sampleRate {sample_rate}; expected {SAMPLE_RATE}")

        mode = str(msg.get("mode") or MODE_SINGLE).lower()
        if mode not in (MODE_SINGLE, MODE_AB):
            raise ValueError(f"unsupported mode {mode}; expected {MODE_SINGLE} or {MODE_AB}")

        model = self.get_model()

        if session_id in self._sessions:
            # Resume: reuse journal for same session id
            existing = self._sessions[session_id]
            existing.active = True
            existing.mode = mode
            if mode == MODE_AB:
                existing.asr_by_speaker = {
                    SPEAKER_A: StreamingASR(model),
                    SPEAKER_B: StreamingASR(model),
                }
                existing.asr = None
            else:
                existing.asr = StreamingASR(model)
                existing.asr_by_speaker = {}
            return existing

        active = [s for s in self._sessions.values() if s.active]
        if active:
            raise ValueError("another transcription session is already active")

        state = SessionState(session_id, mode, model)
        self._sessions[session_id] = state
        return state

    async def _emit_segments(
        self,
        websocket: ServerConnection,
        session: SessionState,
        segments,
        speaker: str = "",
    ) -> None:
        for seg in segments:
            if seg.text:
                line = session.journal.append(seg.text, speaker=speaker, t0=seg.t0, t1=seg.t1)
                payload: dict = {
                    "type": "segment",
                    "text": line,
                    "t0": seg.t0,
                    "t1": seg.t1,
                }
                if speaker:
                    payload["speaker"] = speaker
                await websocket.send(json.dumps(payload))
            lagging = seg.rtf > 1.05
            await websocket.send(
                json.dumps({"type": "status", "rtf": round(seg.rtf, 3), "lagging": lagging})
            )

    async def _handle_audio(
        self, websocket: ServerConnection, session: SessionState, data: bytes
    ) -> None:
        try:
            if session.mode == MODE_AB:
                speaker_id, pcm = decode_speaker_pcm(data)
                speaker = SPEAKER_LABELS[speaker_id]
                asr = session.asr_by_speaker[speaker_id]
            else:
                pcm = decode_float32_pcm(data)
                speaker = ""
                asr = session.asr
                assert asr is not None
        except ValueError as exc:
            await websocket.send(json.dumps({"type": "error", "message": str(exc)}))
            return

        async with session.lock:
            # Offload blocking whisper to a thread
            segments = await asyncio.to_thread(asr.append_pcm, pcm)

        await self._emit_segments(websocket, session, segments, speaker=speaker)

    async def _stop_session(self, websocket: ServerConnection, session: SessionState) -> str:
        async with session.lock:
            if session.mode == MODE_AB:
                flushed: list[tuple[str, list]] = []
                for speaker_id, asr in session.asr_by_speaker.items():
                    segments = await asyncio.to_thread(asr.flush)
                    flushed.append((SPEAKER_LABELS[speaker_id], segments))
            else:
                assert session.asr is not None
                segments = await asyncio.to_thread(session.asr.flush)
                flushed = [("", segments)]

        for speaker, segments in flushed:
            await self._emit_segments(websocket, session, segments, speaker=speaker)

        session.active = False
        text = session.journal.full_text()
        # Retain journal by default for crash recovery window
        return text


async def run_server(port: int, model_size: str, device: str, compute_type: str) -> None:
    token = generate_or_load_token()
    helper = HelperServer(token, model_size, device, compute_type)

    print(f"Token file: {_token_path()}", flush=True)
    print("Paste this token into the extension while the model loads.", flush=True)
    print("Loading Whisper model (first run may download weights)…", flush=True)
    await asyncio.to_thread(helper.get_model)
    print("Model ready.", flush=True)

    print(f"Tab Transcriber helper listening on ws://{HOST}:{port}", flush=True)
    print(f"Connect with ?token=<contents of {_token_path().name}>", flush=True)

    async with serve(helper.handler, HOST, port, max_size=8 * 1024 * 1024):
        await asyncio.Future()



def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Tab Transcriber local helper")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--model", default="base.en", help="faster-whisper model size")
    parser.add_argument("--device", default="cpu", choices=["cpu", "cuda", "auto"])
    parser.add_argument("--compute-type", default="int8")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    device = args.device
    if device == "auto":
        device = "cuda"
        try:
            import ctranslate2

            if ctranslate2.get_cuda_device_count() <= 0:
                device = "cpu"
        except Exception:
            device = "cpu"

    try:
        asyncio.run(run_server(args.port, args.model, device, args.compute_type))
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
