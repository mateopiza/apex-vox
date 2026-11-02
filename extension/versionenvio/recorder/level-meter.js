/**
 * Apex Box — Medidor de nivel (AudioWorklet)
 * Corre en el hilo de audio: sigue midiendo aunque la pestaña esté en segundo plano.
 * Publica { rms, peak } cada ~50 ms.
 */
class LevelMeterProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.sum = 0;
    this.peak = 0;
    this.count = 0;
    this.window = Math.round(sampleRate * 0.05);
  }

  process(inputs) {
    const channels = inputs[0];
    if (channels && channels.length) {
      const frames = channels[0].length;
      for (let i = 0; i < frames; i++) {
        let v = 0;
        for (let c = 0; c < channels.length; c++) v += channels[c][i];
        v /= channels.length;
        this.sum += v * v;
        const a = v < 0 ? -v : v;
        if (a > this.peak) this.peak = a;
      }
      this.count += frames;
    } else {
      this.count += 128; // sin entrada = silencio
    }

    if (this.count >= this.window) {
      this.port.postMessage({ rms: Math.sqrt(this.sum / this.count), peak: this.peak });
      this.sum = 0;
      this.peak = 0;
      this.count = 0;
    }
    return true;
  }
}

registerProcessor("level-meter", LevelMeterProcessor);
