/**
 * Apex Box — Offscreen Audio Capture & Zero-RAM Block Rotation Engine
 * (extension/offscreen/offscreen.js)
 * -------------------------------------------------------------------
 * Strictly follows Manifest V3 Offscreen Document rules:
 * - Uses ONLY `chrome.runtime.onMessage`, `chrome.runtime.sendMessage`, and Web APIs
 *   (`navigator.mediaDevices.getUserMedia`, `AudioContext`, `MediaRecorder`, `IndexedDB`, `fetch`).
 * - Implements `dual_recorder_zero_gap_ebml`:
 *   Every `blockDurationSec` (default 180s = 3 min), a new `MediaRecorder` is started on the
 *   persistent `MediaStream` BEFORE stopping the previous `MediaRecorder`.
 *   Each finished block (~1.03 MB at 48 kbps Opus) has a complete WebM/EBML header, is uploaded
 *   immediately to `/api/box/sessions/{id}/blocks`, and its memory buffer (`chunks.length = 0`)
 *   is immediately released for Garbage Collection.
 */

"use strict";

const RECORDER_BITRATE = 48000; // 48 kbps Opus voice-optimized (~6 KB/s, ~1.03 MB per 3-min block)
const DB_NAME = "apex_box_offline_blocks_db";
const STORE_NAME = "pending_blocks";

let activeStreams = [];
let audioContext = null;
let currentRecorder = null;
let rotationTimerId = null;
let isStopping = false;

let sessionConfig = {
  serverUrl: "http://localhost:8000",
  boxSessionId: null,
  blockDurationSec: 180,
  mode: "presencial",
  blockCounter: 0,
};

function selectSupportedMimeType() {
  const candidates = [
    "audio/webm;codecs=opus",
    "audio/webm",
    "audio/ogg;codecs=opus",
    "audio/mp4",
  ];
  for (const mime of candidates) {
    if (typeof MediaRecorder !== "undefined" && MediaRecorder.isTypeSupported(mime)) {
      return mime;
    }
  }
  return "";
}

/**
 * IndexedDB helper to buffer blocks if network briefly drops during a 10-hour recording.
 */
