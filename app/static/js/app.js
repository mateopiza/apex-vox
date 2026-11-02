/**
 * Apex Vox, Apex Summa & Apex Box — Frontend Application Controller
 * Potenciado por Groq · Pagos Bold API
 *
 * Manages:
 * - Bilingual UI (Español / English)
 * - Landing Page, User Portal & Playground navigation
 * - User Registration (2h free/day + 24h retention) & Apex Pro via Bold (USD 10 / 30 days, manual renewal; 20% off within 24 h)
 * - Multi-audio upload, drag-and-drop sequence ordering, and Mc-Series engines (Mc-Ayrton, Mc-Lewis, Mc-Norris, Mc-Piastri)
 * - Apex Summa 7-Part Post-Transcription Intelligence Suite (Who spoke most, Topics, Objectives, Callouts, Calendar, Charts, Minutes)
 */

(function () {
  "use strict";

  function detectInitialLanguage() {
    const fromServer = document.documentElement.getAttribute("data-default-lang");
    if (fromServer === "es" || fromServer === "en") return fromServer;
    const prefs = navigator.languages && navigator.languages.length ? navigator.languages : [navigator.language || "en"];
    for (const tag of prefs) {
      const base = String(tag || "").toLowerCase().split("-")[0];
      if (base === "es" || base === "en") return base;
    }
    return "en";
  }

  const QUERY_LANG = ["es", "en"].find((l) => l === new URLSearchParams(location.search).get("lang")) || null;

  const state = {
    lang: QUERY_LANG || localStorage.getItem("apex_vox_lang_choice") || detectInitialLanguage(),
    activeView: "playground",
    user: JSON.parse(localStorage.getItem("apex_vox_user") || "null"),
    token: localStorage.getItem("apex_vox_token") || null,
    plan: "free",
    config: { oauth_providers: [], pro_period_days: 30, pro_price_usd: 10, promo_discount_pct: 20, promo_window_hours: 24, promo_ip_cooldown_days: 90, guest_max_audios: 3, guest_max_minutes: 30, guest_audios_remaining: 3, newsletter_enabled: true },
    sessionId: null,
    files: [],
    voiceProfiles: [],
    currentJobId: null,
    currentResult: null,
    currentMinutes: null,
    selectedSpeaker: "ALL",
    searchQuery: "",
    dragSrcIndex: null,
    pollTimer: null,
  };

  // ---------------------------------------------------------------------------
  // Bilingual Dictionary (ES / EN)
  // ---------------------------------------------------------------------------
  const I18N = {
    es: {
      android_step1: "Abre esta página en <strong>Chrome</strong>.",
      android_step2: "Toca el menú <strong>⋮</strong>.",
      android_step3: "Elige <strong>Instalar app</strong> o <strong>Agregar a pantalla de inicio</strong>.",
      app_card_desc: "Ábrelo como una app desde tu pantalla de inicio y graba tus reuniones presenciales.",
      app_card_title: "Instala Apex Vox en tu celular",
      app_install_btn: "Instalar app",
      app_installed: "Ya estás usando la app instalada.",
      box_blocks_log_empty: "Aún no has grabado.",
      box_btn_add_note: "+ Anotar",
      box_btn_cut_block: "Enviar bloque ahora",
      box_btn_download_ext: "Descargar extensión (.zip)",
      box_btn_open_summa: "Ver resumen completo",
      box_btn_start: "● Grabar",
      box_btn_stop_finalize: "■ Detener y crear resumen",
      box_empty_live_desc: "Pulsa <strong>Grabar</strong> y la transcripción aparecerá cada 3 minutos.",
      box_empty_live_title: "Aquí verás lo que se dice",
      box_ext_card_desc: "Graba desde una pestaña fija de Chrome, también tus llamadas de Zoom, Meet o Teams. Al terminar recibes un enlace con notas, resumen y acta.",
      box_ext_card_title: "Extensión de Chrome",
      box_kpi_blocks: "Bloques enviados",
      box_kpi_segments: "Frases transcritas",
      box_lbl_elapsed: "TIEMPO GRABADO",
      box_lbl_engine: "Modelo",
      box_lbl_note_speaker: "Quién (opcional)",
      box_lbl_note_text: "Nota",
      box_lbl_platform: "Plataforma",
      box_lbl_title: "Título de la reunión",
      box_lead_desc: "Graba tu reunión el tiempo que necesites. Se guarda en <strong>bloques de 3 minutos</strong> y la transcripción aparece mientras hablas.",
      box_live_feed_title: "Transcripción en vivo",
      box_main_title: "Grabar una reunión",
      box_mode_pres_desc: "Usa el micrófono de este equipo o de tu celular.",
      box_mode_pres_title: "Presencial",
      box_mode_virt_desc: "Zoom, Google Meet, Teams o Webex: graba la llamada y tu micrófono.",
      box_mode_virt_title: "Virtual",
      box_notes_desc: "Anota acuerdos o tareas sin parar la grabación. Cada nota guarda el minuto exacto y aparece en el resumen.",
      box_notes_empty: "Aún no hay notas.",
      box_notes_title: "Notas",
      box_status_ready: "LISTO",
      ext_step1: "Descomprime el <strong>.zip</strong>.",
      ext_step2: "Abre <code>chrome://extensions</code> y activa el <strong>Modo de desarrollador</strong>.",
      ext_step3: "Pulsa <strong>Cargar descomprimida</strong> y elige la carpeta.",
      guest_notice: "Sin cuenta: hasta <strong>3 audios al día</strong> de máximo <strong>30 minutos</strong>, con cualquier motor. No guardamos ni analizamos nada.",
      ios_step1: "Abre esta página en <strong>Safari</strong>.",
      ios_step2: "Toca <strong>Compartir</strong> (el cuadro con la flecha).",
      ios_step3: "Elige <strong>Agregar a pantalla de inicio</strong>.",
      tag_Warning: "Alerta",
      tag_agreement: "Acuerdo",
      tag_idea: "Idea",
      tag_note: "Nota",
      tag_question: "Pregunta",
      tag_task: "Tarea",
      brand_title: "Apex Vox",
      powered_by_groq: "Potenciado por Groq",
      brand_subtitle: "Transcribe, identifica quién habla y resume tus reuniones",
      nav_landing: "Inicio",
      nav_playground: "Studio",
      nav_box: "Grabar",
      nav_portal: "Mi cuenta",
      btn_register_login: "Registrarse / Entrar",
      hero_badge: "POTENCIADO POR GROQ · ALMACENADO EN APEX-VOX.IALABS.APP",
      hero_title: "Transcribe y resume tus reuniones",
      hero_desc: "Regístrate hoy y obtén <strong>2 horas gratis al día</strong> en 1 o varios audios con almacenamiento por 24 horas, o activa <strong>Apex Pro por USD 10 al mes</strong> (<strong>20% de descuento</strong> si pagas en tus primeras 24 horas): transcripciones y almacenamiento ilimitados y resúmenes ejecutivos con <strong>Apex Summa</strong>.",
      hero_cta_playground: "Abrir Studio",
      hero_cta_box: "Grabar una reunión",
      hero_cta_register: "Crear cuenta gratis",
      hero_cta_trial: "Activar Apex Pro",
      suite_heading: "Lo que hace Apex Vox",
      suite_vox_status: "Producto Listo",
      suite_vox_part: "Transcripción (el núcleo)",
      suite_vox_desc: "Sube uno o varios audios en orden y obtén la transcripción con quién dijo qué.",
      suite_summa_status: "Activo en Plan Pro",
      suite_summa_part: "Notas y resúmenes",
      suite_summa_desc: "Al terminar la transcripción identifica: 1. Quién habló más, 2. De qué se habló, 3. Objetivos, 4. Llamados de atención, 5. Próximas tareas en calendario, 6. Gráficas y 7. Creación de Actas (Consejo, Comité, Asamblea).",
      suite_box_status: "Web, extensión y celular",
      suite_box_part: "Grabar reuniones",
      suite_box_desc: "Graba reuniones presenciales o virtuales (Zoom, Meet, Teams) en bloques de 3 minutos, con notas en vivo.",
      tbl_col_part: "Parte del Producto",
      tbl_col_name: "Nombre",
      tbl_col_state: "Estado",
      mc_models_heading: "Motores de Voz Serie Mc — Potenciado por Groq",
      mc_ayrton_tag: "EL MEJOR",
      mc_ayrton_desc: "Máxima fidelidad acústica, separación milimétrica de múltiples voces y precisión superior.",
      mc_lewis_tag: "MODO HÍBRIDO",
      mc_lewis_desc: "Modo híbrido balanceado que combina velocidad extrema con alineación acústica de hablantes.",
      mc_norris_tag: "HUELLA VOCAL",
      mc_norris_desc: "Especializado en timbre vocal y reconocimiento de perfiles de oradores registrados.",
      mc_piastri_tag: "ULTRA RÁPIDO",
      mc_piastri_desc: "Procesamiento instantáneo optimizado para despachos rápidos y atribución contextual.",
      plan_free_badge: "REGISTRO GRATUITO",
      plan_free_title: "Plan Gratis",
      plan_free_period: "/ siempre",
      plan_free_f1: "<strong>2 horas gratis al día</strong> en 1 o varios audios al día",
      plan_free_f2: "<strong>Almacenado por 24 horas</strong>: descárgalo si lo necesitas",
      plan_free_f3: "Modelos <strong>Mc-Ayrton, Mc-Lewis, Mc-Norris y Mc-Piastri</strong>",
      plan_free_f4: "Exportación TXT, SRT, VTT, JSON, CSV y Markdown",
      plan_free_cta: "Crear cuenta gratis",
      plan_pro_badge: "20% DE DESCUENTO SI PAGAS EN TUS PRIMERAS 24 H",
      plan_pro_title: "Plan Apex Pro",
      per_month: "mes",
      plan_pro_f1: "<strong>USD 8 el primer mes</strong> si pagas dentro de las 24 h siguientes a crear tu cuenta (una promoción por red cada 90 días)",
      plan_pro_f2: "<strong>Transcripciones ilimitadas</strong> (sin límite diario de horas ni archivos)",
      plan_pro_f3: "<strong>Almacenado sin límite de tiempo</strong> en apex-vox.ialabs.app",
      plan_pro_f4: "<strong>Resumen IA Apex Summa completo:</strong> Quién habló más, De qué se habló, Objetivos, Llamados de atención, Calendario de tareas y Gráficas",
      plan_pro_f5: "<strong>Generador de Actas Corporativas:</strong> Actas de Consejo, Junta Directiva, Comité y Asamblea",
      plan_pro_cta: "Activar Apex Pro",
      portal_profile_title: "Mi cuenta",
      lbl_name: "Nombre:",
      lbl_email: "Correo:",
      lbl_storage_retention: "Retención de tus archivos:",
      lbl_language: "Idioma:",
      portal_quota_label: "Consumo de Audio Hoy (1 o varios audios):",
      portal_quota_hint: "Tienes 2 horas gratis cada día. En el plan gratuito lo almacenamos por 24 horas: descárgalo si lo necesitas.",
      portal_billing_title: "Apex Pro — Pagos con Bold",
      portal_billing_desc: "El pago activa <strong>30 días de Apex Pro</strong>: transcripciones ilimitadas, almacenamiento ilimitado y <strong>Apex Summa</strong>. Bold no permite suscripciones: <strong>no se cobra nada automáticamente</strong> y cada mes renuevas de forma manual (te avisamos por correo).",
      lbl_billing_mode: "Modalidad",
      btn_generate_bold_link: "Pagar con Bold",
      portal_cloud_history_title: "Historial de transcripciones",
      btn_refresh: "Actualizar",
      kpi_retention_policy: "Política de Retención",
      kpi_stored_jobs: "Transcripciones Guardadas",
      step1_title: "Sube tus audios",
      btn_clear_queue: "Limpiar cola",
      btn_play_sequence: "Escuchar en orden",
      dropzone_title: "Arrastra tus archivos de audio aquí o haz clic para seleccionarlos",
      dropzone_hint: "MP3, OGG, WAV, M4A, FLAC o WEBM · uno o varios audios",
      reorder_hint: "Arrastra desde <strong>⠿</strong> (o usa <strong>↑ / ↓</strong>) para ordenar y pulsa <strong>Escuchar</strong> para revisar cada audio.",
      step2_title: "Modelo",
      lbl_engine_select: "Modelo",
      lbl_speakers_count: "Número de Oradores",
      spk_auto: "Automático (1, 2 o varios oradores)",
      lbl_audio_lang: "Idioma del Audio",
      lbl_context_hint: "Contexto / Vocabulario (Opcional)",
      lbl_active_plan_mode: "Plan Activo (Simulador / Cuenta)",
      lbl_api_override: "Configuración Avanzada de Clave Groq (Opcional — ya configurada en servidor)",
      btn_transcribe_now: "Transcribir",
      step3_vp_title: "Perfiles de voz",
      vp_desc: "Graba 5–30 segundos de la voz de alguien para que Apex Vox lo reconozca por su nombre.",
      btn_enroll_vp: "Guardar voz",
      result_card_title: "Transcripción",
      btn_rename_speakers: "Renombrar Oradores",
      empty_state_heading: "Listo para transcribir",
      empty_state_desc: "Sube uno o varios audios a la izquierda, elige el modelo y pulsa <strong>Transcribir</strong>.",
      kpi_duration_lbl: "Duración Global",
      kpi_speakers_lbl: "Oradores Detectados",
      kpi_engine_lbl: "Modelo Serie Mc",
      kpi_storage_lbl: "Almacenado",
      player_caption: "Haz clic en una marca de tiempo para ir a ese momento",
      rename_panel_title: "Asignar nombres personalizados a los oradores identificados:",
      btn_save_names: "Guardar Nombres",
      btn_cancel: "Cancelar",
      summa_main_title: "Resumen, tareas y actas",
      summa_locked_msg: "El Resumen IA completo de Apex Summa, las Gráficas y el Generador de Actas están incluidos en Apex Pro (USD 10 / mes · 20% de descuento si pagas en tus primeras 24 horas).",
      summa_sec1_who: "1. ¿Quién Habló Más?",
      summa_sec6_charts: "6. Gráficas de la Transcripción",
      summa_timeline_chart_lbl: "Densidad de Palabras por Tramo de Tiempo:",
      summa_sec2_what: "2. ¿De Qué se Habló?",
      summa_sec3_objectives: "3. Objetivos Identificados",
      summa_sec4_callouts: "4. Llamados de Atención y Alertas",
      summa_sec5_calendar: "5. Próximas Tareas en Forma de Calendario",
      btn_download_ics: "Exportar a Calendario (.ICS)",
      summa_sec7_minutes: "7. Crear Actas Oficiales (Consejo, Junta Directiva, Comité, Asamblea)",
      lbl_minutes_type: "Tipo de Acta a Generar",
      lbl_minutes_org: "Nombre de la Organización / Entidad",
      btn_generate_minutes: "Generar Acta Oficial Ahora",
      btn_download_minutes_md: "Descargar Acta (.MD)",
      btn_print_minutes: "Imprimir / Guardar PDF",
      auth_modal_title: "Crea tu cuenta: 2 horas gratis al día",
      auth_modal_subtitle: "Al registrarte obtienes <strong>2 horas gratis cada día</strong> (en 1 o varios audios). Lo transcrito lo almacenamos por 24 horas: descárgalo si lo necesitas.",
      lbl_full_name: "Nombre Completo",
      lbl_password: "Contraseña",
      btn_create_free_account: "Crear cuenta",
      btn_login_existing: "Entrar",
      plan_pro_f6: "<strong>Bot de Telegram:</strong> envía notas de voz y recibe la transcripción en tu chat (1 por suscripción)",
      kpi_plan: "Plan",
      kpi_networks: "Redes este mes",
      tg_title: "Bot de Telegram",
      tg_badge: "Apex Pro",
      tg_desc: "Envía notas de voz o audios a nuestro bot y recibe la transcripción en Telegram. Un chat por suscripción; la vinculación usa un código de un solo uso.",
      tg_link: "Generar código de vinculación",
      tg_unlink: "Desvincular chat",
      sec_title: "Seguridad y privacidad",
      sec_desc: "Tu cuenta puede usarse desde un máximo de 3 redes distintas por mes. Puedes eliminar tu cuenta y todos sus datos cuando quieras.",
      sec_policy: "Política de seguridad",
      sec_privacy: "Privacidad",
      sec_delete: "Eliminar mi cuenta",
      guest_cta: "Crea tu cuenta gratis: 2 horas al día, historial y Apex Summa",
      vp_guest: "Inicia sesión para registrar perfiles de voz privados.",
      guest_result_cta: "Este resultado no se guarda y desaparece en 60 minutos. Crea tu cuenta para conservar tu historial y obtener el análisis de Apex Summa.",
      footer_privacy: "Privacidad",
      footer_terms: "Términos y Condiciones",
      footer_habeas: "Habeas Data",
      footer_security: "Seguridad",
      news_label: "Boletín de Apex Vox: lanzamientos y guías, sin spam.",
      news_btn: "Suscribirme",
      btn_send_reset: "Enviar enlace",
      btn_back: "Volver",
      btn_save_password: "Guardar nueva contraseña",
      forgot_link: "¿Olvidaste tu contraseña?",
      auth_legal: "Al continuar aceptas los <a href=\"/legal/terminos\" target=\"_blank\">Términos y Condiciones</a> y autorizas el tratamiento de tus datos, incluida tu voz, según la <a href=\"/legal/habeas-data\" target=\"_blank\">Política de Tratamiento de Datos (Habeas Data)</a>.",
      lbl_billing_mode_value: "Pago único · 30 días por pago",
      oauth_google: "Continuar con Google",
      oauth_github: "Continuar con GitHub",
      oauth_divider: "o con tu correo",
      btn_logout: "Cerrar sesión",
      speed_overline: "Velocidad Groq",
      speed_title: "Minutos de audio, transcritos en segundos.",
      speed_body: "La inferencia de Groq procesa el audio mucho más rápido que el tiempo real. Sube la reunión, sigue con tu día y vuelve a una transcripción con oradores, resumen y acta.",
      speed_audio_lbl: "Audio de la reunión",
      speed_text_lbl: "Transcripción lista",
      footer_statement: "Cada audio, en orden. Cada voz, con nombre. Cada reunión, con acta.",
      footer_status: "Estado del servicio",
      lbl_vp_name: "Nombre",
      lbl_vp_sample: "Muestra de voz",
    },
    en: {
      android_step1: "Open this page in <strong>Chrome</strong>.",
      android_step2: "Tap the <strong>⋮</strong> menu.",
      android_step3: "Choose <strong>Install app</strong> or <strong>Add to Home screen</strong>.",
      app_card_desc: "Open it like an app from your home screen and record your in-person meetings.",
      app_card_title: "Install Apex Vox on your phone",
      app_install_btn: "Install app",
      app_installed: "You are already using the installed app.",
      box_blocks_log_empty: "Nothing recorded yet.",
      box_btn_add_note: "+ Add note",
      box_btn_cut_block: "Send block now",
      box_btn_download_ext: "Download extension (.zip)",
      box_btn_open_summa: "View full summary",
      box_btn_start: "● Record",
      box_btn_stop_finalize: "■ Stop and create summary",
      box_empty_live_desc: "Press <strong>Record</strong> and the transcript will appear every 3 minutes.",
      box_empty_live_title: "What is said will appear here",
      box_ext_card_desc: "Record from a pinned Chrome tab, including your Zoom, Meet or Teams calls. When you finish you get a link with notes, summary and minutes.",
      box_ext_card_title: "Chrome extension",
      box_kpi_blocks: "Blocks sent",
      box_kpi_segments: "Sentences transcribed",
      box_lbl_elapsed: "TIME RECORDED",
      box_lbl_engine: "Model",
      box_lbl_note_speaker: "Who (optional)",
      box_lbl_note_text: "Note",
      box_lbl_platform: "Platform",
      box_lbl_title: "Meeting title",
      box_lead_desc: "Record your meeting for as long as you need. It is saved in <strong>3-minute blocks</strong> and the transcript appears as you talk.",
      box_live_feed_title: "Live transcript",
      box_main_title: "Record a meeting",
      box_mode_pres_desc: "Uses the microphone of this computer or your phone.",
      box_mode_pres_title: "In person",
      box_mode_virt_desc: "Zoom, Google Meet, Teams or Webex: records the call and your microphone.",
      box_mode_virt_title: "Virtual",
      box_notes_desc: "Write down agreements or tasks without stopping the recording. Each note keeps the exact minute and shows up in the summary.",
      box_notes_empty: "No notes yet.",
      box_notes_title: "Notes",
      box_status_ready: "READY",
      ext_step1: "Unzip the <strong>.zip</strong>.",
      ext_step2: "Open <code>chrome://extensions</code> and turn on <strong>Developer mode</strong>.",
      ext_step3: "Click <strong>Load unpacked</strong> and choose the folder.",
      guest_notice: "Without an account: up to <strong>3 audios a day</strong> of at most <strong>30 minutes</strong>, with any engine. We don't store or analyze anything.",
      ios_step1: "Open this page in <strong>Safari</strong>.",
      ios_step2: "Tap <strong>Share</strong> (the square with the arrow).",
      ios_step3: "Choose <strong>Add to Home Screen</strong>.",
      tag_Warning: "Alert",
      tag_agreement: "Agreement",
      tag_idea: "Idea",
      tag_note: "Note",
      tag_question: "Question",
      tag_task: "Task",
      brand_title: "Apex Vox",
      powered_by_groq: "Powered by Groq",
      brand_subtitle: "Transcribe, identify speakers and summarize your meetings",
      nav_landing: "Home",
      nav_playground: "Studio",
      nav_box: "Record",
      nav_portal: "My account",
      btn_register_login: "Sign Up / Log In",
      hero_badge: "POWERED BY GROQ · STORED ON APEX-VOX.IALABS.APP",
      hero_title: "Transcribe and summarize your meetings",
      hero_desc: "Sign up today and get <strong>2 free hours per day</strong> across 1 or multiple audios with 24-hour storage, or activate <strong>Apex Pro for USD 10 a month</strong> (<strong>20% off</strong> if you pay within your first 24 hours): unlimited transcriptions and storage, and executive AI insights with <strong>Apex Summa</strong>.",
      hero_cta_playground: "Open Studio",
      hero_cta_box: "Record a meeting",
      hero_cta_register: "Create a free account",
      hero_cta_trial: "Activate Apex Pro",
      suite_heading: "What Apex Vox does",
      suite_vox_status: "Product Ready",
      suite_vox_part: "Transcription (the core)",
      suite_vox_desc: "Upload one or more audios in order and get the transcript with who said what.",
      suite_summa_status: "Active on Pro Plan",
      suite_summa_part: "AI Notes & Summaries",
      suite_summa_desc: "Upon completing transcription, identifies: 1. Who spoke the most, 2. What was discussed, 3. Objectives, 4. Callouts/Warnings, 5. Upcoming tasks calendar, 6. Transcription charts & 7. Formal Minutes (Board, Committee, Assembly).",
      suite_box_status: "Web, extension and phone",
      suite_box_part: "Record meetings",
      suite_box_desc: "Record in-person or virtual meetings (Zoom, Meet, Teams) in 3-minute blocks, with live notes.",
      tbl_col_part: "Product Part",
      tbl_col_name: "Name",
      tbl_col_state: "Status",
      mc_models_heading: "Mc-Series Voice Engines — Powered by Groq",
      mc_ayrton_tag: "THE BEST",
      mc_ayrton_desc: "Maximum acoustic fidelity, pinpoint multi-speaker separation, and superior accuracy.",
      mc_lewis_tag: "HYBRID MODE",
      mc_lewis_desc: "Balanced hybrid mode combining extreme speed with acoustic speaker alignment.",
      mc_norris_tag: "VOICEPRINT",
      mc_norris_desc: "Specialized in vocal timbre clustering and enrolled speaker recognition.",
      mc_piastri_tag: "ULTRA FAST",
      mc_piastri_desc: "Instantaneous processing optimized for rapid turnaround and contextual attribution.",
      plan_free_badge: "FREE REGISTRATION",
      plan_free_title: "Free Plan",
      plan_free_period: "/ forever",
      plan_free_f1: "<strong>2 hours free per day</strong> across 1 or multiple audios",
      plan_free_f2: "<strong>Stored for 24 hours</strong>: download it if you need it",
      plan_free_f3: "<strong>Mc-Ayrton, Mc-Lewis, Mc-Norris and Mc-Piastri</strong> models",
      plan_free_f4: "Export to TXT, SRT, VTT, JSON, CSV & Markdown",
      plan_free_cta: "Create a free account",
      plan_pro_badge: "20% OFF IF YOU PAY IN YOUR FIRST 24 H",
      plan_pro_title: "Apex Pro Plan",
      per_month: "month",
      plan_pro_f1: "<strong>USD 8 for the first month</strong> if you pay within 24 h of creating your account (one promo per network every 90 days)",
      plan_pro_f2: "<strong>Unlimited transcriptions</strong> (no daily hour or file limit)",
      plan_pro_f3: "<strong>Stored with no time limit</strong> on apex-vox.ialabs.app",
      plan_pro_f4: "<strong>Full Apex Summa AI Report:</strong> Who spoke most, Topics, Objectives, Callouts, Calendar Tasks & Charts",
      plan_pro_f5: "<strong>Corporate Minutes Generator:</strong> Board of Directors, Committee & Assembly Minutes",
      plan_pro_cta: "Activate Apex Pro",
      portal_profile_title: "My account",
      lbl_name: "Name:",
      lbl_email: "Email:",
      lbl_storage_retention: "File retention:",
      lbl_language: "Language:",
      portal_quota_label: "Audio Usage Today (1 or multiple audios):",
      portal_quota_hint: "You get 2 free hours every day. On the free plan we store it for 24 hours: download it if you need it.",
      portal_billing_title: "Apex Pro — Payments with Bold",
      portal_billing_desc: "Paying activates <strong>30 days of Apex Pro</strong>: unlimited transcriptions, unlimited storage and <strong>Apex Summa</strong>. Bold has no subscriptions: <strong>nothing is charged automatically</strong> and you renew manually each month (we email you a reminder).",
      lbl_billing_mode: "Billing",
      btn_generate_bold_link: "Pay with Bold",
      portal_cloud_history_title: "Transcription history",
      btn_refresh: "Refresh",
      kpi_retention_policy: "Retention Policy",
      kpi_stored_jobs: "Saved Transcriptions",
      step1_title: "Upload your audios",
      btn_clear_queue: "Clear queue",
      btn_play_sequence: "Play in order",
      dropzone_title: "Drag and drop your audio files here or click to browse",
      dropzone_hint: "MP3, OGG, WAV, M4A, FLAC or WEBM · one or more audios",
      reorder_hint: "Drag from <strong>⠿</strong> (or use <strong>↑ / ↓</strong>) to reorder and press <strong>Listen</strong> to check each audio.",
      step2_title: "Model",
      lbl_engine_select: "Model",
      lbl_speakers_count: "Number of Speakers",
      spk_auto: "Automatic (1, 2 or multiple speakers)",
      lbl_audio_lang: "Audio Language",
      lbl_context_hint: "Context / Vocabulary (Optional)",
      lbl_active_plan_mode: "Active Plan (Simulator / Account)",
      lbl_api_override: "Advanced Groq Key Override (Optional — configured on server)",
      btn_transcribe_now: "Transcribe",
      step3_vp_title: "Voice profiles",
      vp_desc: "Record 5–30 seconds of someone's voice so Apex Vox recognizes them by name.",
      btn_enroll_vp: "Save voice",
      result_card_title: "Transcript",
      btn_rename_speakers: "Rename Speakers",
      empty_state_heading: "Ready to transcribe",
      empty_state_desc: "Upload one or more audios on the left, choose the model and press <strong>Transcribe</strong>.",
      kpi_duration_lbl: "Total Duration",
      kpi_speakers_lbl: "Detected Speakers",
      kpi_engine_lbl: "Mc-Series Model",
      kpi_storage_lbl: "Stored",
      player_caption: "Click a timestamp to jump to that moment",
      rename_panel_title: "Assign custom names to identified speakers:",
      btn_save_names: "Save Names",
      btn_cancel: "Cancel",
      summa_main_title: "Summary, tasks and minutes",
      summa_locked_msg: "The full Apex Summa AI Summary, Charts, and Minutes Generator are included in Apex Pro (USD 10 / month · 20% off if you pay within your first 24 hours).",
      summa_sec1_who: "1. Who Spoke the Most?",
      summa_sec6_charts: "6. Transcription Charts",
      summa_timeline_chart_lbl: "Word Density Across Timeline:",
      summa_sec2_what: "2. What Was Discussed?",
      summa_sec3_objectives: "3. Identified Objectives",
      summa_sec4_callouts: "4. Callouts & Critical Warnings",
      summa_sec5_calendar: "5. Upcoming Tasks Calendar",
      btn_download_ics: "Export to Calendar (.ICS)",
      summa_sec7_minutes: "7. Create Official Minutes (Board, Committee, Assembly)",
      lbl_minutes_type: "Minutes Template Type",
      lbl_minutes_org: "Organization / Entity Name",
      btn_generate_minutes: "Generate Official Minutes Now",
      btn_download_minutes_md: "Download Minutes (.MD)",
      btn_print_minutes: "Print / Save PDF",
      auth_modal_title: "Create your account: 2 free hours a day",
      auth_modal_subtitle: "Register to get <strong>2 free hours every day</strong> (in 1 or multiple audios). We store your transcripts for 24 hours: download them if you need them.",
      lbl_full_name: "Full Name",
      lbl_password: "Password",
      btn_create_free_account: "Create account",
      btn_login_existing: "Log In",
      plan_pro_f6: "<strong>Telegram bot:</strong> send voice notes and get the transcript in your chat (1 per subscription)",
      kpi_plan: "Plan",
      kpi_networks: "Networks this month",
      tg_title: "Telegram bot",
      tg_badge: "Apex Pro",
      tg_desc: "Send voice notes or audio to our bot and get the transcript in Telegram. One chat per subscription, linked with a one-time code.",
      tg_link: "Generate link code",
      tg_unlink: "Unlink chat",
      sec_title: "Security and privacy",
      sec_desc: "Your account can be used from up to 3 different networks per month. You can delete your account and all its data at any time.",
      sec_policy: "Security policy",
      sec_privacy: "Privacy",
      sec_delete: "Delete my account",
      guest_cta: "Create your free account: 2 hours a day, history and Apex Summa",
      vp_guest: "Sign in to enrol private voice profiles.",
      guest_result_cta: "This result is not saved and disappears in 60 minutes. Create an account to keep your history and get the Apex Summa analysis.",
      footer_privacy: "Privacy",
      footer_terms: "Terms and Conditions",
      footer_habeas: "Habeas Data",
      footer_security: "Security",
      news_label: "Apex Vox newsletter: launches and guides, no spam.",
      news_btn: "Subscribe",
      btn_send_reset: "Send link",
      btn_back: "Back",
      btn_save_password: "Save new password",
      forgot_link: "Forgot your password?",
      auth_legal: "By continuing you accept the <a href=\"/legal/terminos?lang=en\" target=\"_blank\">Terms and Conditions</a> and authorize the processing of your data, including your voice, under the <a href=\"/legal/habeas-data?lang=en\" target=\"_blank\">Personal Data Processing Policy (Habeas Data)</a>.",
      lbl_billing_mode_value: "One-off payment · 30 days each",
      oauth_google: "Continue with Google",
      oauth_github: "Continue with GitHub",
      oauth_divider: "or with your email",
      btn_logout: "Sign out",
      speed_overline: "Groq speed",
      speed_title: "Minutes of audio, transcribed in seconds.",
      speed_body: "Groq inference processes audio far faster than real time. Upload the meeting, get on with your day, and come back to a transcript with speakers, a summary and minutes.",
      speed_audio_lbl: "Meeting audio",
      speed_text_lbl: "Transcript ready",
      footer_statement: "Every audio, in order. Every voice, named. Every meeting, minuted.",
      footer_status: "Service status",
      lbl_vp_name: "Name",
      lbl_vp_sample: "Voice sample",
    },
  };

  const ENGINE_LABELS = {
    "Mc-Ayrton": "Mc-Ayrton",
    "Mc-Lewis": "Mc-Lewis (Híbrido)",
    "Mc-Norris": "Mc-Norris",
    "Mc-Piastri": "Mc-Piastri",
    hybrid_deepgram_groq: "Mc-Lewis (Híbrido)",
    deepgram: "Mc-Ayrton",
    acoustic_local: "Mc-Norris",
    groq_llm: "Mc-Piastri",
  };

  // DOM Elements
  const viewLanding = document.getElementById("view-landing");
  const viewPlayground = document.getElementById("view-playground");
  const viewBox = document.getElementById("view-box");
  const viewPortal = document.getElementById("view-portal");
  const navLandingBtn = document.getElementById("nav-landing-btn");
  const navPlaygroundBtn = document.getElementById("nav-playground-btn");
  const navBoxBtn = document.getElementById("nav-box-btn");
  const navPortalBtn = document.getElementById("nav-portal-btn");

  const langEsBtn = document.getElementById("lang-es-btn");
  const langEnBtn = document.getElementById("lang-en-btn");
  const planPillText = document.getElementById("plan-pill-text");
  const openAuthBtn = document.getElementById("open-auth-btn");
  const authDialog = document.getElementById("auth-dialog");
  const closeAuthDialogBtn = document.getElementById("close-auth-dialog-btn");

  const dropzone = document.getElementById("dropzone");
  const fileInput = document.getElementById("file-input");
  const trackListEl = document.getElementById("track-list");
  const queueSummaryEl = document.getElementById("queue-summary");
  const queueCountLabel = document.getElementById("queue-count-label");
  const queueDurationLabel = document.getElementById("queue-duration-label");
  const reorderHintEl = document.getElementById("reorder-hint");
  const clearQueueBtn = document.getElementById("clear-queue-btn");

  const engineSelect = document.getElementById("engine-select");
  const modelSelect = document.getElementById("model-select");
  const speakersSelect = document.getElementById("speakers-select");
  const languageSelect = document.getElementById("language-select");
  const promptHintInput = document.getElementById("prompt-hint-input");
  const transcribeBtn = document.getElementById("transcribe-btn");

  const vpNameInput = document.getElementById("vp-name-input");
  const vpFileInput = document.getElementById("vp-file-input");
  const enrollVpBtn = document.getElementById("enroll-vp-btn");
  const voiceProfilesListEl = document.getElementById("voice-profiles-list");

  const progressBox = document.getElementById("progress-box");
  const progressStep = document.getElementById("progress-step");
  const progressPct = document.getElementById("progress-pct");
  const progressBarFill = document.getElementById("progress-bar-fill");
  const progressSubtext = document.getElementById("progress-subtext");
  const alertBox = document.getElementById("alert-box");

  const emptyResultState = document.getElementById("empty-result-state");
  const resultContainer = document.getElementById("result-container");
  const kpiDuration = document.getElementById("kpi-duration");
  const kpiSpeakers = document.getElementById("kpi-speakers");
  const kpiEngine = document.getElementById("kpi-engine");
  const kpiFiles = document.getElementById("kpi-files");
  const mergedAudioPlayer = document.getElementById("merged-audio-player");

  const renameSpeakersBtn = document.getElementById("rename-speakers-btn");
  const renamePanel = document.getElementById("rename-panel");
  const renameInputsContainer = document.getElementById("rename-inputs-container");
  const applyRenameBtn = document.getElementById("apply-rename-btn");
  const cancelRenameBtn = document.getElementById("cancel-rename-btn");

  const searchInput = document.getElementById("search-input");
  const speakerTabsEl = document.getElementById("speaker-tabs");
  const segmentsListEl = document.getElementById("segments-list");
  const copyTranscriptBtn = document.getElementById("copy-transcript-btn");

  const healthDot = document.getElementById("health-dot");
  const healthText = document.getElementById("health-text");

  // ---------------------------------------------------------------------------
  // Light-Dismiss Dialog Fallback (per modern-web-guidance: light-dismiss-a-dialog)
  // ---------------------------------------------------------------------------
  if (authDialog && !("closedBy" in HTMLDialogElement.prototype)) {
    authDialog.addEventListener("click", (event) => {
      if (event.target !== authDialog) return;
      const rect = authDialog.getBoundingClientRect();
      const isDialogContent =
        rect.top <= event.clientY &&
        event.clientY <= rect.top + rect.height &&
        rect.left <= event.clientX &&
        event.clientX <= rect.left + rect.width;
      if (isDialogContent) return;
      authDialog.close();
    });
  }

  // ---------------------------------------------------------------------------
  // Language & View Switching
  // ---------------------------------------------------------------------------


  // ---------------------------------------------------------------------------
  // Traducción de textos fijos sin clave data-i18n (coincidencia exacta)
  // ---------------------------------------------------------------------------
  const TEXT_EN = {
      "Saltar al contenido": "Skip to content",
      "Plan Gratis (2h/día)": "Free plan (2h/day)",
      "Potenciado por Groq": "Powered by Groq",
      "Plan Gratis": "Free plan",
      "Usuario Invitado": "Guest user",
      "24 horas (Plan Gratis)": "24 hours (Free plan)",
      "USD 10 / 30 días": "USD 10 / 30 days",
      "/ 30 días": "/ 30 days",
      "Conectar con ChatGPT y Claude": "Connect with ChatGPT and Claude",
      "Solo lectura": "Read-only",
      "Pregúntale a ChatGPT o a Claude por tus reuniones: qué se acordó, quién dijo qué, tareas pendientes. Agrega este conector y autoriza tu cuenta.": "Ask ChatGPT or Claude about your meetings: what was agreed, who said what, pending tasks. Add this connector and authorize your account.",
      "Copiar": "Copy",
      "Configuración → Conectores → Agregar conector personalizado → pega la URL.": "Settings → Connectors → Add custom connector → paste the URL.",
      "Configuración → Aplicaciones y conectores → Crear (modo desarrollador) → pega la URL con autenticación OAuth.": "Settings → Apps & connectors → Create (developer mode) → paste the URL with OAuth authentication.",
      "Inicia sesión y pulsa": "Sign in and press",
      "Permitir acceso": "Allow access",
      ". Resúmenes y tareas: Apex Pro.": ". Summaries and tasks: Apex Pro.",
      "Apps conectadas: —": "Connected apps: —",
      "Desconectar todas las apps": "Disconnect all apps",
      "Gratis": "Free",
      "24 Horas": "24 Hours",
      "0 archivos en orden": "0 files in order",
      "Duración total: 00:00:00": "Total duration: 00:00:00",
      "Preparando pipeline...": "Preparing…",
      "Potenciado por Groq · Guardando de forma segura...": "Powered by Groq · Saving securely…",
      "Ilimitado": "Unlimited",
      "Subtítulos SRT": "SRT subtitles",
      "Subtítulos VTT": "VTT subtitles",
      "Copiar texto": "Copy text",
      "Apex Summa IA · Potenciado por Groq": "Apex Summa AI · Powered by Groq",
      "Desbloquear con Prueba Pro 3 Días": "Unlock with Apex Pro",
      "Activar Apex Pro": "Activate Apex Pro",
      "Buscar en la transcripción": "Search the transcript",
      "BLOQUE 1": "BLOCK 1",
      "0 notas": "0 notes",
      "Bot para reuniones virtuales": "Bot for virtual meetings",
      "El bot entra a tu Zoom, Meet o Teams, graba y te envía la transcripción con resumen y acta.": "The bot joins your Zoom, Meet or Teams, records and sends you the transcript with summary and minutes.",
      "Enviar bot": "Send bot",
      "También puedes invitar a": "You can also invite",
      "a tus reuniones: el bot entrará solo a la hora.": "to your meetings: the bot will join on time by itself.",
      "Grabar": "Record",
      "CUENTA": "ACCOUNT",
      "Mi cuenta": "My account",
      "PLANES": "PLANS",
      "Inicio": "Home",
    "NOTA": "NOTE",
      "Apex Vox — Inicio": "Apex Vox — Home",
      "Navegación principal": "Main navigation",
      "Plan activo y cuota diaria": "Active plan and daily quota",
      "Apex Vox — Inicio y planes": "Apex Vox — Home and plans",
      "URL del conector MCP": "MCP connector URL",
      "Configuración y cola de audios": "Settings and audio queue",
      "Limpiar lista": "Clear list",
      "Subir archivos de audio": "Upload audio files",
      "Secuencia ordenada de pistas de audio": "Ordered audio tracks",
      "Ej: Reunión de Consejo entre Carlos y Ana...": "E.g. Board meeting between Carlos and Ana…",
      "Nombre (ej. Carlos, Dra. Ana)": "Name (e.g. Carlos, Dr. Ana)",
      "Resultados de transcripción y resumen IA Apex Summa": "Transcript and Apex Summa AI summary",
      "Descargar transcripción": "Download transcript",
      "Buscar palabra o frase...": "Search a word or phrase…",
      "Apex Box — Grabar reuniones": "Apex Box — Record meetings",
      "Grabar una reunión y tomar notas": "Record a meeting and take notes",
      "Tipo de reunión": "Meeting type",
      "Ej. Comité semanal": "E.g. Weekly committee",
      "Nivel de sonido en vivo": "Live sound level",
      "Tipo de nota": "Note type",
      "Ej. Carlos": "E.g. Carlos",
      "Escribe y presiona Enter": "Type and press Enter",
      "Extensión de Chrome y transcripción en vivo": "Chrome extension and live transcript",
      "Pega el enlace de la reunión": "Paste the meeting link",
      "Enlace de la reunión": "Meeting link",
      "Navegación móvil": "Mobile navigation",
      "tu@correo.com": "you@email.com",
      "Cerrar": "Close",
      "Ej. Carlos Mendoza": "E.g. Carlos Mendoza",
      "Presencial / Celular": "In person / Phone",
      "Mc-Lewis · Híbrido": "Mc-Lewis · Hybrid",
      "Mc-Ayrton · Máxima precisión": "Mc-Ayrton · Highest accuracy",
      "Mc-Norris · Huella vocal": "Mc-Norris · Voiceprint",
      "Mc-Piastri · Ultra rápido": "Mc-Piastri · Ultra fast"
  };
  const originalText = new WeakMap();
  let englishApplied = false;
  const I18N_ATTRS = ["placeholder", "aria-label", "title", "alt"];

  function translateNode(root, lang) {
    if (!root) return;
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
      const parent = node.parentElement;
      if (!parent || parent.closest("[data-i18n], [data-no-translate], script, style, code, textarea")) continue;
      if (!originalText.has(node)) originalText.set(node, node.nodeValue);
      const orig = originalText.get(node);
      const key = orig.replace(/\s+/g, " ").trim();
      if (!key) continue;
      const en = TEXT_EN[key];
      if (!en) continue;
      node.nodeValue = lang === "en" ? orig.replace(key, en) : orig;
    }
    const els = root.querySelectorAll ? root.querySelectorAll(I18N_ATTRS.map((a) => `[${a}]`).join(",")) : [];
    els.forEach((el) => {
      I18N_ATTRS.forEach((attr) => {
        if (!el.hasAttribute(attr)) return;
        const store = `data-orig-${attr}`;
        if (!el.hasAttribute(store)) el.setAttribute(store, el.getAttribute(attr));
        const orig = el.getAttribute(store);
        const en = TEXT_EN[orig.trim()];
        if (en) el.setAttribute(attr, lang === "en" ? en : orig);
      });
    });
  }

  const PAGE_META = (() => {
    try {
      return JSON.parse(document.getElementById("page-meta").textContent);
    } catch (e) {
      return {};
    }
  })();

  function applyPageMeta(lang) {
    const meta = PAGE_META[lang] || PAGE_META.es;
    if (!meta) return;
    document.title = meta.title;
    const desc = document.querySelector('meta[name="description"]');
    if (desc) desc.setAttribute("content", meta.description);
  }

  // Contenido que el JS agrega después (listas, alertas): se traduce al aparecer
  new MutationObserver((mutations) => {
    if (state.lang !== "en") return;
    mutations.forEach((m) => m.addedNodes.forEach((n) => {
      if (n.nodeType === 1) translateNode(n, "en");
      else if (n.nodeType === 3 && n.parentElement) translateNode(n.parentElement, "en");
    }));
  }).observe(document.body, { childList: true, subtree: true });

  function applyLanguage(lang) {
    const clean = lang === "en" ? "en" : "es";
    state.lang = clean;
    const langSelect = document.getElementById("profile-lang-select");
    if (langSelect) langSelect.value = clean;
    document.documentElement.lang = clean;

    if (langEsBtn && langEnBtn) {
      langEsBtn.classList.toggle("active", clean === "es");
      langEnBtn.classList.toggle("active", clean === "en");
    }

    if (clean === "en" || englishApplied) translateNode(document.body, clean);
    englishApplied = englishApplied || clean === "en";
    applyPageMeta(clean);
    const dict = I18N[clean] || I18N.es;
    document.querySelectorAll("[data-i18n]").forEach((el) => {
      const key = el.getAttribute("data-i18n");
      if (dict[key]) {
        el.innerHTML = dict[key];
      }
    });

    // Update engine dropdown options in selected language
    if (engineSelect) {
      const val = engineSelect.value;
      engineSelect.options[0].textContent =
        clean === "en"
          ? "Mc-Ayrton (The Best · Maximum Precision)"
          : "Mc-Ayrton (El Mejor · Máxima Precisión)";
      engineSelect.options[1].textContent =
        clean === "en"
          ? "Mc-Lewis (Hybrid Mode · Recommended)"
          : "Mc-Lewis (Modo Híbrido · Recomendado)";
      engineSelect.options[2].textContent =
        clean === "en"
          ? "Mc-Norris (Vocal Timbre & Voiceprint)"
          : "Mc-Norris (Timbre y Huella Vocal)";
      engineSelect.options[3].textContent =
        clean === "en"
          ? "Mc-Piastri (Contextual Speed)"
          : "Mc-Piastri (Velocidad Contextual)";
      engineSelect.value = val;
    }

    if (typeof refreshAuthUi === "function" && openAuthBtn) refreshAuthUi();
    else updateHeaderPlanPill();
    if (state.currentResult && state.currentResult.plan !== "guest") {
      renderApexSumma(state.currentResult);
    }
  }

  function switchView(viewName) {
    state.activeView = viewName;
    if (viewLanding) viewLanding.classList.toggle("hidden", viewName !== "landing");
    if (viewPlayground) viewPlayground.classList.toggle("hidden", viewName !== "playground");
    if (viewBox) viewBox.classList.toggle("hidden", viewName !== "box");
    if (viewPortal) viewPortal.classList.toggle("hidden", viewName !== "portal");

    if (navLandingBtn) navLandingBtn.classList.toggle("active", viewName === "landing");
    if (navPlaygroundBtn) navPlaygroundBtn.classList.toggle("active", viewName === "playground");
    if (navBoxBtn) navBoxBtn.classList.toggle("active", viewName === "box");
    if (navPortalBtn) navPortalBtn.classList.toggle("active", viewName === "portal");
    [navLandingBtn, navPlaygroundBtn, navBoxBtn, navPortalBtn].forEach((btn) => {
      if (!btn) return;
      if (btn.classList.contains("active")) btn.setAttribute("aria-current", "page");
      else btn.removeAttribute("aria-current");
    });

    document.querySelectorAll(".mobile-nav-item").forEach((btn) => {
      btn.classList.toggle("active", btn.getAttribute("data-goto-view") === viewName);
    });

    window.scrollTo({ top: 0, behavior: "auto" });

    if (viewName === "portal") {
      loadUserPortalSummary();
    } else if (viewName === "box") {
      if (typeof loadMeetingBots === "function") loadMeetingBots();
    }
  }

  function updateHeaderPlanPill() {
    if (!planPillText) return;
    const isEn = state.lang === "en";
    if (!state.user) {
      planPillText.textContent = isEn ? "Guest · no account" : "Sin cuenta";
    } else if (state.plan === "pro" || state.plan === "trial") {
      planPillText.textContent = isEn
        ? "Apex Pro (Unlimited)"
        : "Apex Pro (Ilimitado)";
    } else {
      planPillText.textContent = isEn
        ? "Free Plan (2h/day · 24h)"
        : "Plan Gratis (2h/día · 24h)";
    }
  }

  // ---------------------------------------------------------------------------
  // Formatting Helpers
  // ---------------------------------------------------------------------------

  function formatSecondsHHMMSS(seconds) {
    const s = Math.max(0, Math.floor(Number(seconds) || 0));
    const hrs = Math.floor(s / 3600);
    const mins = Math.floor((s % 3600) / 60);
    const secs = s % 60;
    return [hrs, mins, secs].map((v) => String(v).padStart(2, "0")).join(":");
  }

  function formatBytes(bytes) {
    const b = Number(bytes) || 0;
    if (b < 1024) return `${b} B`;
    if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} KB`;
    return `${(b / (1024 * 1024)).toFixed(2)} MB`;
  }

  function authHeaders(extra) {
    const headers = Object.assign({}, extra || {});
    if (state.token) headers.Authorization = `Bearer ${state.token}`;
    return headers;
  }

  // Enlaces que el navegador abre sin cabecera Authorization (audio, descargas): token firmado
  function withMediaToken(url, token) {
    return token ? `${url}?t=${encodeURIComponent(token)}` : url;
  }

  function authFetch(url, options) {
    const opts = Object.assign({}, options || {});
    opts.headers = authHeaders(opts.headers);
    return fetch(url, opts).then((res) => {
      if (res.status === 401 && state.token && !url.startsWith("/api/auth/")) {
        clearSession();
      }
      return res;
    });
  }

  function planLabel(quota) {
    if (quota && quota.is_unlimited) return "Apex Pro";
    return t("Plan gratis (2 h al día)", "Free plan (2 h a day)");
  }

  function t(es, en) {
    return state.lang === "en" ? en : es;
  }

  function storeSession(profile) {
    state.user = profile;
    if (profile.access_token) state.token = profile.access_token;
    state.plan = (profile.quota && profile.quota.plan) || profile.plan || "free";
    localStorage.setItem("apex_vox_user", JSON.stringify(Object.assign({}, profile, { access_token: "" })));
    if (state.token) localStorage.setItem("apex_vox_token", state.token);
    // Con sesión iniciada, manda el idioma guardado en la cuenta
    if (profile.preferred_language === "es" || profile.preferred_language === "en") {
      localStorage.setItem("apex_vox_lang_choice", profile.preferred_language);
      if (profile.preferred_language !== state.lang) applyLanguage(profile.preferred_language);
    }
    refreshAuthUi();
    const oauthNext = sessionStorage.getItem("apex_oauth_next");
    if (state.token && oauthNext && oauthNext.startsWith("/oauth/authorize?")) {
      sessionStorage.removeItem("apex_oauth_next");
      location.assign(oauthNext);
    }
  }

  function clearSession() {
    state.user = null;
    state.token = null;
    state.plan = "free";
    localStorage.removeItem("apex_vox_user");
    localStorage.removeItem("apex_vox_token");
    localStorage.removeItem("apex_vox_plan");
    refreshAuthUi();
  }

  function refreshAuthUi() {
    if (openAuthBtn) {
      const initialsEl = document.getElementById("user-initials");
      const name = state.user ? (state.user.full_name || state.user.email || "") : "";
      const initials = name.split(/[\s@.]+/).filter(Boolean).slice(0, 2).map((p) => p[0].toUpperCase()).join("");
      openAuthBtn.classList.toggle("signed-in", Boolean(state.user));
      if (initialsEl) {
        initialsEl.textContent = initials;
        initialsEl.classList.toggle("hidden", !state.user);
      }
      const label = state.user ? t(`Mi cuenta (${name})`, `My account (${name})`) : t("Entrar o crear cuenta", "Sign in or create account");
      openAuthBtn.setAttribute("aria-label", label);
      openAuthBtn.title = label;
    }
    const guestNotice = document.getElementById("guest-notice");
    if (guestNotice) {
      guestNotice.classList.toggle("hidden", Boolean(state.user));
      const p = guestNotice.querySelector("p");
      const c = state.config;
      if (p && !state.user) {
        p.innerHTML = t(
          `Sin cuenta: hasta <strong>${c.guest_max_audios} audios al día</strong> de máximo <strong>${c.guest_max_minutes} minutos</strong>, con cualquier motor. No guardamos ni analizamos nada.${c.guest_audios_remaining !== null && c.guest_audios_remaining !== undefined ? ` Te quedan <strong>${c.guest_audios_remaining}</strong> hoy.` : ""}`,
          `Without an account: up to <strong>${c.guest_max_audios} audios a day</strong>, <strong>${c.guest_max_minutes} minutes</strong> each, any engine. Nothing is saved or analysed.${c.guest_audios_remaining !== null && c.guest_audios_remaining !== undefined ? ` <strong>${c.guest_audios_remaining}</strong> left today.` : ""}`
        );
      }
    }
    document.querySelectorAll(".vp-guest").forEach((el) => el.classList.toggle("hidden", Boolean(state.user)));
    ["vp-name-input", "vp-file-input", "enroll-vp-btn"].forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.disabled = !state.user;
    });
    const logoutBtn = document.getElementById("portal-logout-btn");
    if (logoutBtn) logoutBtn.classList.toggle("hidden", !state.user);
    updateHeaderPlanPill();
    updateBillingButtons();
  }

  function updateBillingButtons() {
    loadBillingOffer();
  }

  function requireSession(message) {
    if (state.token) return true;
    const fbBox = document.getElementById("auth-feedback-box");
    if (fbBox && message) {
      fbBox.textContent = message;
      fbBox.className = "alert-box alert-success";
      fbBox.classList.remove("hidden");
    }
    if (authDialog && !authDialog.open) authDialog.showModal();
    return false;
  }

  async function refreshProfile() {
    if (!state.token) return;
    try {
      const res = await authFetch("/api/auth/me");
      if (res.ok) storeSession(await res.json());
    } catch (err) {
      /* offline: keep cached profile */
    }
  }

  async function loadClientConfig() {
    try {
      const res = await fetch("/api/auth/config");
      if (res.ok) state.config = Object.assign(state.config, await res.json());
    } catch (err) {
      /* keep defaults */
    }
    refreshAuthUi();
    const oauthBox = document.getElementById("oauth-options");
    let shown = 0;
    document.querySelectorAll("[data-oauth-provider]").forEach((el) => {
      const on = (state.config.oauth_providers || []).includes(el.getAttribute("data-oauth-provider"));
      el.classList.toggle("hidden", !on);
      if (on) shown += 1;
    });
    if (oauthBox) oauthBox.classList.toggle("hidden", shown === 0);
  }

  async function handleRedirectParams() {
    const params = new URLSearchParams(window.location.search);
    const authCode = params.get("auth_code");
    const authError = params.get("auth_error");
    const billing = params.get("billing");
    const newsletter = params.get("newsletter");
    const resetToken = params.get("reset_token");
    if (authCode || authError || billing || newsletter || resetToken) {
      window.history.replaceState({}, document.title, window.location.pathname);
    }
    if (authCode) {
      try {
        const res = await fetch("/api/auth/oauth/exchange", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ code: authCode }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Login failed");
        storeSession(data);
        showAlert(t(`¡Hola ${data.full_name}! Sesión iniciada.`, `Hi ${data.full_name}! You're signed in.`), "success");
      } catch (err) {
        showAlert(err.message);
      }
    } else if (authError) {
      showAlert(t("No se pudo iniciar sesión con el proveedor. Intenta de nuevo.", "Could not sign in with that provider. Please try again."));
    }
    if (newsletter) {
      const msgs = {
        confirmed: [t("¡Listo! Ya estás suscrito al boletín de Apex Vox.", "Done! You're subscribed to the Apex Vox newsletter."), "success"],
        unsubscribed: [t("Te diste de baja del boletín.", "You've unsubscribed from the newsletter."), "success"],
        invalid: [t("El enlace del boletín no es válido o expiró.", "The newsletter link is invalid or expired."), "error"],
      };
      const m = msgs[newsletter];
      if (m) showAlert(m[0], m[1]);
    }
    if (resetToken && authDialog) {
      state.resetToken = resetToken;
      setAuthMode("reset");
      authDialog.showModal();
    }
    if (billing === "return" && state.token) {
      switchView("portal");
      await confirmBoldPayments(true);
    }
  }

  function showAlert(message, type = "error") {
    alertBox.textContent = message;
    alertBox.className = `alert-box ${type === "success" ? "alert-success" : "alert-error"}`;
    alertBox.classList.remove("hidden");
  }

  function hideAlert() {
    alertBox.classList.add("hidden");
  }

  function escapeHtml(str) {
    return String(str || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  // ---------------------------------------------------------------------------
  // Auth, User Portal & Bold API Subscription
  // ---------------------------------------------------------------------------

  async function handleRegisterUser() {
    const nameEl = document.getElementById("auth-name-input");
    const emailEl = document.getElementById("auth-email-input");
    const pwdEl = document.getElementById("auth-password-input");
    const fbBox = document.getElementById("auth-feedback-box");

    try {
      const res = await fetch("/api/auth/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email: emailEl.value.trim(),
          password: pwdEl.value,
          full_name: nameEl.value.trim(),
          preferred_language: state.lang,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || t("Error al registrar la cuenta.", "Could not create the account."));

      storeSession(data);
      if (authDialog) authDialog.close();
      showAlert(
        state.lang === "en"
          ? `Welcome ${data.full_name}! You have 2 free hours/day; we store your work for 24 hours.`
          : `¡Bienvenido ${data.full_name}! Tienes 2 horas gratis al día; guardamos tu trabajo por 24 horas.`,
        "success"
      );
      loadUserPortalSummary();
    } catch (err) {
      if (fbBox) {
        fbBox.textContent = err.message;
        fbBox.className = "alert-box alert-error";
        fbBox.classList.remove("hidden");
      }
    }
  }

  async function handleLoginUser() {
    const emailEl = document.getElementById("auth-email-input");
    const pwdEl = document.getElementById("auth-password-input");
    const fbBox = document.getElementById("auth-feedback-box");

    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email: emailEl.value.trim(),
          password: pwdEl.value,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || t("Correo o contraseña incorrectos.", "Wrong email or password."));

      storeSession(data);
      if (authDialog) authDialog.close();
      loadUserPortalSummary();
    } catch (err) {
      if (fbBox) {
        fbBox.textContent = err.message;
        fbBox.className = "alert-box alert-error";
        fbBox.classList.remove("hidden");
      }
    }
  }

  // Abre la sección de pago de "Mi cuenta" (sin prueba gratis: Apex Pro se activa pagando).
  function openProCheckout() {
    if (!requireSession(t(
      "Crea tu cuenta o inicia sesión para activar Apex Pro. Si pagas en tus primeras 24 horas, tu primer mes tiene 20% de descuento.",
      "Create your account or sign in to activate Apex Pro. Pay within your first 24 hours and your first month is 20% off."
    ))) return;
    switchView("portal");
    loadBillingOffer();
    const card = document.getElementById("billing-offer-box");
    if (card) card.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  function formatUsd(value) {
    const n = Number(value) || 0;
    return Number.isInteger(n) ? `USD ${n}` : `USD ${n.toFixed(2)}`;
  }

  let promoCountdownTimer = null;

  async function loadBillingOffer() {
    const box = document.getElementById("billing-offer-box");
    const payBtn = document.getElementById("portal-generate-bold-link-btn");
    if (!box) return;
    if (!state.token) {
      box.innerHTML = `<div class="billing-offer-price">${formatUsd(state.config.pro_price_usd || 10)} <span>/ ${state.config.pro_period_days || 30} ${t("días", "days")}</span></div>
        <p class="billing-offer-note">${t("Inicia sesión para ver tu precio. Si pagas en tus primeras 24 horas, el primer mes tiene 20% de descuento.", "Sign in to see your price. Pay within your first 24 hours and the first month is 20% off.")}</p>`;
      return;
    }
    try {
      const res = await authFetch("/api/billing/offer");
      const offer = await res.json();
      if (!res.ok) throw new Error(offer.detail || "");
      if (promoCountdownTimer) clearInterval(promoCountdownTimer);
      if (offer.promo_eligible) {
        box.innerHTML = `
          <div class="billing-offer-badge">${t(`${offer.discount_pct}% de descuento · primer mes`, `${offer.discount_pct}% off · first month`)}</div>
          <div class="billing-offer-price">${formatUsd(offer.price)} <s>${formatUsd(offer.regular_price)}</s> <span>/ ${offer.period_days} ${t("días", "days")}</span></div>
          <p class="billing-offer-note">${t("La promoción termina en", "The promo ends in")} <strong id="promo-countdown">—</strong>. ${t(`Después, ${formatUsd(offer.regular_price)} al mes.`, `After that, ${formatUsd(offer.regular_price)} a month.`)}</p>`;
        const ends = new Date(offer.promo_ends_at).getTime();
        const tick = () => {
          const el = document.getElementById("promo-countdown");
          const left = Math.max(0, Math.floor((ends - Date.now()) / 1000));
          if (el) el.textContent = `${String(Math.floor(left / 3600)).padStart(2, "0")}:${String(Math.floor((left % 3600) / 60)).padStart(2, "0")}:${String(left % 60).padStart(2, "0")}`;
          if (left === 0) { clearInterval(promoCountdownTimer); loadBillingOffer(); }
        };
        tick();
        promoCountdownTimer = setInterval(tick, 1000);
      } else {
        const why = {
          first_month_only: t("La promoción aplica solo al primer mes.", "The promo applies to the first month only."),
          window_expired: t("La promoción de las primeras 24 horas ya terminó.", "The first-24-hours promo has ended."),
          ip_used_this_quarter: t("Esta red ya usó una promoción en los últimos 90 días.", "This network already used a promo in the last 90 days."),
        }[offer.promo_reason] || "";
        box.innerHTML = `
          <div class="billing-offer-price">${formatUsd(offer.price)} <span>/ ${offer.period_days} ${t("días", "days")}</span></div>
          <p class="billing-offer-note">${escapeHtml(why)}</p>`;
      }
      if (payBtn) payBtn.textContent = t(`Pagar ${formatUsd(offer.price)} con Bold`, `Pay ${formatUsd(offer.price)} with Bold`);
    } catch (err) {
      box.innerHTML = `<p class="billing-offer-note">${escapeHtml(err.message || t("No se pudo cargar el precio.", "Could not load the price."))}</p>`;
    }
  }

  async function startBoldCheckout() {
    if (!requireSession(t(
      "Inicia sesión para pagar Apex Pro con Bold.",
      "Sign in to pay for Apex Pro with Bold."
    ))) return;
    const previewEl = document.getElementById("bold-checkout-preview");
    try {
      const res = await authFetch("/api/billing/checkout", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ currency: "USD" }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || t("No se pudo crear el link de pago.", "Could not create the payment link."));
      if (previewEl) {
        previewEl.classList.remove("hidden");
        previewEl.innerHTML = `
          <div><strong>${t("Referencia", "Reference")}</strong> <code>${escapeHtml(data.order_id)}</code></div>
          <div><strong>${t("Monto", "Amount")}</strong> ${escapeHtml(data.amount_display)}</div>
          <div class="bold-checkout-link">${t("Redirigiendo a Bold…", "Redirecting to Bold…")}</div>
        `;
      }
      if (/^https:\/\/checkout\.bold\.co\//.test(data.checkout_url)) {
        window.location.assign(data.checkout_url);
      }
    } catch (err) {
      showAlert(err.message);
    }
  }

  async function confirmBoldPayments(fromRedirect) {
    if (!state.token) return;
    try {
      const res = await authFetch("/api/billing/confirm", { method: "POST" });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "");
      const wasPaid = state.plan === "pro";
      storeSession(data);
      await loadUserPortalSummary();
      if (fromRedirect) {
        showAlert(
          data.quota && data.quota.pro_until && data.plan !== "free"
            ? t("¡Pago recibido! Apex Pro está activo.", "Payment received! Apex Pro is active.")
            : t("Estamos esperando la confirmación de Bold. Si ya pagaste, se activará en unos minutos.",
                "Waiting for Bold's confirmation. If you already paid, it will activate in a few minutes."),
          data.plan !== "free" || wasPaid ? "success" : "error"
        );
      }
    } catch (err) {
      if (fromRedirect) showAlert(err.message);
    }
  }

  async function refreshSummaAccess() {
    if (!state.currentResult) return;
    try {
      const res = await authFetch(`/api/jobs/${state.currentResult.job_id}/summa?lang=${state.lang}`);
      if (!res.ok) return;
      state.currentResult.summa_report = await res.json();
      renderApexSumma(state.currentResult);
    } catch (err) {
      /* keep current report */
    }
  }

  async function loadAccountExtras() {
    if (!state.token) return;
    try {
      const sec = await authFetch("/api/auth/security");
      if (sec.ok) {
        const data = await sec.json();
        const el = document.getElementById("portal-kpi-networks");
        if (el) el.textContent = `${data.used} / ${data.limit}`;
      }
    } catch (err) { /* ignore */ }
    const planEl = document.getElementById("portal-kpi-plan");
    if (planEl && state.user && state.user.quota) planEl.textContent = planLabel(state.user.quota);
    await loadTelegramStatus();
  }

  async function loadTelegramStatus() {
    const statusEl = document.getElementById("tg-status");
    const linkBtn = document.getElementById("tg-link-btn");
    const unlinkBtn = document.getElementById("tg-unlink-btn");
    if (!statusEl || !state.token) return;
    try {
      const res = await authFetch("/api/telegram/link");
      if (!res.ok) return;
      const st = await res.json();
      if (!st.configured) {
        statusEl.textContent = t("El bot de Telegram estará disponible pronto.", "The Telegram bot is coming soon.");
      } else if (st.linked) {
        statusEl.textContent = t(`Vinculado a @${st.telegram_username || "tu chat"}. Envíale audios al bot.`, `Linked to @${st.telegram_username || "your chat"}. Send audio to the bot.`);
      } else if (!st.eligible) {
        statusEl.textContent = t("Disponible con Apex Pro.", "Available with Apex Pro.");
      } else {
        statusEl.textContent = t("Sin vincular.", "Not linked.");
      }
      if (linkBtn) linkBtn.classList.toggle("hidden", !st.configured || st.linked);
      if (unlinkBtn) unlinkBtn.classList.toggle("hidden", !st.linked);
    } catch (err) { /* ignore */ }
  }

  async function createTelegramCode() {
    const box = document.getElementById("tg-code-box");
    try {
      const res = await authFetch("/api/telegram/link-code", { method: "POST" });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Error");
      if (box) {
        box.classList.remove("hidden");
        const link = data.deep_link
          ? `<a class="text-link-strong" href="${escapeHtml(data.deep_link)}" target="_blank" rel="noopener noreferrer">${t("Abrir el bot en Telegram", "Open the bot in Telegram")}</a>`
          : "";
        box.innerHTML = `
          <div><strong>${t("Código", "Code")}</strong> <code>${escapeHtml(data.code)}</code></div>
          <div>${t(`Envía <code>/start ${escapeHtml(data.code)}</code> al bot. Vence en ${data.expires_in_minutes} minutos.`, `Send <code>/start ${escapeHtml(data.code)}</code> to the bot. Expires in ${data.expires_in_minutes} minutes.`)}</div>
          <div class="bold-checkout-link">${link}</div>`;
      }
    } catch (err) {
      showAlert(err.message);
    }
  }

  async function unlinkTelegram() {
    await authFetch("/api/telegram/link", { method: "DELETE" });
    const box = document.getElementById("tg-code-box");
    if (box) box.classList.add("hidden");
    loadTelegramStatus();
  }

  async function deleteAccount() {
    const ok = window.confirm(t(
      "¿Eliminar tu cuenta y todos sus datos (historial, perfiles de voz, vinculación de Telegram)? Esta acción no se puede deshacer.",
      "Delete your account and all its data (history, voice profiles, Telegram link)? This cannot be undone."
    ));
    if (!ok) return;
    const res = await authFetch("/api/auth/account", { method: "DELETE" });
    if (res.ok) {
      clearSession();
      switchView("landing");
      showAlert(t("Tu cuenta y sus datos fueron eliminados.", "Your account and its data were deleted."), "success");
    } else {
      const data = await res.json().catch(() => ({}));
      showAlert(data.detail || "Error");
    }
  }

  // --- password recovery ---------------------------------------------------------
  function setAuthMode(mode) {
    const show = (id, on) => { const el = document.getElementById(id); if (el) el.classList.toggle("hidden", !on); };
    show("auth-name-group", mode === "register");
    show("auth-email-group", mode !== "reset");
    show("auth-password-group", mode !== "forgot");
    show("auth-main-actions", mode === "register");
    show("auth-forgot-actions", mode === "forgot");
    show("auth-reset-actions", mode === "reset");
    show("forgot-password-btn", mode === "register");
    show("oauth-options", mode === "register" && (state.config.oauth_providers || []).length > 0);
    const title = document.getElementById("auth-dialog-title");
    if (title) {
      title.textContent = mode === "forgot"
        ? t("Recupera tu contraseña", "Recover your password")
        : mode === "reset"
          ? t("Elige una nueva contraseña", "Choose a new password")
          : (I18N[state.lang] || I18N.es).auth_modal_title;
    }
    state.authMode = mode;
  }

  async function submitForgotPassword() {
    const email = document.getElementById("auth-email-input").value.trim();
    const fb = document.getElementById("auth-feedback-box");
    await fetch("/api/auth/password/forgot", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, lang: state.lang }),
    }).catch(() => null);
    if (fb) {
      fb.textContent = t("Si el correo tiene una cuenta, te enviamos un enlace para restablecer la contraseña.", "If that email has an account, we sent a reset link.");
      fb.className = "alert-box alert-success";
    }
  }

  async function submitResetPassword() {
    const password = document.getElementById("auth-password-input").value;
    const fb = document.getElementById("auth-feedback-box");
    try {
      const res = await fetch("/api/auth/password/reset", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token: state.resetToken || "", password }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Error");
      storeSession(data);
      state.resetToken = null;
      if (authDialog) authDialog.close();
      setAuthMode("register");
      showAlert(t("Contraseña actualizada. Cerramos tus otras sesiones.", "Password updated. Your other sessions were signed out."), "success");
    } catch (err) {
      if (fb) { fb.textContent = err.message; fb.className = "alert-box alert-error"; }
    }
  }

  // --- newsletter -------------------------------------------------------------------
  async function submitNewsletter(e) {
    e.preventDefault();
    const input = document.getElementById("newsletter-email");
    const fb = document.getElementById("newsletter-feedback");
    try {
      const res = await fetch("/api/newsletter/subscribe", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: input.value.trim(), lang: state.lang }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Error");
      if (fb) fb.textContent = t("Revisa tu correo y confirma la suscripción.", "Check your inbox to confirm your subscription.");
      input.value = "";
    } catch (err) {
      if (fb) fb.textContent = err.message;
    }
  }

  const botStatusLabel = (status) => ({
    scheduled: t("Programado", "Scheduled"), joining: t("Entrando", "Joining"), waiting_room: t("En sala de espera", "In waiting room"),
    recording: t("Grabando", "Recording"), processing: t("Procesando", "Processing"), done: t("Listo", "Done"),
    failed: t("Falló", "Failed"), cancelled: t("Cancelado", "Cancelled"),
  }[status] || status);

  async function loadMeetingBots() {
    const list = document.getElementById("bot-list");
    if (!list) return;
    if (!state.token) {
      list.innerHTML = `<li class="track-item track-item--static">${t("Inicia sesión para usar el bot.", "Sign in to use the bot.")}</li>`;
      return;
    }
    try {
      const res = await authFetch("/api/meetings");
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "");
      const addr = document.getElementById("bot-invite-address");
      if (addr && data.invites_address) addr.textContent = data.invites_address;
      const hint = document.getElementById("bot-invite-hint");
      if (hint) hint.classList.toggle("hidden", !data.invites_address);
      const rows = [];
      (data.events || []).forEach((e) => {
        if (e.bot_id) return;
        rows.push(`<li class="track-item"><div class="track-meta"><div class="track-name">${escapeHtml(e.title)}</div>
          <div class="track-sub"><span>${escapeHtml(new Date(e.start).toLocaleString())}</span><span>${e.meeting_url ? t("Sin bot", "No bot") : t("Sin enlace de reunión", "No meeting link")}</span></div></div></li>`);
      });
      (data.bots || []).forEach((b) => {
        const when = b.join_at ? new Date(b.join_at).toLocaleString() : new Date(b.created_at).toLocaleString();
        const link = b.job_id ? ` · <a class="text-link-strong" href="/?job=${encodeURIComponent(b.job_id)}">${t("Ver resumen", "View summary")}</a>` : "";
        rows.push(`<li class="track-item"><div class="track-meta"><div class="track-name">${escapeHtml(b.title)}</div>
          <div class="track-sub"><span>${escapeHtml(when)}</span><span>${escapeHtml(botStatusLabel(b.status))}${link}</span></div></div></li>`);
      });
      list.innerHTML = rows.join("") || `<li class="track-item track-item--static">${t("Aún no has enviado el bot.", "You haven't sent the bot yet.")}</li>`;
    } catch (err) {
      list.innerHTML = "";
    }
  }

  async function sendMeetingBot() {
    if (!requireSession(t("Inicia sesión para usar el bot.", "Sign in to use the bot."))) return;
    const input = document.getElementById("bot-url-input");
    const alertBox = document.getElementById("bot-alert");
    const title = (document.getElementById("box-title-input") || {}).value || "";
    try {
      const res = await authFetch("/api/meetings/bot", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ meeting_url: input.value.trim(), title: title.trim() || null }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || t("No se pudo enviar el bot.", "Could not send the bot."));
      alertBox.className = "alert-box alert-success";
      alertBox.textContent = t("El bot va en camino. Acéptalo en la reunión si te lo pide.", "The bot is on its way. Admit it if asked.");
      input.value = "";
      loadMeetingBots();
    } catch (err) {
      alertBox.className = "alert-box alert-error";
      alertBox.textContent = err.message;
    }
  }

  async function loadMcpConnections() {
    const info = document.getElementById("mcp-connections");
    const revokeBtn = document.getElementById("mcp-revoke-btn");
    if (!info) return;
    if (!state.token) {
      info.textContent = t("Inicia sesión para conectar tus apps.", "Sign in to connect your apps.");
      if (revokeBtn) revokeBtn.classList.add("hidden");
      return;
    }
    try {
      const res = await authFetch("/api/mcp/connections");
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "");
      const urlInput = document.getElementById("mcp-url-input");
      if (urlInput && data.mcp_url) urlInput.value = data.mcp_url;
      const names = (data.connections || []).map((c) => c.client_name);
      info.textContent = names.length
        ? t(`Apps conectadas: ${names.join(", ")}`, `Connected apps: ${names.join(", ")}`)
        : t("Apps conectadas: ninguna todavía.", "Connected apps: none yet.");
      if (revokeBtn) revokeBtn.classList.toggle("hidden", !names.length);
    } catch (err) {
      info.textContent = t("No se pudieron cargar las apps conectadas.", "Could not load connected apps.");
    }
  }

  async function loadUserPortalSummary() {
    loadMcpConnections();
    try {
      const res = await authFetch("/api/portal/summary");
      if (!res.ok) return;
      const data = await res.json();

      const nameEl = document.getElementById("portal-user-name");
      const emailEl = document.getElementById("portal-user-email");
      const badgeEl = document.getElementById("portal-plan-badge");
      const retEl = document.getElementById("portal-retention-label");
      const qNumbers = document.getElementById("portal-quota-numbers");
      const qBar = document.getElementById("portal-quota-bar");
      loadAccountExtras();
      const kpiRet = document.getElementById("portal-kpi-retention");
      const kpiCount = document.getElementById("portal-kpi-jobs-count");
      const histList = document.getElementById("portal-history-list");

      if (nameEl) nameEl.textContent = data.user.full_name;
      if (emailEl) emailEl.textContent = data.user.email;
      if (badgeEl) badgeEl.textContent = planLabel(data.quota);
      if (retEl) retEl.textContent = data.quota.is_unlimited ? t("Sin límite de tiempo (Apex Pro)", "No time limit (Apex Pro)") : t("24 horas (Plan gratis)", "24 hours (Free plan)");
      if (kpiRet) kpiRet.textContent = data.quota.is_unlimited ? t("Ilimitado", "Unlimited") : t("24 horas", "24 hours");
      if (kpiCount) kpiCount.textContent = String((data.transcriptions || []).length);

      if (qNumbers && qBar) {
        if (data.quota.is_unlimited) {
          qNumbers.textContent = `${formatSecondsHHMMSS(data.quota.used_today_seconds)} / ∞ (Ilimitado)`;
          qBar.style.width = "100%";
        } else {
          const used = Number(data.quota.used_today_seconds) || 0;
          const limit = Number(data.quota.daily_limit_seconds) || 7200;
          qNumbers.textContent = `${formatSecondsHHMMSS(used)} / ${formatSecondsHHMMSS(limit)} (${t("2 h gratis", "2 h free")})`;
          qBar.style.width = `${Math.min(100, Math.max(3, (used / limit) * 100))}%`;
        }
      }

      if (histList) {
        histList.innerHTML = "";
        const items = data.transcriptions || [];
        if (items.length === 0) {
          histList.innerHTML = `<li class="track-item track-item--static">${t("Aún no tienes transcripciones. Ve a Studio para transcribir tus audios.", "No transcripts yet. Go to Studio to transcribe your audio.")}</li>`;
        } else {
          items.forEach((rec) => {
            const li = document.createElement("li");
            li.className = "track-item";
            li.style.cursor = "pointer";
            li.innerHTML = `
              <div class="track-top">
                <span class="track-order-badge">${escapeHtml(rec.engine_brand || "Mc-Lewis")}</span>
                <span class="track-name">Job ${escapeHtml(rec.job_id)} — Orador principal: ${escapeHtml(rec.dominant_speaker || "Hablante 1")}</span>
                <span class="meta-tag timeline">${rec.retention_policy === "unlimited" ? t("Almacenado · sin límite", "Stored · no limit") : t("Almacenado · 24 h", "Stored · 24 h")}</span>
              </div>
              <div class="track-meta">
                <span class="meta-tag">Duración: ${escapeHtml(rec.total_duration_formatted || "00:00:00")}</span>
                <span class="meta-tag">Oradores: ${rec.detected_speakers_count || 1}</span>
              </div>
            `;
            li.addEventListener("click", () => {
              switchView("playground");
              loadJobResult(rec.job_id);
            });
            histList.appendChild(li);
          });
        }
      }
    } catch (err) {
      console.warn("Portal summary load warning:", err);
    }
  }

  // ---------------------------------------------------------------------------
  // Health Check & Voice Profiles Init
  // ---------------------------------------------------------------------------

  async function checkSystemHealth() {
    try {
      const res = await fetch("/api/health");
      const data = await res.json();
      if (data.status === "ok") {
        healthDot.className = "status-dot";
        healthText.textContent =
          state.lang === "en" ? "Powered by Groq · Active" : "Potenciado por Groq · Activo";
      } else {
        healthDot.className = "status-dot warn";
        healthText.textContent = "Sistema Parcial";
      }
    } catch (err) {
      healthDot.className = "status-dot warn";
      healthText.textContent = t("Sin conexión", "Offline");
    }
  }

  async function loadVoiceProfiles() {
    try {
      if (!state.token) {
        state.voiceProfiles = [];
        renderVoiceProfiles();
        return;
      }
      const res = await authFetch("/api/voice-profiles");
      if (res.ok) {
        state.voiceProfiles = await res.json();
        renderVoiceProfiles();
      }
    } catch (err) {
      console.warn("Could not load voice profiles:", err);
    }
  }

  function renderVoiceProfiles() {
    voiceProfilesListEl.innerHTML = "";
    if (!state.voiceProfiles || state.voiceProfiles.length === 0) return;

    state.voiceProfiles.forEach((prof) => {
      const li = document.createElement("li");
      li.className = "track-item";
      li.style.cursor = "default";
      li.innerHTML = `
        <div class="track-top">
          <span class="track-order-badge track-order-badge--voice">Voz</span>
          <span class="track-name">${escapeHtml(prof.name)}</span>
          <button type="button" class="icon-btn danger delete-vp-btn" title="Eliminar perfil">×</button>
        </div>
        <div class="track-meta">
          <span class="meta-tag">Tono: ~${Number(prof.pitch_hz || 0).toFixed(0)} Hz</span>
          <span class="meta-tag">Muestra: ${Number(prof.sample_duration_sec || 0).toFixed(1)}s</span>
          <span class="meta-tag timeline">Huella Activa</span>
        </div>
      `;
      li.querySelector(".delete-vp-btn").addEventListener("click", async () => {
        const res = await authFetch(`/api/voice-profiles/${prof.profile_id}`, {
          method: "DELETE",
        });
        if (res.ok) {
          state.voiceProfiles = await res.json();
          renderVoiceProfiles();
        }
      });
      voiceProfilesListEl.appendChild(li);
    });
  }

  async function handleEnrollVoiceProfile() {
    const name = vpNameInput.value.trim();
    const file = vpFileInput.files && vpFileInput.files[0];
    if (!name || !file) {
      showAlert("Ingresa el nombre del orador y selecciona un archivo de muestra de su voz.");
      return;
    }

    hideAlert();
    enrollVpBtn.disabled = true;
    const formData = new FormData();
    formData.append("name", name);
    formData.append("file", file);

    try {
      const res = await authFetch("/api/voice-profiles", {
        method: "POST",
        body: formData,
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || t("No se pudo guardar el perfil de voz.", "Could not save the voice profile."));
      vpNameInput.value = "";
      vpFileInput.value = "";
      await loadVoiceProfiles();
      showAlert(`Perfil de voz '${data.name}' registrado en Apex Vox.`, "success");
    } catch (err) {
      showAlert(err.message);
    } finally {
      enrollVpBtn.disabled = false;
    }
  }

  // ---------------------------------------------------------------------------
  // Upload & Queue Rendering
  // ---------------------------------------------------------------------------

  async function uploadFiles(fileList) {
    if (!fileList || fileList.length === 0) return;
    hideAlert();

    const formData = new FormData();
    for (const file of fileList) {
      formData.append("files", file);
    }
    if (state.sessionId) {
      formData.append("session_id", state.sessionId);
    }

    transcribeBtn.disabled = true;
    dropzone.classList.add("drag-active");

    try {
      const res = await authFetch("/api/upload", {
        method: "POST",
        body: formData,
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || t("No se pudieron subir los audios.", "Could not upload the audio files."));

      state.sessionId = data.session_id;
      state.files = data.files || [];
      state.sessionMediaToken = data.media_token || state.sessionMediaToken;
      renderTrackQueue();
    } catch (err) {
      showAlert(err.message || "Error subiendo archivos.");
    } finally {
      dropzone.classList.remove("drag-active");
      transcribeBtn.disabled = state.files.length === 0;
      fileInput.value = "";
    }
  }

  function renderTrackQueue() {
    trackListEl.innerHTML = "";
    const count = state.files.length;

    if (count === 0) {
      queueSummaryEl.classList.add("hidden");
      reorderHintEl.classList.add("hidden");
      clearQueueBtn.classList.add("hidden");
      transcribeBtn.disabled = true;
      return;
    }

    queueSummaryEl.classList.remove("hidden");
    reorderHintEl.classList.remove("hidden");
    clearQueueBtn.classList.remove("hidden");
    transcribeBtn.disabled = false;

    let cumulativeSec = 0;
    const isEn = state.lang === "en";

    state.files.forEach((file, index) => {
      const startOffset = cumulativeSec;
      const endOffset = cumulativeSec + (Number(file.duration_sec) || 0);
      cumulativeSec = endOffset;

      const li = document.createElement("li");
      li.className = "track-item";
      li.draggable = true;
      li.dataset.index = String(index);
      li.dataset.fileId = file.file_id;

      const timelineLabel = `${formatSecondsHHMMSS(startOffset)} → ${formatSecondsHHMMSS(endOffset)}`;
      const chunkLabel = file.is_over_25mb
        ? `<span class="meta-tag chunk-warn">Auto-Chunk &lt;25MB</span>`
        : `<span class="meta-tag">Almacenado</span>`;
      const audioSrc = withMediaToken(
        `/api/sessions/${encodeURIComponent(state.sessionId)}/files/${encodeURIComponent(file.file_id)}/audio`,
        state.sessionMediaToken
      );
      const listenLabel = isEn ? "Listen" : "Escuchar";
      const pauseLabel = isEn ? "Pause" : "Pausar";

      li.innerHTML = `
        <div class="track-top">
          <span class="drag-handle" title="${isEn ? "Drag to reorder audio" : "Arrastra para cambiar el orden del audio"}">⠿</span>
          <span class="track-order-badge" title="${t("Posición en la secuencia", "Position in the sequence")}">#${index + 1}</span>
          <span class="track-name" title="${escapeHtml(file.filename)}">${escapeHtml(file.filename)}</span>
          <div class="track-controls">
            <button type="button" class="icon-btn move-up-btn" title="${t("Subir", "Move up")}" ${index === 0 ? "disabled" : ""}>↑</button>
            <button type="button" class="icon-btn move-down-btn" title="${t("Bajar", "Move down")}" ${index === count - 1 ? "disabled" : ""}>↓</button>
            <button type="button" class="icon-btn danger remove-track-btn" title="Eliminar audio">×</button>
          </div>
        </div>
        <div class="track-meta">
          <span class="meta-tag">${escapeHtml((file.format || "audio").toUpperCase())}</span>
          <span class="meta-tag">${formatBytes(file.size_bytes)}</span>
          <span class="meta-tag">${Number(file.duration_sec).toFixed(1)}s</span>
          <span class="meta-tag timeline">${timelineLabel}</span>
          ${chunkLabel}
        </div>
        <div class="track-preview-row">
          <button type="button" class="track-play-btn" title="${isEn ? "Play/Pause this track to verify order" : "Escuchar/Pausar este audio para verificar el orden"}">${listenLabel}</button>
          <audio class="track-audio-preview" controls preload="metadata" src="${audioSrc}"></audio>
        </div>
      `;

      const previewRow = li.querySelector(".track-preview-row");
      const controlsRow = li.querySelector(".track-controls");
      const playToggleBtn = li.querySelector(".track-play-btn");
      const audioEl = li.querySelector(".track-audio-preview");

      // Prevent scrubbing the audio player or clicking buttons from triggering HTML5 card drag
      [previewRow, controlsRow].forEach((zone) => {
        if (!zone) return;
        zone.addEventListener("mousedown", () => {
          li.draggable = false;
        });
        zone.addEventListener("mouseup", () => {
          li.draggable = true;
        });
        zone.addEventListener("mouseleave", () => {
          li.draggable = true;
        });
      });

      playToggleBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        if (audioEl.paused) {
          audioEl.play().catch(() => {});
        } else {
          audioEl.pause();
        }
      });

      audioEl.addEventListener("play", () => {
        // Pause all other preview players so only one track plays at a time
        trackListEl.querySelectorAll(".track-audio-preview").forEach((otherAudio) => {
          if (otherAudio !== audioEl && !otherAudio.paused) {
            otherAudio.pause();
          }
        });
        li.classList.add("playing");
        playToggleBtn.textContent = pauseLabel;
      });

      audioEl.addEventListener("pause", () => {
        li.classList.remove("playing");
        playToggleBtn.textContent = listenLabel;
      });

      audioEl.addEventListener("ended", () => {
        li.classList.remove("playing");
        playToggleBtn.textContent = listenLabel;
        // If sequential preview mode is active, advance to the next ordered track
        if (state.playingSequence) {
          const nextLi = trackListEl.querySelector(`li.track-item[data-index="${index + 1}"]`);
          if (nextLi) {
            const nextAudio = nextLi.querySelector(".track-audio-preview");
            if (nextAudio) {
              nextAudio.currentTime = 0;
              nextAudio.play().catch(() => {});
              return;
            }
          }
          state.playingSequence = false;
        }
      });

      li.querySelector(".move-up-btn").addEventListener("click", (e) => {
        e.stopPropagation();
        moveTrack(index, index - 1);
      });
      li.querySelector(".move-down-btn").addEventListener("click", (e) => {
        e.stopPropagation();
        moveTrack(index, index + 1);
      });
      li.querySelector(".remove-track-btn").addEventListener("click", (e) => {
        e.stopPropagation();
        removeTrack(file.file_id);
      });

      li.addEventListener("dragstart", (e) => {
        state.dragSrcIndex = index;
        li.classList.add("dragging");
        e.dataTransfer.effectAllowed = "move";
        try {
          e.dataTransfer.setData("text/plain", String(index));
        } catch (_) {}
      });
      li.addEventListener("dragend", () => {
        li.classList.remove("dragging");
        trackListEl.querySelectorAll(".track-item").forEach((item) => {
          item.classList.remove("drag-over-target");
        });
        state.dragSrcIndex = null;
      });
      li.addEventListener("dragenter", (e) => {
        e.preventDefault();
        if (state.dragSrcIndex !== null && state.dragSrcIndex !== index) {
          li.classList.add("drag-over-target");
        }
      });
      li.addEventListener("dragover", (e) => {
        e.preventDefault();
        e.dataTransfer.dropEffect = "move";
        if (state.dragSrcIndex !== null && state.dragSrcIndex !== index) {
          li.classList.add("drag-over-target");
        }
      });
      li.addEventListener("dragleave", () => {
        li.classList.remove("drag-over-target");
      });
      li.addEventListener("drop", (e) => {
        e.preventDefault();
        li.classList.remove("drag-over-target");
        if (state.dragSrcIndex !== null && state.dragSrcIndex !== index) {
          moveTrack(state.dragSrcIndex, index);
        }
      });

      trackListEl.appendChild(li);
    });

    queueCountLabel.textContent = `${count} archivo${count === 1 ? "" : "s"} en secuencia`;
    queueDurationLabel.textContent = `${t("Duración total", "Total duration")}: ${formatSecondsHHMMSS(cumulativeSec)}`;
  }

  async function moveTrack(fromIdx, toIdx) {
    if (toIdx < 0 || toIdx >= state.files.length) return;
    const updated = [...state.files];
    const [moved] = updated.splice(fromIdx, 1);
    updated.splice(toIdx, 0, moved);
    state.files = updated;
    renderTrackQueue();

    if (state.sessionId) {
      try {
        await fetch(`/api/sessions/${state.sessionId}/order`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            session_id: state.sessionId,
            file_order: state.files.map((f) => f.file_id),
          }),
        });
      } catch (err) {
        console.warn("Could not sync order with server:", err);
      }
    }
  }

  async function removeTrack(fileId) {
    if (!state.sessionId) return;
    try {
      const res = await fetch(`/api/sessions/${state.sessionId}/files/${fileId}`, {
        method: "DELETE",
      });
      if (res.ok) {
        const data = await res.json();
        state.files = data.files || [];
      state.sessionMediaToken = data.media_token || state.sessionMediaToken;
        renderTrackQueue();
      }
    } catch (err) {
      showAlert("No se pudo eliminar el archivo.");
    }
  }

  // ---------------------------------------------------------------------------
  // Transcription & Apex Summa Execution
  // ---------------------------------------------------------------------------

  async function startTranscription() {
    if (!state.sessionId || state.files.length === 0) {
      showAlert("Sube al menos un archivo de audio antes de transcribir.");
      return;
    }

    hideAlert();
    transcribeBtn.disabled = true;
    progressBox.classList.remove("hidden");
    const chosenEngine = engineSelect ? engineSelect.value : "Mc-Lewis";
    updateProgressUI(
      5,
      t(`Transcribiendo con ${chosenEngine}…`, `Transcribing with ${chosenEngine}…`)
    );

    const spkVal = speakersSelect.value;
    const numSpeakers = spkVal === "auto" ? null : parseInt(spkVal, 10);
    updateHeaderPlanPill();

    const payload = {
      session_id: state.sessionId,
      file_order: state.files.map((f) => f.file_id),
      model: chosenEngine,
      diarization_engine: chosenEngine,
      language: languageSelect.value === "auto" ? null : languageSelect.value,
      num_speakers: numSpeakers,
      prompt_hint: promptHintInput.value.trim() || null,
    };

    try {
      const res = await authFetch("/api/transcribe", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || t("No se pudo iniciar la transcripción.", "Could not start the transcription."));
      }

      state.currentJobId = data.job_id;
      pollJobStatus(data.job_id);
    } catch (err) {
      showAlert(err.message || "Error al iniciar la transcripción.");
      transcribeBtn.disabled = false;
      progressBox.classList.add("hidden");
    }
  }

  function updateProgressUI(pct, stepText, subText) {
    const clamped = Math.max(0, Math.min(100, Number(pct) || 0));
    progressPct.textContent = `${clamped}%`;
    progressBarFill.style.width = `${clamped}%`;
    if (stepText) progressStep.textContent = stepText;
    if (subText) progressSubtext.textContent = subText;
  }

  function pollJobStatus(jobId) {
    if (state.pollTimer) clearInterval(state.pollTimer);

    state.pollTimer = setInterval(async () => {
      try {
        const res = await authFetch(`/api/jobs/${jobId}/status`);
        const statusData = await res.json();
        if (!res.ok) {
          throw new Error(statusData.detail || t("No se pudo consultar el estado.", "Could not check the status."));
        }

        const chunkInfo =
          statusData.total_chunks > 0
            ? `Fragmentos procesados: ${statusData.completed_chunks}/${statusData.total_chunks} · Almacenando`
            : "Potenciado por Groq · Procesando audio e inteligencia Apex Summa...";

        updateProgressUI(statusData.progress, statusData.current_step, chunkInfo);

        if (statusData.status === "completed") {
          clearInterval(state.pollTimer);
          state.pollTimer = null;
          await loadJobResult(jobId);
          transcribeBtn.disabled = false;
        } else if (statusData.status === "failed") {
          clearInterval(state.pollTimer);
          state.pollTimer = null;
          showAlert(statusData.error || "El proceso de transcripción falló.");
          transcribeBtn.disabled = false;
        }
      } catch (err) {
        clearInterval(state.pollTimer);
        state.pollTimer = null;
        showAlert(err.message);
        transcribeBtn.disabled = false;
      }
    }, 900);
  }

  async function loadJobResult(jobId) {
    try {
      const res = await authFetch(`/api/jobs/${jobId}/result`);
      const result = await res.json();
      if (!res.ok) {
        throw new Error(result.detail || t("No se pudo obtener el resultado.", "Could not load the result."));
      }

      state.currentResult = result;
      state.selectedSpeaker = "ALL";
      renderResultView(result);
      showAlert(
        state.lang === "en"
          ? "Apex Vox Transcription & Apex Summa Intelligence Report completed!"
          : "¡Transcripción Apex Vox y Resumen Inteligente Apex Summa completados!",
        "success"
      );
    } catch (err) {
      showAlert(err.message);
    }
  }

  // ---------------------------------------------------------------------------
  // Result Viewer & APEX SUMMA 7-Part Intelligence Renderer
  // ---------------------------------------------------------------------------

  function renderResultView(result) {
    emptyResultState.classList.add("hidden");
    resultContainer.classList.remove("hidden");
    renameSpeakersBtn.classList.remove("hidden");

    kpiDuration.textContent =
      result.total_duration_formatted || formatSecondsHHMMSS(result.total_duration_sec);
    kpiSpeakers.textContent = String(result.detected_speakers_count || 1);
    if (kpiEngine) {
      kpiEngine.textContent =
        result.engine_brand ||
        ENGINE_LABELS[result.diarization_engine_used] ||
        "Mc-Lewis";
    }
    if (kpiFiles) {
      kpiFiles.textContent =
        result.plan === "guest"
          ? t("No se guarda", "Not saved")
          : result.plan === "free" ? t("24 horas", "24 hours") : t("Ilimitado", "Unlimited");
    }
    const isGuestResult = result.plan === "guest";
    const summaBox = document.getElementById("apex-summa-container");
    const guestCta = document.getElementById("guest-result-cta");
    if (summaBox) summaBox.classList.toggle("hidden", isGuestResult);
    if (guestCta) guestCta.classList.toggle("hidden", !isGuestResult);

    mergedAudioPlayer.src = withMediaToken(`/api/jobs/${result.job_id}/audio`, result.media_token);

    const jid = result.job_id;
    ["txt", "srt", "vtt", "json", "csv", "md"].forEach((fmt) => {
      document.getElementById(`export-${fmt}`).href = withMediaToken(`/api/jobs/${jid}/export/${fmt}`, result.media_token);
    });

    if (!isGuestResult) renderApexSumma(result);
    renderSpeakerTabs(result);
    renderSegmentsList(result);
  }

  function renderApexSumma(result) {
    const report = result.summa_report;
    if (!report) return;

    const isLocked = Boolean(report.is_locked);
    const lockedBanner = document.getElementById("summa-locked-banner");
    const unlockTopBtn = document.getElementById("unlock-summa-pro-btn");
    const contentBody = document.getElementById("summa-content-body");

    if (lockedBanner) lockedBanner.classList.toggle("hidden", !isLocked);
    if (unlockTopBtn) unlockTopBtn.classList.toggle("hidden", !isLocked);
    if (contentBody) {
      contentBody.style.opacity = isLocked ? "0.48" : "1";
      contentBody.style.pointerEvents = isLocked ? "none" : "auto";
    }

    // 1. Quién Habló Más
    const domCard = document.getElementById("summa-dominant-speaker-card");
    const spkBarsEl = document.getElementById("summa-speaker-bars");
    const stats = report.speaker_stats || [];

    if (domCard && stats.length > 0) {
      const top = stats[0];
      domCard.innerHTML = `
        <div class="dominant-speaker-title">
          ${escapeHtml(top.speaker)} lideró la conversación (${top.talk_percentage}%)
        </div>
        <div class="dominant-speaker-meta">
          Tiempo hablado: <strong>${escapeHtml(top.duration_formatted)}</strong> ·
          Palabras: <strong>${top.word_count}</strong> ·
          Intervenciones: <strong>${top.turn_count}</strong> ·
          Ritmo: <strong>${top.words_per_minute} pal/min</strong>
        </div>
      `;
    }

    if (spkBarsEl) {
      spkBarsEl.innerHTML = stats
        .map(
          (s) => `
          <div class="spk-stat-row">
            <div class="spk-stat-top">
              <span>${escapeHtml(s.speaker)}</span>
              <span>${s.talk_percentage}% (${escapeHtml(s.duration_formatted)} · ${s.word_count} pal.)</span>
            </div>
            <div class="spk-bar-track">
              <div class="spk-bar-fill" style="width: ${Math.max(4, s.talk_percentage)}%;"></div>
            </div>
          </div>
        `
        )
        .join("");
    }

    // 6. Gráficas de la Transcripción (SVG Donut + Timeline Density)
    const donutWrap = document.getElementById("summa-donut-chart-wrap");
    if (donutWrap && stats.length > 0) {
      const colors = ["#f43e01", "#4646dd", "#225c05", "#a2003f", "#a27900", "#0090a2"];
      let cumulativePct = 0;
      const circles = stats
        .map((s, idx) => {
          const pct = Number(s.talk_percentage) || 0;
          const dashArray = `${pct} ${100 - pct}`;
          const dashOffset = 25 - cumulativePct;
          cumulativePct += pct;
          return `<circle r="15.915" cx="21" cy="21" fill="transparent" stroke="${colors[idx % colors.length]}" stroke-width="5.5" stroke-dasharray="${dashArray}" stroke-dashoffset="${dashOffset}"></circle>`;
        })
        .join("");

      const legend = stats
        .map(
          (s, idx) => `
          <div class="chart-legend-row">
            <span class="chart-legend-swatch" style="background: ${colors[idx % colors.length]};"></span>
            <strong>${escapeHtml(s.speaker)}:</strong> ${s.talk_percentage}% (${s.turn_count} turnos)
          </div>
        `
        )
        .join("");

      donutWrap.innerHTML = `
        <svg width="96" height="96" viewBox="0 0 42 42" aria-label="Distribución de voz por orador">
          <circle r="15.915" cx="21" cy="21" fill="transparent" stroke="#e8e8de" stroke-width="5.5"></circle>
          ${circles}
        </svg>
        <div class="chart-legend">
          ${legend}
        </div>
      `;
    }

    const tlChart = document.getElementById("summa-timeline-chart");
    if (tlChart && report.charts && report.charts.timeline_density) {
      const pts = report.charts.timeline_density;
      const maxWords = Math.max(1, ...pts.map((p) => p.word_count || 1));
      tlChart.innerHTML = pts
        .map((p) => {
          const h = Math.max(10, Math.round(((p.word_count || 0) / maxWords) * 58));
          return `
            <div class="tl-bar-col" title="${escapeHtml(p.bucket_label)}: ${p.word_count} palabras (${escapeHtml(p.dominant_speaker)})">
              <span class="tl-bar-value">${p.word_count}w</span>
              <div class="tl-bar-visual" style="height: ${h}px;"></div>
              <span class="tl-bar-label">${escapeHtml(p.bucket_label)}</span>
            </div>
          `;
        })
        .join("");
    }

    // 2. De Qué se Habló
    const execSumEl = document.getElementById("summa-exec-summary");
    if (execSumEl) execSumEl.textContent = report.executive_summary || "";

    const topicsEl = document.getElementById("summa-topics-list");
    if (topicsEl) {
      topicsEl.innerHTML = (report.topics || [])
        .map(
          (t) => `
          <div class="topic-item-card">
            <div class="topic-item-head">
              <span>${escapeHtml(t.title)}</span>
              <span>${t.relevance_pct}%</span>
            </div>
            <div class="topic-item-body">${escapeHtml(t.summary)}</div>
          </div>
        `
        )
        .join("");
    }

    // 3. Objetivos
    const objEl = document.getElementById("summa-objectives-list");
    if (objEl) {
      objEl.innerHTML = (report.objectives || [])
        .map((o) => `<li>${escapeHtml(o)}</li>`)
        .join("");
    }

    // 4. Llamados de Atención
    const calloutsEl = document.getElementById("summa-callouts-list");
    if (calloutsEl) {
      calloutsEl.innerHTML = (report.callouts || [])
        .map(
          (c) => `
          <div class="callout-item-card">
            <div class="callout-item-title"><span class="callout-item-sev">${escapeHtml(c.severity.toUpperCase())}</span> ${escapeHtml(c.title)}</div>
            <div class="callout-item-body">${escapeHtml(c.description)}</div>
            <div class="callout-item-meta">
              ${escapeHtml(c.speaker)} · ${escapeHtml(c.timestamp)}
            </div>
          </div>
        `
        )
        .join("");
    }

    // 5. Próximas Tareas en Forma de Calendario
    const icsBtn = document.getElementById("summa-download-ics-btn");
    if (icsBtn) {
      icsBtn.href = withMediaToken(`/api/jobs/${result.job_id}/calendar.ics`, result.media_token);
      icsBtn.dataset.jobId = result.job_id;
    }
    const calGrid = document.getElementById("summa-calendar-grid");
    if (calGrid) {
      calGrid.innerHTML = (report.calendar_tasks || [])
        .map(
          (t) => `
          <div class="calendar-card">
            <div class="calendar-date-badge">${escapeHtml(t.due_date)} · ${escapeHtml(t.due_time)}</div>
            <div class="calendar-card-title">
              ${escapeHtml(t.title)}
            </div>
            <div class="calendar-card-body">
              ${escapeHtml(t.description)}
            </div>
            <div class="calendar-card-foot">
              <span>${escapeHtml(t.assignee)}</span>
              <span class="badge-pill ${t.priority === "alta" ? "warn" : "info"}">${escapeHtml(t.priority.toUpperCase())}</span>
            </div>
          </div>
        `
        )
        .join("");
    }
  }

  async function handleGenerateMinutes() {
    if (!state.currentResult) return;
    const tplSelect = document.getElementById("minutes-template-select");
    const orgInput = document.getElementById("minutes-org-input");
    const previewContainer = document.getElementById("minutes-preview-container");
    const dlBtn = document.getElementById("download-minutes-md-btn");
    const printBtn = document.getElementById("print-minutes-btn");

    const jid = state.currentResult.job_id;
    try {
      const res = await authFetch(`/api/jobs/${jid}/minutes`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          template_type: tplSelect ? tplSelect.value : "consejo",
          language: state.lang,
          organization_name: orgInput ? orgInput.value.trim() : "Apex Vox",
        }),
      });
      const doc = await res.json();
      if (!res.ok) throw new Error(doc.detail || t("No se pudo generar el acta.", "Could not generate the minutes."));

      state.currentMinutes = doc;
      if (previewContainer) {
        previewContainer.innerHTML = doc.html_content;
        previewContainer.classList.remove("hidden");
      }
      if (dlBtn) dlBtn.classList.remove("hidden");
      if (printBtn) printBtn.classList.remove("hidden");
    } catch (err) {
      showAlert(err.message);
    }
  }

  function downloadMinutesMarkdown() {
    if (!state.currentMinutes) return;
    const blob = new Blob([state.currentMinutes.markdown_content], {
      type: "text/markdown;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${state.currentMinutes.job_id}_acta_${state.currentMinutes.template_type}.md`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  function printMinutesDocument() {
    if (!state.currentMinutes) return;
    const win = window.open("", "_blank");
    if (!win) return;
    win.document.write(`
      <!DOCTYPE html>
      <html>
      <head>
        <meta charset="utf-8" />
        <title>${escapeHtml(state.currentMinutes.template_title)}</title>
        <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;500&family=Share+Tech+Mono&family=IBM+Plex+Mono:wght@400;500&display=swap" />
        <style>
          body { font-family: "IBM Plex Mono", ui-monospace, Menlo, monospace; padding: 32px; color: #2d2f33; line-height: 1.45; letter-spacing: -0.02em; }
          h1, h2, h3 { font-family: "Outfit", system-ui, sans-serif; font-weight: 500; letter-spacing: -0.023em; color: #302b28; margin-bottom: 4px; }
          h2 { border-bottom: 2px solid #f43e01; padding-bottom: 6px; }
          table { width: 100%; border-collapse: collapse; margin-top: 12px; }
          th, td { border: 1px solid #cecebf; padding: 8px; text-align: left; font-size: 13px; }
          th { background: #e8e8de; font-family: "Share Tech Mono", ui-monospace, monospace; text-transform: uppercase; letter-spacing: 0.08em; font-weight: 400; }
          .minutes-signatures { display: flex; justify-content: space-around; margin-top: 48px; text-align: center; }
        </style>
      </head>
      <body>${state.currentMinutes.html_content}</body>
      </html>
    `);
    win.document.close();
    win.focus();
    win.print();
  }

  // ---------------------------------------------------------------------------
  // Speaker Tabs, Segments & Renaming
  // ---------------------------------------------------------------------------

  function getUniqueSpeakers(result) {
    const seen = [];
    for (const seg of result.segments || []) {
      if (!seen.includes(seg.speaker)) {
        seen.push(seg.speaker);
      }
    }
    return seen;
  }

  function renderSpeakerTabs(result) {
    speakerTabsEl.innerHTML = "";
    const speakers = getUniqueSpeakers(result);

    const allBtn = document.createElement("button");
    allBtn.type = "button";
    allBtn.className = `speaker-tab ${state.selectedSpeaker === "ALL" ? "active" : ""}`;
    allBtn.textContent = `Todos (${(result.segments || []).length})`;
    allBtn.addEventListener("click", () => {
      state.selectedSpeaker = "ALL";
      renderSpeakerTabs(result);
      renderSegmentsList(result);
    });
    speakerTabsEl.appendChild(allBtn);

    speakers.forEach((spk) => {
      const count = (result.segments || []).filter((s) => s.speaker === spk).length;
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = `speaker-tab ${state.selectedSpeaker === spk ? "active" : ""}`;
      btn.textContent = `${spk} (${count})`;
      btn.addEventListener("click", () => {
        state.selectedSpeaker = spk;
        renderSpeakerTabs(result);
        renderSegmentsList(result);
      });
      speakerTabsEl.appendChild(btn);
    });
  }

  function renderSegmentsList(result) {
    segmentsListEl.innerHTML = "";
    const speakers = getUniqueSpeakers(result);
    const query = state.searchQuery.trim().toLowerCase();

    const filtered = (result.segments || []).filter((seg) => {
      if (state.selectedSpeaker !== "ALL" && seg.speaker !== state.selectedSpeaker) {
        return false;
      }
      if (query) {
        const hay = `${seg.text} ${seg.speaker} ${seg.source_file}`.toLowerCase();
        return hay.includes(query);
      }
      return true;
    });

    if (filtered.length === 0) {
      segmentsListEl.innerHTML = `
        <div class="empty-state empty-state--compact">
          No se encontraron segmentos que coincidan con el filtro actual.
        </div>
      `;
      return;
    }

    let lastSourceFile = null;

    filtered.forEach((seg) => {
      if (seg.source_file && seg.source_file !== lastSourceFile) {
        lastSourceFile = seg.source_file;
        const divider = document.createElement("div");
        divider.className = "file-divider";
        divider.innerHTML = `
          <span>Archivo #${(seg.file_order_index || 0) + 1}: ${escapeHtml(seg.source_file)}</span>
          <span>Inicio: ${seg.start_formatted}</span>
        `;
        segmentsListEl.appendChild(divider);
      }

      const spkIdx = Math.max(0, speakers.indexOf(seg.speaker));
      const badgeClass = `speaker-${spkIdx % 4}`;
      const cardAltClass = spkIdx % 2 === 1 ? "spk-alt" : "";

      const card = document.createElement("div");
      card.className = `segment-card ${cardAltClass}`;
      card.innerHTML = `
        <div class="segment-header">
          <span class="speaker-badge ${badgeClass}">${escapeHtml(seg.speaker)}</span>
          <button
            type="button"
            class="timestamp-btn"
            title="Reproducir desde ${seg.start_formatted}"
            data-start="${seg.start}"
          >
            [${seg.start_formatted} - ${seg.end_formatted}]
          </button>
        </div>
        <p class="segment-text">${escapeHtml(seg.text)}</p>
      `;

      card.querySelector(".timestamp-btn").addEventListener("click", () => {
        if (mergedAudioPlayer && mergedAudioPlayer.src) {
          mergedAudioPlayer.currentTime = Number(seg.start) || 0;
          mergedAudioPlayer.play().catch(() => {});
        }
      });

      segmentsListEl.appendChild(card);
    });
  }

  function openRenamePanel() {
    if (!state.currentResult) return;
    const speakers = getUniqueSpeakers(state.currentResult);
    renameInputsContainer.innerHTML = "";

    speakers.forEach((spk) => {
      const wrap = document.createElement("div");
      wrap.innerHTML = `
        <label class="form-label">${escapeHtml(spk)}</label>
        <input
          type="text"
          class="form-control speaker-rename-input"
          data-original="${escapeHtml(spk)}"
          value="${escapeHtml(spk)}"
        />
      `;
      renameInputsContainer.appendChild(wrap);
    });

    renamePanel.classList.remove("hidden");
  }

  async function applySpeakerRename() {
    if (!state.currentResult) return;
    const inputs = renameInputsContainer.querySelectorAll(".speaker-rename-input");
    const speakerMap = {};
    inputs.forEach((inp) => {
      const orig = inp.dataset.original;
      const val = inp.value.trim();
      if (orig && val) {
        speakerMap[orig] = val;
      }
    });

    try {
      const res = await authFetch(`/api/jobs/${state.currentResult.job_id}/speakers`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ speaker_map: speakerMap }),
      });
      const updated = await res.json();
      if (!res.ok) {
        throw new Error(updated.detail || t("No se pudieron renombrar los oradores.", "Could not rename the speakers."));
      }

      state.currentResult = updated;
      state.selectedSpeaker = "ALL";
      renamePanel.classList.add("hidden");
      renderResultView(updated);
    } catch (err) {
      showAlert(err.message);
    }
  }

  // ---------------------------------------------------------------------------
  // Event Listeners
  // ---------------------------------------------------------------------------

  if (navLandingBtn) navLandingBtn.addEventListener("click", () => switchView("landing"));
  if (navPlaygroundBtn) navPlaygroundBtn.addEventListener("click", () => switchView("playground"));
  if (navBoxBtn) navBoxBtn.addEventListener("click", () => switchView("box"));
  if (navPortalBtn) navPortalBtn.addEventListener("click", () => switchView("portal"));

  const heroGoBoxBtn = document.getElementById("hero-go-box-btn");
  if (heroGoBoxBtn) {
    heroGoBoxBtn.addEventListener("click", () => switchView("box"));
  }

  const brandTrigger = document.getElementById("brand-home-trigger");
  if (brandTrigger) brandTrigger.addEventListener("click", () => switchView("landing"));

  document.querySelectorAll("[data-goto-view]").forEach((el) => {
    el.addEventListener("click", () => switchView(el.getAttribute("data-goto-view")));
  });

  const footerYear = document.getElementById("footer-year");
  if (footerYear) footerYear.textContent = String(new Date().getFullYear());

  // El idioma se elige solo en "Mi cuenta"; por defecto sale del dispositivo y del país.
  localStorage.removeItem("apex_vox_lang");
  const profileLangSelect = document.getElementById("profile-lang-select");
  if (profileLangSelect) {
    profileLangSelect.addEventListener("change", async () => {
      const lang = profileLangSelect.value === "en" ? "en" : "es";
      localStorage.setItem("apex_vox_lang_choice", lang);
      applyLanguage(lang);
      if (state.token) {
        try {
          await authFetch("/api/auth/me/language", {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ preferred_language: lang }),
          });
        } catch (_) { /* se mantiene la elección local */ }
      }
    });
  }

  if (openAuthBtn && authDialog) {
    openAuthBtn.addEventListener("click", () => {
      if (state.user) {
        switchView("portal");
      } else {
        authDialog.showModal();
      }
    });
  }

  const on = (id, evt, fn) => { const el = document.getElementById(id); if (el) el.addEventListener(evt, fn); };
  on("tg-link-btn", "click", createTelegramCode);
  on("tg-unlink-btn", "click", unlinkTelegram);
  on("delete-account-btn", "click", deleteAccount);
  on("forgot-password-btn", "click", () => setAuthMode("forgot"));
  on("back-to-login-btn", "click", () => setAuthMode("register"));
  on("submit-forgot-btn", "click", submitForgotPassword);
  on("submit-reset-btn", "click", submitResetPassword);
  on("newsletter-form", "submit", submitNewsletter);
  const openSignup = () => { setAuthMode("register"); if (authDialog && !authDialog.open) authDialog.showModal(); };
  on("guest-signup-btn", "click", openSignup);
  on("guest-result-signup-btn", "click", openSignup);
  if (authDialog) authDialog.addEventListener("close", () => { if (state.authMode !== "reset") setAuthMode("register"); });

  const portalLogoutBtn = document.getElementById("portal-logout-btn");
  if (portalLogoutBtn) {
    portalLogoutBtn.addEventListener("click", async () => {
      try {
        await authFetch("/api/auth/logout", { method: "POST" });
      } finally {
        clearSession();
        loadUserPortalSummary();
      }
    });
  }

  const icsDownloadBtn = document.getElementById("summa-download-ics-btn");
  if (icsDownloadBtn) {
    icsDownloadBtn.addEventListener("click", async (e) => {
      e.preventDefault();
      const jobId = icsDownloadBtn.dataset.jobId;
      if (!jobId) return;
      const res = await authFetch(`/api/jobs/${jobId}/calendar.ics`);
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        showAlert(data.detail || t("No se pudo exportar el calendario.", "Could not export the calendar."));
        return;
      }
      const url = URL.createObjectURL(await res.blob());
      const a = document.createElement("a");
      a.href = url;
      a.download = `${jobId}_apex_summa_tasks.ics`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    });
  }
  if (closeAuthDialogBtn && authDialog) {
    closeAuthDialogBtn.addEventListener("click", () => authDialog.close());
  }

  const heroGoPlaygroundBtn = document.getElementById("hero-go-playground-btn");
  if (heroGoPlaygroundBtn) {
    heroGoPlaygroundBtn.addEventListener("click", () => switchView("playground"));
  }
  const heroRegisterBtn = document.getElementById("hero-register-btn");
  if (heroRegisterBtn && authDialog) {
    heroRegisterBtn.addEventListener("click", () => authDialog.showModal());
  }
  const pricingFreeBtn = document.getElementById("pricing-free-btn");
  if (pricingFreeBtn && authDialog) {
    pricingFreeBtn.addEventListener("click", () => authDialog.showModal());
  }

  const heroTrialBtn = document.getElementById("hero-trial-btn");
  if (heroTrialBtn) heroTrialBtn.addEventListener("click", openProCheckout);
  const pricingProBtn = document.getElementById("pricing-pro-btn");
  if (pricingProBtn) pricingProBtn.addEventListener("click", openProCheckout);

  const submitRegisterBtn = document.getElementById("submit-register-btn");
  if (submitRegisterBtn) submitRegisterBtn.addEventListener("click", handleRegisterUser);

  const submitLoginBtn = document.getElementById("submit-login-btn");
  if (submitLoginBtn) submitLoginBtn.addEventListener("click", handleLoginUser);

  const portalGenerateBoldLinkBtn = document.getElementById("portal-generate-bold-link-btn");
  if (portalGenerateBoldLinkBtn) {
    portalGenerateBoldLinkBtn.addEventListener("click", startBoldCheckout);
  }
  const botSendBtn = document.getElementById("bot-send-btn");
  if (botSendBtn) botSendBtn.addEventListener("click", sendMeetingBot);
  const navBoxForBots = document.getElementById("nav-box-btn");
  if (navBoxForBots) navBoxForBots.addEventListener("click", loadMeetingBots);
  if (new URLSearchParams(location.search).get("view") === "box") setTimeout(loadMeetingBots, 300);
  const mcpCopyBtn = document.getElementById("mcp-copy-btn");
  if (mcpCopyBtn) {
    mcpCopyBtn.addEventListener("click", async () => {
      const input = document.getElementById("mcp-url-input");
      try {
        await navigator.clipboard.writeText(input.value);
        mcpCopyBtn.textContent = t("Copiado", "Copied");
        setTimeout(() => (mcpCopyBtn.textContent = t("Copiar", "Copy")), 1500);
      } catch (_) {
        input.select();
      }
    });
  }
  const mcpRevokeBtn = document.getElementById("mcp-revoke-btn");
  if (mcpRevokeBtn) {
    mcpRevokeBtn.addEventListener("click", async () => {
      await authFetch("/api/mcp/connections", { method: "DELETE" });
      loadMcpConnections();
    });
  }
  const refreshPortalBtn = document.getElementById("refresh-portal-btn");
  if (refreshPortalBtn) {
    refreshPortalBtn.addEventListener("click", loadUserPortalSummary);
  }

  const unlockSummaBtn = document.getElementById("unlock-summa-pro-btn");
  if (unlockSummaBtn) unlockSummaBtn.addEventListener("click", openProCheckout);
  const summaTrialBtn = document.getElementById("summa-activate-trial-btn");
  if (summaTrialBtn) summaTrialBtn.addEventListener("click", openProCheckout);

  const generateMinutesBtn = document.getElementById("generate-minutes-btn");
  if (generateMinutesBtn) generateMinutesBtn.addEventListener("click", handleGenerateMinutes);
  const downloadMinutesMdBtn = document.getElementById("download-minutes-md-btn");
  if (downloadMinutesMdBtn) downloadMinutesMdBtn.addEventListener("click", downloadMinutesMarkdown);
  const printMinutesBtn = document.getElementById("print-minutes-btn");
  if (printMinutesBtn) printMinutesBtn.addEventListener("click", printMinutesDocument);


  dropzone.addEventListener("click", () => fileInput.click());
  dropzone.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      fileInput.click();
    }
  });

  fileInput.addEventListener("change", (e) => {
    if (e.target.files && e.target.files.length > 0) {
      uploadFiles(e.target.files);
    }
  });

  dropzone.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropzone.classList.add("drag-active");
  });

  dropzone.addEventListener("dragleave", () => {
    dropzone.classList.remove("drag-active");
  });

  dropzone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropzone.classList.remove("drag-active");
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      uploadFiles(e.dataTransfer.files);
    }
  });

  clearQueueBtn.addEventListener("click", () => {
    state.sessionId = null;
    state.files = [];
    state.playingSequence = false;
    renderTrackQueue();
  });

  const playSequenceBtn = document.getElementById("play-sequence-btn");
  if (playSequenceBtn) {
    playSequenceBtn.addEventListener("click", () => {
      const allAudios = Array.from(trackListEl.querySelectorAll(".track-audio-preview"));
      if (allAudios.length === 0) return;

      const anyPlaying = allAudios.some((a) => !a.paused);
      if (anyPlaying) {
        state.playingSequence = false;
        allAudios.forEach((a) => a.pause());
        playSequenceBtn.textContent = state.lang === "en" ? "Play in order" : "Escuchar en orden";
      } else {
        state.playingSequence = true;
        playSequenceBtn.textContent = state.lang === "en" ? "Stop sequence" : "Detener secuencia";
        allAudios[0].currentTime = 0;
        allAudios[0].play().catch(() => {});
      }
    });
  }

  transcribeBtn.addEventListener("click", startTranscription);
  if (enrollVpBtn) {
    enrollVpBtn.addEventListener("click", handleEnrollVoiceProfile);
  }

  searchInput.addEventListener("input", (e) => {
    state.searchQuery = e.target.value || "";
    if (state.currentResult) {
      renderSegmentsList(state.currentResult);
    }
  });

  renameSpeakersBtn.addEventListener("click", openRenamePanel);
  applyRenameBtn.addEventListener("click", applySpeakerRename);
  cancelRenameBtn.addEventListener("click", () => renamePanel.classList.add("hidden"));

  copyTranscriptBtn.addEventListener("click", async () => {
    if (!state.currentResult) return;
    try {
      await navigator.clipboard.writeText(state.currentResult.full_text || "");
      const prev = copyTranscriptBtn.textContent;
      copyTranscriptBtn.textContent = t("¡Copiado!", "Copied!");
      setTimeout(() => {
        copyTranscriptBtn.textContent = prev;
      }, 1800);
    } catch (err) {
      showAlert("No se pudo copiar al portapapeles.");
    }
  });

  // ---------------------------------------------------------------------------
  // Apex Box — Unlimited Block Recorder (Desktop, Virtual Zoom/Meet/Teams & Mobile Web App)
  // ---------------------------------------------------------------------------
  const IS_IOS = /iPhone|iPad|iPod/i.test(navigator.userAgent || "") ||
    (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  const IS_ANDROID = /Android/i.test(navigator.userAgent || "");

  const boxState = {
    mode: "presencial", // "presencial" | "virtual"
    status: "idle", // "idle" | "starting" | "recording" | "stopping"
    boxSessionId: null,
    blockDurationSec: 180,
    nextBlockIndex: 0,
    startedAtMs: null,
    blockStartedAtMs: null,
    clockTimer: null,
    activeRecorder: null,
    activeStream: null,
    micStream: null,
    displayStream: null,
    audioCtx: null,
    analyser: null,
    animFrameId: null,
    wakeLock: null,
    recordedMsBefore: 0, // tiempo grabado antes de una pausa/interrupción
    runStartedAtMs: null,
    rotating: false,
    uploads: [], // envíos en curso: se esperan antes de crear el resumen
    segments: [],
    notes: [],
    blocks: [],
  };

  const boxModePresencialBtn = document.getElementById("box-mode-presencial-btn");
  const boxModeVirtualBtn = document.getElementById("box-mode-virtual-btn");
  const boxTitleInput = document.getElementById("box-title-input");
  const boxPlatformSelect = document.getElementById("box-platform-select");
  const boxEngineSelect = document.getElementById("box-engine-select");

  const boxMasterClock = document.getElementById("box-master-clock");
  const boxBlockClock = document.getElementById("box-block-countdown");
  const boxBlockTitle = document.getElementById("box-current-block-title");
  const boxBlockProgress = document.getElementById("box-block-progress-bar");
  const boxStatusPill = document.getElementById("box-status-pill");
  const boxWaveformCanvas = document.getElementById("box-waveform-canvas");

  const boxStartRecBtn = document.getElementById("box-start-rec-btn");
  const boxCutBlockBtn = document.getElementById("box-cut-block-btn");
  const boxStopRecBtn = document.getElementById("box-stop-rec-btn");

  // Mientras graba: oculta "Iniciar" y muestra "Enviar bloque ahora" + "Detener y finalizar".
  function setBoxRecordingButtons(recording) {
    if (boxStartRecBtn) {
      boxStartRecBtn.disabled = recording;
      boxStartRecBtn.classList.toggle("hidden", recording);
    }
    if (boxCutBlockBtn) {
      boxCutBlockBtn.disabled = !recording;
      boxCutBlockBtn.classList.toggle("hidden", !recording);
    }
    if (boxStopRecBtn) {
      boxStopRecBtn.disabled = !recording;
      boxStopRecBtn.classList.toggle("hidden", !recording);
    }
  }
  const boxStatusAlert = document.getElementById("box-alert-banner");

  const boxNoteTagSelector = document.getElementById("box-note-tag-selector");
  const boxNoteAuthorInput = document.getElementById("box-note-speaker-input");
  const boxNoteTextInput = document.getElementById("box-note-text-input");
  const boxAddNoteBtn = document.getElementById("box-add-note-btn");
  const boxNotesCountBadge = document.getElementById("box-notes-count-pill");
  const boxNotesListEl = document.getElementById("box-notes-list");

  const boxKpiBlocks = document.getElementById("box-kpi-blocks-count");
  const boxKpiSegments = document.getElementById("box-kpi-segments-count");
  const boxLiveSegmentsList = document.getElementById("box-live-segments");
  const boxBlocksHistoryList = document.getElementById("box-blocks-list");
  const boxBlocksLogSummary = document.getElementById("box-blocks-log-summary");
  const boxOpenInPlaygroundBtn = document.getElementById("box-view-full-result-btn");

  const tk = (key) => (I18N[state.lang] || I18N.es)[key] || I18N.es[key];

  function setBoxStatusPill(kind) {
    if (!boxStatusPill) return;
    const labels = {
      ready: tk("box_status_ready"),
      recording: t("GRABANDO", "RECORDING"),
      paused: t("EN PAUSA", "PAUSED"),
      finishing: t("CREANDO RESUMEN", "CREATING SUMMARY"),
    };
    boxStatusPill.removeAttribute("data-i18n");
    boxStatusPill.textContent = labels[kind] || labels.ready;
    boxStatusPill.className = `badge-pill ${kind === "recording" || kind === "paused" ? "warn" : kind === "finishing" ? "info" : "success"}`;
  }

  function boxElapsedMs() {
    return boxState.recordedMsBefore + (boxState.runStartedAtMs ? Date.now() - boxState.runStartedAtMs : 0);
  }

  function showBoxAlert(msg, type = "info") {
    if (!boxStatusAlert) return;
    boxStatusAlert.textContent = msg;
    boxStatusAlert.classList.remove("hidden");
    boxStatusAlert.style.borderColor =
      type === "error" ? "#dc2626" : type === "success" ? "#16a34a" : "var(--brand)";
  }

  function formatBoxMmSs(totalSec) {
    const s = Math.max(0, Math.floor(Number(totalSec) || 0));
    const mins = Math.floor(s / 60);
    const secs = s % 60;
    return `${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
  }

  function setBoxMode(mode) {
    boxState.mode = mode === "virtual" ? "virtual" : "presencial";
    if (boxModePresencialBtn) {
      boxModePresencialBtn.classList.toggle("active", boxState.mode === "presencial");
      boxModePresencialBtn.setAttribute("aria-checked", String(boxState.mode === "presencial"));
    }
    if (boxModeVirtualBtn) {
      boxModeVirtualBtn.classList.toggle("active", boxState.mode === "virtual");
      boxModeVirtualBtn.setAttribute("aria-checked", String(boxState.mode === "virtual"));
    }
    if (boxPlatformSelect && boxState.mode === "presencial" && boxPlatformSelect.value !== "presencial" && boxPlatformSelect.value !== "mobile_pwa") {
      const isMobile = /Android|iPhone|iPad|iPod/i.test(navigator.userAgent || "");
      boxPlatformSelect.value = isMobile ? "mobile_pwa" : "presencial";
    } else if (boxPlatformSelect && boxState.mode === "virtual" && (boxPlatformSelect.value === "presencial" || boxPlatformSelect.value === "mobile_pwa")) {
      boxPlatformSelect.value = "google_meet";
    }
  }

  async function ensureBoxBackendSession() {
    if (boxState.boxSessionId) return boxState.boxSessionId;
    if (!state.token) {
      requireSession(t(
        "Inicia sesión o crea tu cuenta para grabar con Apex Box.",
        "Sign in or create your account to record with Apex Box."
      ));
      throw new Error(t("Debes iniciar sesión para grabar.", "You must sign in to record."));
    }
    const blockSec = boxState.blockDurationSec;

    const payload = {
      title: (boxTitleInput && boxTitleInput.value.trim()) ||
        (boxState.mode === "virtual" ? t("Reunión virtual", "Virtual meeting") : t("Reunión presencial", "In-person meeting")),
      mode: boxState.mode,
      platform: (boxPlatformSelect && boxPlatformSelect.value) || (boxState.mode === "virtual" ? "google_meet" : "presencial"),
      language: "es",
      diarization_engine: (boxEngineSelect && boxEngineSelect.value) || "Mc-Lewis",
      block_duration_sec: blockSec,
      device_type: /Android|iPhone|iPad|iPod/i.test(navigator.userAgent || "") ? "mobile_pwa" : "web_app",
    };

    const res = await authFetch("/api/box/sessions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.detail || t("No se pudo iniciar la grabación.", "Could not start the recording."));
    }
    boxState.boxSessionId = data.box_session_id;
    boxState.nextBlockIndex = 0;
    return boxState.boxSessionId;
  }

  function startBoxWaveformVisualizer(stream) {
    if (!boxWaveformCanvas) return;
    try {
      const AudioContextClass = window.AudioContext || window.webkitAudioContext;
      if (!AudioContextClass) return;
      if (!boxState.audioCtx) {
        boxState.audioCtx = new AudioContextClass();
      }
      const source = boxState.audioCtx.createMediaStreamSource(stream);
      const analyser = boxState.audioCtx.createAnalyser();
      analyser.fftSize = 128;
      source.connect(analyser);
      boxState.analyser = analyser;

      const ctx = boxWaveformCanvas.getContext("2d");
      const bufferLen = analyser.frequencyBinCount;
      const dataArray = new Uint8Array(bufferLen);

      function draw() {
        if (boxState.status !== "recording") return;
        boxState.animFrameId = requestAnimationFrame(draw);
        analyser.getByteFrequencyData(dataArray);
        const w = boxWaveformCanvas.width;
        const h = boxWaveformCanvas.height;
        ctx.clearRect(0, 0, w, h);

        const barCount = 42;
        const step = Math.floor(bufferLen / barCount) || 1;
        const barWidth = Math.max(3, Math.floor((w - barCount * 3) / barCount));

        for (let i = 0; i < barCount; i++) {
          const val = dataArray[i * step] || 4;
          const barHeight = Math.max(4, (val / 255) * (h - 8));
          const x = i * (barWidth + 3) + 4;
          const y = (h - barHeight) / 2;
          ctx.fillStyle = val > 140 ? "#ff6b2b" : "#f54e00";
          ctx.fillRect(x, y, barWidth, barHeight);
        }
      }
      draw();
    } catch (e) {
      // Non-fatal
    }
  }

  async function acquireBoxCaptureStream() {
    if (boxState.mode === "virtual") {
      // Capture remote call audio (Zoom, Meet, Teams tab/window) + user microphone mixed
      const displayStream = await navigator.mediaDevices.getDisplayMedia({
        video: true,
        audio: {
          echoCancellation: false,
          noiseSuppression: false,
          autoGainControl: false,
        },
      });
      boxState.displayStream = displayStream;

      let micStream = null;
      try {
        micStream = await navigator.mediaDevices.getUserMedia({
          audio: {
            echoCancellation: true,
            noiseSuppression: true,
            autoGainControl: true,
          },
          video: false,
        });
        boxState.micStream = micStream;
      } catch (e) {
        // User mic optional if tab audio is shared
      }

      const AudioContextClass = window.AudioContext || window.webkitAudioContext;
      const audioCtx = new AudioContextClass({ sampleRate: 16000 });
      boxState.audioCtx = audioCtx;
      const dest = audioCtx.createMediaStreamDestination();

      if (displayStream.getAudioTracks().length > 0) {
        const sysSource = audioCtx.createMediaStreamSource(displayStream);
        sysSource.connect(dest);
      }
      if (micStream && micStream.getAudioTracks().length > 0) {
        const micSource = audioCtx.createMediaStreamSource(micStream);
        micSource.connect(dest);
      }

      // Stop video tracks only when recording stops; if user clicks "Stop sharing" in browser bar, finalize gracefully
      const videoTrack = displayStream.getVideoTracks()[0];
      if (videoTrack) {
        videoTrack.onended = () => {
          if (boxState.status === "recording") {
            stopAndFinalizeBoxRecording();
          }
        };
      }

      if (dest.stream.getAudioTracks().length === 0 && micStream) {
        return micStream;
      }
      return dest.stream;
    } else {
      // Presencial / Mobile Web App Mode: high-gain acoustic voice capture
      const micStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
          channelCount: 1,
          sampleRate: 16000,
        },
        video: false,
      });
      boxState.micStream = micStream;
      return micStream;
    }
  }

  function getSupportedBoxMimeType() {
    if (typeof MediaRecorder === "undefined") return "";
    const candidates = IS_IOS
      ? ["audio/mp4", "audio/webm;codecs=opus", "audio/webm"]
      : ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4"];
    for (const mime of candidates) {
      if (MediaRecorder.isTypeSupported && MediaRecorder.isTypeSupported(mime)) {
        return mime;
      }
    }
    return "";
  }

  function spawnBoxRecorderForBlock(blockIdx) {
    if (!boxState.activeStream || boxState.status !== "recording") return null;

    const mimeType = getSupportedBoxMimeType();
    const options = mimeType
      ? { mimeType, audioBitsPerSecond: 48000 }
      : { audioBitsPerSecond: 48000 };

    let recorder;
    try {
      recorder = new MediaRecorder(boxState.activeStream, options);
    } catch (e) {
      recorder = new MediaRecorder(boxState.activeStream);
    }
    const blockChunks = [];
    const blockStartMs = Date.now();
    const type = recorder.mimeType || mimeType || "audio/webm";

    recorder.ondataavailable = (ev) => {
      if (ev.data && ev.data.size > 0) blockChunks.push(ev.data);
    };
    recorder.onerror = () => {
      showBoxAlert(t("El celular detuvo el micrófono. Toca ● Grabar para continuar.", "The device stopped the microphone. Tap ● Record to continue."), "error");
    };
    recorder.onstop = async () => {
      const durationSec = Math.max(1, (Date.now() - blockStartMs) / 1000);
      const blob = new Blob(blockChunks, { type });
      blockChunks.length = 0; // libera memoria: cada bloque se envía y se olvida
      // Una sola grabadora a la vez (iPhone no admite dos sobre el mismo micrófono):
      // la siguiente arranca en cuanto se cierra esta.
      if (boxState.rotating) {
        boxState.rotating = false;
        boxState.activeRecorder = spawnBoxRecorderForBlock(boxState.nextBlockIndex);
      }
      if (blob.size > 0) {
        const upload = uploadAndTranscribeBoxBlock(blob, blockIdx, durationSec, type);
        boxState.uploads.push(upload);
        await upload;
      }
    };

    recorder.start(1000);
    boxState.blockStartedAtMs = blockStartMs;
    return recorder;
  }

  function rotateBoxRecorderBlock() {
    if (boxState.status !== "recording" || !boxState.activeStream || boxState.rotating) return;
    const prevRecorder = boxState.activeRecorder;
    boxState.nextBlockIndex += 1;
    boxState.blockStartedAtMs = Date.now();
    if (prevRecorder && prevRecorder.state !== "inactive") {
      boxState.rotating = true;
      try {
        prevRecorder.stop();
      } catch (e) {
        boxState.rotating = false;
        boxState.activeRecorder = spawnBoxRecorderForBlock(boxState.nextBlockIndex);
      }
    } else {
      boxState.activeRecorder = spawnBoxRecorderForBlock(boxState.nextBlockIndex);
    }
  }

  // Reloj, barra del bloque y cambio de bloque. Se basa en la hora real: si el teléfono
  // congela los temporizadores, al volver el bloque se cierra igual.
  function tickBoxRecorder() {
    if (boxState.status !== "recording") return;
    const blockElapsedSec = (Date.now() - boxState.blockStartedAtMs) / 1000;
    if (blockElapsedSec >= boxState.blockDurationSec) {
      rotateBoxRecorderBlock();
    }
    const shownBlockSec = Math.min((Date.now() - boxState.blockStartedAtMs) / 1000, boxState.blockDurationSec);
    if (boxMasterClock) {
      boxMasterClock.textContent = formatSecondsHHMMSS(boxElapsedMs() / 1000);
      boxMasterClock.classList.add("recording");
    }
    const blockTitle = `${t("BLOQUE", "BLOCK")} ${boxState.nextBlockIndex + 1}`;
    if (boxBlockTitle && boxBlockTitle.textContent !== blockTitle) {
      boxBlockTitle.textContent = blockTitle;
    }
    if (boxBlockClock) {
      boxBlockClock.textContent = `${formatBoxMmSs(shownBlockSec)} / ${formatBoxMmSs(boxState.blockDurationSec)}`;
    }
    if (boxBlockProgress) {
      boxBlockProgress.style.width = `${Math.min(100, (shownBlockSec / boxState.blockDurationSec) * 100).toFixed(1)}%`;
    }
  }

  // Pantalla siempre encendida mientras se graba (se pierde al salir de la app: se vuelve a pedir al regresar)
  async function requestBoxWakeLock() {
    if (!("wakeLock" in navigator) || !navigator.wakeLock || !navigator.wakeLock.request) return false;
    try {
      boxState.wakeLock = await navigator.wakeLock.request("screen");
      boxState.wakeLock.addEventListener("release", () => {
        boxState.wakeLock = null;
      });
      return true;
    } catch (e) {
      return false;
    }
  }

  function releaseBoxCapture() {
    [boxState.activeStream, boxState.micStream, boxState.displayStream].forEach((st) => {
      if (st && st.getTracks) st.getTracks().forEach((tr) => tr.stop());
    });
    boxState.activeStream = boxState.micStream = boxState.displayStream = null;
  }

  // El sistema cortó el micrófono (pantalla bloqueada, otra app, llamada…): se guarda lo
  // grabado como un bloque y la grabación queda en pausa para continuar en la misma reunión.
  function pauseBoxRecordingAfterInterruption() {
    if (boxState.status !== "recording") return;
    boxState.recordedMsBefore = boxElapsedMs();
    boxState.runStartedAtMs = null;
    boxState.status = "paused";
    if (boxState.clockTimer) {
      clearInterval(boxState.clockTimer);
      boxState.clockTimer = null;
    }
    const rec = boxState.activeRecorder;
    boxState.activeRecorder = null;
    if (rec && rec.state !== "inactive") {
      try {
        rec.stop();
      } catch (e) {}
    }
    releaseBoxCapture();
    boxState.nextBlockIndex += 1;
    if (boxMasterClock) boxMasterClock.classList.remove("recording");
    setBoxStatusPill("paused");
    if (boxStartRecBtn) {
      boxStartRecBtn.textContent = t("● Continuar grabando", "● Continue recording");
      boxStartRecBtn.disabled = false;
      boxStartRecBtn.classList.remove("hidden");
    }
    if (boxCutBlockBtn) boxCutBlockBtn.classList.add("hidden");
    if (boxStopRecBtn) {
      boxStopRecBtn.disabled = false;
      boxStopRecBtn.classList.remove("hidden");
    }
    showBoxAlert(
      t(
        "Se pausó la grabación: el celular cortó el micrófono (pantalla bloqueada, otra app o llamada). Lo grabado está guardado. Toca «Continuar grabando» para seguir en la misma reunión.",
        "Recording paused: the phone cut off the microphone (screen locked, another app or a call). What you recorded is saved. Tap “Continue recording” to keep going in the same meeting."
      ),
      "error"
    );
    document.title = `⏸ ${t("Grabación en pausa", "Recording paused")} · Apex Vox`;
  }

  function watchBoxStreamInterruptions(stream) {
    stream.getAudioTracks().forEach((track) => {
      track.addEventListener("ended", () => pauseBoxRecordingAfterInterruption());
    });
  }

  document.addEventListener("visibilitychange", async () => {
    if (boxState.status !== "recording") return;
    if (document.visibilityState === "visible") {
      if (!boxState.wakeLock) await requestBoxWakeLock();
      const live = boxState.activeStream &&
        boxState.activeStream.getAudioTracks().some((tr) => tr.readyState === "live");
      const recOk = boxState.activeRecorder && boxState.activeRecorder.state === "recording";
      if (!live || !recOk) {
        pauseBoxRecordingAfterInterruption();
      } else {
        tickBoxRecorder();
      }
    } else if ((IS_IOS || IS_ANDROID)) {
      document.title = `● REC ${t("— vuelve a Apex Vox", "— come back to Apex Vox")}`;
    }
  });

  async function uploadAndTranscribeBoxBlock(blob, blockIndex, durationSec, mimeType) {
    try {
      const sessionId = await ensureBoxBackendSession();
      const ext = mimeType.includes("mp4") ? "m4a" : mimeType.includes("ogg") ? "ogg" : mimeType.includes("wav") ? "wav" : "webm";
      const filename = `block_${String(blockIndex).padStart(4, "0")}.${ext}`;

      const formData = new FormData();
      formData.append("file", blob, filename);
      formData.append("block_index", String(blockIndex));
      formData.append("duration_hint_sec", String(durationSec.toFixed(2)));
      formData.append("transcribe_immediately", "true");

      if (boxState.status !== "paused") {
        showBoxAlert(t(`Transcribiendo el bloque ${blockIndex + 1}…`, `Transcribing block ${blockIndex + 1}…`), "info");
      }

      const res = await authFetch(`/api/box/sessions/${sessionId}/blocks`, {
        method: "POST",
        body: formData,
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || t(`No se pudo procesar el bloque ${blockIndex + 1}`, `Could not process block ${blockIndex + 1}`));
      }

      boxState.blocks.push(data.block);
      if (Array.isArray(data.new_segments) && data.new_segments.length > 0) {
        boxState.segments.push(...data.new_segments);
      }

      renderBoxLiveTelemetry();
      if (boxState.status === "paused") return; // no tapar el aviso de pausa
      showBoxAlert(
        t(
          `Bloque ${blockIndex + 1} listo: ${data.new_segments.length} frases nuevas · total ${data.total_duration_formatted}.`,
          `Block ${blockIndex + 1} done: ${data.new_segments.length} new sentences · total ${data.total_duration_formatted}.`
        ),
        "success"
      );
    } catch (err) {
      showBoxAlert(t(`Bloque ${blockIndex + 1}: ${err.message}`, `Block ${blockIndex + 1}: ${err.message}`), "error");
    }
  }

  function renderBoxLiveTelemetry() {
    if (boxKpiBlocks) boxKpiBlocks.textContent = String(boxState.blocks.length);
    if (boxKpiSegments) boxKpiSegments.textContent = String(boxState.segments.length);
    const uniqueSpeakers = new Set(boxState.segments.map((seg) => seg.speaker).filter(Boolean));

    if (boxBlocksLogSummary) {
      boxBlocksLogSummary.removeAttribute("data-i18n");
      const totalSec = boxState.blocks.reduce((acc, b) => acc + (Number(b.duration_sec) || 0), 0);
      boxBlocksLogSummary.textContent = boxState.blocks.length
        ? t(`${boxState.blocks.length} bloques · ${formatSecondsHHMMSS(totalSec)} enviados`, `${boxState.blocks.length} blocks · ${formatSecondsHHMMSS(totalSec)} sent`)
        : tk("box_blocks_log_empty");
    }
    if (boxBlocksHistoryList) {
      boxBlocksHistoryList.innerHTML = boxState.blocks
        .slice()
        .reverse()
        .map(
          (b) => `
            <li class="track-item">
              <div class="track-meta">
                <div class="track-name">${t("Bloque", "Block")} ${Number(b.block_index) + 1}</div>
                <div class="track-sub">
                  <span>${Math.round(Number(b.duration_sec) || 0)} s</span>
                  <span>${Number(b.segments_count) || 0} ${t("frases", "sentences")}</span>
                  <span>${t("Enviado ✓", "Sent ✓")}</span>
                </div>
              </div>
            </li>`
        )
        .join("");
    }

    if (boxLiveSegmentsList) {
      if (boxState.segments.length === 0) {
        boxLiveSegmentsList.innerHTML = `
          <div class="empty-state">
            <h4>${t("Aquí verás lo que se dice", "What is said will show up here")}</h4>
            <p>${t("Pulsa Grabar: la transcripción aparece al terminar cada bloque.", "Press Record: the transcript appears after each block.")}</p>
          </div>`;
      } else {
        const allSpks = Array.from(uniqueSpeakers);
        boxLiveSegmentsList.innerHTML = boxState.segments
          .map((seg) => {
            const spkIdx = Math.max(0, allSpks.indexOf(seg.speaker));
            return `
              <div class="segment-card">
                <div class="segment-header">
                  <span class="speaker-badge speaker-${spkIdx % 4}">${escapeHtml(seg.speaker)}</span>
                  <span class="timestamp-btn">[${escapeHtml(seg.start_formatted)} - ${escapeHtml(seg.end_formatted)}]</span>
                </div>
                <p class="segment-text">${escapeHtml(seg.text)}</p>
              </div>`;
          })
          .join("");
      }
    }
  }

  async function startBoxRecording() {
    if (boxState.status !== "idle" && boxState.status !== "paused") return;
    if (!state.token) {
      requireSession(t(
        "Inicia sesión o crea tu cuenta para grabar con Apex Box.",
        "Sign in or create your account to record with Apex Box."
      ));
      return;
    }
    if (boxState.mode === "virtual" && !(navigator.mediaDevices && navigator.mediaDevices.getDisplayMedia)) {
      setBoxMode("presencial");
      showBoxAlert(
        t(
          "En el celular se graba con el micrófono (modo presencial). Para Zoom, Meet o Teams usa el bot de reuniones.",
          "On a phone you record with the microphone (in-person mode). For Zoom, Meet or Teams use the meeting bot."
        ),
        "info"
      );
    }
    const resuming = boxState.status === "paused";
    boxState.status = "starting";

    // Lo que exige un toque del usuario (sobre todo en iPhone) se pide aquí, antes de cualquier espera.
    const wakeLockPromise = requestBoxWakeLock();
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if (AudioContextClass && (!boxState.audioCtx || boxState.audioCtx.state === "closed")) {
      try {
        boxState.audioCtx = new AudioContextClass();
      } catch (e) {}
    }
    if (boxState.audioCtx && boxState.audioCtx.state === "suspended") {
      boxState.audioCtx.resume().catch(() => {});
    }

    try {
      const blockSec = boxState.blockDurationSec;
      const streamPromise = acquireBoxCaptureStream();
      await ensureBoxBackendSession();
      const stream = await streamPromise;
      const wakeOk = await wakeLockPromise;

      boxState.activeStream = stream;
      boxState.rotating = false;
      boxState.status = "recording";
      boxState.runStartedAtMs = Date.now();
      if (!resuming) {
        boxState.recordedMsBefore = 0;
        boxState.startedAtMs = Date.now();
        boxState.nextBlockIndex = boxState.blocks.length;
      }
      watchBoxStreamInterruptions(stream);
      boxState.activeRecorder = spawnBoxRecorderForBlock(boxState.nextBlockIndex);
      if (boxState.clockTimer) clearInterval(boxState.clockTimer);
      boxState.clockTimer = setInterval(tickBoxRecorder, 500);
      tickBoxRecorder();

      startBoxWaveformVisualizer(stream);
      setBoxRecordingButtons(true);
      setBoxStatusPill("recording");
      if (boxStartRecBtn) boxStartRecBtn.textContent = tk("box_btn_start");

      const minutes = Math.round(blockSec / 60);
      let msg = t(
        `Grabando. Cada ${minutes} min se envía un bloque y verás la transcripción.`,
        `Recording. Every ${minutes} min a block is sent and you will see the transcript.`
      );
      if ((IS_IOS || IS_ANDROID)) {
        msg += " " + (wakeOk
          ? t(
              "La pantalla se mantendrá encendida. Deja Apex Vox abierto: si bloqueas el celular o cambias de app, el sistema corta el micrófono y la grabación se pausa.",
              "The screen will stay on. Keep Apex Vox open: if you lock the phone or switch apps, the system cuts off the microphone and recording pauses."
            )
          : t(
              "Tu navegador no puede mantener la pantalla encendida: desactiva el bloqueo automático y deja Apex Vox abierto mientras grabas.",
              "Your browser cannot keep the screen on: turn off auto-lock and keep Apex Vox open while recording."
            ));
      }
      showBoxAlert(msg, "success");
    } catch (err) {
      boxState.status = resuming ? "paused" : "idle";
      if (boxState.wakeLock) {
        boxState.wakeLock.release().catch(() => {});
        boxState.wakeLock = null;
      }
      showBoxAlert(
        t(`No se pudo usar el micrófono (${err.message}). Revisa que el navegador tenga permiso.`, `Could not use the microphone (${err.message}). Check the browser permission.`),
        "error"
      );
    }
  }

  async function stopAndFinalizeBoxRecording() {
    if (boxState.status === "stopping") return;
    boxState.status = "stopping";
    boxState.rotating = false;
    setBoxStatusPill("finishing");

    if (boxState.clockTimer) {
      clearInterval(boxState.clockTimer);
      boxState.clockTimer = null;
    }
    if (boxState.animFrameId) {
      cancelAnimationFrame(boxState.animFrameId);
      boxState.animFrameId = null;
    }

    if (boxState.activeRecorder && boxState.activeRecorder.state !== "inactive") {
      await new Promise((resolve) => {
        const origOnStop = boxState.activeRecorder.onstop;
        boxState.activeRecorder.onstop = async (e) => {
          if (origOnStop) await origOnStop(e);
          resolve();
        };
        try {
          boxState.activeRecorder.stop();
        } catch (e) {
          resolve();
        }
      });
    }

    releaseBoxCapture();

    if (boxState.wakeLock) {
      try {
        await boxState.wakeLock.release();
      } catch (e) {}
      boxState.wakeLock = null;
    }

    if (boxMasterClock) boxMasterClock.classList.remove("recording");
    setBoxRecordingButtons(false);
    boxState.status = "idle";
    boxState.runStartedAtMs = null;
    boxState.recordedMsBefore = 0;
    if (boxStartRecBtn) boxStartRecBtn.textContent = tk("box_btn_start");
    document.title = document.title.replace(/^(⏸|● REC)[^·]*· /, "");

    if (!boxState.boxSessionId) return;
    await Promise.allSettled(boxState.uploads);
    boxState.uploads = [];

    try {
      showBoxAlert(t("Uniendo los bloques y tus notas para crear el resumen y el acta…", "Joining the blocks and your notes to create the summary and minutes…"), "info");
      const res = await authFetch(`/api/box/sessions/${boxState.boxSessionId}/finalize`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          generate_minutes: true,
          minutes_type: "general",
          organization_name: (boxTitleInput && boxTitleInput.value.trim()) || "Apex Corporation",
        }),
      });
      const finalized = await res.json();
      if (!res.ok) {
        throw new Error(finalized.detail || t("No se pudo finalizar la grabación.", "Could not finish the recording."));
      }

      state.currentJobId = finalized.job_id;
      state.currentResult = finalized.result;
      state.currentMinutes = finalized.minutes;
      renderResultView(finalized.result);

      if (boxOpenInPlaygroundBtn) {
        boxOpenInPlaygroundBtn.classList.remove("hidden");
      }
      showBoxAlert(
        t(`¡Listo! ${finalized.result.segments.length} frases y ${boxState.notes.length} notas en tu resumen y acta.`, `Done! ${finalized.result.segments.length} sentences and ${boxState.notes.length} notes in your summary and minutes.`),
        "success"
      );
    } catch (err) {
      showBoxAlert(t(`No se pudo crear el resumen: ${err.message}`, `Could not create the summary: ${err.message}`), "error");
      setBoxStatusPill("ready");
    }
  }

  async function handleAddBoxNote() {
    if (!boxNoteTextInput || !boxNoteTextInput.value.trim()) return;
    const text = boxNoteTextInput.value.trim();
    const activeTag = boxNoteTagSelector && boxNoteTagSelector.querySelector(".speaker-tab.active");
    const category = (activeTag && activeTag.getAttribute("data-note-tag")) || "nota";
    const author = (boxNoteAuthorInput && boxNoteAuthorInput.value.trim()) || t("Participante", "Participant");

    // Calculate current timestamp in recording
    let elapsedSec = 0;
    if ((boxState.status === "recording" || boxState.status === "paused") && boxState.startedAtMs) {
      elapsedSec = boxElapsedMs() / 1000;
    } else if (boxState.blocks.length > 0) {
      elapsedSec = boxState.blocks.reduce((acc, b) => acc + (Number(b.duration_sec) || 0), 0);
    }

    try {
      const sessionId = await ensureBoxBackendSession();
      const res = await authFetch(`/api/box/sessions/${sessionId}/notes`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          text,
          timestamp_sec: elapsedSec,
          category,
          author,
        }),
      });
      const note = await res.json();
      if (!res.ok) {
        throw new Error(note.detail || t("No se pudo guardar la nota.", "Could not save the note."));
      }
      boxState.notes.push(note);
      boxNoteTextInput.value = "";
      renderBoxNotesList();
    } catch (err) {
      showBoxAlert(err.message, "error");
    }
  }

  async function handleDeleteBoxNote(noteId) {
    if (!boxState.boxSessionId) return;
    try {
      const res = await authFetch(`/api/box/sessions/${boxState.boxSessionId}/notes/${noteId}`, {
        method: "DELETE",
      });
      if (res.ok) {
        boxState.notes = boxState.notes.filter((n) => n.note_id !== noteId);
        renderBoxNotesList();
      }
    } catch (e) {}
  }

  function renderBoxNotesList() {
    if (boxNotesCountBadge) {
      boxNotesCountBadge.textContent = t(`${boxState.notes.length} notas`, `${boxState.notes.length} notes`);
    }
    if (!boxNotesListEl) return;
    if (boxState.notes.length === 0) {
      boxNotesListEl.innerHTML = `<li class="track-item track-item--static">${tk("box_notes_empty")}</li>`;
      return;
    }
    boxNotesListEl.innerHTML = boxState.notes
      .slice()
      .reverse()
      .map(
        (n) => `
        <li class="track-item">
          <div class="track-meta">
            <div class="track-name">
              <span class="badge badge-accent">[${escapeHtml(n.timestamp_formatted)}] ${escapeHtml(n.category.toUpperCase())}</span>
              <strong>${escapeHtml(n.author)}:</strong> ${escapeHtml(n.text)}
            </div>
          </div>
          <div class="track-actions">
            <button type="button" class="btn-icon-sm" data-delete-note="${escapeHtml(n.note_id)}" title="${t("Eliminar nota", "Delete note")}">✕</button>
          </div>
        </li>
      `
      )
      .join("");

    boxNotesListEl.querySelectorAll("[data-delete-note]").forEach((btn) => {
      btn.addEventListener("click", () => handleDeleteBoxNote(btn.getAttribute("data-delete-note")));
    });
  }

  if (boxModePresencialBtn) {
    boxModePresencialBtn.addEventListener("click", () => setBoxMode("presencial"));
  }
  if (boxModeVirtualBtn) {
    boxModeVirtualBtn.addEventListener("click", () => setBoxMode("virtual"));
  }
  if (boxStartRecBtn) {
    boxStartRecBtn.addEventListener("click", startBoxRecording);
  }
  if (boxCutBlockBtn) {
    boxCutBlockBtn.addEventListener("click", () => rotateBoxRecorderBlock());
  }
  if (boxNoteTagSelector) {
    boxNoteTagSelector.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-note-tag]");
      if (!btn) return;
      boxNoteTagSelector.querySelectorAll("[data-note-tag]").forEach((b) => b.classList.toggle("active", b === btn));
    });
  }
  if (boxStopRecBtn) {
    boxStopRecBtn.addEventListener("click", stopAndFinalizeBoxRecording);
  }
  if (boxAddNoteBtn) {
    boxAddNoteBtn.addEventListener("click", handleAddBoxNote);
  }
  if (boxNoteTextInput) {
    boxNoteTextInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        handleAddBoxNote();
      }
    });
  }
  if (boxOpenInPlaygroundBtn) {
    boxOpenInPlaygroundBtn.addEventListener("click", () => switchView("playground"));
  }
  // Aviso al cerrar o recargar la pestaña mientras se graba
  window.addEventListener("beforeunload", (e) => {
    if (boxState.status === "recording" || boxState.status === "paused") {
      e.preventDefault();
      e.returnValue = "";
    }
  });

  // Dispositivo: en computador se muestra la extensión; en celular, cómo instalar la app
  const isIOS = IS_IOS;
  const isAndroid = IS_ANDROID;
  const isMobile = IS_IOS || IS_ANDROID || /Mobi/i.test(navigator.userAgent || "");
  const isStandalone = window.matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;
  document.documentElement.classList.add(isMobile ? "is-mobile" : "is-desktop");
  document.documentElement.classList.toggle("is-ios", isIOS);
  document.documentElement.classList.toggle("is-android", isAndroid);
  if (isStandalone) {
    document.querySelectorAll(".install-ios, .install-android").forEach((el) => el.classList.add("hidden"));
    const installedMsg = document.getElementById("pwa-installed-msg");
    if (installedMsg) installedMsg.classList.remove("hidden");
  }
  let deferredInstallPrompt = null;
  window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault();
    deferredInstallPrompt = e;
    const btn = document.getElementById("pwa-install-btn");
    if (btn) btn.classList.remove("hidden");
  });
  const pwaInstallBtn = document.getElementById("pwa-install-btn");
  if (pwaInstallBtn) {
    pwaInstallBtn.addEventListener("click", async () => {
      if (!deferredInstallPrompt) return;
      deferredInstallPrompt.prompt();
      await deferredInstallPrompt.userChoice.catch(() => null);
      deferredInstallPrompt = null;
      pwaInstallBtn.classList.add("hidden");
    });
  }

  // Service worker: hace instalable la app web en celulares y escritorio
  if ("serviceWorker" in navigator) {
    window.addEventListener("load", () => navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(() => {}));
  }

  // Initial boot
  if (state.user && state.user.quota) state.plan = state.user.quota.plan || "free";
  applyLanguage(state.lang);
  refreshAuthUi();
  checkSystemHealth();
  loadVoiceProfiles();
  loadClientConfig()
    .then(() => refreshProfile())
    .then(() => handleRedirectParams());

  // Support deep linking via ?view=box (e.g. from Chrome Extension or PWA shortcut)
  const urlParams = new URLSearchParams(window.location.search);
  const initialViewParam = urlParams.get("view");
  if (initialViewParam && ["landing", "playground", "box", "portal"].includes(initialViewParam)) {
    switchView(initialViewParam);
  }

  // ?login=1 (desde la extensión): pide iniciar sesión si no hay sesión activa
  if (urlParams.get("login") && !state.token && authDialog && !authDialog.open) {
    authDialog.showModal();
  }

  // Deep link ?job=<job_id> (enlace final del grabador de la extensión): abre notas, resumen y acta
  const initialJobParam = urlParams.get("job");
  if (initialJobParam && /^[\w-]{1,64}$/.test(initialJobParam)) {
    switchView("playground");
    loadJobResult(initialJobParam);
  }
})();
