import {
  DEFAULT_STATE,
  STORAGE_TOKEN_KEY,
  type BgToPopup,
  type PopupToBg,
  type SessionState,
} from "../lib/messages";

const statusBadge = document.getElementById("statusBadge") as HTMLSpanElement;
const elapsedEl = document.getElementById("elapsed") as HTMLSpanElement;
const tabTitleEl = document.getElementById("tabTitle") as HTMLParagraphElement;
const errorEl = document.getElementById("error") as HTMLParagraphElement;
const startBtn = document.getElementById("startBtn") as HTMLButtonElement;
const stopBtn = document.getElementById("stopBtn") as HTMLButtonElement;
const downloadBtn = document.getElementById("downloadBtn") as HTMLButtonElement;
const transcriptEl = document.getElementById("transcript") as HTMLTextAreaElement;
const rtfEl = document.getElementById("rtf") as HTMLSpanElement;
const lagEl = document.getElementById("lag") as HTMLSpanElement;
const tokenInput = document.getElementById("tokenInput") as HTMLInputElement;
const saveTokenBtn = document.getElementById("saveTokenBtn") as HTMLButtonElement;
const checkHelperBtn = document.getElementById("checkHelperBtn") as HTMLButtonElement;
const clearBtn = document.getElementById("clearBtn") as HTMLButtonElement;

const noteToggleBtn = document.getElementById("noteToggleBtn") as HTMLButtonElement;
const notePanel = document.getElementById("notePanel") as HTMLElement;
const diagnosisInput = document.getElementById("diagnosisInput") as HTMLTextAreaElement;
const resolveNoteBtn = document.getElementById("resolveNoteBtn") as HTMLButtonElement;
const clearNoteBtn = document.getElementById("clearNoteBtn") as HTMLButtonElement;
const downloadNoteBtn = document.getElementById("downloadNoteBtn") as HTMLButtonElement;
const noteReportEl = document.getElementById("noteReport") as HTMLTextAreaElement;

let state: SessionState = { ...DEFAULT_STATE };
let tickTimer: ReturnType<typeof setInterval> | null = null;
let diagnosisSaveTimer: ReturnType<typeof setTimeout> | null = null;

function send<T extends BgToPopup>(msg: PopupToBg): Promise<T> {
  return chrome.runtime.sendMessage(msg) as Promise<T>;
}

function formatElapsed(ms: number): string {
  const totalSec = Math.floor(ms / 1000);
  const h = Math.floor(totalSec / 3600);
  const m = Math.floor((totalSec % 3600) / 60);
  const s = totalSec % 60;
  if (h > 0) {
    return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  }
  return `${m}:${String(s).padStart(2, "0")}`;
}

function statusLabel(s: SessionState): { text: string; cls: string } {
  switch (s.status) {
    case "helper_offline":
      return { text: "Helper offline", cls: "warn" };
    case "idle":
      return { text: "Ready", cls: "ok" };
    case "capturing":
      return { text: "Capturing", cls: "live" };
    case "finalizing":
      return { text: "Finalizing…", cls: "warn" };
    case "ready":
      return { text: "Transcript ready", cls: "ok" };
    case "error":
      return { text: "Error", cls: "err" };
    default:
      return { text: s.status, cls: "" };
  }
}

function render(): void {
  const { text, cls } = statusLabel(state);
  statusBadge.textContent = text;
  statusBadge.className = `badge ${cls}`.trim();

  const elapsed =
    state.status === "capturing" && state.startedAt
      ? Date.now() - state.startedAt
      : state.elapsedMs;
  elapsedEl.textContent = elapsed > 0 ? formatElapsed(elapsed) : "";

  tabTitleEl.textContent = state.tabTitle ? `Tab: ${state.tabTitle}` : "";

  if (state.error) {
    errorEl.hidden = false;
    errorEl.textContent = state.error;
  } else {
    errorEl.hidden = true;
    errorEl.textContent = "";
  }

  startBtn.disabled = state.status === "capturing" || state.status === "finalizing";
  stopBtn.disabled = state.status !== "capturing";
  downloadBtn.disabled = !state.transcript.trim();

  transcriptEl.value = state.transcript;
  rtfEl.textContent = state.rtf != null ? `RTF ${state.rtf.toFixed(2)}` : "";
  lagEl.textContent = state.lagging ? "Helper lagging — dropping quiet audio" : "";

  notePanel.hidden = !state.notePanelOpen;
  noteToggleBtn.classList.toggle("active", state.notePanelOpen);
  noteToggleBtn.textContent = state.notePanelOpen ? "Hide note checkboxes" : "Note checkboxes";

  if (document.activeElement !== diagnosisInput) {
    diagnosisInput.value = state.diagnosis;
  }
  noteReportEl.value = state.noteReport;
  resolveNoteBtn.disabled = state.noteResolving || !state.transcript.trim();
  resolveNoteBtn.textContent = state.noteResolving ? "Resolving…" : "Resolve checkboxes";
  downloadNoteBtn.disabled = !state.noteReport.trim();
  clearNoteBtn.disabled = state.noteResolving;

  if (state.status === "capturing" && !tickTimer) {
    tickTimer = setInterval(() => render(), 500);
  } else if (state.status !== "capturing" && tickTimer) {
    clearInterval(tickTimer);
    tickTimer = null;
  }
}

