# ⚡ Apex Vox — Audio Studio · Potenciado por Groq | Apex Summa & Apex Box

<a href="https://groq.com" target="_blank" rel="noopener noreferrer">
  <img
    src="https://console.groq.com/powered-by-groq-light.svg"
    alt="Powered by Groq for fast inference."
  />
</a>

Plataforma integral de transcripción multi-audio, separación de voces, grabación ilimitada en bloques (10+ horas con RAM constante), analítica conversacional y generación de actas corporativas, contenedorizada en **Docker** con **FastAPI**, **FFmpeg**, **MEGA S4 (S3 Object Storage)**, **Supabase Cloud** y **Bold API**.

---

## 🌐 Ecosistema del Producto

| Parte del Producto | Nombre | Estado |
| :--- | :--- | :--- |
| **Transcripción (el núcleo)** | **Apex Vox** | ✅ **Producto listo** |
| **Notas, analítica y resúmenes IA** | **Apex Summa** | 🔥 **Activo en Plan Pro** |
| **Grabador ilimitado en bloques (Extensión Chrome MV3 + App Web Móvil)** | **Apex Box** | 🎙️ **Activo (10h+ RAM Constante · Presencial & Zoom/Meet/Teams)** |

---

## 🎙️ Apex Box — Grabación Ilimitada en Bloques (10+ Horas Sin Romper la RAM)

- **Cálculo Matemático de Bloques Óptimos (`180s` / 3 Minutos)**:
  - Códec `audio/webm;codecs=opus` a `48 kbps` (`~6 KB/s`) → **`~1.03 MB` por bloque de 3 minutos**.
  - Rotación continua de doble `MediaRecorder` sobre el mismo `MediaStream` (**0 ms de pérdida de voz** y cabecera EBML/WebM íntegra en cada bloque).
  - Liberación inmediata del arreglo en memoria (`blockChunks.length = 0`) tras enviar cada bloque (o encolar en `IndexedDB` si cae la red).
  - **10 horas continuas (`200 bloques`) consumen siempre `~1.05 MB` de RAM constante ($O(1)$)** frente a `~280 MB – 1.2 GB` de una grabación monolítica (**99.6% de ahorro de RAM**).
- **Dos Modos de Captura**:
  1. **Modo Reunión Presencial**: Sala de juntas, auditorio, clase o micrófono directo con filtro acústico vocal.
  2. **Modo Reunión Virtual (Zoom, Google Meet, Microsoft Teams, Webex)**: Mezcla en tiempo real el audio del sistema/pestaña + tu micrófono mediante `AudioContext` + `MediaStreamAudioDestinationNode`.
- **Notas en Vivo con Marca de Tiempo**: Permite tomar notas (`Nota`, `Acuerdo`, `Tarea`, `Alerta`, `Idea`, `Pregunta`) en cualquier instante de las 10+ horas y las integra automáticamente en **Apex Summa** y en el **Acta Oficial**.
- **Extensión Chrome (Manifest V3) & App Web Móvil (PWA)**:
  - Carpeta [`extension/`](extension/) lista para `chrome://extensions` o descarga directa desde `/api/box/extension.zip`.
  - Misma experiencia en celular (`?view=box` + `WakeLock API` + `/manifest.webmanifest`).

---

## 🏎️ Motores Serie Mc — Potenciado por Groq

Sin exponer modos ni proveedores subyacentes, el selector ofrece la línea de motores **Potenciado por Groq**:
- 🏆 **Mc-Ayrton** — *El Mejor (Máxima Precisión y Separación Acústica)*
- 🔥 **Mc-Lewis** — *Modo Híbrido (Equilibrio Ideal Velocidad + Acústica)*
- 🧬 **Mc-Norris** — *Huella Vocal y Reconocimiento de Timbre*
- ⚡ **Mc-Piastri** — *Velocidad Contextual Ultra-Rápida*

---

## 💳 Planes, Cuotas y Almacenamiento en MEGA S4

1. **Plan Gratis (Al Registrarse)**:
   - **2 horas gratis al día** (`7,200` segundos/día) distribuidas en **1 o varios audios al día**.
   - **Almacenamiento por 24 horas** en **MEGA S4** (`s4.mega.io`).
2. **Plan Apex Pro ($30.000 COP / $10 USD al mes)**:
   - **Prueba gratis de 3 días** con **cobro automático** mensual integrado con **Bold API** (firma de integridad `SHA-256` y webhooks).
   - **Transcripciones ilimitadas** y **almacenamiento ilimitado** en **MEGA S4** y **Supabase Cloud**.
   - Incluye el informe ejecutivo completo **Apex Summa**:
     1. 🏆 **Quién habló más** (tiempo exacto, porcentaje, conteo de palabras, turnos y palabras por minuto).
     2. 💬 **De qué se habló** (resumen ejecutivo y bloques temáticos ponderados).
     3. 🎯 **Objetivos** (metas y acuerdos clave identificados).
     4. 🚨 **Llamados de atención** (alertas, cuellos de botella y puntos críticos con marca de tiempo).
     5. 📅 **Próximas tareas en forma de calendario** (vista calendario + exportación `.ics` iCalendar).
     6. 📊 **Gráficas de la transcripción** (gráfica de dona por orador + barra de densidad en línea de tiempo).
     7. 📜 **Generador de Actas Oficiales** (*Acta de Reunión de Consejo / Junta Directiva*, *Acta de Comité Ejecutivo*, *Acta de Asamblea General*, *Acta de Seguimiento* y *Minuta Ejecutiva*, en Español e Inglés).

