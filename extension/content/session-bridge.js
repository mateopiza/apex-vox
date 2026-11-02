/**
 * Apex Box — Puente de sesión (content/session-bridge.js)
 * Corre solo en apex-vox.ialabs.app. Sincroniza el token de la sesión iniciada
 * en la web con el almacenamiento local de la extensión para que el grabador
 * suba las reuniones a tu cuenta. Si cierras sesión en la web, la extensión
 * también limpia el token.
 */
"use strict";

(function () {
  const KEY = "apex_vox_token";
  let last;

  async function sync() {
    if (!chrome || !chrome.runtime || !chrome.runtime.id) return;
    let token = null;
    try {
      token = window.localStorage.getItem(KEY);
    } catch (_) {
      return;
    }
    if (token === last) return;
    last = token;
    try {
      await chrome.storage.local.set({
        authToken: token || null,
        authOrigin: location.origin,
      });
    } catch (_) {
      // Contexto de extensión invalidado tras actualización o recarga
    }
  }

  sync();
  setInterval(sync, 2000);
  window.addEventListener("storage", sync);
  window.addEventListener("focus", sync);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) sync();
  });
})();