function openOfflineDb() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, 1);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        db.createObjectStore(STORE_NAME, { keyPath: "id", autoIncrement: true });
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function saveBlockOffline(record) {
  try {
    const db = await openOfflineDb();
    await new Promise((resolve, reject) => {
      const tx = db.transaction(STORE_NAME, "readwrite");
      tx.objectStore(STORE_NAME).add(record);
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
    db.close();
  } catch (err) {
    console.warn("Could not buffer block in IndexedDB:", err);
  }
}

async function flushOfflineBlocks() {
  try {
    const db = await openOfflineDb();
    const items = await new Promise((resolve, reject) => {
      const tx = db.transaction(STORE_NAME, "readonly");
      const req = tx.objectStore(STORE_NAME).getAll();
      req.onsuccess = () => resolve(req.result || []);
      req.onerror = () => reject(req.error);
    });

    for (const item of items) {
      const uploaded = await uploadSingleBlockToBackend(
        item.blob,
        item.blockIndex,
        item.durationSec,
        item.serverUrl,
        item.boxSessionId,
        false
      );
      if (uploaded) {
        await new Promise((resolve) => {
          const tx = db.transaction(STORE_NAME, "readwrite");
          tx.objectStore(STORE_NAME).delete(item.id);
          tx.oncomplete = () => resolve();
          tx.onerror = () => resolve();
        });
      }
    }
    db.close();
  } catch (err) {
    console.warn("Offline queue flush check:", err);
  }
}

/**
 * Upload a completed audio block to the Apex Box backend and notify the Service Worker.
 */
async function uploadSingleBlockToBackend(
  blob,
  blockIndex,
  durationSec,
  serverUrl,
  boxSessionId,
  saveOnFailure = true
) {
  if (!boxSessionId || !blob || blob.size === 0) return false;

  const ext = blob.type.includes("mp4")
    ? "m4a"
    : blob.type.includes("ogg")
    ? "ogg"
    : "webm";
  const filename = `bloque_${String(blockIndex + 1).padStart(4, "0")}.${ext}`;

  const formData = new FormData();
  formData.append("file", blob, filename);
  formData.append("block_index", String(blockIndex));
  formData.append("duration_hint_sec", String(durationSec));
  formData.append("transcribe_immediately", "true");

  try {
    const response = await fetch(
      `${serverUrl}/api/box/sessions/${encodeURIComponent(boxSessionId)}/blocks`,
      {
        method: "POST",
        body: formData,
      }
    );
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const data = await response.json();

    await chrome.runtime.sendMessage({
      type: "OFFSCREEN_BLOCK_UPLOADED",
      payload: {
        blockIndex,
        totalBlocks: data.total_blocks_received,
        totalDurationSec: data.total_duration_sec,
        estimatedRamMb: data.estimated_client_ram_mb,
        ramFreedMb: data.ram_freed_total_mb,
        newSegments: data.new_segments || [],
        blockInfo: data.block || null,
      },
    });

    // Attempt to flush any previously queued offline blocks
    flushOfflineBlocks();
    return true;
  } catch (err) {
    console.warn(`Upload failed for block #${blockIndex}, queueing in IndexedDB:`, err);
    if (saveOnFailure) {
      await saveBlockOffline({
        blob,
        blockIndex,
        durationSec,
        serverUrl,
        boxSessionId,
        createdAt: Date.now(),
      });
    }
    return false;
  }
}

/**
 * Create a single MediaRecorder instance bound to its own isolated chunk array
 * that self-cleans on stop to guarantee O(1) RAM usage over 10+ hours.
 */
function spawnBlockRecorder(stream, blockIndex, serverUrl, boxSessionId) {
  const mimeType = selectSupportedMimeType();
  const recOptions = { audioBitsPerSecond: RECORDER_BITRATE };
  if (mimeType) {
    recOptions.mimeType = mimeType;
  }

  const recorder = new MediaRecorder(stream, recOptions);
  let blockChunks = [];
  const startedAt = Date.now();

  recorder.ondataavailable = (event) => {
    if (event.data && event.data.size > 0) {
      blockChunks.push(event.data);
    }
  };

  recorder.onstop = async () => {
    const elapsedSec = Math.max(0.5, (Date.now() - startedAt) / 1000.0);
    const finalMime = recorder.mimeType || mimeType || "audio/webm";
    const blockBlob = new Blob(blockChunks, { type: finalMime });

    // CRITICAL FOR 10-HOUR ZERO-RAM GUARANTEE:
    // Dereference chunk array immediately so V8 Garbage Collector frees RAM
    blockChunks.length = 0;
    blockChunks = null;

    await uploadSingleBlockToBackend(
      blockBlob,
      blockIndex,
      Number(elapsedSec.toFixed(2)),
      serverUrl,
      boxSessionId,
      true
    );
  };

  recorder.start();
  return recorder;
}

/**
 * Build the unified MediaStream for either:
 * - Presencial Mode (Microphone with room gain & noise suppression)
 * - Virtual Meeting Mode (Tab/Desktop Audio from Zoom/Meet/Teams + Microphone mixed via Web Audio API)
 */
async function acquireRecordingStream(options) {
  await cleanupStreams();

  const { mode = "presencial", captureSource = "microphone", streamId = null } = options;

  if (mode === "virtual" && streamId) {
    const constraintSource = captureSource === "desktop" ? "desktop" : "tab";
    const tabStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        mandatory: {
          chromeMediaSource: constraintSource,
          chromeMediaSourceId: streamId,
        },
      },
      video: false,
    });
    activeStreams.push(tabStream);

    audioContext = new AudioContext();
    const destination = audioContext.createMediaStreamDestination();

    const tabSource = audioContext.createMediaStreamSource(tabStream);
    // Keep playing tab audio to local speakers so user hears the meeting normally
    tabSource.connect(audioContext.destination);
    tabSource.connect(destination);

    // Also mix microphone if permissions allow so both remote participants and local user are captured
    try {
      const micStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
        video: false,
      });
      activeStreams.push(micStream);
      const micSource = audioContext.createMediaStreamSource(micStream);
      micSource.connect(destination);
    } catch (micErr) {
      console.info("Recording virtual meeting tab audio without secondary mic stream:", micErr.message);
    }

    return destination.stream;
  }

  // Presencial mode (or Virtual fallback): capture microphone with acoustic voice optimization
  const micStream = await navigator.mediaDevices.getUserMedia({
    audio: {
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: true,
      channelCount: 1,
      sampleRate: 16000,
    },
    video: false,
  });
  activeStreams.push(micStream);
  return micStream;
}

