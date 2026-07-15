import { HELPER_WS_BASE } from "./messages";

export type SpeakerId = "A" | "B";

export type HelperClientEvents = {
  onReady?: (sessionId: string, journalPath?: string) => void;
  onSegment?: (text: string, t0: number, t1: number, speaker?: SpeakerId) => void;
  onStatus?: (rtf: number, lagging: boolean) => void;
  onDone?: (text: string) => void;
  onError?: (message: string) => void;
  onClose?: () => void;
};

const SPEAKER_BYTE: Record<SpeakerId, number> = { A: 0, B: 1 };

/**
 * WebSocket client for the local faster-whisper helper (127.0.0.1 only).
 */
export class HelperClient {
  private ws: WebSocket | null = null;
  private pingTimer: ReturnType<typeof setInterval> | null = null;
  private readonly events: HelperClientEvents;
  private intentionalClose = false;

  constructor(events: HelperClientEvents = {}) {
    this.events = events;
  }

  get connected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN;
  }

  async connect(token: string, sessionId?: string): Promise<void> {
    this.intentionalClose = false;
    if (this.ws) {
      this.close();
    }

    const url = new URL(HELPER_WS_BASE);
    url.searchParams.set("token", token);
    if (sessionId) {
      url.searchParams.set("sessionId", sessionId);
    }

    await new Promise<void>((resolve, reject) => {
      const ws = new WebSocket(url.toString());
      ws.binaryType = "arraybuffer";
      this.ws = ws;

      const onOpen = () => {
        cleanupConnect();
        this.startHeartbeat();
        resolve();
      };
      const onError = () => {
        cleanupConnect();
        reject(new Error("Unable to connect to local helper at 127.0.0.1:17341"));
      };
      const cleanupConnect = () => {
        ws.removeEventListener("open", onOpen);
        ws.removeEventListener("error", onError);
      };

      ws.addEventListener("open", onOpen);
      ws.addEventListener("error", onError);
      ws.addEventListener("message", (ev) => this.handleMessage(ev));
      ws.addEventListener("close", () => {
        this.stopHeartbeat();
        if (!this.intentionalClose) {
          this.events.onClose?.();
        }
      });
    });
  }

  startSession(sessionId: string, sampleRate = 16000, mode: "single" | "ab" = "ab"): void {
    this.sendJson({ type: "start", sessionId, sampleRate, mode });
  }

  stopSession(): void {
    this.sendJson({ type: "stop" });
  }

  /**
   * Send float32 PCM little-endian samples.
   * In mode "ab", frames are prefixed with a uint32 LE speaker id (0=A mic, 1=B tab).
   */
  sendPcm(samples: Float32Array, speaker?: SpeakerId): void {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
    const copy = new Float32Array(samples.length);
    copy.set(samples);

    if (!speaker) {
      this.ws.send(copy.buffer);
      return;
    }

    const frame = new ArrayBuffer(4 + copy.byteLength);
    const view = new DataView(frame);
    view.setUint32(0, SPEAKER_BYTE[speaker], true);
    new Uint8Array(frame, 4).set(new Uint8Array(copy.buffer));
    this.ws.send(frame);
  }

  close(): void {
    this.intentionalClose = true;
    this.stopHeartbeat();
    if (this.ws) {
      try {
        this.ws.close();
      } catch {
        /* ignore */
      }
      this.ws = null;
    }
  }

  private sendJson(payload: unknown): void {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
    this.ws.send(JSON.stringify(payload));
  }

  private startHeartbeat(): void {
    this.stopHeartbeat();
    this.pingTimer = setInterval(() => {
      this.sendJson({ type: "ping" });
    }, 15_000);
  }

  private stopHeartbeat(): void {
    if (this.pingTimer) {
      clearInterval(this.pingTimer);
      this.pingTimer = null;
    }
  }

  private handleMessage(ev: MessageEvent): void {
    if (typeof ev.data !== "string") return;
    let msg: Record<string, unknown>;
    try {
      msg = JSON.parse(ev.data) as Record<string, unknown>;
    } catch {
      return;
    }

    const type = msg.type;
    if (type === "ready") {
      this.events.onReady?.(String(msg.sessionId ?? ""), msg.journalPath as string | undefined);
      return;
    }
    if (type === "segment") {
      const rawSpeaker = msg.speaker;
      const speaker =
        rawSpeaker === "A" || rawSpeaker === "B" ? (rawSpeaker as SpeakerId) : undefined;
      this.events.onSegment?.(
        String(msg.text ?? ""),
        Number(msg.t0 ?? 0),
        Number(msg.t1 ?? 0),
        speaker,
      );
      return;
    }
    if (type === "status") {
      this.events.onStatus?.(Number(msg.rtf ?? 0), Boolean(msg.lagging));
      return;
    }
    if (type === "done") {
      this.events.onDone?.(String(msg.text ?? ""));
      return;
    }
    if (type === "error") {
      this.events.onError?.(String(msg.message ?? "helper error"));
      return;
    }
    if (type === "pong" || type === "hello") {
      return;
    }
  }
}

/** Probe helper by opening/closing a WS with the token. */
export async function probeHelper(token: string, timeoutMs = 2000): Promise<boolean> {
  if (!token) return false;
  return new Promise((resolve) => {
    const url = new URL(HELPER_WS_BASE);
    url.searchParams.set("token", token);
    const ws = new WebSocket(url.toString());
    const timer = setTimeout(() => {
      try {
        ws.close();
      } catch {
        /* ignore */
      }
      resolve(false);
    }, timeoutMs);
    ws.addEventListener("open", () => {
      clearTimeout(timer);
      ws.close();
      resolve(true);
    });
    ws.addEventListener("error", () => {
      clearTimeout(timer);
      resolve(false);
    });
  });
}
