/** Target sample rate for Whisper. */
export const TARGET_SAMPLE_RATE = 16_000;

/** Chunk cadence for streaming to the helper (~1.5s). */
export const CHUNK_MS = 1500;

/**
 * Linear-resample Float32 PCM from sourceRate to TARGET_SAMPLE_RATE.
 */
export function resampleTo16k(input: Float32Array, sourceRate: number): Float32Array {
  if (sourceRate === TARGET_SAMPLE_RATE) {
    return input;
  }
  const ratio = sourceRate / TARGET_SAMPLE_RATE;
  const outLength = Math.max(1, Math.floor(input.length / ratio));
  const output = new Float32Array(outLength);
  for (let i = 0; i < outLength; i++) {
    const srcIndex = i * ratio;
    const i0 = Math.floor(srcIndex);
    const i1 = Math.min(i0 + 1, input.length - 1);
    const frac = srcIndex - i0;
    output[i] = input[i0] * (1 - frac) + input[i1] * frac;
  }
  return output;
}

/** Mix down interleaved multi-channel float32 to mono. */
export function toMono(input: Float32Array, channels: number): Float32Array {
  if (channels <= 1) return input;
  const frames = Math.floor(input.length / channels);
  const mono = new Float32Array(frames);
  for (let i = 0; i < frames; i++) {
    let sum = 0;
    for (let c = 0; c < channels; c++) {
      sum += input[i * channels + c];
    }
    mono[i] = sum / channels;
  }
  return mono;
}

/**
 * Accumulates float32 samples and flushes ~CHUNK_MS worth at the target rate.
 */
export class PcmChunker {
  private buffer: Float32Array = new Float32Array(0);
  private readonly samplesPerChunk: number;

  constructor(chunkMs = CHUNK_MS) {
    this.samplesPerChunk = Math.floor((TARGET_SAMPLE_RATE * chunkMs) / 1000);
  }

  push(samples: Float32Array): Float32Array[] {
    if (samples.length === 0) return [];
    const merged = new Float32Array(this.buffer.length + samples.length);
    merged.set(this.buffer);
    merged.set(samples, this.buffer.length);
    this.buffer = merged;

    const out: Float32Array[] = [];
    while (this.buffer.length >= this.samplesPerChunk) {
      out.push(this.buffer.slice(0, this.samplesPerChunk));
      this.buffer = this.buffer.slice(this.samplesPerChunk);
    }
    return out;
  }

  flush(): Float32Array | null {
    if (this.buffer.length === 0) return null;
    const rest = this.buffer;
    this.buffer = new Float32Array(0);
    return rest;
  }

  clear(): void {
    this.buffer = new Float32Array(0);
  }
}
