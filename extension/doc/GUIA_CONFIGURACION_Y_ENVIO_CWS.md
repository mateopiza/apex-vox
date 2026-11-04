# Guía Completa de Configuración, Cumplimiento y Envío a Google Chrome Web Store

Esta guía documenta la estructura reorganizada de `extension`, las adaptaciones técnicas aplicadas para cumplir las políticas de **Google Chrome Web Store (Manifest V3)** y todos los textos/configuraciones listos para copiar y pegar en el **Chrome Web Store Developer Dashboard**.

---

## 1. Estructura Organizada de la Carpeta `extension/`

```text
extension/
├── CHROMEWEBSTORE.md                         # Fuente única de verdad para la ficha de Chrome Web Store
├── manifest.json                             # Manifest V3 de desarrollo (incluye localhost:8000 para pruebas)
├── service-worker.js                         # Service Worker MV3 (sin estado global, async/await puro)
├── content/
│   └── session-bridge.js                     # Puente de sesión con validación de contexto de extensión
├── icons/
│   ├── icon-16.png                           # 16×16 px PNG
│   ├── icon-32.png                           # 32×32 px PNG
│   ├── icon-48.png                           # 48×48 px PNG
│   └── icon-128.png                          # 128×128 px PNG
├── recorder/
│   ├── recorder.html                         # Interfaz de grabación en pestaña fija
│   ├── recorder.css                          # Estilos de la interfaz
│   ├── recorder.js                           # Lógica de captura, AudioWorklet y subida por bloques
│   ├── level-meter.js                        # Procesador AudioWorklet en tiempo real
│   └── powered-by-groq-light.svg             # Insignia SVG empaquetada localmente (cero peticiones externas)
├── scripts/
│   └── package-extension.sh                  # Script automatizado que genera el ZIP limpio para Chrome Web Store
```

---

## 2. Adaptaciones Críticas Realizadas para Aprobar la Revisión de Google

Google Chrome Web Store rechaza extensiones automáticamente o en revisión manual cuando detecta permisos de desarrollo, cargas de recursos remotos no declarados, uso de marcas registradas en la descripción corta o problemas de concurrencia en `tabCapture`. El paquete que genera el script aplica estas correcciones:

1. **Eliminación de permisos de desarrollo (`localhost` y `127.0.0.1`)**:
   - El script de empaquetado deja en el `manifest.json` del ZIP, en `host_permissions` y `content_scripts.matches`, **únicamente** `"https://apex-vox.ialabs.app/*"`. Dejar `http://localhost:8000/*` o `http://127.0.0.1:8000/*` provoca rechazo por la política de *Minimum Permissions* de Chrome Web Store.
2. **Eliminación del selector de servidor arbitrario en producción**:
   - Sin permiso de localhost, `recorder.js` oculta el campo editable de URL de servidor y muestra el indicador fijo `Conectado a apex-vox.ialabs.app`, garantizando que la extensión de producción solo se comunique con el dominio declarado en `host_permissions`.
3. **Empaquetado local de activos gráficos (`powered-by-groq-light.svg`)**:
   - Antes, `recorder.html` cargaba `https://console.groq.com/powered-by-groq-light.svg` desde un servidor externo al abrir la extensión. Ahora se sirve localmente desde `recorder/powered-by-groq-light.svg`, eliminando peticiones de red a terceros no declaradas.
4. **Descripción corta sin infracción de marcas registradas (`Trademark Policy`)**:
   - Se ajustó `description` en `manifest.json` a 122 caracteres (límite máximo: 132) evitando listar marcas registradas de terceros en el campo corto del manifiesto:
     `"Graba reuniones presenciales o videollamadas en una pestaña fija y obtén transcripción, notas, resumen y acta en Apex Vox."`
5. **Iconos completos en las 4 resoluciones estándar (`16`, `32`, `48`, `128`)**:
   - Se añadió `icons/icon-32.png` (32×32 px reales) junto a `16×16`, `48×48` y `128×128` tanto en `icons` como en `action.default_icon`.
