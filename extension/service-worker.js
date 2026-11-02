/**
 * Apex Box — Chrome Extension Service Worker (Manifest V3)
 * --------------------------------------------------------
 * Coordinates:
 * - Side Panel opening (`openPanelOnActionClick: true`, context menu, shortcut, content script)
 * - State-locked Tab Capture (`chrome.tabCapture`) & Desktop Capture (`chrome.desktopCapture`)
 * - Offscreen Document lifecycle (`chrome.offscreen`) for unlimited block recording
 * - Ephemeral state in `chrome.storage.session` and persistent settings in `chrome.storage.local`
 * - Heartbeat & badge updates via `chrome.alarms` (zero global variables, zero setInterval)
 */

"use strict";

// Enable opening Side Panel directly when clicking the extension toolbar icon
chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true });

/**
 * Helper to ensure the single Offscreen Document exists for Web Audio + MediaRecorder work.
 */
async function ensureOffscreenDocument() {
  const hasDoc = await chrome.offscreen.hasDocument();
  if (hasDoc) return;

  await chrome.offscreen.createDocument({
    url: "offscreen/offscreen.html",
    reasons: ["USER_MEDIA", "AUDIO_PLAYBACK"],
    justification:
      "Grabación continua por bloques de 3 minutos (Opus/WebM) y mezcla de audio de reunión virtual sin llenar la memoria RAM.",
  });
}

/**
 * Detect virtual meeting platform from a URL string.
 */
function detectMeetingPlatform(urlStr) {
  const u = String(urlStr || "").toLowerCase();
  if (u.includes("meet.google.com")) {
    return { isVirtualMeeting: true, platform: "google_meet", label: "Google Meet" };
  }
  if (u.includes("zoom.us")) {
    return { isVirtualMeeting: true, platform: "zoom", label: "Zoom" };
  }
  if (u.includes("teams.microsoft.com") || u.includes("teams.live.com")) {
    return { isVirtualMeeting: true, platform: "microsoft_teams", label: "Microsoft Teams" };
  }
  if (u.includes("webex.com")) {
    return { isVirtualMeeting: true, platform: "webex", label: "Cisco Webex" };
  }
  return { isVirtualMeeting: false, platform: "in_person", label: "Reunión Presencial / Web" };
}

/**
 * Initialize default storage and context menus on installation/update.
 */
chrome.runtime.onInstalled.addListener(async (details) => {
  if (details.reason === "install") {
    await chrome.storage.local.set({
      serverUrl: "http://localhost:8000",
      blockDurationSec: 180,
      defaultMode: "presencial",
      diarizationEngine: "Mc-Lewis",
      language: "es",
    });
  }

  await chrome.storage.session.set({
    recordingState: "idle",
    boxSessionId: null,
    uploadSessionId: null,
    blocksSent: 0,
    totalDurationSec: 0,
    estimatedRamMb: 0,
    ramFreedMb: 0,
    activeMode: "presencial",
    activePlatform: "in_person",
  });

  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create({
      id: "open-apex-box-panel",
      title: "Abrir Apex Box — Grabador Ilimitado por Bloques",
      contexts: ["page", "selection", "action"],
    });
    chrome.contextMenus.create({
      id: "save-selection-as-note",
      title: "Guardar texto seleccionado como Nota en Vivo (Apex Box)",
      contexts: ["selection"],
    });
  });
});

/**
 * Context menu handler — always provides visible user feedback via notification + badge.
 */
chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId === "open-apex-box-panel" && tab) {
    await chrome.sidePanel.open({ windowId: tab.windowId });
    await chrome.action.setBadgeText({ text: "ON" });
    await chrome.action.setBadgeBackgroundColor({ color: "#f43e01" });
    await chrome.notifications.create(`panel-opened-${Date.now()}`, {
      type: "basic",
      iconUrl: chrome.runtime.getURL("icons/icon-128.png"),
      title: "Apex Box — Panel Lateral Abierto",
      message: "Listo para grabar sin límite en bloques de 3 minutos (~1 MB RAM).",
    });
    return;
  }

  if (info.menuItemId === "save-selection-as-note" && info.selectionText) {
    const { serverUrl = "http://localhost:8000" } = await chrome.storage.local.get("serverUrl");
    const { boxSessionId = null, totalDurationSec = 0 } = await chrome.storage.session.get([
      "boxSessionId",
      "totalDurationSec",
    ]);

    const noteText = info.selectionText.trim();
    if (boxSessionId) {
      try {
        await fetch(`${serverUrl}/api/box/sessions/${encodeURIComponent(boxSessionId)}/notes`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            text: noteText,
            tag: "nota",
            timestamp_sec: totalDurationSec,
          }),
        });
      } catch (err) {
        console.warn("Could not post context menu note to backend:", err);
      }
    }

    const { quickNotes = [] } = await chrome.storage.local.get("quickNotes");
    quickNotes.push({
      text: noteText,
      tag: "nota",
      timestampSec: totalDurationSec,
      createdAt: new Date().toISOString(),
    });
    await chrome.storage.local.set({ quickNotes });

    await chrome.notifications.create(`note-saved-${Date.now()}`, {
      type: "basic",
      iconUrl: chrome.runtime.getURL("icons/icon-128.png"),
      title: "Nota Guardada en Apex Box",
      message: `"${noteText.slice(0, 90)}" registrada con marca de tiempo.`,
    });
  }
});

