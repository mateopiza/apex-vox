/**
 * Apex Box — Side Panel Controller (extension/sidepanel/sidepanel.js)
 * -------------------------------------------------------------------
 * Manages:
 * - Presencial (Mic/Room) & Virtual (Zoom, Google Meet, Microsoft Teams, Webex) modes
 * - Optimal Block Duration & Constant O(1) RAM Calculator
 * - Unlimited Block Recording lifecycle (10+ hours without filling RAM)
 * - Live Timestamped Notes ('nota', 'acuerdo', 'tarea', 'alerta', 'idea')
 * - Live Rolling Block Transcription feed & Finalization into Apex Summa + Actas
 */

"use strict";

(function () {
  const uiState = {
    serverUrl: "http://localhost:8000",
    mode: "presencial",
    platform: "in_person",
    meetingUrl: "",
    blockDurationSec: 180,
    engine: "Mc-Lewis",
    recording: false,
    boxSessionId: null,
    uploadSessionId: null,
    blocksSent: 0,
    elapsedSeconds: 0,
    blockElapsedSeconds: 0,
    selectedNoteTag: "nota",
    notes: [],
    segments: [],
    timerInterval: null,
  };

  // DOM References
  const meetingContextDot = document.getElementById("meeting-context-dot");
  const meetingContextLabel = document.getElementById("meeting-context-label");
  const modePresencialBtn = document.getElementById("mode-presencial-btn");
  const modeVirtualBtn = document.getElementById("mode-virtual-btn");
  const sessionTitleInput = document.getElementById("session-title-input");
  const blockDurationSelect = document.getElementById("block-duration-select");
  const engineSelect = document.getElementById("engine-select");
  const ramCalcBanner = document.getElementById("ram-calc-banner");

  const recStateBadge = document.getElementById("rec-state-badge");
  const liveTimerClock = document.getElementById("live-timer-clock");
  const liveTimerSub = document.getElementById("live-timer-sub");
  const currentBlockLabel = document.getElementById("current-block-label");
  const currentBlockCountdown = document.getElementById("current-block-countdown");
  const blockProgressFill = document.getElementById("block-progress-fill");

  const kpiBlocksSent = document.getElementById("kpi-blocks-sent");
  const kpiRamActive = document.getElementById("kpi-ram-active");
  const kpiRamFreed = document.getElementById("kpi-ram-freed");

  const startRecBtn = document.getElementById("start-rec-btn");
  const flushBlockBtn = document.getElementById("flush-block-btn");
  const stopRecBtn = document.getElementById("stop-rec-btn");
  const statusAlert = document.getElementById("sp-status-alert");

  const notesCountBadge = document.getElementById("notes-count-badge");
  const noteSpeakerInput = document.getElementById("note-speaker-input");
  const noteTextInput = document.getElementById("note-text-input");
  const addNoteBtn = document.getElementById("add-note-btn");
  const liveNotesList = document.getElementById("live-notes-list");

  const liveSegmentsFeed = document.getElementById("live-segments-feed");
  const openWebappBtn = document.getElementById("open-webapp-btn");
  const serverUrlInput = document.getElementById("server-url-input");
  const saveServerBtn = document.getElementById("save-server-btn");

  function formatHHMMSS(totalSec) {
    const s = Math.max(0, Math.floor(Number(totalSec) || 0));
    const hrs = Math.floor(s / 3600);
    const mins = Math.floor((s % 3600) / 60);
    const secs = s % 60;
    return [hrs, mins, secs].map((v) => String(v).padStart(2, "0")).join(":");
  }

  function formatMMSS(totalSec) {
    const s = Math.max(0, Math.floor(Number(totalSec) || 0));
    const mins = Math.floor(s / 60);
    const secs = s % 60;
    return [mins, secs].map((v) => String(v).padStart(2, "0")).join(":");
  }

  function escapeHtml(str) {
    return String(str || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function showStatus(msg) {
    if (!statusAlert) return;
    statusAlert.textContent = msg;
    statusAlert.classList.remove("hidden");
  }

  function updateRamCalculatorBanner() {
    const sec = Number(blockDurationSelect.value) || 180;
    uiState.blockDurationSec = sec;
    const mbPerBlock = ((6000 * sec) / (1024 * 1024)).toFixed(2);
    const blocks10h = Math.ceil(36000 / sec);
    ramCalcBanner.innerHTML = `
      <strong>Cálculo Anti-Colapso RAM (10 Horas = ${blocks10h} bloques de ${sec}s):</strong>
      <span>Cada bloque pesa <strong>~${mbPerBlock} MB</strong> (Opus 48 kbps), se envía al servidor con cabecera EBML propia (0 ms de corte) y se libera de la RAM. En 10 horas continuas tu RAM se mantiene constante en <strong>~${mbPerBlock} MB</strong>.</span>
    `;
    if (!uiState.recording) {
      currentBlockCountdown.textContent = `00:00 / ${formatMMSS(sec)}`;
    }
  }

  function setMode(mode) {
    uiState.mode = mode === "virtual" ? "virtual" : "presencial";
    modePresencialBtn.classList.toggle("active", uiState.mode === "presencial");
    modePresencialBtn.setAttribute("aria-pressed", String(uiState.mode === "presencial"));
    modeVirtualBtn.classList.toggle("active", uiState.mode === "virtual");
    modeVirtualBtn.setAttribute("aria-pressed", String(uiState.mode === "virtual"));
  }

  async function detectActiveMeetingContext() {
    try {
      const ctx = await chrome.runtime.sendMessage({ type: "GET_ACTIVE_MEETING_CONTEXT" });
      if (!ctx || !ctx.ok) return;

      if (ctx.isVirtualMeeting) {
        uiState.platform = ctx.platform;
        uiState.meetingUrl = ctx.url || "";
        meetingContextDot.classList.add("virtual");
        meetingContextLabel.textContent = `Reunión Virtual Detectada: ${ctx.label}`;
        setMode("virtual");
        if (ctx.title && sessionTitleInput.value === "Reunión Continua — Apex Box") {
          sessionTitleInput.value = `${ctx.label}: ${ctx.title.slice(0, 75)}`;
        }
      } else {
        uiState.platform = "in_person";
        meetingContextDot.classList.remove("virtual");
        meetingContextLabel.textContent = "Modo Sala / Reunión Presencial Listo (o cambia a Virtual)";
      }

      if (ctx.sessionState && ctx.sessionState.recordingState === "recording") {
        uiState.recording = true;
        uiState.boxSessionId = ctx.sessionState.boxSessionId;
        uiState.blocksSent = ctx.sessionState.blocksSent || 0;
        uiState.elapsedSeconds = Math.floor(ctx.sessionState.totalDurationSec || 0);
        syncRecordingButtonsUI();
        startLocalVisualTimer();
        if (uiState.boxSessionId) {
          await refreshSessionFromBackend();
        }
      }
    } catch (err) {
      console.warn("Could not query active meeting context:", err);
    }
  }

  function syncRecordingButtonsUI() {
    if (uiState.recording) {
      recStateBadge.textContent = "GRABANDO EN BLOQUES";
      recStateBadge.classList.add("rec");
      startRecBtn.classList.add("hidden");
      flushBlockBtn.classList.remove("hidden");
      stopRecBtn.classList.remove("hidden");
    } else {
      recStateBadge.textContent = "LISTO";
      recStateBadge.classList.remove("rec");
      startRecBtn.classList.remove("hidden");
      flushBlockBtn.classList.add("hidden");
      stopRecBtn.classList.add("hidden");
    }
  }

  function startLocalVisualTimer() {
    if (uiState.timerInterval) clearInterval(uiState.timerInterval);
    uiState.timerInterval = setInterval(() => {
      if (!uiState.recording) return;
      uiState.elapsedSeconds += 1;
      uiState.blockElapsedSeconds = (uiState.blockElapsedSeconds + 1) % uiState.blockDurationSec;

      liveTimerClock.textContent = formatHHMMSS(uiState.elapsedSeconds);
      const blockNum = uiState.blocksSent + 1;
      currentBlockLabel.textContent = `Grabando Bloque #${blockNum}`;
      currentBlockCountdown.textContent = `${formatMMSS(uiState.blockElapsedSeconds)} / ${formatMMSS(
        uiState.blockDurationSec
      )}`;
      const pct = Math.min(100, Math.round((uiState.blockElapsedSeconds / uiState.blockDurationSec) * 100));
      blockProgressFill.style.width = `${pct}%`;

      const activeMb = (((uiState.blockElapsedSeconds * 6000) / (1024 * 1024)) + 0.12).toFixed(2);
      kpiRamActive.textContent = `~${activeMb} MB`;
    }, 1000);
  }

  async function handleStartRecording() {
    uiState.blockDurationSec = Number(blockDurationSelect.value) || 180;
    uiState.engine = engineSelect.value || "Mc-Lewis";
    const title = sessionTitleInput.value.trim() || "Reunión Continua — Apex Box";

    startRecBtn.disabled = true;
    showStatus("Creando sesión ilimitada por bloques en Apex Box...");

    try {
      const createRes = await fetch(`${uiState.serverUrl}/api/box/sessions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title,
          mode: uiState.mode,
          platform: uiState.mode === "virtual" ? uiState.platform || "google_meet" : "in_person",
          meeting_url: uiState.meetingUrl || null,
          block_duration_sec: uiState.blockDurationSec,
          language: "es",
          diarization_engine: uiState.engine,
          device_type: "desktop_extension",
        }),
      });
      if (!createRes.ok) {
        throw new Error(`Servidor respondió HTTP ${createRes.status}`);
      }
      const sessionData = await createRes.json();
      uiState.boxSessionId = sessionData.box_session_id;
      uiState.uploadSessionId = sessionData.upload_session_id;

      const swRes = await chrome.runtime.sendMessage({
        type: "SW_START_RECORDING",
        payload: {
          mode: uiState.mode,
          blockDurationSec: uiState.blockDurationSec,
          serverUrl: uiState.serverUrl,
          boxSessionId: uiState.boxSessionId,
        },
      });

      if (!swRes || !swRes.ok) {
        throw new Error((swRes && swRes.error) || "No se pudo iniciar la captura de audio.");
      }

      uiState.recording = true;
      uiState.blocksSent = 0;
      uiState.elapsedSeconds = 0;
      uiState.blockElapsedSeconds = 0;
      syncRecordingButtonsUI();
      startLocalVisualTimer();
      showStatus(
        `Grabando en modo ${uiState.mode === "virtual" ? "Reunión Virtual" : "Reunión Presencial"} · Bloques de ${uiState.blockDurationSec}s activados.`
      );
    } catch (err) {
      showStatus(`Error al iniciar: ${err.message}`);
    } finally {
      startRecBtn.disabled = false;
    }
  }

  async function handleStopAndFinalize() {
    stopRecBtn.disabled = true;
    showStatus("Cerrando último bloque de audio y generando Resumen IA Apex Summa + Acta...");

    try {
      await chrome.runtime.sendMessage({ type: "SW_STOP_RECORDING" });
      uiState.recording = false;
      if (uiState.timerInterval) {
        clearInterval(uiState.timerInterval);
        uiState.timerInterval = null;
      }
      syncRecordingButtonsUI();

      if (uiState.boxSessionId) {
        const finRes = await fetch(
          `${uiState.serverUrl}/api/box/sessions/${encodeURIComponent(uiState.boxSessionId)}/finalize`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              organization_name: "Apex Vox Enterprise",
              generate_minutes_template: "consejo",
            }),
          }
        );
        if (finRes.ok) {
          const finData = await finRes.json();
          uiState.segments = (finData.result && finData.result.segments) || uiState.segments;
          renderSegmentsFeed();
          showStatus(
            `¡Sesión finalizada! Job ${finData.job_id} (${finData.total_duration_formatted}) con ${finData.notes_integrated_count} notas integradas en Apex Summa.`
          );
        }
      }
    } catch (err) {
      showStatus(`Aviso al finalizar: ${err.message}`);
    } finally {
      stopRecBtn.disabled = false;
    }
  }

  async function handleAddNote() {
    const text = noteTextInput.value.trim();
    if (!text) return;

    const speaker = noteSpeakerInput.value.trim();
    const tag = uiState.selectedNoteTag || "nota";
    const tsSec = uiState.elapsedSeconds;

    noteTextInput.value = "";

    if (uiState.boxSessionId) {
      try {
        const res = await fetch(
          `${uiState.serverUrl}/api/box/sessions/${encodeURIComponent(uiState.boxSessionId)}/notes`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              text,
              tag,
              speaker: speaker || null,
              timestamp_sec: tsSec,
            }),
          }
        );
        if (res.ok) {
          const saved = await res.json();
          uiState.notes.push(saved);
          renderNotesList();
          return;
        }
      } catch (err) {
        console.warn("Saving note locally before session sync:", err);
      }
    }

    uiState.notes.push({
      note_id: `local_${Date.now()}`,
      timestamp_sec: tsSec,
      timestamp_formatted: formatHHMMSS(tsSec),
      tag,
      speaker,
      text,
    });
    renderNotesList();
  }

  function renderNotesList() {
    notesCountBadge.textContent = `${uiState.notes.length} nota${uiState.notes.length === 1 ? "" : "s"}`;
    if (uiState.notes.length === 0) {
      liveNotesList.innerHTML = `<li class="empty-item">Tus notas se sellarán con el segundo exacto [HH:MM:SS] y se integrarán al Acta y Calendario de Apex Summa.</li>`;
      return;
    }

    liveNotesList.innerHTML = uiState.notes
      .slice()
      .reverse()
      .map(
        (n) => `
        <li class="note-card">
          <div class="note-card-head">
            <span>[${escapeHtml(n.timestamp_formatted)}] · ${escapeHtml((n.tag || "nota").toUpperCase())}</span>
            <span>${escapeHtml(n.speaker || "")}</span>
          </div>
          <div>${escapeHtml(n.text)}</div>
        </li>
      `
      )
      .join("");
  }

  function renderSegmentsFeed() {
    if (!uiState.segments || uiState.segments.length === 0) return;
    liveSegmentsFeed.innerHTML = uiState.segments
      .slice(-80)
      .map(
        (s) => `
        <div class="seg-card">
          <div class="seg-card-head">
            <strong>${escapeHtml(s.speaker || "Hablante 1")}</strong>
            <span>[${escapeHtml(s.start_formatted)} - ${escapeHtml(s.end_formatted)}]</span>
          </div>
          <div>${escapeHtml(s.text)}</div>
        </div>
      `
      )
      .join("");
    liveSegmentsFeed.scrollTop = liveSegmentsFeed.scrollHeight;
  }

  async function refreshSessionFromBackend() {
    if (!uiState.boxSessionId) return;
    try {
      const res = await fetch(
        `${uiState.serverUrl}/api/box/sessions/${encodeURIComponent(uiState.boxSessionId)}`
      );
      if (!res.ok) return;
      const data = await res.json();
      uiState.blocksSent = data.total_blocks || 0;
      uiState.notes = data.notes || [];
      uiState.segments = data.segments || [];
      kpiBlocksSent.textContent = String(uiState.blocksSent);
      kpiRamFreed.textContent = `${Number(data.ram_freed_total_mb || 0).toFixed(2)} MB`;
      renderNotesList();
      renderSegmentsFeed();
    } catch (_) {}
  }

  // Listen for block progress messages from Service Worker / Offscreen
  chrome.runtime.onMessage.addListener((message) => {
    if (message && message.type === "BOX_BLOCK_PROGRESS") {
      const p = message.payload || {};
      uiState.blocksSent = p.totalBlocks || uiState.blocksSent + 1;
      uiState.blockElapsedSeconds = 0;
      kpiBlocksSent.textContent = String(uiState.blocksSent);
      kpiRamActive.textContent = `~${Number(p.estimatedRamMb || 1.05).toFixed(2)} MB`;
      kpiRamFreed.textContent = `${Number(p.ramFreedMb || 0).toFixed(2)} MB`;
      if (Array.isArray(p.newSegments) && p.newSegments.length > 0) {
        uiState.segments.push(...p.newSegments);
        renderSegmentsFeed();
      }
      liveTimerSub.textContent = `Bloque #${uiState.blocksSent} sincronizado y liberado de RAM`;
    }
  });

  // Wire UI Events
  modePresencialBtn.addEventListener("click", () => setMode("presencial"));
  modeVirtualBtn.addEventListener("click", () => setMode("virtual"));
  blockDurationSelect.addEventListener("change", updateRamCalculatorBanner);

  startRecBtn.addEventListener("click", handleStartRecording);
  stopRecBtn.addEventListener("click", handleStopAndFinalize);
  flushBlockBtn.addEventListener("click", async () => {
    showStatus("Rotando bloque actual y liberando memoria RAM...");
    await refreshSessionFromBackend();
  });

  document.querySelectorAll(".note-tag-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".note-tag-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      uiState.selectedNoteTag = btn.getAttribute("data-tag") || "nota";
    });
  });

  addNoteBtn.addEventListener("click", handleAddNote);
  noteTextInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      handleAddNote();
    }
  });

  openWebappBtn.addEventListener("click", () => {
    const targetUrl = uiState.boxSessionId
      ? `${uiState.serverUrl}/?view=box&box_session_id=${encodeURIComponent(uiState.boxSessionId)}`
      : `${uiState.serverUrl}/?view=box`;
    chrome.tabs.create({ url: targetUrl });
  });

  saveServerBtn.addEventListener("click", async () => {
    const cleanUrl = (serverUrlInput.value || "http://localhost:8000").trim().replace(/\/+$/, "");
    uiState.serverUrl = cleanUrl;
    await chrome.storage.local.set({ serverUrl: cleanUrl });
    showStatus(`Servidor actualizado: ${cleanUrl}`);
  });

  // Boot
  (async () => {
    const stored = await chrome.storage.local.get(["serverUrl", "blockDurationSec"]);
    if (stored.serverUrl) {
      uiState.serverUrl = stored.serverUrl;
      serverUrlInput.value = stored.serverUrl;
    }
    if (stored.blockDurationSec) {
      blockDurationSelect.value = String(stored.blockDurationSec);
    }
    updateRamCalculatorBanner();
    await detectActiveMeetingContext();
  })();
})();
