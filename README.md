# ⚡ Apex Vox — Audio Studio · Potenciado por Groq | Apex Summa & Apex Box

Plataforma integral de transcripción multi-audio, separación de voces, analítica conversacional y generación de actas corporativas, contenedorizada en **Docker** con **FastAPI**, **FFmpeg**, **MEGA S4 (S3 Object Storage)**, **Supabase Cloud** y **Bold API**.

---

## 🌐 Ecosistema del Producto

| Parte del Producto | Nombre | Estado |
| :--- | :--- | :--- |
| **Transcripción (el núcleo)** | **Apex Vox** | ✅ **Producto listo** |
| **Notas, analítica y resúmenes IA** | **Apex Summa** | 🔥 **Activo en Plan Pro** |
| **Bot de reuniones / llamadas / estático de grabación** | **Apex Box** | ⏳ **Próximamente** |

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