/**
 * Keyboard command handler (`Ctrl+Shift+Y` / `Command+Shift+Y`).
 */
chrome.commands.onCommand.addListener(async (command) => {
  if (command === "open-side-panel") {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (tab) {
      await chrome.sidePanel.open({ windowId: tab.windowId });
    }
  }
});

/**
 * Monitor tab navigation to detect Google Meet, Zoom, Microsoft Teams, or Webex calls.
 */
chrome.tabs.onUpdated.addListener(async (tabId, changeInfo, tab) => {
  if (changeInfo.status !== "complete" || !tab.url) return;
  const detected = detectMeetingPlatform(tab.url);
  if (detected.isVirtualMeeting) {
    await chrome.storage.session.set({
      detectedMeetingTabId: tabId,
      detectedMeetingUrl: tab.url,
      detectedMeetingTitle: tab.title || detected.label,
      detectedPlatform: detected.platform,
      detectedPlatformLabel: detected.label,
    });
  }
});

/**
 * Periodic alarm for recording badge heartbeat (replaces setInterval in MV3 SW).
 */
chrome.alarms.onAlarm.addListener(async (alarm) => {
  if (alarm.name !== "apex-box-heartbeat") return;
  const { recordingState = "idle", blocksSent = 0 } = await chrome.storage.session.get([
    "recordingState",
    "blocksSent",
  ]);
  if (recordingState === "recording") {
    const badgeLabel = blocksSent > 0 ? `B${blocksSent}` : "REC";
    await chrome.action.setBadgeText({ text: badgeLabel });
    await chrome.action.setBadgeBackgroundColor({ color: "#f43e01" });
  } else if (recordingState === "idle") {
    await chrome.action.setBadgeText({ text: "" });
    await chrome.alarms.clear("apex-box-heartbeat");
  }
});

/**
 * Start unlimited block recording with strict state locking to prevent double-capture errors.
 */
async function startBlockRecording(options) {
  const { recordingState = "idle" } = await chrome.storage.session.get("recordingState");
  if (recordingState === "starting" || recordingState === "stopping" || recordingState === "recording") {
    return { ok: false, error: `Grabación ya en estado '${recordingState}'.` };
  }

  await chrome.storage.session.set({ recordingState: "starting" });

  try {
    const [activeTab] = await chrome.tabs.query({ active: true, currentWindow: true });
    const mode = options.mode || "presencial";
    const blockDurationSec = Number(options.blockDurationSec) || 180;
    const serverUrl = options.serverUrl || "http://localhost:8000";
    const boxSessionId = options.boxSessionId || null;

    let streamId = null;
    let captureSource = "microphone";

    if (mode === "virtual" && activeTab && activeTab.id) {
      if (options.useDesktopPicker) {
        // Use desktopCapture with targetTab (requires "tabs" + "desktopCapture" permissions)
        streamId = await new Promise((resolve) => {
          chrome.desktopCapture.chooseDesktopMedia(
            ["tab", "window", "screen"],
            activeTab,
            (chosenStreamId) => {
              resolve(chosenStreamId || null);
            }
          );
        });
        captureSource = streamId ? "desktop" : "microphone";
      } else {
        try {
          streamId = await chrome.tabCapture.getMediaStreamId({
            targetTabId: activeTab.id,
          });
          captureSource = "tab";
        } catch (tabErr) {
          console.warn("tabCapture fallback to microphone/offscreen stream:", tabErr.message);
          streamId = null;
          captureSource = "microphone";
        }
      }
    }

    await ensureOffscreenDocument();

    const offscreenResponse = await chrome.runtime.sendMessage({
      target: "offscreen",
      type: "OFFSCREEN_START_RECORDING",
      mode,
      captureSource,
      streamId,
      blockDurationSec,
      serverUrl,
      boxSessionId,
    });

    if (offscreenResponse && offscreenResponse.ok === false) {
      throw new Error(offscreenResponse.error || "No se pudo iniciar la captura de audio.");
    }

    await chrome.storage.session.set({
      recordingState: "recording",
      boxSessionId,
      activeMode: mode,
      blocksSent: 0,
      totalDurationSec: 0,
      estimatedRamMb: 1.05,
      ramFreedMb: 0,
      startedAtIso: new Date().toISOString(),
    });

    await chrome.action.setBadgeText({ text: "REC" });
    await chrome.action.setBadgeBackgroundColor({ color: "#f43e01" });
    await chrome.alarms.create("apex-box-heartbeat", { periodInMinutes: 0.5 });

    return {
      ok: true,
      recordingState: "recording",
      captureSource,
      boxSessionId,
    };
  } catch (err) {
    console.error("Failed to start block recording:", err);
    await chrome.storage.session.set({ recordingState: "idle" });
    await chrome.action.setBadgeText({ text: "" });
    return { ok: false, error: err.message || String(err) };
  }
}

