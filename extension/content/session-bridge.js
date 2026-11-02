/**
 * Apex Box — Puente de sesión (extension/content/session-bridge.js)
 * Corre solo en apex-vox.ialabs.app (y localhost:8000). Copia el token de la sesión
 * iniciada en la web al almacenamiento de la extensión, para que el grabador grabe
 * con tu cuenta. Si cierras sesión en la web, la extensión también la pierde.
 */
"use strict";

(function () {
  const KEY = "apex_vox_token";
  let last;

  function sync() {
    let token = null;
    try {
      token = window.localStorage.getItem(KEY);
    } catch (_) {
      return;
    }
    if (token === last) return;
    last = token;
    chrome.storage.local.set({ authToken: token || null, authOrigin: location.origin });
  }

  sync();
  // El login/logout ocurre en esta misma página (localStorage no emite "storage" aquí).
  setInterval(sync, 2000);
  window.addEventListener("storage", sync);
})();
