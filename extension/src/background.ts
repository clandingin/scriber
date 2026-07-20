import {
  DEFAULT_STATE,
  HELPER_WS_BASE,
  STORAGE_DIAGNOSIS_KEY,
  STORAGE_TOKEN_KEY,
  type BgToOffscreen,
  type BgToPopup,
  type OffscreenToBg,
  type PopupToBg,
  type SessionState,
} from "./lib/messages";
import { probeHelper, resolveNoteViaHelper } from "./lib/helperClient";

let state: SessionState = { ...DEFAULT_STATE };
let helperToken = "";

function broadcast(): void {
  const msg: BgToPopup = { type: "STATE", state: { ...state } };
  chrome.runtime.sendMessage(msg).catch(() => {
    /* popup may be closed */
  });
}

function setState(partial: Partial<SessionState>): void {
  state = { ...state, ...partial };
  if (state.startedAt && (state.status === "capturing" || state.status === "finalizing")) {
    state.elapsedMs = Date.now() - state.startedAt;
  }
  void chrome.storage.session.set({ sessionState: state });
  broadcast();
}

let offscreenBooted = false;

async function ensureOffscreen(): Promise<void> {
  const existing = await chrome.runtime.getContexts({
    contextTypes: [chrome.runtime.ContextType.OFFSCREEN_DOCUMENT],
  });
  if (existing.length > 0 && offscreenBooted) return;

  if (existing.length === 0) {
    offscreenBooted = false;
    const booted = new Promise<void>((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error("Offscreen document failed to boot")), 10_000);
      const listener = (message: OffscreenToBg) => {
        if (message?.type === "OFFSCREEN_BOOTED") {
          clearTimeout(timer);
          chrome.runtime.onMessage.removeListener(listener);
          offscreenBooted = true;
          resolve();
        }
      };
      chrome.runtime.onMessage.addListener(listener);
    });
    await chrome.offscreen.createDocument({
      url: "src/offscreen/index.html",
      reasons: [chrome.offscreen.Reason.USER_MEDIA],
      justification:
        "Capture tab audio and microphone for local transcription of both sides of a call",
    });
    await booted;
    return;
  }

  // Document exists (e.g. SW restarted) — assume ready
  offscreenBooted = true;
}

async function loadToken(): Promise<void> {
  const stored = await chrome.storage.local.get(STORAGE_TOKEN_KEY);
  if (typeof stored[STORAGE_TOKEN_KEY] === "string") {
    helperToken = stored[STORAGE_TOKEN_KEY];
  }
}

async function checkHelper(): Promise<boolean> {
  await loadToken();
  const online = await probeHelper(helperToken);
  setState({
    helperOnline: online,
    status:
      state.status === "capturing" || state.status === "finalizing"
        ? state.status
        : online
          ? state.transcript
            ? "ready"
            : "idle"
          : "helper_offline",
  });
  return online;
}

async function startTranscription(): Promise<void> {
  await loadToken();
  if (!helperToken) {
    setState({
      status: "error",
      error:
        "Helper token missing. Start the helper, then paste the token from helper/.token into Settings.",
      helperOnline: false,
    });
    return;
  }

  const online = await probeHelper(helperToken);
  if (!online) {
    setState({
      status: "helper_offline",
      helperOnline: false,
      error: "Local helper not reachable on 127.0.0.1:17341. Run start-helper.bat first.",
    });
    return;
  }

  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.id) {
    setState({ status: "error", error: "No active tab to capture." });
    return;
  }

  const sessionId = crypto.randomUUID();
  await ensureOffscreen();

  const streamId = await new Promise<string>((resolve, reject) => {
    chrome.tabCapture.getMediaStreamId({ targetTabId: tab.id }, (id) => {
      const err = chrome.runtime.lastError;
      if (err || !id) {
        reject(new Error(err?.message ?? "Failed to get tab media stream id"));
        return;
      }
      resolve(id);
    });
  });

  setState({
    status: "capturing",
    sessionId,
    transcript: "",
    segments: [],
    startedAt: Date.now(),
    elapsedMs: 0,
    error: null,
    helperOnline: true,
    lagging: false,
    rtf: null,
    tabTitle: tab.title ?? null,
  });

  const msg: BgToOffscreen = {
    type: "OFFSCREEN_START",
    streamId,
    sessionId,
    token: helperToken,
    helperUrl: HELPER_WS_BASE,
  };
  await chrome.runtime.sendMessage(msg);
}

async function stopTranscription(): Promise<void> {
  if (state.status !== "capturing") return;
  setState({ status: "finalizing" });
  const msg: BgToOffscreen = { type: "OFFSCREEN_STOP" };
  await chrome.runtime.sendMessage(msg);
}

function handleOffscreen(message: OffscreenToBg): void {
  switch (message.type) {
    case "OFFSCREEN_BOOTED":
      offscreenBooted = true;
      break;
    case "OFFSCREEN_READY":
      setState({ helperOnline: true, error: null });
      break;
    case "OFFSCREEN_SEGMENT": {
      const segments = [
        ...state.segments,
        {
          text: message.text,
          t0: message.t0,
          t1: message.t1,
          speaker: message.speaker,
        },
      ].sort((a, b) => a.t0 - b.t0 || (a.speaker ?? "").localeCompare(b.speaker ?? ""));
      const transcript = segments.map((s) => s.text).join("\n");
      setState({ segments, transcript });
      break;
    }
    case "OFFSCREEN_STATUS":
      setState({ rtf: message.rtf, lagging: message.lagging });
      break;
    case "OFFSCREEN_DONE":
      setState({
        status: "ready",
        transcript: message.text || state.transcript,
        startedAt: state.startedAt,
        elapsedMs: state.startedAt ? Date.now() - state.startedAt : state.elapsedMs,
      });
      break;
    case "OFFSCREEN_ERROR":
      setState({ status: "error", error: message.message });
      break;
    case "OFFSCREEN_STOPPED":
      if (state.status === "finalizing") {
        setState({ status: "ready" });
      }
      break;
    default:
      break;
  }
}

