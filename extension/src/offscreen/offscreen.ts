import { HelperClient } from "../lib/helperClient";
import type { BgToOffscreen, OffscreenToBg } from "../lib/messages";
import { PcmChunker, resampleTo16k, TARGET_SAMPLE_RATE } from "../lib/pcm";

let mediaStream: MediaStream | null = null;
let audioContext: AudioContext | null = null;
let workletNode: AudioWorkletNode | null = null;
let sourceNode: MediaStreamAudioSourceNode | null = null;
let silentGain: GainNode | null = null;
let helper: HelperClient | null = null;
let chunker: PcmChunker | null = null;
let lagging = false;
let scriptNode: ScriptProcessorNode | null = null;
let doneWaiter: { resolve: (text: string) => void; reject: (err: Error) => void } | null =
  null;

function post(msg: OffscreenToBg): void {
  chrome.runtime.sendMessage(msg);
}

async function startCapture(msg: Extract<BgToOffscreen, { type: "OFFSCREEN_START" }>): Promise<void> {
  await stopCaptureInternal(false);

  helper = new HelperClient({
    onReady: (sessionId) => post({ type: "OFFSCREEN_READY", sessionId }),
    onSegment: (text, t0, t1) => post({ type: "OFFSCREEN_SEGMENT", text, t0, t1 }),
    onStatus: (rtf, isLagging) => {
      lagging = isLagging;
      post({ type: "OFFSCREEN_STATUS", rtf, lagging: isLagging });
    },
    onDone: (text) => {
      post({ type: "OFFSCREEN_DONE", text });
      doneWaiter?.resolve(text);
      doneWaiter = null;
    },
    onError: (message) => {
      post({ type: "OFFSCREEN_ERROR", message });
      doneWaiter?.reject(new Error(message));
      doneWaiter = null;
    },
    onClose: () => {
      if (doneWaiter) {
        doneWaiter.reject(new Error("Helper connection closed"));
        doneWaiter = null;
      } else {
        post({ type: "OFFSCREEN_ERROR", message: "Helper connection closed" });
      }
    },
  });

  await helper.connect(msg.token, msg.sessionId);
  helper.startSession(msg.sessionId, TARGET_SAMPLE_RATE);

  mediaStream = await navigator.mediaDevices.getUserMedia({
    audio: {
      // Chrome extension tab capture constraints
      mandatory: {
        chromeMediaSource: "tab",
        chromeMediaSourceId: msg.streamId,
      },
    } as MediaTrackConstraints,
    video: false,
  });

  audioContext = new AudioContext();
  sourceNode = audioContext.createMediaStreamSource(mediaStream);
  // Keep tab audible — tabCapture otherwise mutes the tab
  sourceNode.connect(audioContext.destination);

  chunker = new PcmChunker();
  const sourceRate = audioContext.sampleRate;

  const onPcm = (input: Float32Array) => {
    if (!helper || !chunker) return;
    if (lagging) {
      let energy = 0;
      const step = 64;
      for (let i = 0; i < input.length; i += step) energy += Math.abs(input[i]);
      if (energy / Math.max(1, input.length / step) < 0.01) {
        return;
      }
    }
    const resampled = resampleTo16k(input, sourceRate);
    for (const piece of chunker.push(resampled)) {
      helper.sendPcm(piece);
    }
  };

  try {
    const workletUrl = chrome.runtime.getURL("pcm-processor.js");
    await audioContext.audioWorklet.addModule(workletUrl);
    workletNode = new AudioWorkletNode(audioContext, "pcm-capture-processor");
    workletNode.port.onmessage = (ev: MessageEvent<Float32Array>) => onPcm(ev.data);
    sourceNode.connect(workletNode);
  } catch {
    scriptNode = audioContext.createScriptProcessor(4096, 1, 1);
    scriptNode.onaudioprocess = (ev) => {
      const input = ev.inputBuffer.getChannelData(0);
      onPcm(new Float32Array(input));
    };
    silentGain = audioContext.createGain();
    silentGain.gain.value = 0;
    sourceNode.connect(scriptNode);
    scriptNode.connect(silentGain);
    silentGain.connect(audioContext.destination);
  }
}

async function stopCaptureInternal(notifyHelper: boolean): Promise<void> {
  if (chunker && helper) {
    const rest = chunker.flush();
    if (rest) helper.sendPcm(rest);
  }

  if (notifyHelper && helper?.connected) {
    const donePromise = new Promise<string>((resolve, reject) => {
      doneWaiter = { resolve, reject };
      setTimeout(() => {
        if (doneWaiter) {
          doneWaiter.resolve("");
          doneWaiter = null;
        }
      }, 120_000);
    });
    helper.stopSession();
    const text = await donePromise;
    if (text) {
      // OFFSCREEN_DONE already posted from event handler
    }
  }

  workletNode?.port.close();
  workletNode?.disconnect();
  workletNode = null;

  scriptNode?.disconnect();
  scriptNode = null;
  silentGain?.disconnect();
  silentGain = null;

  sourceNode?.disconnect();
  sourceNode = null;

  if (mediaStream) {
    for (const track of mediaStream.getTracks()) track.stop();
    mediaStream = null;
  }

  if (audioContext) {
    await audioContext.close().catch(() => undefined);
    audioContext = null;
  }

  chunker?.clear();
  chunker = null;

  helper?.close();
  helper = null;
  lagging = false;
}

chrome.runtime.onMessage.addListener((message: BgToOffscreen) => {
  if (!message || typeof message !== "object") return;
  if (message.type === "OFFSCREEN_START") {
    void startCapture(message).catch((err: unknown) => {
      const messageText = err instanceof Error ? err.message : String(err);
      post({ type: "OFFSCREEN_ERROR", message: messageText });
    });
  } else if (message.type === "OFFSCREEN_STOP") {
    void stopCaptureInternal(true)
      .then(() => post({ type: "OFFSCREEN_STOPPED" }))
      .catch((err: unknown) => {
        const messageText = err instanceof Error ? err.message : String(err);
        post({ type: "OFFSCREEN_ERROR", message: messageText });
      });
  }
});

post({ type: "OFFSCREEN_BOOTED" });
