/**
 * Apex Box — Grabador en pestaña fija (extension/recorder/recorder.js)
 * --------------------------------------------------------------------
 * 1. El usuario elige tipo de reunión, título, tipo de grabación y modelo.
 * 2. Graba en bloques de 3 min (cada bloque se sube y se libera de la RAM).
 * 3. Al detener, finaliza la sesión y entrega un enlace con notas, resumen y acta.
 * El icono de la extensión muestra REC + tiempo mientras se graba.
 */

"use strict";

(function () {
  const BLOCK_SEC = 180;
  const BITRATE = 48000;
  const MAX_RETRIES = 3;
  const SOUND_RMS = 0.006; // ~ -44 dBFS: por encima se considera que hay sonido
  const SILENCE_WARN_SEC = 15; // aviso tras este silencio continuo
  const WAVE_POINTS = 160;

  const $ = (id) => document.getElementById(id);
  const el = {
    form: $("setup-form"),
    meetingType: $("meeting-type"),
    title: $("title"),
    engine: $("engine"),
    modeHint: $("mode-hint"),
    pill: $("rec-pill"),
    clock: $("clock"),
    recBtn: $("rec-btn"),
    blocks: $("stat-blocks"),
    segments: $("stat-segments"),
    speakers: $("stat-speakers"),
    pending: $("stat-pending"),
    status: $("status"),
    wave: $("wave"),
    signal: $("signal"),
    sources: $("sources"),
    result: $("result"),
    resultMeta: $("result-meta"),
    resultLink: $("result-link"),
    resultUrl: $("result-url"),
    copyBtn: $("copy-btn"),
    newBtn: $("new-btn"),
    serverUrl: $("server-url"),
    saveServer: $("save-server"),
  };

  const st = {
    serverUrl: "http://localhost:8000",
    source: null, // { id, url, title } pestaña de la reunión virtual
    recording: false,
    busy: false,
    boxSessionId: null,
    startedAt: 0,
    blockIndex: 0,
    recorder: null,
    rotationTimer: null,
    tickTimer: null,
    streams: [],
    audioCtx: null,
    inFlight: new Set(),
    retryQueue: [],
    blocksSent: 0,
    failedBlocks: 0,
    segments: 0,
    speakers: new Set(),
    meters: [], // [{ label, level, lastSoundAt, ended, row }]
    wave: [],
    lastTickAt: 0,
  };

  // ---------------------------------------------------------------------------
  // Utilidades
  // ---------------------------------------------------------------------------

  function hhmmss(sec) {
    const s = Math.max(0, Math.floor(sec));
    return [Math.floor(s / 3600), Math.floor((s % 3600) / 60), s % 60]
      .map((v) => String(v).padStart(2, "0"))
      .join(":");
  }

  // El badge admite ~4 caracteres: 9:59 → 59m → 1h05 → 10h
  function badgeTime(sec) {
    const s = Math.floor(sec);
    if (s < 600) return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
    if (s < 3600) return `${Math.floor(s / 60)}m`;
    const h = Math.floor(s / 3600);
    return h >= 10 ? `${h}h` : `${h}h${String(Math.floor((s % 3600) / 60)).padStart(2, "0")}`;
  }

  function elapsedSec() {
    return st.startedAt ? (Date.now() - st.startedAt) / 1000 : 0;
  }

  function mode() {
    return el.form.querySelector('input[name="mode"]:checked').value;
  }

  function setMode(value) {
    const input = el.form.querySelector(`input[name="mode"][value="${value}"]`);
    if (input) input.checked = true;
    renderModeHint();
  }

  function detectPlatform(url) {
    const u = String(url || "").toLowerCase();
    if (u.includes("meet.google.com")) return { id: "google_meet", label: "Google Meet" };
    if (u.includes("zoom.us")) return { id: "zoom", label: "Zoom" };
    if (u.includes("teams.microsoft.com") || u.includes("teams.live.com"))
      return { id: "microsoft_teams", label: "Microsoft Teams" };
    if (u.includes("webex.com")) return { id: "webex", label: "Webex" };
    return null;
  }

  function showStatus(msg, isError = false) {
    el.status.textContent = msg;
    el.status.classList.toggle("error", isError);
    el.status.classList.toggle("hidden", !msg);
  }

  async function api(path, options = {}) {
    const res = await fetch(`${st.serverUrl}${path}`, options);
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `El servidor respondió HTTP ${res.status}`);
    return data;
  }

  // ---------------------------------------------------------------------------
  // UI
  // ---------------------------------------------------------------------------

  function renderModeHint() {
    if (mode() === "presencial") {
      el.modeHint.textContent = "Graba el micrófono de este equipo.";
      el.modeHint.classList.remove("warn");
      return;
    }
    if (st.source) {
      const p = detectPlatform(st.source.url);
      el.modeHint.textContent = `Graba el audio de «${(p && p.label) || st.source.title || st.source.url}» + tu micrófono.`;
      el.modeHint.classList.remove("warn");
    } else {
      el.modeHint.textContent =
        "Abre la pestaña de la reunión y pulsa el icono de Apex Box para elegirla como fuente.";
      el.modeHint.classList.add("warn");
    }
  }

  function renderStats() {
    el.blocks.textContent = String(st.blocksSent);
    el.segments.textContent = String(st.segments);
    el.speakers.textContent = String(st.speakers.size);
    el.pending.textContent = String(st.inFlight.size + st.retryQueue.length);
  }

  function renderRecordingState() {
    el.pill.textContent = st.recording ? "REC" : "NO REC";
    el.pill.classList.toggle("on", st.recording);
    if (!st.recording) el.pill.classList.remove("warn");
    el.recBtn.textContent = st.recording ? "■ Detener" : "● Grabar";
    el.recBtn.classList.toggle("stop", st.recording);
    el.recBtn.disabled = st.busy;
    el.form.querySelectorAll("input, select").forEach((n) => (n.disabled = st.recording || st.busy));
  }

  function tick() {
    st.lastTickAt = Date.now();
    const sec = elapsedSec();
    const sig = signalState();
    const noSound = sig.kind === "warn" || sig.kind === "off";
    el.clock.textContent = hhmmss(sec);
    document.title = `${noSound ? "⚠ SIN SONIDO" : "● REC"} ${hhmmss(sec)} · Apex Box`;
    // Badge: tiempo en rojo si entra sonido; "MUDO" en ámbar si no se está captando nada.
    chrome.action.setBadgeBackgroundColor({ color: noSound ? "#d97706" : "#f43e01" });
    chrome.action.setBadgeText({ text: noSound ? "MUDO" : badgeTime(sec) });
    chrome.action.setTitle({
      title: `Apex Box · REC ${hhmmss(sec)}${
        sig.kind === "off" ? " · ⚠ fuente desconectada" : noSound ? ` · ⚠ sin sonido hace ${sig.silentSec} s` : " · captando sonido"
      }`,
    });
    if (document.hidden) return;
    renderMeters();
  }

  function setIdleIndicator() {
    document.title = "Apex Box · Grabador";
    chrome.action.setBadgeText({ text: "" });
    chrome.action.setTitle({ title: "Apex Box · No grabando" });
  }

  // ---------------------------------------------------------------------------
  // Captura de audio
  // ---------------------------------------------------------------------------

  async function getMic() {
    const mic = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      video: false,
    });
    st.streams.push(mic);
    return mic;
  }

  async function acquireStream() {
    st.meterSources = [];
    if (mode() === "presencial") {
      const mic = await getMic();
      st.meterSources.push({ label: "Micrófono", stream: mic, node: st.audioCtx.createMediaStreamSource(mic) });
      return mic;
    }

    if (!st.source) {
      throw new Error("Elige la pestaña de la reunión: ábrela y pulsa el icono de Apex Box.");
    }
    const me = await chrome.tabs.getCurrent();
    const streamId = await chrome.tabCapture.getMediaStreamId({
      targetTabId: st.source.id,
      consumerTabId: me.id,
    });
    const tabStream = await navigator.mediaDevices.getUserMedia({
      audio: { mandatory: { chromeMediaSource: "tab", chromeMediaSourceId: streamId } },
      video: false,
    });
    st.streams.push(tabStream);

    const out = st.audioCtx.createMediaStreamDestination();
    const tabSrc = st.audioCtx.createMediaStreamSource(tabStream);
    tabSrc.connect(st.audioCtx.destination); // seguir escuchando la reunión
    tabSrc.connect(out);
    st.meterSources.push({ label: "Reunión", stream: tabStream, node: tabSrc });

    try {
      const mic = await getMic();
      const micSrc = st.audioCtx.createMediaStreamSource(mic);
      micSrc.connect(out);
      st.meterSources.push({ label: "Micrófono", stream: mic, node: micSrc });
    } catch (err) {
      showStatus("Grabando solo el audio de la reunión (sin micrófono).");
    }
    return out.stream;
  }

  // ---------------------------------------------------------------------------
  // Medidor de sonido: ondas + aviso de silencio
  // ---------------------------------------------------------------------------

  // dBFS -60..0 → 0..1
  function levelToUnit(rms) {
    if (rms <= 0) return 0;
    return Math.min(1, Math.max(0, (20 * Math.log10(rms) + 60) / 60));
  }

  async function startMeters() {
    const ctx = st.audioCtx;
    await ctx.audioWorklet.addModule("level-meter.js");
    // Salida a ganancia 0 → destino: asegura que el grafo procese el medidor sin sonar.
    const sink = ctx.createGain();
    sink.gain.value = 0;
    sink.connect(ctx.destination);

    const now = Date.now();
    el.sources.innerHTML = "";
    st.meters = st.meterSources.map(({ label, stream, node }) => {
      const row = document.createElement("li");
      row.innerHTML = `<span></span><span class="bar"><i></i></span><span class="state"></span>`;
      row.firstChild.textContent = label;
      el.sources.appendChild(row);

      const meter = { label, level: 0, lastSoundAt: now, ended: false, row };
      const worklet = new AudioWorkletNode(ctx, "level-meter");
      worklet.port.onmessage = (e) => onLevel(meter, e.data);
      node.connect(worklet);
      worklet.connect(sink);

      stream.getAudioTracks().forEach((t) => {
        t.addEventListener("ended", () => (meter.ended = true));
      });
      return meter;
    });
    st.wave = [];
  }

  function onLevel(meter, { rms }) {
    const now = Date.now();
    meter.level = rms;
    if (rms >= SOUND_RMS) meter.lastSoundAt = now;

    // El primer medidor marca el ritmo de la onda (≈20 puntos/s) con el nivel combinado.
    if (meter === st.meters[0]) {
      const combined = Math.max(...st.meters.map((m) => m.level));
      st.wave.push(combined);
      if (st.wave.length > WAVE_POINTS) st.wave.shift();
      if (!document.hidden) renderMeters();
      // Los mensajes del hilo de audio no se frenan en segundo plano: también mueven el reloj/badge.
      if (st.recording && now - st.lastTickAt >= 1000) tick();
    }
  }

  function signalState() {
    if (!st.recording || !st.meters.length) return { kind: "idle", silentSec: 0 };
    const now = Date.now();
    if (st.meters.every((m) => m.ended)) return { kind: "off", silentSec: 0 };
    const lastSound = Math.max(...st.meters.filter((m) => !m.ended).map((m) => m.lastSoundAt));
    const silentSec = Math.floor((now - lastSound) / 1000);
    return { kind: silentSec >= SILENCE_WARN_SEC ? "warn" : "ok", silentSec };
  }

  function renderMeters() {
    const sig = signalState();
    el.signal.className = `signal ${sig.kind}`;
    el.signal.textContent = {
      idle: "Sin grabar",
      ok: "● Captando sonido",
      warn: `⚠ No entra sonido hace ${sig.silentSec} s — revisa micrófono o pestaña`,
      off: "⚠ Fuente de audio desconectada — no se está grabando sonido",
    }[sig.kind];

    if (st.recording) {
      const noSound = sig.kind === "warn" || sig.kind === "off";
      el.pill.textContent = noSound ? "REC · SIN SONIDO" : "REC";
      el.pill.classList.toggle("warn", noSound);
    }

    const now = Date.now();
    st.meters.forEach((m) => {
      const silent = (now - m.lastSoundAt) / 1000 >= SILENCE_WARN_SEC;
      m.row.className = m.ended ? "off" : silent ? "warn" : "";
      m.row.querySelector("i").style.width = `${Math.round(levelToUnit(m.level) * 100)}%`;
      m.row.querySelector(".state").textContent = m.ended ? "desconectada" : silent ? "sin señal" : "ok";
    });

    drawWave(sig.kind);
  }

  function drawWave(kind) {
    const c = el.wave;
    const dpr = window.devicePixelRatio || 1;
    const w = Math.max(1, Math.round(c.clientWidth * dpr));
    const h = Math.max(1, Math.round(c.clientHeight * dpr));
    if (c.width !== w || c.height !== h) {
      c.width = w;
      c.height = h;
    }
    const g = c.getContext("2d");
    g.clearRect(0, 0, w, h);
    const mid = h / 2;
    g.fillStyle = { ok: "#225c05", warn: "#d97706", off: "#c93706" }[kind] || "#cecebf";

    const step = w / WAVE_POINTS;
    const barW = Math.max(1, step * 0.6);
    const offset = WAVE_POINTS - st.wave.length;
    for (let i = 0; i < WAVE_POINTS; i++) {
      const v = i >= offset ? levelToUnit(st.wave[i - offset]) : 0;
      const bh = Math.max(dpr, v * (h - 4 * dpr));
      g.fillRect(i * step, mid - bh / 2, barW, bh);
    }
  }

  function resetMeters() {
    st.meters = [];
    st.meterSources = [];
    st.wave = [];
    el.sources.innerHTML = "";
    renderMeters();
  }

  async function releaseStreams() {
    st.streams.forEach((s) => s.getTracks().forEach((t) => t.stop()));
    st.streams = [];
    if (st.audioCtx) {
      await st.audioCtx.close().catch(() => {});
      st.audioCtx = null;
    }
  }

  function mimeType() {
    return ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4"].find((m) =>
      MediaRecorder.isTypeSupported(m)
    );
  }

  // ---------------------------------------------------------------------------
  // Bloques: subir y liberar RAM
  // ---------------------------------------------------------------------------

  async function uploadBlock(item) {
    const ext = item.blob.type.includes("mp4") ? "m4a" : item.blob.type.includes("ogg") ? "ogg" : "webm";
    const fd = new FormData();
    fd.append("file", item.blob, `bloque_${String(item.index + 1).padStart(4, "0")}.${ext}`);
    fd.append("block_index", String(item.index));
    fd.append("duration_hint_sec", String(item.durationSec));
    fd.append("transcribe_immediately", "true");

    const data = await api(`/api/box/sessions/${encodeURIComponent(item.sessionId)}/blocks`, {
      method: "POST",
      body: fd,
    });
    st.blocksSent = data.total_blocks_received || st.blocksSent + 1;
    st.segments = data.total_segments_count || st.segments;
    (data.new_segments || []).forEach((s) => s.speaker && st.speakers.add(s.speaker));
  }

  function sendBlock(item) {
    const p = uploadBlock(item)
      .catch(() => {
        item.attempts = (item.attempts || 0) + 1;
        if (item.attempts < MAX_RETRIES) st.retryQueue.push(item);
        else st.failedBlocks += 1;
      })
      .finally(() => {
        st.inFlight.delete(p);
        renderStats();
      });
    st.inFlight.add(p);
    renderStats();
    return p;
  }

  function retryFailed() {
    const items = st.retryQueue.splice(0);
    return Promise.all(items.map(sendBlock));
  }

  function startBlock(stream) {
    const type = mimeType();
    const rec = new MediaRecorder(stream, { audioBitsPerSecond: BITRATE, ...(type ? { mimeType: type } : {}) });
    const index = st.blockIndex++;
    const sessionId = st.boxSessionId;
    const startedAt = Date.now();
    let chunks = [];

    rec.ondataavailable = (e) => e.data && e.data.size > 0 && chunks.push(e.data);
    rec.stopped = new Promise((resolve) => {
      rec.onstop = () => {
        const blob = new Blob(chunks, { type: rec.mimeType || type || "audio/webm" });
        chunks = null; // liberar RAM del bloque
        const durationSec = Number(Math.max(0.5, (Date.now() - startedAt) / 1000).toFixed(2));
        if (blob.size > 0) sendBlock({ blob, index, durationSec, sessionId });
        retryFailed();
        resolve();
      };
    });
    rec.start();
    return rec;
  }

  // ---------------------------------------------------------------------------
  // Grabar / Detener
  // ---------------------------------------------------------------------------

  async function startRecording() {
    // Crear el AudioContext en el mismo clic (antes de cualquier await) evita que Chrome
    // lo deje suspendido por la política de autoplay.
    st.audioCtx = new AudioContext();
    st.busy = true;
    renderRecordingState();
    el.result.classList.add("hidden");
    showStatus("Preparando grabación…");

    try {
      const stream = await acquireStream();
      if (st.audioCtx.state === "suspended") await st.audioCtx.resume().catch(() => {});
      await startMeters();
      const platform = mode() === "virtual" && st.source ? detectPlatform(st.source.url) : null;
      const session = await api("/api/box/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: el.title.value.trim() || "Reunión — Apex Box",
          mode: mode(),
          platform: mode() === "virtual" ? (platform && platform.id) || "google_meet" : "in_person",
          meeting_url: mode() === "virtual" && st.source ? st.source.url : null,
          block_duration_sec: BLOCK_SEC,
          language: "es",
          diarization_engine: el.engine.value,
          device_type: "desktop_extension",
        }),
      });

      Object.assign(st, {
        boxSessionId: session.box_session_id,
        blockIndex: 0,
        blocksSent: 0,
        failedBlocks: 0,
        segments: 0,
        speakers: new Set(),
        retryQueue: [],
        startedAt: Date.now(),
        recording: true,
      });

      st.recorder = startBlock(stream);
      // Rotación sin cortes: arranca el siguiente bloque antes de cerrar el anterior.
      st.rotationTimer = setInterval(() => {
        const prev = st.recorder;
        st.recorder = startBlock(stream);
        if (prev.state !== "inactive") prev.stop();
      }, BLOCK_SEC * 1000);

      tick();
      st.tickTimer = setInterval(tick, 1000);
      showStatus("");
      chrome.storage.local.set({
        lastMeetingType: el.meetingType.value,
        lastMode: mode(),
        lastEngine: el.engine.value,
      });
    } catch (err) {
      await releaseStreams();
      resetMeters();
      showStatus(`No se pudo iniciar: ${err.message}`, true);
    } finally {
      st.busy = false;
      renderStats();
      renderRecordingState();
    }
  }

  async function stopRecording() {
    st.busy = true;
    renderRecordingState();
    clearInterval(st.rotationTimer);
    clearInterval(st.tickTimer);
    const totalSec = elapsedSec();
    showStatus("Subiendo el último bloque…");

    try {
      if (st.recorder && st.recorder.state !== "inactive") {
        st.recorder.stop();
        await st.recorder.stopped;
      }
      await releaseStreams();
      // Esperar subidas en curso y reintentar las fallidas.
      while (st.inFlight.size || st.retryQueue.length) {
        await Promise.all([...st.inFlight]);
        if (st.retryQueue.length) await new Promise((r) => setTimeout(r, 2000));
        await retryFailed();
      }

      showStatus("Generando notas, resumen y acta…");
      const fin = await api(`/api/box/sessions/${encodeURIComponent(st.boxSessionId)}/finalize`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ generate_minutes: true, generate_minutes_template: el.meetingType.value }),
      });

      const url = `${st.serverUrl}/?job=${encodeURIComponent(fin.job_id)}`;
      el.resultLink.href = url;
      el.resultUrl.value = url;
      el.resultMeta.textContent = `${fin.total_duration_formatted || hhmmss(totalSec)} · ${
        fin.total_blocks || st.blocksSent
      } bloques · ${fin.notes_integrated_count || 0} notas${
        st.failedBlocks ? ` · ⚠ ${st.failedBlocks} bloque(s) no se pudieron subir` : ""
      }`;
      el.result.classList.remove("hidden");
      showStatus("");
    } catch (err) {
      showStatus(`Error al finalizar: ${err.message}`, true);
    } finally {
      st.recording = false;
      st.busy = false;
      st.recorder = null;
      resetMeters();
      setIdleIndicator();
      renderStats();
      renderRecordingState();
    }
  }

  // ---------------------------------------------------------------------------
  // Eventos
  // ---------------------------------------------------------------------------

  el.recBtn.addEventListener("click", () => (st.recording ? stopRecording() : startRecording()));
  el.form.addEventListener("change", renderModeHint);
  el.form.addEventListener("submit", (e) => e.preventDefault());

  el.copyBtn.addEventListener("click", async () => {
    await navigator.clipboard.writeText(el.resultUrl.value);
    el.copyBtn.textContent = "Copiado";
    setTimeout(() => (el.copyBtn.textContent = "Copiar"), 1500);
  });

  el.newBtn.addEventListener("click", () => {
    el.result.classList.add("hidden");
    el.clock.textContent = "00:00:00";
    Object.assign(st, { blocksSent: 0, segments: 0, speakers: new Set(), startedAt: 0 });
    renderStats();
  });

  el.saveServer.addEventListener("click", async () => {
    st.serverUrl = (el.serverUrl.value || "http://localhost:8000").trim().replace(/\/+$/, "");
    el.serverUrl.value = st.serverUrl;
    await chrome.storage.local.set({ serverUrl: st.serverUrl });
    showStatus(`Servidor: ${st.serverUrl}`);
  });

  window.addEventListener("beforeunload", (e) => {
    if (st.recording) {
      e.preventDefault();
      e.returnValue = "";
    }
  });

  function setSource(tab) {
    if (st.recording || !tab) return;
    st.source = { id: tab.id, url: tab.url || "", title: tab.title || "" };
    const p = detectPlatform(st.source.url);
    if (p) {
      setMode("virtual");
      if (!el.title.value.trim()) el.title.value = `${p.label}: ${st.source.title}`.slice(0, 140);
    }
    renderModeHint();
  }

  chrome.runtime.onMessage.addListener((msg) => {
    if (msg && msg.type === "SOURCE_TAB") setSource({ id: msg.tabId, url: msg.url, title: msg.title });
  });

  // ---------------------------------------------------------------------------
  // Arranque
  // ---------------------------------------------------------------------------

  (async () => {
    const saved = await chrome.storage.local.get(["serverUrl", "lastMeetingType", "lastMode", "lastEngine"]);
    if (saved.serverUrl) st.serverUrl = el.serverUrl.value = saved.serverUrl;
    if (saved.lastMeetingType) el.meetingType.value = saved.lastMeetingType;
    if (saved.lastEngine) el.engine.value = saved.lastEngine;
    if (saved.lastMode) setMode(saved.lastMode);

    const sourceId = Number(new URLSearchParams(location.search).get("source"));
    if (sourceId) {
      try {
        setSource(await chrome.tabs.get(sourceId));
      } catch (_) {}
    }
    setIdleIndicator();
    renderModeHint();
    renderStats();
    renderRecordingState();
    renderMeters();
  })();

  document.addEventListener("visibilitychange", () => !document.hidden && renderMeters());
  window.addEventListener("resize", renderMeters);
})();