/**
 * Stop unlimited block recording and flush the final partial block.
 */
async function stopBlockRecording() {
  const { recordingState = "idle" } = await chrome.storage.session.get("recordingState");
  if (recordingState === "stopping" || recordingState === "idle") {
    return { ok: true, recordingState: "idle" };
  }

  await chrome.storage.session.set({ recordingState: "stopping" });
  try {
    const hasDoc = await chrome.offscreen.hasDocument();
    if (hasDoc) {
      await chrome.runtime.sendMessage({
        target: "offscreen",
        type: "OFFSCREEN_STOP_RECORDING",
      });
    }
    return { ok: true, recordingState: "idle" };
  } catch (err) {
    console.warn("Warning while stopping offscreen recorder:", err);
    return { ok: false, error: err.message };
  } finally {
    await chrome.storage.session.set({ recordingState: "idle" });
    await chrome.action.setBadgeText({ text: "" });
    await chrome.alarms.clear("apex-box-heartbeat");
  }
}

/**
 * Central message router (IIFE + return true pattern for async responses).
 */
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!message || message.target === "offscreen") {
    return false;
  }

  (async () => {
    try {
      if (message.type === "OPEN_SIDE_PANEL") {
        const winId = sender.tab ? sender.tab.windowId : undefined;
        if (winId !== undefined) {
          await chrome.sidePanel.open({ windowId: winId });
        } else {
          const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
          if (tab) await chrome.sidePanel.open({ windowId: tab.windowId });
        }
        sendResponse({ ok: true });
        return;
      }

      if (message.type === "GET_ACTIVE_MEETING_CONTEXT") {
        const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
        const detected = tab ? detectMeetingPlatform(tab.url) : detectMeetingPlatform("");
        const sessionData = await chrome.storage.session.get(null);
        sendResponse({
          ok: true,
          tabId: tab ? tab.id : null,
          url: tab ? tab.url : "",
          title: tab ? tab.title : "",
          ...detected,
          sessionState: sessionData,
        });
        return;
      }

      if (message.type === "SW_START_RECORDING") {
        const result = await startBlockRecording(message.payload || {});
        sendResponse(result);
        return;
      }

      if (message.type === "SW_STOP_RECORDING") {
        const result = await stopBlockRecording();
        sendResponse(result);
        return;
      }

      if (message.type === "OFFSCREEN_BLOCK_UPLOADED") {
        const {
          blockIndex = 0,
          totalBlocks = 1,
          totalDurationSec = 0,
          estimatedRamMb = 1.05,
          ramFreedMb = 0,
          newSegments = [],
          blockInfo = null,
        } = message.payload || {};

        await chrome.storage.session.set({
          blocksSent: totalBlocks,
          totalDurationSec,
          estimatedRamMb,
          ramFreedMb,
          lastBlockAtIso: new Date().toISOString(),
        });

        await chrome.action.setBadgeText({ text: `B${totalBlocks}` });
        await chrome.action.setBadgeBackgroundColor({ color: "#f43e01" });

        // Broadcast to Side Panel & Content Scripts
        try {
          await chrome.runtime.sendMessage({
            type: "BOX_BLOCK_PROGRESS",
            payload: {
              blockIndex,
              totalBlocks,
              totalDurationSec,
              estimatedRamMb,
              ramFreedMb,
              newSegments,
              blockInfo,
            },
          });
        } catch (_) {
          // Side panel might be closed; state is safely persisted in chrome.storage.session
        }
        sendResponse({ ok: true });
        return;
      }

      if (message.type === "CONTENT_QUICK_NOTE") {
        const { text = "", tag = "nota" } = message.payload || {};
        const { serverUrl = "http://localhost:8000" } = await chrome.storage.local.get("serverUrl");
        const { boxSessionId = null, totalDurationSec = 0 } = await chrome.storage.session.get([
          "boxSessionId",
          "totalDurationSec",
        ]);

        let savedNote = null;
        if (boxSessionId && text.trim()) {
          const res = await fetch(
            `${serverUrl}/api/box/sessions/${encodeURIComponent(boxSessionId)}/notes`,
            {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                text: text.trim(),
                tag,
                timestamp_sec: totalDurationSec,
              }),
            }
          );
          if (res.ok) {
            savedNote = await res.json();
          }
        }
        sendResponse({ ok: true, note: savedNote });
        return;
      }

      sendResponse({ ok: false, error: "Tipo de mensaje no reconocido." });
    } catch (err) {
      sendResponse({ ok: false, error: err.message || String(err) });
    }
  })();

  return true;
});
