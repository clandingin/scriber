import { defineManifest } from "@crxjs/vite-plugin";

const HELPER_ORIGIN = "http://127.0.0.1:17341";

export default defineManifest({
  manifest_version: 3,
  name: "Tab Transcriber",
  description:
    "HIPAA-oriented local tab + microphone transcription via a localhost faster-whisper helper. Audio never leaves this machine.",
  version: "0.1.1",
  action: {
    default_title: "Tab Transcriber",
    default_popup: "src/popup/index.html",
  },
  background: {
    service_worker: "src/background.ts",
    type: "module",
  },
  permissions: ["tabCapture", "offscreen", "storage", "activeTab", "audioCapture"],
  host_permissions: [`${HELPER_ORIGIN}/*`, "ws://127.0.0.1:17341/*"],
  content_security_policy: {
    extension_pages:
      "script-src 'self'; object-src 'self'; connect-src 'self' http://127.0.0.1:17341 ws://127.0.0.1:17341;",
  },
});
