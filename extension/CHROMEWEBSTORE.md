# Chrome Web Store Listing — Apex Box — Grabador de Reuniones

> Last Updated: 2026-11-02

## Store Listing

**Extension Name** [REQUIRED]
Apex Box — Grabador de Reuniones

**Short Description** [REQUIRED]
Graba reuniones presenciales o videollamadas en una pestaña fija y obtén transcripción, notas, resumen y acta en Apex Vox.

**Detailed Description** [REQUIRED]
Graba reuniones presenciales o videollamadas desde una pestaña fija del navegador y recibe automáticamente un enlace con la transcripción por hablantes, notas clave, resumen ejecutivo y acta formal en Apex Vox.

FUNCIONES PRINCIPALES
• Dos modos de grabación: Modo Presencial (captura el micrófono de tu equipo en salas de juntas) y Modo Virtual (captura el audio de la videollamada junto con tu micrófono).
• Pestaña de grabación fija y estable: La grabación permanece activa en una pestaña dedicada para evitar que se detenga por accidente al cambiar de ventana o hacer clic fuera.
• Envío continuo por bloques: Sube el audio cada 3 minutos de forma progresiva, permitiéndote grabar sesiones largas de varias horas sin agotar la memoria de tu computadora y con reintentos automáticos si tu conexión a internet parpadea.
• Monitor de sonido en tiempo real: Visualiza las ondas de audio y el nivel de cada fuente (reunión y micrófono). Si deja de entrar sonido durante más de 15 segundos o se desconecta el micrófono, el icono de la barra del navegador te avisa al instante.
• Plantillas de acta según tu reunión: Elige entre Ejecutiva, Consejo / Junta directiva, Comité, Asamblea o Seguimiento, y selecciona el modelo de reconocimiento de voz e identificación de hablantes que prefieras.

CÓMO USARLA
1. Inicia sesión con tu cuenta en https://apex-vox.ialabs.app.
2. Si vas a grabar una videollamada, abre la pestaña de la reunión y haz clic en el icono de Apex Box en la barra de Chrome para seleccionarla como fuente de audio.
3. En la pestaña fija de Apex Box, elige el tipo de reunión, escribe un título opcional y selecciona el modo Presencial o Virtual.
4. Pulsa "Grabar". El icono mostrará el tiempo transcurrido y el estado del sonido en vivo.
5. Al terminar la reunión, pulsa "Detener" y obtendrás al instante el enlace directo a tu transcripción, resumen y acta lista para revisar o compartir.

