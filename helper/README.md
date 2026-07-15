# Tab Transcriber Helper

Local **faster-whisper** WebSocket service bound to `127.0.0.1` only. The Chrome extension streams 16 kHz PCM here (dual-channel mode: **A** = mic, **B** = tab); nothing is uploaded.

## Setup (Windows)

```bat
cd helper
scripts\start-helper.bat
```

Or manually:

```bat
cd helper
python -m venv .venv
.venv\Scripts\pip install -U pip
.venv\Scripts\pip install -e .
.venv\Scripts\python -m tab_transcriber_helper.server
```

On first run the Whisper model (default `base.en`) downloads into the Hugging Face / faster-whisper cache. That fetch is **model weights only** — never call audio.

## Token

A random token is written to `helper\.token`. Paste it into the extension popup under **Helper settings**.

Connect URL shape:

`ws://127.0.0.1:17341/?token=<token>`

## Options

```bat
.venv\Scripts\python -m tab_transcriber_helper.server --model small.en --device auto -v
```

| Flag | Default | Notes |
|------|---------|--------|
| `--port` | `17341` | Loopback only |
| `--model` | `base.en` | faster-whisper size |
| `--device` | `cpu` | `cpu`, `cuda`, or `auto` |
| `--compute-type` | `int8` | Use `float16` on CUDA if desired |

## Journals

Finalized segments append under `%LOCALAPPDATA%\tab-transcriber\sessions\` for crash recovery during long calls.
