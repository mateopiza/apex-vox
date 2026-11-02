# Chrome Web Store Listing — Apex Box — Grabador de Reuniones

> Last Updated: 2026-11-02

## Store Listing

**Extension Name** [REQUIRED]
Apex Box — Grabador de Reuniones

**Short Description** [REQUIRED]
Graba reuniones presenciales o virtuales (Zoom, Meet, Teams) desde una pestaña fija y recibe un enlace con notas, resumen y acta.

**Detailed Description** [REQUIRED]
Graba reuniones presenciales y llamadas virtuales durante horas desde una pestaña fija del navegador y, al terminar, recibe un enlace con la transcripción por oradores, las notas, el resumen ejecutivo y el acta.

Funciones principales:
Grabación por bloques de 3 minutos que se envían y liberan de la memoria, para sesiones de 10 horas o más.
Modo Presencial (micrófono del equipo) y modo Virtual (audio de la pestaña de Google Meet, Zoom, Microsoft Teams o Webex + tu micrófono).
Indicador en el icono de la extensión: REC y tiempo transcurrido mientras se graba; "MUDO" en ámbar si no entra sonido.
Ondas de sonido en vivo y nivel por fuente (micrófono y reunión) para confirmar que se está captando audio; aviso si pasan 15 s sin sonido o si la fuente se desconecta.
Estadísticas en vivo: tiempo, bloques enviados, segmentos transcritos y hablantes detectados.
Al finalizar, un enlace con el informe Apex Summa y el acta según el tipo de reunión (Ejecutiva, Consejo, Comité, Asamblea o Seguimiento).

Cómo usarlo:
1. Haz clic en el icono de Apex Box (en una reunión virtual, hazlo desde la pestaña de la reunión). Se abre una pestaña fija del grabador.
2. Elige tipo de reunión, título, tipo de grabación (Presencial o Virtual) y modelo.
3. Pulsa Grabar. El icono muestra REC y el tiempo.
4. Pulsa Detener: recibes el enlace con notas, resumen y acta.

Privacidad y seguridad:
El audio y las notas solo se capturan cuando inicias explícitamente una grabación y se envían únicamente a tu servidor configurado de Apex Vox.

Soporte y contacto:
Para soporte técnico o consultas escribe a soporte@apexvox.ai.

**Category** [REQUIRED]
Productivity

**Single Purpose** [REQUIRED]
Records in-person and virtual meetings in continuous blocks to generate speaker-diarized transcripts, timestamped live notes, and formal meeting minutes without exhausting browser memory.

**Primary Language** [REQUIRED]
Spanish (Español) / English

## Graphics & Assets

| Asset | Dimensions | Status | Filename |
|-------|-----------|--------|----------|
| Store Icon [REQUIRED] | 128×128 PNG | ✅ Ready | `extension/icons/icon-128.png` |
| Screenshot 1 [REQUIRED] | 1280×800 | 🟡 Needs update | `docs/screenshots/recorder-tab.png` |
| Screenshot 2 [RECOMMENDED] | 1280×800 | 🟡 Needs update | `docs/screenshots/result-link.png` |
| Small Promo Tile [RECOMMENDED] | 440×280 | ⬜ Not created | |

### Screenshot Notes
- Screenshot 1: Pinned recorder tab while recording (REC badge with elapsed time, live stats).
- Screenshot 2: Final result link opening notes, Apex Summa report and minutes in the web app.

## Permissions Justification

| Permission | Type | Justification |
|------------|------|---------------|
| `storage` | permissions | Stores user preferences (server URL, last meeting type, recording mode and model). |
| `tabs` | permissions | Finds and focuses the pinned recorder tab and reads the meeting tab URL to detect Google Meet, Zoom, Microsoft Teams or Webex. |
| `tabCapture` | permissions | Captures the audio of the meeting tab (where the user clicked the extension icon) in Virtual mode so remote participants can be transcribed. No offscreen document is used: recording runs in the extension's own pinned tab. |
| `https://apex-vox.ialabs.app/*` | host_permissions | Uploads recorded 3-minute audio blocks to the Apex Vox cloud service and finalizes the session (default server). |
| `http://localhost:8000/*`, `http://127.0.0.1:8000/*` | host_permissions | Optional self-hosted/local Apex Vox server, selectable under "Servidor". |

## Privacy & Data Use

### Data Collection

**Does the extension collect user data?** Yes

| Data Type | Collected? | Transmitted Off-Device? | Purpose | Shared with Third Parties? |
|-----------|-----------|------------------------|---------|---------------------------|
| Personally identifiable info | No | No | N/A | No |
| Health info | No | No | N/A | No |
| Financial info | No | No | N/A | No |
| Authentication info | No | No | N/A | No |
| Personal communications | Yes | Yes (to user's Apex Vox server) | Audio blocks and meeting notes explicitly recorded by the user for transcription and meeting minutes generation | No |
| Location | No | No | N/A | No |
| Web history | No | No | N/A | No |
| User activity | No | No | N/A | No |
| Website content | No | No | N/A | No |

### Data Use Certification
- [x] Data is NOT sold to third parties
- [x] Data is NOT used for purposes unrelated to the extension's core functionality
- [x] Data is NOT used for creditworthiness or lending purposes

## Privacy Policy

**Privacy Policy URL** [REQUIRED]
https://apexvox.ai/privacy

## Distribution

**Visibility**: Public
**Regions**: All regions

## Developer Info

**Publisher Name** [REQUIRED]
Apex Vox Audio Studio

**Contact Email** [REQUIRED]
soporte@apexvox.ai

**Support URL / Email** [RECOMMENDED]
mailto:soporte@apexvox.ai

**Homepage URL** [RECOMMENDED]
https://apex-vox.ialabs.app

## Version History

| Version | Date | Changes | Status |
|---------|------|---------|--------|
| 3.1.0 | 2026-11-02 | Connects to the cloud service (https://apex-vox.ialabs.app) by default; live sound waves and no-sound warning ("MUDO" badge). | Draft |
| 3.0.0 | 2026-11-02 | Simplified: recording moves to a pinned extension tab (no side panel/offscreen/content scripts); four fields (meeting type, title, recording type, model), REC + time badge, final results link. | Draft |
| 2.0.0 | 2026-11-02 | Initial release of Apex Box MV3 extension with 3-minute zero-RAM block rotation (10h+ continuous recording), Presencial & Virtual meeting modes (Meet, Zoom, Teams, Webex), live timestamped notes, and Apex Summa integration. | Draft |
