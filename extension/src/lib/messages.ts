export type SessionStatus =
  | "helper_offline"
  | "idle"
  | "capturing"
  | "finalizing"
  | "ready"
  | "error";

export interface TranscriptSegment {
  text: string;
  t0: number;
  t1: number;
  /** A = own mic, B = browser/tab audio */
  speaker?: "A" | "B";
}

export interface SessionState {
  status: SessionStatus;
  sessionId: string | null;
  transcript: string;
  segments: TranscriptSegment[];
  elapsedMs: number;
  startedAt: number | null;
  helperOnline: boolean;
  lagging: boolean;
  rtf: number | null;
  error: string | null;
  tabTitle: string | null;
}

export const DEFAULT_STATE: SessionState = {
  status: "idle",
  sessionId: null,
  transcript: "",
  segments: [],
  elapsedMs: 0,
  startedAt: null,
  helperOnline: false,
  lagging: false,
  rtf: null,
  error: null,
  tabTitle: null,
};

export type PopupToBg =
  | { type: "GET_STATE" }
  | { type: "START" }
  | { type: "STOP" }
  | { type: "CHECK_HELPER" }
  | { type: "CLEAR_TRANSCRIPT" }
  | { type: "SET_TOKEN"; token: string };

export type BgToPopup =
  | { type: "STATE"; state: SessionState }
  | { type: "ERROR"; message: string };

export type BgToOffscreen =
  | {
      type: "OFFSCREEN_START";
      streamId: string;
      sessionId: string;
      token: string;
      helperUrl: string;
    }
  | { type: "OFFSCREEN_STOP" };

export type OffscreenToBg =
  | { type: "OFFSCREEN_BOOTED" }
  | { type: "OFFSCREEN_READY"; sessionId: string }
  | {
      type: "OFFSCREEN_SEGMENT";
      text: string;
      t0: number;
      t1: number;
      speaker?: "A" | "B";
    }
  | { type: "OFFSCREEN_STATUS"; rtf: number; lagging: boolean }
  | { type: "OFFSCREEN_DONE"; text: string }
  | { type: "OFFSCREEN_ERROR"; message: string }
  | { type: "OFFSCREEN_STOPPED" };

export const HELPER_PORT = 17341;
export const HELPER_WS_BASE = `ws://127.0.0.1:${HELPER_PORT}`;
export const HELPER_HTTP_BASE = `http://127.0.0.1:${HELPER_PORT}`;
export const STORAGE_TOKEN_KEY = "helperToken";