PRIVACIDAD Y SEGURIDAD
Apex Box únicamente graba audio cuando tú inicias explícitamente una grabación pulsando el botón "Grabar". El audio se envía de forma cifrada (HTTPS) a tu cuenta de Apex Vox (https://apex-vox.ialabs.app) exclusivamente para generar tu transcripción, resumen y acta. No recopilamos historial de navegación, no ejecutamos rastreadores publicitarios ni vendemos tus datos a terceros.

SOPORTE
¿Tienes dudas o necesitas ayuda? Visita https://apex-vox.ialabs.app o escríbenos al correo de soporte indicado en esta ficha.

Versión 3.2.0 — Monitor de nivel de audio con aviso visual de silencio en el icono, sincronización automática de sesión con Apex Vox y soporte para plantillas de actas ejecutivas, de comité y de consejo.

**Category** [REQUIRED]
Productivity

**Single Purpose** [REQUIRED]
Grabar el audio de reuniones presenciales o videollamadas iniciadas por el usuario y enviarlo a su cuenta de Apex Vox para generar la transcripción, el resumen y el acta de la reunión.

**Primary Language** [REQUIRED]
Español (Spanish)

---

## Graphics & Assets

| Asset | Dimensions | Status | Filename |
|-------|-----------|--------|----------|
| Store Icon [REQUIRED] | 128×128 PNG | ✅ Ready | `doc/assets/store-icon-128x128.png` |
| Screenshot 1 [REQUIRED] | 1280×800 PNG | ✅ Ready | `doc/assets/screenshot-1-grabador-1280x800.png` |
| Screenshot 2 [RECOMMENDED] | 1280×800 PNG | ✅ Ready | `doc/assets/screenshot-2-resultado-acta-1280x800.png` |
| Small Promo Tile [RECOMMENDED] | 440×280 PNG | ✅ Ready | `doc/assets/small-promo-tile-440x280.png` |

### Screenshot Notes
- **Screenshot 1 (`screenshot-1-grabador-1280x800.png`)**: Muestra la interfaz del grabador en pestaña fija durante una sesión activa (`00:18:42`), con el monitor de ondas de sonido en vivo, barras de nivel para Reunión y Micrófono, selector de tipo de reunión y estadísticas de bloques/hablantes.
- **Screenshot 2 (`screenshot-2-resultado-acta-1280x800.png`)**: Muestra la tarjeta de finalización ("Reunión lista") con el botón directo para abrir las notas, resumen y acta generadas en Apex Vox y copiar el enlace.

---

## Permissions Justification

> Copia y pega estas justificaciones directamente en la pestaña **Privacy practices (Prácticas de privacidad)** del Chrome Web Store Developer Dashboard.

| Permission | Type | Justification (Español — y versión en Inglés debajo) |
|------------|------|------------------------------------------------------|
| `storage` | `permissions` | **ES:** Se utiliza para guardar localmente en el navegador las preferencias de grabación del usuario (último tipo de reunión, modo presencial/virtual y modelo seleccionado), sincronizar el token de sesión activa de su cuenta de Apex Vox y mantener el bloqueo de estado de grabación activa entre el icono de la extensión y la pestaña del grabador.<br>**EN:** Used to store the user's recording preferences locally (meeting type, recording mode, and selected model), sync the active session token from their Apex Vox account, and maintain the recording state lock between the toolbar action icon and the pinned recorder tab. |
| `tabs` | `permissions` | **ES:** Necesario para abrir o enfocar la pestaña fija única del grabador cuando el usuario hace clic en el icono de la extensión, e identificar el ID y título de la pestaña de videollamada donde el usuario invocó la extensión para asignarla como fuente de audio en el modo virtual.<br>**EN:** Required to open or focus the single pinned recorder tab when the user clicks the extension icon, and to identify the tab ID, URL, and title of the meeting tab where the user invoked the extension so it can be selected as the audio source in virtual meeting mode. |
| `tabCapture` | `permissions` | **ES:** Necesario para capturar el flujo de audio de la pestaña de videollamada seleccionada por el usuario cuando elige el modo de grabación "Virtual" y pulsa explícitamente el botón "Grabar".<br>**EN:** Required to capture the audio stream of the virtual meeting tab selected by the user when they choose "Virtual" recording mode and explicitly click the "Record" button. |
| `https://apex-vox.ialabs.app/*` | `host_permissions` | **ES:** Necesario exclusivamente para comunicarse con el servidor oficial de la plataforma Apex Vox (`https://apex-vox.ialabs.app`), permitiendo verificar la sesión activa del usuario, subir los bloques de audio grabados y solicitar la generación del acta y transcripción.<br>**EN:** Required exclusively to communicate with the official Apex Vox backend (`https://apex-vox.ialabs.app`) to verify the user's active session, upload recorded audio blocks, and finalize the meeting transcription and minutes. |

---

## Privacy & Data Use

### Data Collection

**Does the extension collect user data?** Yes (Solo para usuarios autenticados que inician una grabación en su cuenta de Apex Vox).

| Data Type | Collected? | Transmitted Off-Device? | Purpose | Shared with Third Parties? |
|-----------|-----------|------------------------|---------|---------------------------|
| Personally identifiable info | No (solo se consulta el email de la sesión activa desde el servidor propio) | No | Mostrar al usuario qué cuenta de Apex Vox tiene conectada | No |
| Health info | No | No | N/A | No |
| Financial info | No | No | N/A | No |
| Authentication info | **Yes** (` ☑ Authentication information `) | **Yes** (`https://apex-vox.ialabs.app`) | Sincronizar el token de sesión de `apex-vox.ialabs.app` para autenticar la subida de grabaciones a la cuenta del usuario | No |
| Personal communications | **Yes** (` ☑ Personal communications `) | **Yes** (`https://apex-vox.ialabs.app`) | Transmitir los bloques de audio de la reunión que el usuario decide grabar para generar su transcripción, resumen y acta en Apex Vox | No |
| Location | No | No | N/A | No |
| Web history | No | No | N/A | No |
| User activity | No | No | N/A | No |
| Website content | No | No | N/A | No |

### Data Use Certification
En el panel de Chrome Web Store debes marcar las **3 casillas obligatorias de certificación**:
- [x] Data is NOT sold to third parties (No vendo ni transfiero datos de usuarios a terceros fuera de los casos de uso aprobados)
- [x] Data is NOT used for purposes unrelated to the extension's core functionality (No uso ni transfiero datos de usuarios para fines no relacionados con el propósito único de la extensión)
- [x] Data is NOT used for creditworthiness or lending purposes (No uso ni transfiero datos de usuarios para determinar solvencia crediticia ni fines de préstamos)

---

## Privacy Policy

**Privacy Policy URL** [REQUIRED]
`https://apex-vox.ialabs.app/privacy` (Plantilla lista para publicar incluida en `doc/PRIVACY_POLICY.md` y `doc/PRIVACY_POLICY.html`).

---

## Distribution

- **Visibility**: Public (o Unlisted si deseas compartirla primero solo por enlace)
- **Regions**: All regions (Todas las regiones)

## Developer Info

- **Publisher Name**: IALabs / Apex Vox
- **Homepage URL**: `https://apex-vox.ialabs.app`
- **Support URL**: `https://apex-vox.ialabs.app`

---

## Version History

| Version | Date | Changes | Status |
|---------|------|---------|--------|
| 3.2.0 | 2026-11-02 | Versión de producción adaptada para Chrome Web Store (Manifest V3, permisos estrictos de producción, bloqueo de estado en `chrome.storage.session`, recursos gráficos 100% locales sin peticiones a terceros al iniciar). | Ready to Submit |
