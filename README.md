# Tab Transcriber

Lightweight, **local-only** Chrome extension that captures audio from the active browser tab, streams it to a small **faster-whisper** helper on `127.0.0.1`, and exports a `.txt` transcript. Designed for **hour-long** video calls via chunked PCM + VAD windows — audio and transcripts never leave the machine.

> **HIPAA note:** This software implements technical controls suited to local PHI processing (loopback-only helper, token auth, no cloud STT, minimal permissions). It does **not** by itself constitute a HIPAA compliance program. Covered entities still need organizational policies, BAAs where applicable, workstation hardening, and workforce training.

## Architecture

1. **Extension (MV3)** — `tabCapture` + offscreen document captures tab audio, keeps it audible, resamples to 16 kHz, and streams ~1.5 s PCM chunks over WebSocket.
2. **Helper (Python)** — `faster-whisper` (CTranslate2) with Silero VAD, ~28 s rolling windows, incremental segments, append-only session journal.

## Quick start

### 1. Start the helper

```bat
cd helper
scripts\start-helper.bat
```

Wait until you see `listening on ws://127.0.0.1:17341`. Copy the token from `helper\.token`.

### 2. Build the extension

```bat
cd extension
npm install
npm run build
```

### 3. Load in Chrome

1. Open `chrome://extensions`
2. Enable **Developer mode**
3. **Load unpacked** → select `extension/dist`
4. Open the popup → **Helper settings** → paste token → **Save token** → **Check helper**

### 4. Transcribe a tab

1. Open a Meet / Zoom-in-browser / YouTube tab (anything with tab audio)
2. Click **Start** — tab audio should remain audible
3. Speak / play audio; transcript grows live as segments finalize (~30 s windows)
4. Click **Stop**, then **Download .txt**

## Project layout

```
tab-transcriber/
  extension/     Chrome MV3 + Vite + @crxjs/vite-plugin
  helper/        Python faster-whisper WebSocket service
  README.md
```

## Privacy / security controls (phase 1)

| Control | Behavior |
|---------|----------|
| Network | Helper binds `127.0.0.1` only; extension CSP `connect-src` limited to that origin |
| Auth | Random token in `helper/.token`; WS rejects missing/wrong token |
| Data | No upload of PCM or transcript; journals stay under local app data |
| Permissions | `tabCapture`, `offscreen`, `storage`, `activeTab` + localhost host permission |

## Long-call behavior

- Extension never buffers a full-hour recording
- Helper discards PCM after each transcribed window
- Backpressure: when RTF &gt; 1, extension drops quiet frames
- Heartbeat every 15 s; journal survives mid-call crashes

## Soak / verification checklist

- [ ] Helper refuses connections without token
- [ ] Short clip produces recognizable text in `.txt`
- [ ] Multi-minute / hour soak: extension memory stays roughly flat; transcript grows; Stop flushes remaining audio
- [ ] Confirm listen address is loopback only (`127.0.0.1`)

## Requirements

- Chrome 116+ (tabCapture stream ID → offscreen)
- Python 3.11+
- Node.js 18+ for building the extension