---

## 🚀 Inicio Rápido con Docker

```bash
cp .env.example .env
# Configura tus credenciales en .env (GROQ_API_KEY, MEGA_S4_*, SUPABASE_*, BOLD_*)
docker compose up -d --build
```

- **Landing, Playground y Portal de Usuario (ES / EN):** http://localhost:8000
- **Documentación OpenAPI (Swagger):** http://localhost:8000/docs
- **Healthcheck del contenedor:** http://localhost:8000/api/health
- **Esquema SQL para Supabase Cloud:** [`supabase/schema.sql`](supabase/schema.sql)

---

## 🎨 Design System — Groq Web

La interfaz usa el lenguaje visual **Groq Web** (referencia no oficial de groq.com; no incluye logo ni fuentes de Groq). El nombre del producto sigue siendo **Apex Vox**.

- **Tokens:** `app/static/css/tokens.css` — variables CSS con el nombre de cada token (`--bg`, `--brand`, `--orange`, `--space-3`, `--bdrs-l`, `--font-sans`…), tema claro por defecto y oscuro opcional con `<html data-theme="dark">`.
- **Componentes:** `app/static/css/styles.css` — NavBar, AnnouncementBanner, botones píldora con placa animada, TextField, Cards con líneas finas, tags cuadrados, motivo de píxeles y footer con `footer-display`.
- **Tipografía (sustitutos libres):** Outfit (titulares/UI), Share Tech Mono (labels en MAYÚSCULAS), IBM Plex Mono (texto de cuerpo), vía Google Fonts.
- **Reglas:** papel y tinta primero, naranja `#f43e01` como único color fuerte, sin emojis en la UI, foco visible de 2px en todo elemento interactivo y soporte de `prefers-reduced-motion`.

---

## 🔐 Cuentas, prueba gratis y pagos

- **Registro:** correo + contraseña (mínimo 8 caracteres, PBKDF2 con sal por usuario) o **Google / GitHub** vía Supabase Auth (flujo PKCE en el servidor). Los botones sociales aparecen solos cuando el proveedor está habilitado en Supabase.
- **Sesiones:** token `Bearer apx_...` con vencimiento (`SESSION_TTL_DAYS`). El `user_id` nunca se acepta como credencial.
- **Prueba gratis:** 3 días de Apex Pro, una sola vez por cuenta registrada, sin tarjeta.
- **Pagos:** API oficial de *Link de pagos* de Bold. Cada pago aprobado ($30.000 COP / $10 USD) da `PRO_PERIOD_DAYS` (30) días de Pro. No hay cobro recurrente automático: Bold cobra link por link.
- **Activación:** webhook firmado (`x-bold-signature`, HMAC-SHA256) en `/api/billing/bold/webhook` y, como respaldo, `/api/billing/confirm` consulta el estado del link al volver de Bold.
- **Apex Summa:** el servidor oculta el análisis Pro y bloquea actas/calendario (402) en el plan gratis.

---

## 🛡️ Producción

```bash
cp .env.example .env          # ENVIRONMENT=production por defecto
# Ajusta ALLOWED_HOSTS, CORS_ORIGINS y ENABLE_HSTS=true si sirves por HTTPS
docker compose up -d --build
```

- `ENVIRONMENT=production`: oculta `/docs`, `/redoc` y `/openapi.json` (forzar con `ENABLE_DOCS=true`) y responde errores 500 genéricos sin detalles internos.
- Cabeceras de seguridad en todas las respuestas: CSP, `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy` y HSTS opcional.
- GZip, caché de 7 días para assets versionados (`?v=APP_VERSION`), `robots.txt` y favicon.
- Uvicorn con `--proxy-headers` (listo para un reverse proxy con TLS) y **1 worker**: los trabajos de transcripción viven en memoria del proceso; escalar a varios workers requiere mover el estado de `job_manager` a un almacén compartido.
- Imagen sin dependencias de test; logs de Docker rotados (10 MB × 5) y `no-new-privileges`.

---

## 🧪 Ejecución de Pruebas Automatizadas

```bash
docker build -t apex-vox-test --build-arg INSTALL_DEV_DEPS=true .
docker run --rm apex-vox-test pytest -p no:cacheprovider -v
```