chrome.runtime.onMessage.addListener((message: PopupToBg | OffscreenToBg, _sender, sendResponse) => {
  if (!message || typeof message !== "object" || !("type" in message)) {
    return false;
  }

  if (String(message.type).startsWith("OFFSCREEN_")) {
    handleOffscreen(message as OffscreenToBg);
    return false;
  }

  const popupMsg = message as PopupToBg;
  switch (popupMsg.type) {
    case "GET_STATE":
      void loadToken().then(() => {
        sendResponse({ type: "STATE", state });
      });
      return true;
    case "CHECK_HELPER":
      void checkHelper().then(() => sendResponse({ type: "STATE", state }));
      return true;
    case "START":
      void startTranscription()
        .then(() => sendResponse({ type: "STATE", state }))
        .catch((err: unknown) => {
          const text = err instanceof Error ? err.message : String(err);
          setState({ status: "error", error: text });
          sendResponse({ type: "ERROR", message: text });
        });
      return true;
    case "STOP":
      void stopTranscription()
        .then(() => sendResponse({ type: "STATE", state }))
        .catch((err: unknown) => {
          const text = err instanceof Error ? err.message : String(err);
          setState({ status: "error", error: text });
          sendResponse({ type: "ERROR", message: text });
        });
      return true;
    case "CLEAR_TRANSCRIPT":
      setState({
        transcript: "",
        segments: [],
        status: state.helperOnline ? "idle" : "helper_offline",
        error: null,
        sessionId: null,
        startedAt: null,
        elapsedMs: 0,
        noteReport: "",
      });
      sendResponse({ type: "STATE", state });
      return false;
    case "SET_TOKEN":
      helperToken = popupMsg.token.trim();
      void chrome.storage.local.set({ [STORAGE_TOKEN_KEY]: helperToken }).then(() => {
        void checkHelper().then(() => sendResponse({ type: "STATE", state }));
      });
      return true;
    case "TOGGLE_NOTE_PANEL":
      setState({ notePanelOpen: !state.notePanelOpen });
      sendResponse({ type: "STATE", state });
      return false;
    case "SET_DIAGNOSIS":
      setState({ diagnosis: popupMsg.diagnosis });
      void chrome.storage.local.set({ [STORAGE_DIAGNOSIS_KEY]: popupMsg.diagnosis });
      sendResponse({ type: "STATE", state });
      return false;
    case "CLEAR_NOTE_REPORT":
      setState({ noteReport: "", error: null });
      sendResponse({ type: "STATE", state });
      return false;
    case "RESOLVE_NOTE":
      void (async () => {
        await loadToken();
        const diagnosis =
          typeof popupMsg.diagnosis === "string" ? popupMsg.diagnosis : state.diagnosis;
        setState({
          diagnosis,
          noteResolving: true,
          notePanelOpen: true,
          error: null,
        });
        void chrome.storage.local.set({ [STORAGE_DIAGNOSIS_KEY]: diagnosis });
        try {
          if (!helperToken) {
            throw new Error(
              "Helper token missing. Start the helper, then paste the token from helper/.token.",
            );
          }
          const online = await probeHelper(helperToken);
          if (!online) {
            throw new Error(
              "Local helper not reachable on 127.0.0.1:17341. Run start-helper.bat first.",
            );
          }
          const report = await resolveNoteViaHelper(
            helperToken,
            state.transcript,
            diagnosis,
            { enableEmbeddings: Boolean(popupMsg.enableEmbeddings) },
          );
          setState({
            noteReport: report,
            noteResolving: false,
            helperOnline: true,
            error: null,
          });
          sendResponse({ type: "STATE", state });
        } catch (err: unknown) {
          const text = err instanceof Error ? err.message : String(err);
          setState({ noteResolving: false, error: text });
          sendResponse({ type: "ERROR", message: text });
        }
      })();
      return true;
    default:
      return false;
  }
});

void (async () => {
  await loadToken();
  const savedLocal = await chrome.storage.local.get(STORAGE_DIAGNOSIS_KEY);
  if (typeof savedLocal[STORAGE_DIAGNOSIS_KEY] === "string") {
    state = { ...state, diagnosis: savedLocal[STORAGE_DIAGNOSIS_KEY] };
  }
  const saved = await chrome.storage.session.get("sessionState");
  if (saved.sessionState && typeof saved.sessionState === "object") {
    state = { ...DEFAULT_STATE, ...(saved.sessionState as SessionState) };
    if (typeof savedLocal[STORAGE_DIAGNOSIS_KEY] === "string") {
      state.diagnosis = savedLocal[STORAGE_DIAGNOSIS_KEY];
    }
    if (state.status === "capturing" || state.status === "finalizing") {
      // Service worker restart mid-capture — mark error for user to restart
      state = {
        ...state,
        status: "error",
        error: "Extension restarted during capture. Press Start to begin a new session.",
        noteResolving: false,
      };
    }
  }
  await checkHelper();
})();