6. **Bloqueo de estado en `chrome.storage.session` para `tabCapture`**:
   - Se implementó la máquina de estados (`idle` → `starting` → `recording` → `stopping` → `idle`) en `chrome.storage.session` para impedir el error `"Cannot capture a tab with an active stream"` ante dobles clics rápidos y limpiar el estado si se cierra la pestaña.
7. **Código 100% `async/await` y sin `innerHTML`**:
   - Se reemplazaron las cadenas `.catch()` / `.finally()` por bloques `try / catch / finally` con `async/await`, se protegió `session-bridge.js` ante invalidación de contexto (`chrome.runtime?.id`) y se reemplazó `row.innerHTML` por creación segura de nodos DOM (`document.createElement`).

---

## 3. Archivo `manifest.json` del paquete (lo genera el script a partir de `extension/manifest.json`)

```json
{
  "manifest_version": 3,
  "name": "Apex Box — Grabador de Reuniones",
  "short_name": "Apex Box",
  "version": "3.2.0",
  "description": "Graba reuniones presenciales o videollamadas en una pestaña fija y obtén transcripción, notas, resumen y acta en Apex Vox.",
  "homepage_url": "https://apex-vox.ialabs.app",
  "minimum_chrome_version": "116",
  "icons": {
    "16": "icons/icon-16.png",
    "32": "icons/icon-32.png",
    "48": "icons/icon-48.png",
    "128": "icons/icon-128.png"
  },
  "action": {
    "default_title": "Apex Box · Abrir grabador",
    "default_icon": {
      "16": "icons/icon-16.png",
      "32": "icons/icon-32.png",
      "48": "icons/icon-48.png",
      "128": "icons/icon-128.png"
    }
  },
  "background": {
    "service_worker": "service-worker.js"
  },
  "permissions": [
    "storage",
    "tabs",
    "tabCapture"
  ],
  "host_permissions": [
    "https://apex-vox.ialabs.app/*"
  ],
  "content_scripts": [
    {
      "matches": [
        "https://apex-vox.ialabs.app/*"
      ],
      "js": [
        "content/session-bridge.js"
      ],
      "run_at": "document_idle"
    }
  ]
}
```

---

## 4. Paso a Paso para Subir la Extensión al Chrome Web Store Developer Console

