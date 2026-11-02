# Apex Box Chrome extension

`extension/` contains a Manifest V3 extension that records in-person or virtual meetings from a **pinned recorder tab** and uploads them to Apex Vox in 3-minute blocks. When you stop recording you get a link to the transcript, notes, Apex Summa report and minutes. The interface is in Spanish or English, following the browser language (`_locales/`).

## Install

**From the Chrome Web Store**

Open [Apex Box on the Chrome Web Store](https://chromewebstore.google.com/detail/hjjecchpiodaefnmdhfkbiejcakojgdo) and click **Add to Chrome**. The extension card in the web app links there.

**From a build of the server**

1. Download the ZIP from `https://<your-host>/api/box/extension/download` (or `/api/box/extension.zip`) and unzip it.
2. Open `chrome://extensions`, turn on **Developer mode**, click **Load unpacked**, and select the unzipped folder.

**From the repository**

1. Open `chrome://extensions`, turn on **Developer mode**, click **Load unpacked**, and select the `extension/` folder.
2. After editing files, click the reload icon on the extension card.

**First use**

1. Sign in to Apex Vox in a normal tab (`https://apex-vox.ialabs.app`, or `http://localhost:8000` for local development). The session bridge copies your session to the extension.
2. Click the Apex Box icon. A pinned recorder tab opens.
3. To record a self-hosted server, open **Server** in the recorder, enter its origin, and save. The origin must also appear in `host_permissions` and `content_scripts.matches` (see [Self-hosting](#self-hosting)).

## How it works

### Files

| File | Role |
| --- | --- |
| `manifest.json` | MV3 manifest: permissions, host permissions, content script, localized name and description |
| `service-worker.js` | Opens or focuses the pinned recorder tab when the icon is clicked. Remembers which tab was clicked as the virtual-mode audio source. Clears the badge when the recorder tab closes. Defaults the server to the cloud URL on install |
| `content/session-bridge.js` | Runs only on the Apex Vox origins. Every 2 s it copies `localStorage["apex_vox_token"]` and the page origin into `chrome.storage.local` (`authToken`, `authOrigin`). Signing out on the web clears it |
| `recorder/recorder.html`, `recorder.js`, `recorder.css` | The recorder UI and all capture, upload and finalize logic |
| `recorder/level-meter.js` | `AudioWorklet` that reports RMS and peak level about every 50 ms, even when the tab is in the background |
| `_locales/*/messages.json` | Extension name, description and action title in `es`, `es_419` and `en` |

### Pinned recorder tab

Recording runs in an extension page (`recorder/recorder.html`) opened as a **pinned tab**. It does not use a popup, side panel or offscreen document. A pinned tab keeps running while you use other tabs, and the user can see it. Clicking the icon again focuses the existing tab instead of opening a new one.

The recorder uses the session token only if `authOrigin` matches the configured server origin. Otherwise it asks you to sign in.

### Capture modes

- **In person:** `getUserMedia` on the microphone, with echo cancellation, noise suppression and automatic gain.
- **Virtual (Meet, Zoom, Teams, Webex):** click the extension icon *from the meeting tab*. That tab becomes the source. The recorder calls `chrome.tabCapture.getMediaStreamId({targetTabId, consumerTabId})`, opens the tab stream with `chromeMediaSource: "tab"`, plays it back so you still hear the meeting, and mixes it with your microphone through an `AudioContext` and `MediaStreamDestination`. If the microphone is unavailable it records the meeting audio only. The platform is detected from the tab URL.

### Sound meter and silence warning

Each source (microphone, meeting) feeds a `level-meter` worklet. The recorder draws a live waveform and a level bar per source:

- Sound counts as present above an RMS of about 0.006 (around -44 dBFS).
- After **15 s** of continuous silence, the status line, the tab title (`⚠ NO SOUND`) and the toolbar badge (amber `MUDO`/`MUTE`) warn the user. If a source track ends, the recorder reports "source disconnected".
- While sound is coming in, the badge shows the elapsed time on a red background, and the recorder shows a `REC` pill.

### Block upload

1. On **Record** the recorder creates a session with `POST /api/box/sessions` (`mode`, `platform`, `meeting_url`, `block_duration_sec: 180`, engine).
2. A `MediaRecorder` (`audio/webm;codecs=opus` when supported, 48 kbps) records the stream. Every 180 s a **new recorder is started on the same stream before the previous one is stopped**, so every block is a complete, playable file and no audio is lost between blocks.
3. When a recorder stops, its chunks become one `Blob`, the chunk array is released, and the blob is sent to `POST /api/box/sessions/{id}/blocks` with `block_index` and `duration_hint_sec`. The response updates counters for blocks, segments, speakers and pending uploads.
4. Failed uploads are retried, up to 3 attempts per block, from an in-memory queue. A block that still fails is counted and reported in the final summary.
5. On **Stop** the last block is flushed, pending uploads are awaited, and `POST /api/box/sessions/{id}/finalize` is called with the selected minutes template. The recorder shows and copies the link `https://<server>/?job=<job_id>`.

Free accounts consume their daily quota per block. When the quota runs out, block uploads return 402.

## Permissions

| Permission | Why it is needed |
| --- | --- |
| `storage` | Stores the server URL, the last meeting type, mode and engine, and the session token copied by the session bridge. |
| `tabs` | Finds and focuses the pinned recorder tab, reads the clicked tab's URL and title to detect the meeting platform, and opens the sign-in page. |
| `tabCapture` | Captures the audio of the meeting tab in virtual mode. Chrome only allows it for a tab where the user invoked the extension. |
| Host `https://apex-vox.ialabs.app/*` | Calls the Apex Vox API (session, blocks, notes, finalize, profile) on the default server. |
| Host `http://localhost:8000/*`, `http://127.0.0.1:8000/*` | Same, for a local development server. |
| Content script on the same three origins | `session-bridge.js` reads the signed-in session token from the Apex Vox page so the recorder can authenticate. It does not run on any other site. |

The extension records only after you press **Record**, and sends audio only to the configured Apex Vox server.

## Self-hosting

To point the extension at your own domain:

1. Add `https://<your-host>/*` to both `host_permissions` and `content_scripts[0].matches` in `extension/manifest.json`.
2. Optionally change `CLOUD_URL` in `service-worker.js` and `recorder/recorder.js` so that new installs default to your server.
3. Bump `version`. `GET /api/box/extension/download` names the ZIP after the manifest version, and it publishes each version to object storage once.

## Publishing to the Chrome Web Store

The listing draft lives in [`CHROMEWEBSTORE.md`](../CHROMEWEBSTORE.md): name, descriptions, single purpose, permission justifications, privacy answers and version history.

1. Bump `version` in `extension/manifest.json` and add a row to the version history in `CHROMEWEBSTORE.md`.
2. Build the ZIP. `curl -o apex-box.zip https://<host>/api/box/extension.zip` packages exactly the `extension/` folder (it skips `.DS_Store`, `.map`, `.sh` and `__pycache__`). You can also zip the folder contents yourself.
3. In the [Chrome Web Store Developer Dashboard](https://chrome.google.com/webstore/devconsole), upload the ZIP, then fill in the listing and the **Privacy practices** tab from `CHROMEWEBSTORE.md`. Copy the permission justifications from the table above, including the content script.
4. Add screenshots at 1280×800 (planned under `docs/screenshots/`), the 128×128 icon (`extension/icons/icon-128.png`) and a privacy policy URL (`https://<host>/legal/privacidad`).
5. Submit for review. Store review of `tabCapture` and of content scripts tends to focus on whether the single purpose is clear and on the data disclosure.