function applyState(next: SessionState): void {
  state = next;
  render();
}

function downloadText(filenamePrefix: string, text: string): void {
  const trimmed = text.trim();
  if (!trimmed) return;
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  const name = `${filenamePrefix}-${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}-${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}.txt`;
  const blob = new Blob([trimmed + "\n"], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

/**
 * Offscreen documents cannot show Chrome's mic permission prompt.
 * Request (or re-confirm) permission from the popup first so Start can open the mic.
 */
async function ensureMicrophonePermission(): Promise<void> {
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: {
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: true,
    },
    video: false,
  });
  for (const track of stream.getTracks()) track.stop();
}

startBtn.addEventListener("click", () => {
  void (async () => {
    try {
      await ensureMicrophonePermission();
    } catch (err: unknown) {
      const detail = err instanceof Error ? err.message : String(err);
      errorEl.hidden = false;
      errorEl.textContent = `Microphone permission required to transcribe your voice. Allow access, then press Start again. (${detail})`;
      return;
    }
    const res = await send({ type: "START" });
    if (res.type === "STATE") applyState(res.state);
  })();
});

stopBtn.addEventListener("click", () => {
  void send({ type: "STOP" }).then((res) => {
    if (res.type === "STATE") applyState(res.state);
  });
});

downloadBtn.addEventListener("click", () => downloadText("transcript", state.transcript));

clearBtn.addEventListener("click", () => {
  void send({ type: "CLEAR_TRANSCRIPT" }).then((res) => {
    if (res.type === "STATE") applyState(res.state);
  });
});

checkHelperBtn.addEventListener("click", () => {
  void send({ type: "CHECK_HELPER" }).then((res) => {
    if (res.type === "STATE") applyState(res.state);
  });
});

saveTokenBtn.addEventListener("click", () => {
  const token = tokenInput.value.trim();
  void send({ type: "SET_TOKEN", token }).then((res) => {
    if (res.type === "STATE") applyState(res.state);
  });
});

noteToggleBtn.addEventListener("click", () => {
  void send({ type: "TOGGLE_NOTE_PANEL" }).then((res) => {
    if (res.type === "STATE") applyState(res.state);
  });
});

diagnosisInput.addEventListener("input", () => {
  if (diagnosisSaveTimer) clearTimeout(diagnosisSaveTimer);
  diagnosisSaveTimer = setTimeout(() => {
    void send({ type: "SET_DIAGNOSIS", diagnosis: diagnosisInput.value });
  }, 300);
});

resolveNoteBtn.addEventListener("click", () => {
  void send({
    type: "RESOLVE_NOTE",
    diagnosis: diagnosisInput.value,
    enableEmbeddings: false,
  }).then((res) => {
    if (res.type === "STATE") applyState(res.state);
    if (res.type === "ERROR") {
      errorEl.hidden = false;
      errorEl.textContent = res.message;
      resolveNoteBtn.disabled = false;
      resolveNoteBtn.textContent = "Resolve checkboxes";
    }
  });
});

clearNoteBtn.addEventListener("click", () => {
  void send({ type: "CLEAR_NOTE_REPORT" }).then((res) => {
    if (res.type === "STATE") applyState(res.state);
  });
});

downloadNoteBtn.addEventListener("click", () => downloadText("note-checkboxes", state.noteReport));

chrome.runtime.onMessage.addListener((message: BgToPopup) => {
  if (message?.type === "STATE") {
    applyState(message.state);
  }
});

void (async () => {
  const stored = await chrome.storage.local.get(STORAGE_TOKEN_KEY);
  if (typeof stored[STORAGE_TOKEN_KEY] === "string") {
    tokenInput.value = stored[STORAGE_TOKEN_KEY];
  }
  const res = await send<BgToPopup>({ type: "GET_STATE" });
  if (res?.type === "STATE") {
    applyState(res.state);
  } else {
    render();
  }
  await send({ type: "CHECK_HELPER" });
})();
