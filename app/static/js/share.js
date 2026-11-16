// Página compartida (/s/<token>): las marcas de tiempo llevan el reproductor a ese instante.
(function () {
  "use strict";
  const player = document.getElementById("share-audio");
  if (!player) return;
  document.querySelectorAll("button.timestamp-btn[data-start]").forEach((btn) => {
    btn.addEventListener("click", () => {
      player.currentTime = Number(btn.dataset.start) || 0;
      player.play().catch(() => {});
    });
  });
})();
