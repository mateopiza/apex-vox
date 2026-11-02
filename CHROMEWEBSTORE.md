# Chrome Web Store Listing — Apex Box — Grabador Ilimitado por Bloques y Notas IA

> Last Updated: 2026-11-02

## Store Listing

**Extension Name** [REQUIRED]
Apex Box — Grabador Ilimitado por Bloques y Notas IA

**Short Description** [REQUIRED]
Graba reuniones presenciales y virtuales (Zoom, Meet, Teams) por bloques sin llenar RAM, con transcripción continua y notas.

**Detailed Description** [REQUIRED]
Graba reuniones presenciales y llamadas virtuales durante horas sin interrupciones ni consumo excesivo de memoria, mientras obtienes transcripciones continuas con identificación de oradores y tomas notas con marca de tiempo en vivo.

Funciones principales:
Grabación ilimitada por bloques de 3 minutos que libera la memoria automáticamente después de enviar cada fragmento, permitiendo sesiones continuas de 10 horas o más sin saturar tu navegador.
Modo Reunión Presencial para salas de juntas, conferencias, clases o entrevistas con captura de voz optimizada.
Modo Reunión Virtual compatible con Google Meet, Zoom, Microsoft Teams y Cisco Webex que captura tanto a los participantes remotos como tu propia voz.
Toma de notas en vivo con etiquetas rápidas (Nota, Acuerdo, Tarea, Alerta, Idea) selladas con el minuto y segundo exacto de la sesión.
Generación automática del informe ejecutivo Apex Summa (quién habló más, temas principales, objetivos, alertas, calendario de tareas exportable a iCalendar y actas oficiales de Consejo, Comité o Asamblea).

Cómo usarlo:
1. Haz clic en el icono de Apex Box en la barra del navegador (o presiona Ctrl+Shift+Y) para abrir el panel lateral.
2. Elige entre Reunión Presencial o Reunión Virtual (se activa automáticamente cuando entras a Google Meet, Zoom, Microsoft Teams o Webex).
3. Presiona Iniciar Grabación Ilimitada por Bloques; cada bloque de 3 minutos se envía y transcribe automáticamente mientras sigues hablando.
4. Escribe tus notas, acuerdos o tareas en cualquier momento sin detener la grabación.
5. Al terminar, presiona Finalizar y Generar Acta IA para obtener la transcripción unificada y tu acta corporativa lista para descargar o imprimir.

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
| Screenshot 1 [REQUIRED] | 1280×800 | 🟡 Needs update | `docs/screenshots/sidepanel-recording.png` |
| Screenshot 2 [RECOMMENDED] | 1280×800 | 🟡 Needs update | `docs/screenshots/virtual-meeting-notes.png` |
| Small Promo Tile [RECOMMENDED] | 440×280 | ⬜ Not created | |

### Screenshot Notes
- Screenshot 1: Side panel open alongside a Google Meet / Zoom call showing the 10-hour constant RAM meter (~1.03 MB), live block progress, and live rolling transcript.
- Screenshot 2: Taking timestamped notes (`[02:14:30] Acuerdo`) and generating a Board of Directors Minutes document with Apex Summa.

## Permissions Justification

| Permission | Type | Justification |
|------------|------|---------------|
| `sidePanel` | permissions | Displays the persistent recording controls, live block transcript, and note-taking interface alongside online meetings without closing when clicking the page. |
| `storage` | permissions | Stores user preferences (server URL, preferred block duration, language) and current recording session status across service worker restarts. |
| `tabs` | permissions | Detects when the active tab is an online meeting (Google Meet, Zoom, Microsoft Teams, Webex) and provides the required target tab reference when choosing a window/tab to capture. |
| `tabCapture` | permissions | Captures the audio output of the active meeting tab in Virtual Meeting mode so remote participants can be transcribed. |
| `desktopCapture` | permissions | Allows the user to select a specific application window or screen with audio when recording external Zoom, Teams, or Webex desktop calls. |
| `offscreen` | permissions | Runs the audio recorder and microphone/tab mixer continuously in the background while rotating 3-minute audio blocks and freeing memory. |
| `alarms` | permissions | Maintains the recording status badge indicator during multi-hour recording sessions. |
| `notifications` | permissions | Confirms to the user when a highlighted text selection is saved as a timestamped meeting note via the context menu. |
| `contextMenus` | permissions | Adds right-click menu options to open the Apex Box side panel or save selected text directly as a timestamped meeting note. |
| `http://localhost:8000/*`, `http://127.0.0.1:8000/*` | host_permissions | Uploads recorded 3-minute audio blocks and live timestamped notes to the user's Apex Vox transcription server. |
| `https://meet.google.com/*`, `https://*.zoom.us/*`, `https://teams.microsoft.com/*`, `https://teams.live.com/*`, `https://*.webex.com/*` | host_permissions | Displays the in-meeting quick note bar and detects active virtual meeting sessions on supported video conferencing platforms. |

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
| Website content | Yes | Yes (to user's Apex Vox server) | Only text explicitly highlighted by the user when clicking "Save selection as note" | No |

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
http://localhost:8000

## Version History

| Version | Date | Changes | Status |
|---------|------|---------|--------|
| 2.0.0 | 2026-11-02 | Initial release of Apex Box MV3 extension with 3-minute zero-RAM block rotation (10h+ continuous recording), Presencial & Virtual meeting modes (Meet, Zoom, Teams, Webex), live timestamped notes, and Apex Summa integration. | Draft |
