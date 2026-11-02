/**
 * Pantalla de autorización OAuth (conectar ChatGPT / Claude con Apex Vox).
 * Usa la sesión iniciada en la web (localStorage) para permitir o rechazar el acceso.
 */
"use strict";

(function () {
  const params = Object.fromEntries(new URLSearchParams(location.search));
  const token = localStorage.getItem("apex_vox_token");
  const $ = (id) => document.getElementById(id);
  const account = $("oauth-account");
  const allowBtn = $("oauth-allow");
  const loginBtn = $("oauth-login");
  const denyBtn = $("oauth-deny");
  const errorBox = $("oauth-error");

  function showError(msg) {
    errorBox.textContent = msg;
    errorBox.classList.remove("hidden");
  }

  async function decide(approve) {
    allowBtn.disabled = true;
    denyBtn.disabled = true;
    try {
      const res = await fetch("/oauth/authorize/decision", {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token || ""}` },
        body: JSON.stringify({ params, approve }),
      });
      const data = await res.json();
      if (!res.ok || !data.redirect_to) throw new Error(data.error_description || data.detail || "No se pudo completar.");
      location.assign(data.redirect_to);
    } catch (err) {
      showError(err.message);
      allowBtn.disabled = false;
      denyBtn.disabled = false;
    }
  }

  function needLogin() {
    sessionStorage.setItem("apex_oauth_next", location.pathname + location.search);
    account.textContent = "Inicia sesión en Apex Vox para continuar.";
    loginBtn.classList.remove("hidden");
    allowBtn.classList.add("hidden");
  }

  allowBtn.addEventListener("click", () => decide(true));
  denyBtn.addEventListener("click", () => (token ? decide(false) : history.back()));

  if (!token) return needLogin();
  fetch("/api/auth/me", { headers: { Authorization: `Bearer ${token}` } })
    .then((r) => (r.ok ? r.json() : Promise.reject()))
    .then((me) => {
      const plan = me.quota && me.quota.is_unlimited ? "Apex Pro" : "Plan gratis";
      account.innerHTML = "";
      account.append("Conectarás la cuenta ");
      const b = document.createElement("strong");
      b.textContent = me.email;
      account.append(b, ` · ${plan}`);
      allowBtn.classList.remove("hidden");
    })
    .catch(needLogin);
})();
