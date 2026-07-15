import { HelperClient, type SpeakerId } from "../lib/helperClient";
import type { BgToOffscreen, OffscreenToBg } from "../lib/messages";
import { PcmChunker, resampleTo16k, TARGET_SAMPLE_RATE } from "../lib/pcm";

let tabStream: MediaStream | null = null;
let micStream: MediaStream | null = null;
let audioContext: AudioContext | null = null;
let tabWorklet: AudioWorkletNode | null = null;
let micWorklet: AudioWorkletNode | null = null;
let tabSource: MediaStreamAudioSourceNode | null = null;
let micSource: MediaStreamAudioSourceNode | null = null;
let silentGain: GainNode | null = null;
let helper: HelperClient | null = null;
let micChunker: PcmChunker | null = null;
let tabChunker: PcmChunker | null = null;
let lagging = false;
let tabScriptNode: ScriptProcessorNode | null = null;
let micScriptNode: ScriptProcessorNode | null = null;
let doneWaiter: { resolve: (text: string) => void; reject: (err: Error) => void } | null =
  null;

function post(msg: OffscreenToBg): void {
  chrome.runtime.sendMessage(msg);
}

function stopTracks(stream: MediaStream | null): void {
  if (!stream) return;
  for (const track of stream.getTracks()) track.stop();
}

async function openMicrophone(): Promise<MediaStream> {
  try {
    return await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
      video: false,
    });
  } catch (err: unknown) {
    const detail = err instanceof Error ? err.message : String(err);
    throw new Error(
      `Microphone access failed (${detail}). Allow microphone permission for Tab Transcriber, then press Start again.`,
    );
  }
}

function makePcmHandler(speaker: SpeakerId, chunker: () => PcmChunker | null, sourceRate: number) {
  return (input: Float32Array) => {
    const activeChunker = chunker();
    if (!helper || !activeChunker) return;
    if (lagging) {
      let energy = 0;
      const step = 64;
      for (let i = 0; i < input.length; i += step) energy += Math.abs(input[i]);
      if (energy / Math.max(1, input.length / step) < 0.01) {
        return;
      }
    }
    const resampled = resampleTo16k(input, sourceRate);
    for (const piece of activeChunker.push(resampled)) {
      helper.sendPcm(piece, speaker);
    }
  };
}

async function startCapture(msg: Extract<BgToOffscreen, { type: "OFFSCREEN_START" }>): Promise<void> {
  await stopCaptureInternal(false);

  helper = new HelperClient({
    onReady: (sessionId) => post({ type: "OFFSCREEN_READY", sessionId }),
    onSegment: (text, t0, t1, speaker) =>
      post({ type: "OFFSCREEN_SEGMENT", text, t0, t1, speaker }),
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
  helper.startSession(msg.sessionId, TARGET_SAMPLE_RATE, "ab");

  tabStream = await navigator.mediaDevices.getUserMedia({
    audio: {
      // Chrome extension tab capture constraints
      mandatory: {
        chromeMediaSource: "tab",
        chromeMediaSourceId: msg.streamId,
      },
    } as MediaTrackConstraints,
    video: false,
  });

  micStream = await openMicrophone();

  audioContext = new AudioContext();
  tabSource = audioContext.createMediaStreamSource(tabStream);
  micSource = audioContext.createMediaStreamSource(micStream);

  // Keep tab audible — tabCapture otherwise mutes the tab.
  // Do NOT route mic to speakers (would create feedback / echo).
  tabSource.connect(audioContext.destination);

  micChunker = new PcmChunker();
  tabChunker = new PcmChunker();
  const sourceRate = audioContext.sampleRate;
  const onMicPcm = makePcmHandler("A", () => micChunker, sourceRate);
  const onTabPcm = makePcmHandler("B", () => tabChunker, sourceRate);

  try {
    const workletUrl = chrome.runtime.getURL("pcm-processor.js");
    await audioContext.audioWorklet.addModule(workletUrl);

    micWorklet = new AudioWorkletNode(audioContext, "pcm-capture-processor");
    micWorklet.port.onmessage = (ev: MessageEvent<Float32Array>) => onMicPcm(ev.data);
    micSource.connect(micWorklet);

    tabWorklet = new AudioWorkletNode(audioContext, "pcm-capture-processor");
    tabWorklet.port.onmessage = (ev: MessageEvent<Float32Array>) => onTabPcm(ev.data);
    tabSource.connect(tabWorklet);
  } catch {
    silentGain = audioContext.createGain();
    silentGain.gain.value = 0;
    silentGain.connect(audioContext.destination);

    micScriptNode = audioContext.createScriptProcessor(4096, 1, 1);
    micScriptNode.onaudioprocess = (ev) => {
      onMicPcm(new Float32Array(ev.inputBuffer.getChannelData(0)));
    };
    micSource.connect(micScriptNode);
    micScriptNode.connect(silentGain);

    tabScriptNode = audioContext.createScriptProcessor(4096, 1, 1);
    tabScriptNode.onaudioprocess = (ev) => {
      onTabPcm(new Float32Array(ev.inputBuffer.getChannelData(0)));
    };
    tabSource.connect(tabScriptNode);
    tabScriptNode.connect(silentGain);
  }
}

async function stopCaptureInternal(notifyHelper: boolean): Promise<void> {
  if (helper) {
    if (micChunker) {
      const rest = micChunker.flush();
      if (rest) helper.sendPcm(rest, "A");
    }
    if (tabChunker) {
      const rest = tabChunker.flush();
      if (rest) helper.sendPcm(rest, "B");
    }
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

  micWorklet?.port.close();
  micWorklet?.disconnect();
  micWorklet = null;
  tabWorklet?.port.close();
  tabWorklet?.disconnect();
  tabWorklet = null;

  micScriptNode?.disconnect();
  micScriptNode = null;
  tabScriptNode?.disconnect();
  tabScriptNode = null;
  silentGain?.disconnect();
  silentGain = null;

  micSource?.disconnect();
  micSource = null;
  tabSource?.disconnect();
  tabSource = null;

  stopTracks(micStream);
  micStream = null;
  stopTracks(tabStream);
  tabStream = null;

  if (audioContext) {
    await audioContext.close().catch(() => undefined);
    audioContext = null;
  }

  micChunker?.clear();
  micChunker = null;
  tabChunker?.clear();
  tabChunker = null;

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