### Paso 1: Subir el paquete ZIP
1. Ingresa a [Chrome Web Store Developer Dashboard](https://chrome.google.com/webstore/devconsole).
2. Haz clic en **New Item (Nuevo elemento)**.
3. Sube el archivo generado:
   `dist/apex-box-v<versión>-chrome-webstore.zip`
   *(Se genera con `extension/scripts/package-extension.sh`; vuelve a ejecutarlo tras cualquier cambio).*

---

### Paso 2: Pestaña "Store Listing" (Ficha de la tienda)

- **Title (Nombre)**: Se autocompleta desde `manifest.json` (`Apex Box — Grabador de Reuniones`).
- **Summary (Resumen)**: Se autocompleta desde `manifest.json` (`Graba reuniones presenciales o videollamadas en una pestaña fija y obtén transcripción, notas, resumen y acta en Apex Vox.`).
- **Description (Descripción detallada)**: Copia y pega el bloque de `Detailed Description` de `CHROMEWEBSTORE.md`, en la raíz del repositorio.
- **Category (Categoría)**: `Productivity` (Productividad).
- **Language (Idioma)**: `Español` (Spanish).
- **Store Icon (Icono de tienda 128×128)**: Sube `doc/assets/store-icon-128x128.png`.
- **Screenshots (Capturas de pantalla 1280×800)**:
  1. Sube `doc/assets/screenshot-1-grabador-1280x800.png`
  2. Sube `doc/assets/screenshot-2-resultado-acta-1280x800.png`
- **Small Promo Tile (Mosaico promocional pequeño 440×280)**:
  - Sube `doc/assets/small-promo-tile-440x280.png`
- **Official URL / Homepage URL**: `https://apex-vox.ialabs.app`
- **Support URL**: `https://apex-vox.ialabs.app`

---

### Paso 3: Pestaña "Privacy Practices" (Prácticas de privacidad)

Esta es la pestaña más revisada por el equipo de Google. Rellena cada campo exactamente así:

#### A. Single Purpose Description (Propósito único)
```text
Grabar el audio de reuniones presenciales o videollamadas iniciadas por el usuario y enviarlo a su cuenta de Apex Vox para generar la transcripción, el resumen y el acta de la reunión.
```

#### B. Permission Justifications (Justificación de cada permiso)

- **`storage` justification**:
  ```text
  Se utiliza para guardar localmente en el navegador las preferencias de grabación del usuario (último tipo de reunión, modo presencial/virtual y modelo seleccionado), sincronizar el token de sesión activa de su cuenta de Apex Vox y mantener el bloqueo de estado de grabación activa entre el icono de la extensión y la pestaña del grabador.
  ```
- **`tabs` justification**:
  ```text
  Necesario para abrir o enfocar la pestaña fija única del grabador cuando el usuario hace clic en el icono de la extensión, e identificar el ID, URL y título de la pestaña de videollamada donde el usuario invocó la extensión para asignarla como fuente de audio en el modo virtual.
  ```
- **`tabCapture` justification**:
  ```text
  Necesario para capturar el flujo de audio de la pestaña de videollamada seleccionada por el usuario cuando elige el modo de grabación "Virtual" y pulsa explícitamente el botón "Grabar".
  ```
- **`Host permission (https://apex-vox.ialabs.app/*)` justification**:
  ```text
  Necesario exclusivamente para comunicarse con el servidor oficial de la plataforma Apex Vox (https://apex-vox.ialabs.app), permitiendo sincronizar y verificar la sesión activa del usuario, subir los bloques de audio grabados y solicitar la generación de la transcripción, resumen y acta.
  ```
- **Are you using remote code? (¿Usas código remoto?)**:
  Selecciona **No, I am not using Remote code** (Todo el código JavaScript y recursos están incluidos dentro del paquete de la extensión).

#### C. Data Usage Disclosure (Declaración de uso de datos)
Marca **únicamente** estas dos casillas (que corresponden exactamente con lo que hace el código y lo que declara la Política de Privacidad):
- [x] **Authentication information** (por la sincronización del token de sesión de `apex-vox.ialabs.app`)
- [x] **Personal communications** (por el audio de la reunión que el usuario graba y envía a `apex-vox.ialabs.app`)

*(Deja desmarcadas: Personally identifiable information, Health information, Financial and payment information, Location, Web history, User activity, Website content).*

Y marca las **3 casillas de certificación obligatorias**:
- [x] *I do not sell or transfer user data to third parties, outside of the approved use cases.*
- [x] *I do not use or transfer user data for purposes that are unrelated to my item's single purpose.*
- [x] *I do not use or transfer user data to determine creditworthiness or for lending purposes.*

#### D. Privacy Policy URL (URL de la Política de Privacidad)
- Publica el archivo `doc/PRIVACY_POLICY.html` en tu servidor bajo `https://apex-vox.ialabs.app/privacy` (o en GitHub Pages) y coloca esa URL pública en el campo **Privacy policy URL**.

---

### Paso 4: Verificación Local con Chrome y Chrome DevTools antes de Enviar

1. Abre `chrome://extensions` en Google Chrome.
2. Activa el **Modo de desarrollador (Developer mode)** en la esquina superior derecha.
3. Haz clic en **Cargar descomprimida (Load unpacked)** y selecciona la carpeta donde descomprimiste el ZIP de `dist/`.
4. Verifica en la tarjeta de la extensión:
   - Que no aparezca ningún botón de **Errores (Errors)**.
   - Haz clic en el enlace **Inspeccionar vistas: service worker** para abrir Chrome DevTools sobre el Service Worker y comprobar que la consola está limpia.
   - Haz clic en el icono de **Apex Box** en la barra de herramientas: se abrirá la pestaña fija `recorder/recorder.html` sin errores de CSP ni peticiones externas bloqueadas en la pestaña **Network** de DevTools.
