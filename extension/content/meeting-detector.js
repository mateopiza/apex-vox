/**
 * Apex Box — Virtual Meeting Detector & Quick Note Bar
 * (extension/content/meeting-detector.js)
 * ----------------------------------------------------
 * Injected into Google Meet, Zoom, Microsoft Teams, and Webex.
 * Batches all DOM updates with `requestAnimationFrame` per Chrome Extensions MV3 best practices.
 */

"use strict";

(function () {
  if (document.getElementById("apexbox-ext-floating-bar")) return;

  function getPlatformName() {
    const host = location.hostname.toLowerCase();
    if (host.includes("meet.google.com")) return "Google Meet";
    if (host.includes("zoom.us")) return "Zoom";
    if (host.includes("teams.microsoft.com") || host.includes("teams.live.com")) return "MS Teams";
    if (host.includes("webex.com")) return "Webex";
    return "Reunión Virtual";
  }

  async function mountFloatingMeetingBar() {
    const platformName = getPlatformName();

    await new Promise((resolve) =>
      requestAnimationFrame(() => {
        const bar = document.createElement("div");
        bar.id = "apexbox-ext-floating-bar";
        bar.className = "apexbox-ext-bar";
        bar.setAttribute("role", "region");
        bar.setAttribute("aria-label", "Apex Box — Grabador Ilimitado por Bloques");

        const dot = document.createElement("span");
        dot.className = "apexbox-ext-dot";

        const label = document.createElement("span");
        label.className = "apexbox-ext-title";
        label.textContent = `Apex Box · ${platformName}`;

        const noteInput = document.createElement("input");
        noteInput.type = "text";
        noteInput.className = "apexbox-ext-note-input";
        noteInput.placeholder = "+ Tomar nota rápida en llamada...";
        noteInput.maxLength = 240;

        const saveNoteBtn = document.createElement("button");
        saveNoteBtn.type = "button";
        saveNoteBtn.className = "apexbox-ext-btn apexbox-ext-btn-sec";
        saveNoteBtn.textContent = "Anotar";

        const openPanelBtn = document.createElement("button");
        openPanelBtn.type = "button";
        openPanelBtn.className = "apexbox-ext-btn";
        openPanelBtn.textContent = "Grabar Bloques (10h+)";

        const toast = document.createElement("span");
        toast.className = "apexbox-ext-toast";

        async function submitQuickNote() {
          const text = noteInput.value.trim();
          if (!text) return;
          noteInput.value = "";
          try {
            await chrome.runtime.sendMessage({
              type: "CONTENT_QUICK_NOTE",
              payload: { text, tag: "nota" },
            });
            toast.textContent = "✓ Nota guardada";
            setTimeout(() => {
              requestAnimationFrame(() => {
                toast.textContent = "";
              });
            }, 2200);
          } catch (err) {
            console.warn("Apex Box quick note warning:", err);
          }
        }

        saveNoteBtn.addEventListener("click", submitQuickNote);
        noteInput.addEventListener("keydown", (e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            submitQuickNote();
          }
        });

        openPanelBtn.addEventListener("click", async () => {
          try {
            await chrome.runtime.sendMessage({ type: "OPEN_SIDE_PANEL" });
          } catch (err) {
            console.warn("Could not open side panel:", err);
          }
        });

        bar.appendChild(dot);
        bar.appendChild(label);
        bar.appendChild(noteInput);
        bar.appendChild(saveNoteBtn);
        bar.appendChild(openPanelBtn);
        bar.appendChild(toast);

        document.body.appendChild(bar);
        resolve();
      })
    );

    if (globalThis.scheduler && globalThis.scheduler.yield) {
      await globalThis.scheduler.yield();
    }
  }

  mountFloatingMeetingBar();
})();