async function startOffscreenRecording(options) {
  isStopping = false;
  sessionConfig = {
    serverUrl: options.serverUrl || "http://localhost:8000",
    boxSessionId: options.boxSessionId,
    blockDurationSec: Math.max(5, Number(options.blockDurationSec) || 180),
    mode: options.mode || "presencial",
    blockCounter: 0,
  };

  const mixedStream = await acquireRecordingStream(options);

  // Start Block #0
  const firstIdx = sessionConfig.blockCounter++;
  currentRecorder = spawnBlockRecorder(
    mixedStream,
    firstIdx,
    sessionConfig.serverUrl,
    sessionConfig.boxSessionId
  );

  // Schedule seamless zero-gap rotation every blockDurationSec
  const intervalMs = sessionConfig.blockDurationSec * 1000;
  rotationTimerId = setInterval(() => {
    if (isStopping || !mixedStream.active) return;
    const prevRecorder = currentRecorder;
    const nextIdx = sessionConfig.blockCounter++;

    // 1. Start next block recorder FIRST on the live stream (0 ms audio gap)
    currentRecorder = spawnBlockRecorder(
      mixedStream,
      nextIdx,
      sessionConfig.serverUrl,
      sessionConfig.boxSessionId
    );

    // 2. Stop previous block recorder (triggers upload + immediate RAM release)
    if (prevRecorder && prevRecorder.state !== "inactive") {
      try {
        prevRecorder.stop();
      } catch (e) {
        console.warn("Error stopping previous block recorder:", e);
      }
    }
  }, intervalMs);
}

async function stopOffscreenRecording() {
  isStopping = true;
  if (rotationTimerId) {
    clearInterval(rotationTimerId);
    rotationTimerId = null;
  }

  if (currentRecorder && currentRecorder.state !== "inactive") {
    await new Promise((resolve) => {
      const origStop = currentRecorder.onstop;
      currentRecorder.onstop = async (ev) => {
        if (origStop) await origStop(ev);
        resolve();
      };
      try {
        currentRecorder.stop();
      } catch (_) {
        resolve();
      }
    });
  }
  currentRecorder = null;
  await cleanupStreams();
}

async function cleanupStreams() {
  for (const s of activeStreams) {
    try {
      s.getTracks().forEach((t) => t.stop());
    } catch (_) {}
  }
  activeStreams = [];
  if (audioContext) {
    try {
      await audioContext.close();
    } catch (_) {}
    audioContext = null;
  }
}

/**
 * Listen for commands from Service Worker.
 */
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!message || message.target !== "offscreen") {
    return false;
  }

  (async () => {
    try {
      if (message.type === "OFFSCREEN_START_RECORDING") {
        await startOffscreenRecording(message);
        sendResponse({ ok: true });
        return;
      }

      if (message.type === "OFFSCREEN_STOP_RECORDING") {
        await stopOffscreenRecording();
        sendResponse({ ok: true });
        return;
      }

      sendResponse({ ok: false, error: "Comando offscreen desconocido." });
    } catch (err) {
      sendResponse({ ok: false, error: err.message || String(err) });
    }
  })();

  return true;
});
