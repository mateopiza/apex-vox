/**
 * Apex Box — Service Worker (Manifest V3)
 * ---------------------------------------
 * El icono de la extensión solo abre (o enfoca) la pestaña fija del grabador.
 * Toda la grabación vive en esa pestaña (recorder/recorder.html); el badge del
 * icono lo actualiza el propio grabador con "REC" + tiempo.
 */

"use strict";

const RECORDER_PATH = "recorder/recorder.html";
const CLOUD_URL = "https://apex-vox.ialabs.app";

// Al instalar/actualizar: usar la versión en la nube. Si había guardado un servidor
// local (versiones anteriores), se migra a la nube; se puede volver a cambiar en "Servidor".
chrome.runtime.onInstalled.addListener(async () => {
  const { serverUrl } = await chrome.storage.local.get("serverUrl");
  if (!serverUrl || /^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?\/?$/i.test(serverUrl)) {
    await chrome.storage.local.set({ serverUrl: CLOUD_URL });
  }
});

async function findRecorderTab() {
  const url = chrome.runtime.getURL(RECORDER_PATH);
  const tabs = await chrome.tabs.query({ url: `${url}*` });
  return tabs[0] || null;
}

function isCapturableTab(tab) {
  return Boolean(tab && tab.id !== undefined && /^https?:/i.test(tab.url || ""));
}

chrome.action.onClicked.addListener(async (clickedTab) => {
  // La pestaña donde se pulsó el icono queda como fuente de audio para el modo virtual
  // (tabCapture exige que la extensión haya sido invocada en esa pestaña).
  const sourceTab = isCapturableTab(clickedTab) ? clickedTab : null;
  const existing = await findRecorderTab();

  if (existing) {
    await chrome.tabs.update(existing.id, { active: true });
    await chrome.windows.update(existing.windowId, { focused: true });
    if (sourceTab) {
      chrome.runtime
        .sendMessage({
          type: "SOURCE_TAB",
          tabId: sourceTab.id,
          url: sourceTab.url,
          title: sourceTab.title || "",
        })
        .catch(() => {});
    }
    return;
  }

  const params = new URLSearchParams();
  if (sourceTab) params.set("source", String(sourceTab.id));
  await chrome.tabs.create({
    url: `${RECORDER_PATH}${params.toString() ? `?${params}` : ""}`,
    pinned: true,
    active: true,
    windowId: clickedTab ? clickedTab.windowId : undefined,
  });
});

// Si se cierra la pestaña del grabador, el icono vuelve a "no grabando".
chrome.tabs.onRemoved.addListener(async () => {
  if (!(await findRecorderTab())) {
    await chrome.action.setBadgeText({ text: "" });
    await chrome.action.setTitle({ title: "Apex Box · Abrir grabador" });
  }
});
