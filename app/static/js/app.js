/**
 * Apex Vox, Apex Summa & Apex Box — Frontend Application Controller
 * Potenciado por Groq · Almacenamiento MEGA S4 · Backend Supabase Cloud · Pagos Bold API
 *
 * Manages:
 * - Bilingual UI (Español / English)
 * - Landing Page, User Portal & Playground navigation
 * - User Registration (2h free/day + 24h retention) & Bold API Pro Subscription ($30.000 COP / $10 USD, 3-day trial)
 * - Multi-audio upload, drag-and-drop sequence ordering, and Mc-Series engines (Mc-Ayrton, Mc-Lewis, Mc-Norris, Mc-Piastri)
 * - Apex Summa 7-Part Post-Transcription Intelligence Suite (Who spoke most, Topics, Objectives, Callouts, Calendar, Charts, Minutes)
 */

(function () {
  "use strict";

  const state = {
    lang: localStorage.getItem("apex_vox_lang") || "es",
    activeView: "playground",
    user: JSON.parse(localStorage.getItem("apex_vox_user") || "null"),
    token: localStorage.getItem("apex_vox_token") || null,
    plan: localStorage.getItem("apex_vox_plan") || "pro",
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
      brand_title: "Apex Vox",
      powered_by_groq: "Potenciado por Groq",
      brand_subtitle: "Audio Studio · Transcripción Multi-Audio, Identificación de Oradores y Resumen IA Apex Summa",
      nav_landing: "Inicio & Planes",
      nav_playground: "Playground (Apex Vox)",
      nav_box: "Apex Box (10h+ & Extensión)",
      nav_portal: "Portal de Usuario",
      btn_register_login: "Registrarse / Entrar",
      hero_badge: "POTENCIADO POR GROQ · ALMACENAMIENTO MEGA S4 · SUPABASE CLOUD",
      hero_title: "Apex Vox: Transcripción Inteligente, Separación de Voces y Analítica Ejecutiva",
      hero_desc: "Regístrate hoy y obtén <strong>2 horas gratis al día</strong> en 1 o varios audios con almacenamiento por 24 horas, o activa <strong>Apex Pro</strong> con 3 días de prueba gratis, transcripciones y almacenamiento ilimitados en Mega S4 y resúmenes ejecutivos con <strong>Apex Summa</strong>.",
      hero_cta_playground: "Abrir Playground Ahora",
      hero_cta_box: "Grabar Sin Límite (Apex Box 10h+)",
      hero_cta_register: "Regístrate: 2 Horas Gratis / Día",
      hero_cta_trial: "Probar 3 Días Gratis (Plan Pro · Bold)",
      suite_heading: "Ecosistema del Producto Apex",
      suite_vox_status: "Producto Listo",
      suite_vox_part: "Transcripción (el núcleo)",
      suite_vox_desc: "Subida multi-audio en orden, corte inteligente, reconocimiento de voz con los motores Mc-Ayrton, Mc-Lewis, Mc-Norris y Mc-Piastri (Potenciado por Groq) y perfiles acústicos.",
      suite_summa_status: "Activo en Plan Pro",
      suite_summa_part: "Notas y resúmenes",
      suite_summa_desc: "Al terminar la transcripción identifica: 1. Quién habló más, 2. De qué se habló, 3. Objetivos, 4. Llamados de atención, 5. Próximas tareas en calendario, 6. Gráficas y 7. Creación de Actas (Consejo, Comité, Asamblea).",
      suite_box_status: "Activo · Extensión & App Móvil",
      suite_box_part: "Grabador ilimitado en bloques (Presencial, Zoom/Meet/Teams & App Celular)",
      suite_box_desc: "Grabación continua de 10+ horas en bloques óptimos de 3 min (~1.03 MB) sin saturar la RAM, modo Reunión Presencial y Reunión Virtual (Zoom, Meet, Teams), notas en vivo y extensión Chrome MV3.",
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
      plan_free_f2: "<strong>Almacenamiento de 24 horas</strong> en nube Mega S4",
      plan_free_f3: "Acceso a motores <strong>Mc-Ayrton, Mc-Lewis, Mc-Norris y Mc-Piastri</strong> (Potenciado por Groq)",
      plan_free_f4: "Exportación TXT, SRT, VTT, JSON, CSV y Markdown",
      plan_free_cta: "Registrarse Gratis (2h / día)",
      plan_pro_badge: "3 DÍAS DE PRUEBA GRATIS + COBRO AUTOMÁTICO",
      plan_pro_title: "Plan Apex Pro",
      per_month: "mes",
      plan_pro_f1: "<strong>Prueba gratis de 3 días</strong> con cobro automático mensual vía <strong>Bold API</strong>",
      plan_pro_f2: "<strong>Transcripciones ilimitadas</strong> (sin límite diario de horas ni archivos)",
      plan_pro_f3: "<strong>Almacenamiento ilimitado permanente</strong> en <strong>Mega S4</strong> y <strong>Supabase Cloud</strong>",
      plan_pro_f4: "<strong>Resumen IA Apex Summa completo:</strong> Quién habló más, De qué se habló, Objetivos, Llamados de atención, Calendario de tareas y Gráficas",
      plan_pro_f5: "<strong>Generador de Actas Corporativas:</strong> Actas de Consejo, Junta Directiva, Comité y Asamblea",
      plan_pro_cta: "Activar 3 Días Gratis con Bold API ($30.000 COP / $10 USD)",
      portal_profile_title: "Perfil de Usuario y Cuota Diaria",
      lbl_name: "Nombre:",
      lbl_email: "Correo:",
      lbl_storage_retention: "Retención de Almacenamiento (Mega S4):",
      portal_quota_label: "Consumo de Audio Hoy (1 o varios audios):",
      portal_quota_hint: "Tienes 2 horas gratis cada día. Tus archivos en el plan gratuito se almacenan por 24 horas en Mega S4.",
      portal_billing_title: "Suscripción Apex Pro — Bold API",
      portal_billing_desc: "Obtén <strong>3 días de prueba gratis</strong> con cobro automático mensual ($30.000 COP o $10 USD). Desbloquea transcripciones ilimitadas, almacenamiento ilimitado en Mega S4 y todo el poder de <strong>Apex Summa</strong>.",
      lbl_currency: "Moneda de Cobro (Bold)",
      lbl_billing_mode: "Modalidad",
      btn_start_trial_bold: "Iniciar Prueba Gratis 3 Días (Bold API)",
      btn_generate_bold_link: "Ver Firma y Checkout Bold",
      portal_cloud_history_title: "Almacenamiento MEGA S4 & Historial en Supabase Cloud",
      btn_refresh: "Actualizar",
      kpi_retention_policy: "Política de Retención",
      kpi_stored_jobs: "Transcripciones Guardadas",
      step1_title: "Subir y Ordenar Archivos de Audio",
      btn_clear_queue: "Limpiar cola",
      btn_play_sequence: "Escuchar en orden",
      dropzone_title: "Arrastra tus archivos de audio aquí o haz clic para seleccionarlos",
      dropzone_hint: "Soporta MP3, OGG, WAV, M4A, FLAC, WEBM · 1 o varios audios · Almacenamiento en Mega S4",
      reorder_hint: "Arrastra cualquier tarjeta desde el ícono <strong>⠿</strong> (o usa <strong>↑ / ↓</strong>) para cambiar su posición y presiona <strong>Escuchar</strong> en cada pista para verificar el audio antes de transcribir.",
      step2_title: "Motor Apex Vox (Potenciado por Groq)",
      lbl_engine_select: "Selecciona el Modelo (Potenciado por Groq)",
      lbl_speakers_count: "Número de Oradores",
      spk_auto: "Automático (1, 2 o varios oradores)",
      lbl_audio_lang: "Idioma del Audio",
      lbl_context_hint: "Contexto / Vocabulario (Opcional)",
      lbl_active_plan_mode: "Plan Activo (Simulador / Cuenta)",
      lbl_api_override: "Configuración Avanzada de Clave Groq (Opcional — ya configurada en servidor)",
      btn_transcribe_now: "Procesar, Unir y Transcribir con Apex Vox",
      step3_vp_title: "Perfiles de Voz (Identificación de Oradores Conocidos)",
      vp_desc: "Registra una muestra corta de voz (5–30s) de una persona para que Apex Vox reconozca automáticamente su timbre de voz y le asigne su nombre real.",
      btn_enroll_vp: "Registrar Huella de Voz",
      result_card_title: "Transcripción Ordenada con Marcas de Tiempo y Oradores",
      btn_rename_speakers: "Renombrar Oradores",
      empty_state_heading: "Apex Vox — Listo para transcribir e identificar voces en orden",
      empty_state_desc: "Sube uno o varios archivos MP3, OGG o WAV en el panel izquierdo, elige tu modelo <strong>Mc-Ayrton, Mc-Lewis, Mc-Norris o Mc-Piastri</strong> (Potenciado por Groq) y obtén tu transcripción junto con el análisis ejecutivo de <strong>Apex Summa</strong>.",
      kpi_duration_lbl: "Duración Global",
      kpi_speakers_lbl: "Oradores Detectados",
      kpi_engine_lbl: "Modelo Serie Mc",
      kpi_storage_lbl: "Almacenamiento Mega S4",
      player_caption: "Reproductor Continuo Sincronizado (Haz clic en cualquier marca de tiempo para saltar al instante exacto)",
      rename_panel_title: "Asignar nombres personalizados a los oradores identificados:",
      btn_save_names: "Guardar Nombres",
      btn_cancel: "Cancelar",
      summa_main_title: "Resumen Inteligente, Gráficas, Calendario de Tareas y Generador de Actas",
      summa_locked_msg: "El Resumen IA completo de Apex Summa, las Gráficas y el Generador de Actas están incluidos en el Plan Apex Pro ($30.000 COP / $10 USD mes · 3 días de prueba gratis).",
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
      auth_modal_title: "Regístrate en Apex Vox — 2 Horas Gratis al Día",
      auth_modal_subtitle: "Al registrarte obtienes <strong>2 horas gratis cada día</strong> (en 1 o varios audios) con <strong>almacenamiento de 24 horas en Mega S4</strong>. O inicia tu prueba gratis de 3 días en <strong>Apex Pro</strong>.",
      lbl_full_name: "Nombre Completo",
      lbl_password: "Contraseña",
      btn_create_free_account: "Crear Cuenta (2h Gratis / Día)",
      btn_login_existing: "Entrar",
      footer_statement: "Cada audio, en orden. Cada voz, con nombre. Cada reunión, con acta.",
      footer_status: "Estado del servicio",
      lbl_vp_name: "Nombre",
      lbl_vp_sample: "Muestra de voz",
    },
    en: {
      brand_title: "Apex Vox",
      powered_by_groq: "Powered by Groq",
      brand_subtitle: "Audio Studio · Multi-Audio Transcription, Speaker Identification & Apex Summa AI Summary",
      nav_landing: "Home & Plans",
      nav_playground: "Playground (Apex Vox)",
      nav_box: "Apex Box (10h+ & Extension)",
      nav_portal: "User Portal",
      btn_register_login: "Sign Up / Log In",
      hero_badge: "POWERED BY GROQ · MEGA S4 OBJECT STORAGE · SUPABASE CLOUD",
      hero_title: "Apex Vox: Intelligent Transcription, Speaker Separation & Executive Analytics",
      hero_desc: "Sign up today and get <strong>2 free hours per day</strong> across 1 or multiple audios with 24-hour storage, or activate <strong>Apex Pro</strong> with a 3-day free trial, unlimited transcriptions and storage in Mega S4, and executive AI insights with <strong>Apex Summa</strong>.",
      hero_cta_playground: "Open Playground Now",
      hero_cta_box: "Record Unlimited (Apex Box 10h+)",
      hero_cta_register: "Sign Up: 2 Free Hours / Day",
      hero_cta_trial: "Try 3 Days Free (Pro Plan · Bold)",
      suite_heading: "Apex Product Ecosystem",
      suite_vox_status: "Product Ready",
      suite_vox_part: "Transcription (the core)",
      suite_vox_desc: "Ordered multi-audio upload, smart slicing, speaker recognition with Mc-Ayrton, Mc-Lewis, Mc-Norris & Mc-Piastri engines (Powered by Groq), and voiceprint profiles.",
      suite_summa_status: "Active on Pro Plan",
      suite_summa_part: "AI Notes & Summaries",
      suite_summa_desc: "Upon completing transcription, identifies: 1. Who spoke the most, 2. What was discussed, 3. Objectives, 4. Callouts/Warnings, 5. Upcoming tasks calendar, 6. Transcription charts & 7. Formal Minutes (Board, Committee, Assembly).",
      suite_box_status: "Active · Extension & Mobile App",
      suite_box_part: "Unlimited Block Recorder (In-Person, Zoom/Meet/Teams & Mobile Web App)",
      suite_box_desc: "10+ hours continuous recording in optimal 3-min blocks (~1.03 MB) with constant RAM, In-Person & Virtual Meeting modes (Zoom, Meet, Teams), live notes, and Chrome MV3 extension.",
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
      plan_free_f2: "<strong>24-hour storage retention</strong> in Mega S4 cloud",
      plan_free_f3: "Access to <strong>Mc-Ayrton, Mc-Lewis, Mc-Norris & Mc-Piastri</strong> (Powered by Groq)",
      plan_free_f4: "Export to TXT, SRT, VTT, JSON, CSV & Markdown",
      plan_free_cta: "Sign Up Free (2h / day)",
      plan_pro_badge: "3-DAY FREE TRIAL + AUTO BILLING",
      plan_pro_title: "Apex Pro Plan",
      per_month: "month",
      plan_pro_f1: "<strong>3-day free trial</strong> with automatic monthly billing via <strong>Bold API</strong>",
      plan_pro_f2: "<strong>Unlimited transcriptions</strong> (no daily hour or file limit)",
      plan_pro_f3: "<strong>Unlimited permanent storage</strong> in <strong>Mega S4</strong> & <strong>Supabase Cloud</strong>",
      plan_pro_f4: "<strong>Full Apex Summa AI Report:</strong> Who spoke most, Topics, Objectives, Callouts, Calendar Tasks & Charts",
      plan_pro_f5: "<strong>Corporate Minutes Generator:</strong> Board of Directors, Committee & Assembly Minutes",
      plan_pro_cta: "Start 3-Day Free Trial with Bold API ($30,000 COP / $10 USD)",
      portal_profile_title: "User Profile & Daily Quota",
      lbl_name: "Name:",
      lbl_email: "Email:",
      lbl_storage_retention: "Storage Retention (Mega S4):",
      portal_quota_label: "Audio Usage Today (1 or multiple audios):",
      portal_quota_hint: "You get 2 free hours every day. Free tier files are retained for 24 hours in Mega S4.",
      portal_billing_title: "Apex Pro Subscription — Bold API",
      portal_billing_desc: "Get a <strong>3-day free trial</strong> with automatic monthly billing ($30,000 COP or $10 USD). Unlock unlimited transcriptions, unlimited Mega S4 storage, and the full power of <strong>Apex Summa</strong>.",
      lbl_currency: "Billing Currency (Bold)",
      lbl_billing_mode: "Billing Mode",
      btn_start_trial_bold: "Start 3-Day Free Trial (Bold API)",
      btn_generate_bold_link: "View Bold Signature & Checkout",
      portal_cloud_history_title: "MEGA S4 Storage & Supabase Cloud History",
      btn_refresh: "Refresh",
      kpi_retention_policy: "Retention Policy",
      kpi_stored_jobs: "Saved Transcriptions",
      step1_title: "Upload and Order Audio Files",
      btn_clear_queue: "Clear queue",
      btn_play_sequence: "Play in order",
      dropzone_title: "Drag and drop your audio files here or click to browse",
      dropzone_hint: "Supports MP3, OGG, WAV, M4A, FLAC, WEBM · 1 or multiple audios · Stored in Mega S4",
      reorder_hint: "Drag any card by the <strong>⠿</strong> handle (or use <strong>↑ / ↓</strong>) to reorder it, and press <strong>Listen</strong> on each track to verify the audio before transcribing.",
      step2_title: "Apex Vox Engine (Powered by Groq)",
      lbl_engine_select: "Select Engine Model (Powered by Groq)",
      lbl_speakers_count: "Number of Speakers",
      spk_auto: "Automatic (1, 2 or multiple speakers)",
      lbl_audio_lang: "Audio Language",
      lbl_context_hint: "Context / Vocabulary (Optional)",
      lbl_active_plan_mode: "Active Plan (Simulator / Account)",
      lbl_api_override: "Advanced Groq Key Override (Optional — configured on server)",
      btn_transcribe_now: "Process, Merge & Transcribe with Apex Vox",
      step3_vp_title: "Voice Profiles (Known Speaker Identification)",
      vp_desc: "Enroll a short voice sample (5–30s) so Apex Vox automatically recognizes their vocal timbre and assigns their real name.",
      btn_enroll_vp: "Enroll Voiceprint",
      result_card_title: "Ordered Transcript with Timestamps & Speakers",
      btn_rename_speakers: "Rename Speakers",
      empty_state_heading: "Apex Vox — Ready to transcribe and identify voices in order",
      empty_state_desc: "Upload one or multiple MP3, OGG, or WAV files on the left, choose your <strong>Mc-Ayrton, Mc-Lewis, Mc-Norris, or Mc-Piastri</strong> model (Powered by Groq), and get your transcript plus <strong>Apex Summa</strong> executive analytics.",
      kpi_duration_lbl: "Total Duration",
      kpi_speakers_lbl: "Detected Speakers",
      kpi_engine_lbl: "Mc-Series Model",
      kpi_storage_lbl: "Mega S4 Storage",
      player_caption: "Synchronized Continuous Player (Click any timestamp to jump to that exact moment)",
      rename_panel_title: "Assign custom names to identified speakers:",
      btn_save_names: "Save Names",
      btn_cancel: "Cancel",
      summa_main_title: "AI Executive Summary, Charts, Tasks Calendar & Minutes Generator",
      summa_locked_msg: "The full Apex Summa AI Summary, Charts, and Minutes Generator are included in the Apex Pro Plan ($30,000 COP / $10 USD mo · 3-day free trial).",
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
      auth_modal_title: "Sign Up for Apex Vox — 2 Free Hours Per Day",
      auth_modal_subtitle: "Register to get <strong>2 free hours every day</strong> (in 1 or multiple audios) with <strong>24-hour storage in Mega S4</strong>. Or start your 3-day free trial of <strong>Apex Pro</strong>.",
      lbl_full_name: "Full Name",
      lbl_password: "Password",
      btn_create_free_account: "Create Account (2h Free / Day)",
      btn_login_existing: "Log In",
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
  const playgroundPlanSelect = document.getElementById("playground-plan-select");
  const apiKeyInput = document.getElementById("api-key-input");
  const deepgramKeyInput = document.getElementById("deepgram-key-input");
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

  function applyLanguage(lang) {
    const clean = lang === "en" ? "en" : "es";
    state.lang = clean;
    localStorage.setItem("apex_vox_lang", clean);
    document.documentElement.lang = clean;

    if (langEsBtn && langEnBtn) {
      langEsBtn.classList.toggle("active", clean === "es");
      langEnBtn.classList.toggle("active", clean === "en");
    }

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

    updateHeaderPlanPill();
    if (state.currentResult) {
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
      loadBoxOptimalConfig();
    }
  }

  function updateHeaderPlanPill() {
    if (!planPillText) return;
    const isEn = state.lang === "en";
    if (state.plan === "pro" || state.plan === "trial") {
      planPillText.textContent = isEn
        ? "Apex Pro (Unlimited)"
        : "Apex Pro (Ilimitado)";
    } else {
      planPillText.textContent = isEn
        ? "Free Plan (2h/day · 24h)"
        : "Plan Gratis (2h/día · 24h)";
    }
    if (playgroundPlanSelect && playgroundPlanSelect.value !== state.plan) {
      playgroundPlanSelect.value = state.plan === "free" ? "free" : "pro";
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
      if (!res.ok) throw new Error(data.detail || "Error al registrar cuenta.");

      state.user = data;
      state.token = data.access_token;
      state.plan = data.plan || "free";
      localStorage.setItem("apex_vox_user", JSON.stringify(data));
      localStorage.setItem("apex_vox_token", data.access_token || "");
      localStorage.setItem("apex_vox_plan", state.plan);

      if (openAuthBtn) openAuthBtn.textContent = `${data.full_name}`;
      updateHeaderPlanPill();
      if (authDialog) authDialog.close();
      showAlert(
        state.lang === "en"
          ? `Welcome ${data.full_name}! You have 2 free hours/day and 24h storage in Mega S4.`
          : `¡Bienvenido ${data.full_name}! Tienes 2 horas gratis al día y 24h de almacenamiento en Mega S4.`,
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
      if (!res.ok) throw new Error(data.detail || "Credenciales inválidas.");

      state.user = data;
      state.token = data.access_token;
      state.plan = data.plan || "free";
      localStorage.setItem("apex_vox_user", JSON.stringify(data));
      localStorage.setItem("apex_vox_token", data.access_token || "");
      localStorage.setItem("apex_vox_plan", state.plan);

      if (openAuthBtn) openAuthBtn.textContent = `${data.full_name}`;
      updateHeaderPlanPill();
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

  async function activateBoldProTrial() {
    const currencyEl = document.getElementById("bold-currency-select");
    const currency = currencyEl ? currencyEl.value : "COP";
    const uid = state.user ? state.user.user_id : "guest_default";

    try {
      const res = await fetch("/api/billing/subscribe", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          user_id: uid,
          currency: currency,
          auto_billing: true,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "No se pudo activar la prueba gratis.");

      state.user = data;
      state.plan = "pro";
      localStorage.setItem("apex_vox_user", JSON.stringify(data));
      localStorage.setItem("apex_vox_plan", "pro");
      updateHeaderPlanPill();

      if (state.currentResult && state.currentResult.summa_report) {
        state.currentResult.plan = "pro";
        state.currentResult.summa_report.is_locked = false;
        renderApexSumma(state.currentResult);
      }

      await loadUserPortalSummary();
      showAlert(
        state.lang === "en"
          ? "3-Day Free Trial of Apex Pro Activated via Bold API ($30,000 COP / $10 USD auto-billing)! Unlimited transcriptions, Mega S4 storage & Apex Summa unlocked."
          : "¡Prueba Gratis de 3 Días de Apex Pro activada con Bold API ($30.000 COP / $10 USD cobro automático)! Transcripciones ilimitadas, Mega S4 ilimitado y Apex Summa desbloqueados.",
        "success"
      );
    } catch (err) {
      showAlert(err.message);
    }
  }

  async function previewBoldCheckout() {
    const currencyEl = document.getElementById("bold-currency-select");
    const currency = currencyEl ? currencyEl.value : "COP";
    const previewEl = document.getElementById("bold-checkout-preview");
    if (!previewEl) return;

    try {
      const res = await fetch("/api/billing/checkout", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          user_id: state.user ? state.user.user_id : "guest_default",
          currency: currency,
          start_trial: true,
        }),
      });
      const data = await res.json();
      previewEl.classList.remove("hidden");
      previewEl.innerHTML = `
        <div><strong>Bold Order ID:</strong> <code>${escapeHtml(data.order_id)}</code></div>
        <div><strong>Monto / Plan:</strong> ${escapeHtml(data.amount_display)} (${data.trial_days} días gratis + cobro automático)</div>
        <div><strong>Firma Integridad SHA-256 (Bold):</strong> <code style="word-break: break-all;">${escapeHtml(data.integrity_signature)}</code></div>
        <div class="bold-checkout-link">
          <a href="${escapeHtml(data.checkout_url)}" target="_blank" rel="noopener noreferrer" class="text-link-strong">
            Abrir Pasarela de Pago Bold (${escapeHtml(data.currency)})
          </a>
        </div>
      `;
    } catch (err) {
      showAlert(err.message);
    }
  }

  async function loadUserPortalSummary() {
    const uid = state.user ? state.user.user_id : "guest_default";
    try {
      const res = await fetch(`/api/portal/summary?user_id=${encodeURIComponent(uid)}`);
      if (!res.ok) return;
      const data = await res.json();

      const nameEl = document.getElementById("portal-user-name");
      const emailEl = document.getElementById("portal-user-email");
      const badgeEl = document.getElementById("portal-plan-badge");
      const retEl = document.getElementById("portal-retention-label");
      const qNumbers = document.getElementById("portal-quota-numbers");
      const qBar = document.getElementById("portal-quota-bar");
      const kpiRet = document.getElementById("portal-kpi-retention");
      const kpiCount = document.getElementById("portal-kpi-jobs-count");
      const histList = document.getElementById("portal-history-list");

      if (nameEl) nameEl.textContent = data.user.full_name;
      if (emailEl) emailEl.textContent = data.user.email;
      if (badgeEl) badgeEl.textContent = data.quota.plan_display_name;
      if (retEl) retEl.textContent = data.storage.retention_policy;
      if (kpiRet) kpiRet.textContent = data.quota.is_unlimited ? "Ilimitado" : "24 Horas";
      if (kpiCount) kpiCount.textContent = String((data.transcriptions || []).length);

      if (qNumbers && qBar) {
        if (data.quota.is_unlimited) {
          qNumbers.textContent = `${formatSecondsHHMMSS(data.quota.used_today_seconds)} / ∞ (Ilimitado)`;
          qBar.style.width = "100%";
        } else {
          const used = Number(data.quota.used_today_seconds) || 0;
          const limit = Number(data.quota.daily_limit_seconds) || 7200;
          qNumbers.textContent = `${formatSecondsHHMMSS(used)} / ${formatSecondsHHMMSS(limit)} (2h Gratis)`;
          qBar.style.width = `${Math.min(100, Math.max(3, (used / limit) * 100))}%`;
        }
      }

      if (histList) {
        histList.innerHTML = "";
        const items = data.transcriptions || [];
        if (items.length === 0) {
          histList.innerHTML = `<li class="track-item track-item--static">No hay transcripciones registradas aún. Ve al Playground para procesar tus audios.</li>`;
        } else {
          items.forEach((rec) => {
            const li = document.createElement("li");
            li.className = "track-item";
            li.style.cursor = "pointer";
            li.innerHTML = `
              <div class="track-top">
                <span class="track-order-badge">${escapeHtml(rec.engine_brand || "Mc-Lewis")}</span>
                <span class="track-name">Job ${escapeHtml(rec.job_id)} — Orador principal: ${escapeHtml(rec.dominant_speaker || "Hablante 1")}</span>
                <span class="meta-tag timeline">${rec.retention_policy === "unlimited" ? "Mega S4 Ilimitado" : "Mega S4 (24h)"}</span>
              </div>
              <div class="track-meta">
                <span class="meta-tag">Duración: ${escapeHtml(rec.total_duration_formatted || "00:00:00")}</span>
                <span class="meta-tag">Oradores: ${rec.detected_speakers_count || 1}</span>
                <span class="meta-tag">Key: ${escapeHtml(rec.s4_result_key || "mega_s4")}</span>
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
      healthText.textContent = "Sin conexión";
    }
  }

  async function loadVoiceProfiles() {
    try {
      const res = await fetch("/api/voice-profiles");
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
        const res = await fetch(`/api/voice-profiles/${prof.profile_id}`, {
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
      const res = await fetch("/api/voice-profiles", {
        method: "POST",
        body: formData,
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Error registrando perfil de voz.");
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
      const res = await fetch("/api/upload", {
        method: "POST",
        body: formData,
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Error al subir los archivos de audio.");

      state.sessionId = data.session_id;
      state.files = data.files || [];
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
        : `<span class="meta-tag">Mega S4 Ready</span>`;
      const audioSrc = `/api/sessions/${encodeURIComponent(state.sessionId)}/files/${encodeURIComponent(file.file_id)}/audio`;
      const listenLabel = isEn ? "Listen" : "Escuchar";
      const pauseLabel = isEn ? "Pause" : "Pausar";

      li.innerHTML = `
        <div class="track-top">
          <span class="drag-handle" title="${isEn ? "Drag to reorder audio" : "Arrastra para cambiar el orden del audio"}">⠿</span>
          <span class="track-order-badge" title="Posición en la secuencia">#${index + 1}</span>
          <span class="track-name" title="${escapeHtml(file.filename)}">${escapeHtml(file.filename)}</span>
          <div class="track-controls">
            <button type="button" class="icon-btn move-up-btn" title="Subir posición" ${index === 0 ? "disabled" : ""}>↑</button>
            <button type="button" class="icon-btn move-down-btn" title="Bajar posición" ${index === count - 1 ? "disabled" : ""}>↓</button>
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
    queueDurationLabel.textContent = `Duración total: ${formatSecondsHHMMSS(cumulativeSec)} (${cumulativeSec.toFixed(1)}s)`;
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
      `Iniciando Apex Vox con motor ${chosenEngine} (Potenciado por Groq)...`
    );

    const spkVal = speakersSelect.value;
    const numSpeakers = spkVal === "auto" ? null : parseInt(spkVal, 10);
    const activePlan = playgroundPlanSelect ? playgroundPlanSelect.value : state.plan;
    state.plan = activePlan;
    updateHeaderPlanPill();

    const payload = {
      session_id: state.sessionId,
      file_order: state.files.map((f) => f.file_id),
      model: chosenEngine,
      diarization_engine: chosenEngine,
      language: languageSelect.value === "auto" ? null : languageSelect.value,
      num_speakers: numSpeakers,
      prompt_hint: promptHintInput.value.trim() || null,
      api_key: apiKeyInput.value.trim() || null,
      deepgram_api_key: deepgramKeyInput ? deepgramKeyInput.value.trim() || null : null,
      user_id: state.user ? state.user.user_id : "guest_default",
      plan_override: activePlan,
    };

    try {
      const res = await fetch("/api/transcribe", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || "No se pudo iniciar la transcripción.");
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
        const res = await fetch(`/api/jobs/${jobId}/status`);
        const statusData = await res.json();
        if (!res.ok) {
          throw new Error(statusData.detail || "Error consultando estado del trabajo.");
        }

        const chunkInfo =
          statusData.total_chunks > 0
            ? `Fragmentos procesados: ${statusData.completed_chunks}/${statusData.total_chunks} · Almacenando en Mega S4`
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
      const res = await fetch(`/api/jobs/${jobId}/result`);
      const result = await res.json();
      if (!res.ok) {
        throw new Error(result.detail || "Error al obtener el resultado.");
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
        result.plan === "free" ? "Mega S4 (24h)" : "Mega S4 (Ilimitado)";
    }

    mergedAudioPlayer.src = `/api/jobs/${result.job_id}/audio`;

    const jid = result.job_id;
    document.getElementById("export-txt").href = `/api/jobs/${jid}/export/txt`;
    document.getElementById("export-srt").href = `/api/jobs/${jid}/export/srt`;
    document.getElementById("export-vtt").href = `/api/jobs/${jid}/export/vtt`;
    document.getElementById("export-json").href = `/api/jobs/${jid}/export/json`;
    document.getElementById("export-csv").href = `/api/jobs/${jid}/export/csv`;
    document.getElementById("export-md").href = `/api/jobs/${jid}/export/md`;

    renderApexSumma(result);
    renderSpeakerTabs(result);
    renderSegmentsList(result);
  }

  function renderApexSumma(result) {
    const report = result.summa_report;
    if (!report) return;

    const isLocked = report.is_locked && state.plan === "free";
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
      icsBtn.href = `/api/jobs/${result.job_id}/calendar.ics`;
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
      const res = await fetch(`/api/jobs/${jid}/minutes`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          template_type: tplSelect ? tplSelect.value : "consejo",
          language: state.lang,
          organization_name: orgInput ? orgInput.value.trim() : "Apex Vox",
        }),
      });
      const doc = await res.json();
      if (!res.ok) throw new Error(doc.detail || "Error generando el acta.");

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
      const res = await fetch(`/api/jobs/${state.currentResult.job_id}/speakers`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ speaker_map: speakerMap }),
      });
      const updated = await res.json();
      if (!res.ok) {
        throw new Error(updated.detail || "Error al renombrar oradores.");
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

  if (langEsBtn) langEsBtn.addEventListener("click", () => applyLanguage("es"));
  if (langEnBtn) langEnBtn.addEventListener("click", () => applyLanguage("en"));

  if (openAuthBtn && authDialog) {
    openAuthBtn.addEventListener("click", () => authDialog.showModal());
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
  if (heroTrialBtn) {
    heroTrialBtn.addEventListener("click", () => {
      switchView("portal");
      activateBoldProTrial();
    });
  }
  const pricingProBtn = document.getElementById("pricing-pro-btn");
  if (pricingProBtn) {
    pricingProBtn.addEventListener("click", () => {
      switchView("portal");
      activateBoldProTrial();
    });
  }

  const submitRegisterBtn = document.getElementById("submit-register-btn");
  if (submitRegisterBtn) submitRegisterBtn.addEventListener("click", handleRegisterUser);

  const submitLoginBtn = document.getElementById("submit-login-btn");
  if (submitLoginBtn) submitLoginBtn.addEventListener("click", handleLoginUser);

  const portalActivateProBtn = document.getElementById("portal-activate-pro-btn");
  if (portalActivateProBtn) {
    portalActivateProBtn.addEventListener("click", activateBoldProTrial);
  }
  const portalGenerateBoldLinkBtn = document.getElementById("portal-generate-bold-link-btn");
  if (portalGenerateBoldLinkBtn) {
    portalGenerateBoldLinkBtn.addEventListener("click", previewBoldCheckout);
  }
  const refreshPortalBtn = document.getElementById("refresh-portal-btn");
  if (refreshPortalBtn) {
    refreshPortalBtn.addEventListener("click", loadUserPortalSummary);
  }

  const unlockSummaBtn = document.getElementById("unlock-summa-pro-btn");
  if (unlockSummaBtn) unlockSummaBtn.addEventListener("click", activateBoldProTrial);
  const summaTrialBtn = document.getElementById("summa-activate-trial-btn");
  if (summaTrialBtn) summaTrialBtn.addEventListener("click", activateBoldProTrial);

  const generateMinutesBtn = document.getElementById("generate-minutes-btn");
  if (generateMinutesBtn) generateMinutesBtn.addEventListener("click", handleGenerateMinutes);
  const downloadMinutesMdBtn = document.getElementById("download-minutes-md-btn");
  if (downloadMinutesMdBtn) downloadMinutesMdBtn.addEventListener("click", downloadMinutesMarkdown);
  const printMinutesBtn = document.getElementById("print-minutes-btn");
  if (printMinutesBtn) printMinutesBtn.addEventListener("click", printMinutesDocument);

  if (playgroundPlanSelect) {
    playgroundPlanSelect.addEventListener("change", () => {
      state.plan = playgroundPlanSelect.value;
      localStorage.setItem("apex_vox_plan", state.plan);
      updateHeaderPlanPill();
      if (state.currentResult && state.currentResult.summa_report) {
        state.currentResult.plan = state.plan;
        state.currentResult.summa_report.is_locked = state.plan === "free";
        renderApexSumma(state.currentResult);
      }
    });
  }

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
      copyTranscriptBtn.textContent = "¡Copiado!";
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
  const boxState = {
    mode: "presencial", // "presencial" | "virtual"
    status: "idle", // "idle" | "starting" | "recording" | "stopping"
    boxSessionId: null,
    blockDurationSec: 180,
    nextBlockIndex: 0,
    completedBlocksCount: 0,
    startedAtMs: null,
    blockStartedAtMs: null,
    rotationTimer: null,
    clockTimer: null,
    activeRecorder: null,
    activeStream: null,
    micStream: null,
    displayStream: null,
    audioCtx: null,
    analyser: null,
    animFrameId: null,
    wakeLock: null,
    segments: [],
    notes: [],
    blocks: [],
  };

  const boxModePresencialBtn = document.getElementById("box-mode-presencial-btn");
  const boxModeVirtualBtn = document.getElementById("box-mode-virtual-btn");
  const boxActiveModeBadge = document.getElementById("box-active-mode-badge");
  const boxTitleInput = document.getElementById("box-title-input");
  const boxPlatformSelect = document.getElementById("box-platform-select");
  const boxBlockDurationSelect = document.getElementById("box-block-duration-select");
  const boxEngineSelect = document.getElementById("box-engine-select");
  const boxLanguageSelect = document.getElementById("box-language-select");

  const boxRamBadge = document.getElementById("box-ram-badge");
  const boxRamFormulaText = document.getElementById("box-ram-formula-text");
  const boxMasterClock = document.getElementById("box-master-clock");
  const boxBlockClock = document.getElementById("box-block-clock");
  const boxWaveformCanvas = document.getElementById("box-waveform-canvas");

  const boxStartRecBtn = document.getElementById("box-start-rec-btn");
  const boxStartBtnText = document.getElementById("box-start-btn-text");
  const boxCutBlockBtn = document.getElementById("box-cut-block-btn");
  const boxStopRecBtn = document.getElementById("box-stop-rec-btn");
  const boxSimulate10hBtn = document.getElementById("box-simulate-10h-btn");
  const boxStatusAlert = document.getElementById("box-status-alert");

  const boxNoteCategorySelect = document.getElementById("box-note-category-select");
  const boxNoteAuthorInput = document.getElementById("box-note-author-input");
  const boxNoteTextInput = document.getElementById("box-note-text-input");
  const boxAddNoteBtn = document.getElementById("box-add-note-btn");
  const boxNotesCountBadge = document.getElementById("box-notes-count-badge");
  const boxNotesListEl = document.getElementById("box-notes-list");

  const boxKpiBlocks = document.getElementById("box-kpi-blocks");
  const boxKpiDuration = document.getElementById("box-kpi-duration");
  const boxKpiRam = document.getElementById("box-kpi-ram");
  const boxKpiSpeakers = document.getElementById("box-kpi-speakers");
  const boxLiveSegmentsList = document.getElementById("box-live-segments-list");
  const boxBlocksHistoryList = document.getElementById("box-blocks-history-list");
  const boxOpenInPlaygroundBtn = document.getElementById("box-open-in-playground-btn");

  function showBoxAlert(msg, type = "info") {
    if (!boxStatusAlert) return;
    boxStatusAlert.textContent = msg;
    boxStatusAlert.classList.remove("hidden");
    boxStatusAlert.style.borderColor =
      type === "error" ? "#dc2626" : type === "success" ? "#16a34a" : "var(--brand)";
  }

  function formatBoxHms(totalSec) {
    const s = Math.max(0, Math.floor(Number(totalSec) || 0));
    const hrs = Math.floor(s / 3600);
    const mins = Math.floor((s % 3600) / 60);
    const secs = s % 60;
    return [hrs, mins, secs].map((n) => String(n).padStart(2, "0")).join(":");
  }

  function formatBoxMmSs(totalSec) {
    const s = Math.max(0, Math.floor(Number(totalSec) || 0));
    const mins = Math.floor(s / 60);
    const secs = s % 60;
    return `${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
  }

  async function loadBoxOptimalConfig() {
    try {
      const res = await fetch("/api/box/optimal-config?target_hours=10");
      if (!res.ok) return;
      const cfg = await res.json();
      const selDur = boxBlockDurationSelect ? Number(boxBlockDurationSelect.value) || 180 : (cfg.optimal_block_seconds || 180);
      const blockMb = ((48000 / 8) * selDur / (1024 * 1024)).toFixed(2);
      const totalBlocks10h = Math.ceil((10 * 3600) / selDur);
      const unblockedMb = cfg.unblocked_ram_10h_mb || 540;
      if (boxRamBadge) {
        boxRamBadge.textContent = `~${blockMb} MB RAM constante (${cfg.ram_savings_pct}% ahorro)`;
      }
      if (boxRamFormulaText) {
        boxRamFormulaText.innerHTML =
          `Cada bloque de <strong>${Math.round(selDur / 60)} min (${selDur}s)</strong> en Opus 48 kbps pesa <strong>~${blockMb} MB</strong>. ` +
          `Al enviarse a Apex Vox, el bloque se libera de la memoria del navegador/celular (` +
          `<code>chunks.length = 0</code>), permitiendo grabar <strong>10+ horas continuas (${totalBlocks10h} bloques)</strong> ` +
          `usando siempre <strong>~${blockMb} MB de RAM</strong> en lugar de ~${unblockedMb} MB.`;
      }
    } catch (e) {
      // Non-fatal
    }
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
    if (boxActiveModeBadge) {
      boxActiveModeBadge.textContent =
        boxState.mode === "virtual"
          ? "Modo: Reunión Virtual (Zoom / Meet / Teams + Mic)"
          : "Modo: Reunión Presencial / App Celular";
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
    const blockSec = boxBlockDurationSelect ? Number(boxBlockDurationSelect.value) || 180 : 180;
    boxState.blockDurationSec = blockSec;

    const payload = {
      title: (boxTitleInput && boxTitleInput.value.trim()) ||
        (boxState.mode === "virtual" ? "Reunión Virtual (Zoom/Meet/Teams)" : "Reunión Presencial / App Móvil"),
      mode: boxState.mode,
      platform: (boxPlatformSelect && boxPlatformSelect.value) || (boxState.mode === "virtual" ? "google_meet" : "presencial"),
      language: (boxLanguageSelect && boxLanguageSelect.value) || "es",
      diarization_engine: (boxEngineSelect && boxEngineSelect.value) || "Mc-Lewis",
      block_duration_sec: blockSec,
      device_type: /Android|iPhone|iPad|iPod/i.test(navigator.userAgent || "") ? "mobile_pwa" : "web_app",
      plan: state.plan || "pro",
    };

    const res = await fetch("/api/box/sessions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.detail || "No se pudo inicializar la sesión de Apex Box.");
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
    const candidates = [
      "audio/webm;codecs=opus",
      "audio/webm",
      "audio/ogg;codecs=opus",
      "audio/mp4",
    ];
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

    const recorder = new MediaRecorder(boxState.activeStream, options);
    let blockChunks = [];
    const blockStartPerfMs = performance.now();

    recorder.ondataavailable = (ev) => {
      if (ev.data && ev.data.size > 0) {
        blockChunks.push(ev.data);
      }
    };

    recorder.onstop = async () => {
      const actualDurationSec = Math.max(1, (performance.now() - blockStartPerfMs) / 1000);
      const blob = new Blob(blockChunks, { type: mimeType || "audio/webm" });
      // Free RAM immediately — key to 10+ hours constant O(1) memory
      blockChunks.length = 0;

      if (blob.size > 0) {
        await uploadAndTranscribeBoxBlock(blob, blockIdx, actualDurationSec, mimeType || "audio/webm");
      }
    };

    recorder.start(1000);
    boxState.blockStartedAtMs = Date.now();
    return recorder;
  }

  function rotateBoxRecorderBlock(manual = false) {
    if (boxState.status !== "recording" || !boxState.activeStream) return;
    const prevRecorder = boxState.activeRecorder;
    boxState.nextBlockIndex += 1;
    // Start next recorder BEFORE stopping previous recorder so 0 ms of speech is lost
    boxState.activeRecorder = spawnBoxRecorderForBlock(boxState.nextBlockIndex);
    if (prevRecorder && prevRecorder.state !== "inactive") {
      try {
        prevRecorder.stop();
      } catch (e) {}
    }
    if (manual) {
      if (boxState.rotationTimer) clearInterval(boxState.rotationTimer);
      boxState.rotationTimer = setInterval(() => rotateBoxRecorderBlock(false), boxState.blockDurationSec * 1000);
    }
  }

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

      showBoxAlert(`Enviando y transcribiendo Bloque #${blockIndex + 1} (${(blob.size / 1024).toFixed(1)} KB · RAM liberada)...`, "info");

      const res = await fetch(`/api/box/sessions/${sessionId}/blocks`, {
        method: "POST",
        body: formData,
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || `Error al procesar bloque #${blockIndex + 1}`);
      }

      boxState.completedBlocksCount = data.total_blocks_received;
      boxState.blocks.push(data.block);
      if (Array.isArray(data.new_segments) && data.new_segments.length > 0) {
        boxState.segments.push(...data.new_segments);
      }

      renderBoxLiveTelemetry(data);
      showBoxAlert(
        `Bloque #${blockIndex + 1} transcrito (${data.new_segments.length} segmentos nuevos · Total acumulado: ${data.total_duration_formatted}).`,
        "success"
      );
    } catch (err) {
      showBoxAlert(`Aviso en Bloque #${blockIndex + 1}: ${err.message}`, "error");
    }
  }

  function renderBoxLiveTelemetry(latestResponse = null) {
    if (boxKpiBlocks) {
      boxKpiBlocks.textContent = String(boxState.blocks.length);
    }
    if (boxKpiDuration && latestResponse && latestResponse.total_duration_formatted) {
      boxKpiDuration.textContent = latestResponse.total_duration_formatted;
    }
    if (boxKpiRam && latestResponse && latestResponse.ram_freed_total_mb !== undefined) {
      boxKpiRam.textContent = `~1.05 MB (${latestResponse.ram_freed_total_mb} MB liberados)`;
    }
    const uniqueSpeakers = new Set(boxState.segments.map((s) => s.speaker).filter(Boolean));
    if (boxKpiSpeakers) {
      boxKpiSpeakers.textContent = String(uniqueSpeakers.size);
    }

    // Render blocks history
    if (boxBlocksHistoryList) {
      if (boxState.blocks.length === 0) {
        boxBlocksHistoryList.innerHTML = `<div class="track-item"><span>Sin bloques enviados todavía.</span></div>`;
      } else {
        boxBlocksHistoryList.innerHTML = boxState.blocks
          .slice()
          .reverse()
          .map(
            (b) => `
            <div class="track-item">
              <div class="track-meta">
                <div class="track-name">Bloque #${b.block_index + 1} · ${escapeHtml(b.filename)}</div>
                <div class="track-sub">
                  <span>Duración: ${b.duration_sec.toFixed(1)}s</span>
                  <span>Tamaño: ${(b.size_bytes / 1024).toFixed(1)} KB</span>
                  <span>Segmentos: ${b.segments_count}</span>
                  <span>Estado: RAM Liberada ✓</span>
                </div>
              </div>
            </div>
          `
          )
          .join("");
      }
    }

    // Render live segments
    if (boxLiveSegmentsList) {
      if (boxState.segments.length === 0) {
        boxLiveSegmentsList.innerHTML = `
          <div class="empty-state">
            <h4>Listo para grabar horas ilimitadas sin llenar la RAM</h4>
            <p>A medida que cada bloque se procesa, la transcripción aparecerá aquí de forma continua.</p>
          </div>
        `;
      } else {
        const allSpks = Array.from(uniqueSpeakers);
        boxLiveSegmentsList.innerHTML = boxState.segments
          .map((seg) => {
            const spkIdx = Math.max(0, allSpks.indexOf(seg.speaker));
            const badgeClass = `speaker-${spkIdx % 4}`;
            return `
              <div class="segment-card">
                <div class="segment-header">
                  <span class="speaker-badge ${badgeClass}">${escapeHtml(seg.speaker)}</span>
                  <span class="timestamp-btn">[${escapeHtml(seg.start_formatted)} - ${escapeHtml(seg.end_formatted)}] · ${escapeHtml(seg.source_file || "")}</span>
                </div>
                <p class="segment-text">${escapeHtml(seg.text)}</p>
              </div>
            `;
          })
          .join("");
      }
    }
  }

  async function startBoxRecording() {
    if (boxState.status !== "idle") return;
    boxState.status = "starting";
    try {
      const blockSec = boxBlockDurationSelect ? Number(boxBlockDurationSelect.value) || 180 : 180;
      boxState.blockDurationSec = blockSec;
      await ensureBoxBackendSession();

      // Request Mobile WakeLock so phone screen doesn't sleep during multi-hour recording
      if ("wakeLock" in navigator && navigator.wakeLock && navigator.wakeLock.request) {
        try {
          boxState.wakeLock = await navigator.wakeLock.request("screen");
        } catch (e) {}
      }

      const stream = await acquireBoxCaptureStream();
      boxState.activeStream = stream;
      boxState.status = "recording";
      boxState.startedAtMs = Date.now();
      boxState.blockStartedAtMs = Date.now();
      boxState.nextBlockIndex = boxState.blocks.length;

      boxState.activeRecorder = spawnBoxRecorderForBlock(boxState.nextBlockIndex);
      boxState.rotationTimer = setInterval(() => rotateBoxRecorderBlock(false), blockSec * 1000);

      boxState.clockTimer = setInterval(() => {
        if (boxState.status !== "recording") return;
        const elapsedSec = (Date.now() - boxState.startedAtMs) / 1000;
        const blockElapsedSec = (Date.now() - boxState.blockStartedAtMs) / 1000;
        if (boxMasterClock) {
          boxMasterClock.textContent = formatBoxHms(elapsedSec);
          boxMasterClock.classList.add("recording");
        }
        if (boxBlockClock) {
          boxBlockClock.textContent = `Bloque #${boxState.nextBlockIndex + 1} · ${formatBoxMmSs(blockElapsedSec)} / ${formatBoxMmSs(boxState.blockDurationSec)}`;
        }
      }, 500);

      startBoxWaveformVisualizer(stream);

      if (boxStartRecBtn) boxStartRecBtn.disabled = true;
      if (boxCutBlockBtn) boxCutBlockBtn.disabled = false;
      if (boxStopRecBtn) boxStopRecBtn.disabled = false;

      showBoxAlert(
        `Grabando en continuo (${boxState.mode === "virtual" ? "Reunión Virtual + Mic" : "Reunión Presencial / App Móvil"}). Rotación automática cada ${Math.round(blockSec / 60)} min con 0 ms de pérdida y RAM constante.`,
        "success"
      );
    } catch (err) {
      boxState.status = "idle";
      showBoxAlert(
        `No se pudo acceder al micrófono/audio (${err.message}). Puedes usar el botón "⚡ Simular Bloque 10h" para probar el flujo completo sin micrófono.`,
        "error"
      );
    }
  }

  async function stopAndFinalizeBoxRecording() {
    if (boxState.status === "stopping") return;
    boxState.status = "stopping";

    if (boxState.rotationTimer) {
      clearInterval(boxState.rotationTimer);
      boxState.rotationTimer = null;
    }
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

    [boxState.activeStream, boxState.micStream, boxState.displayStream].forEach((st) => {
      if (st && st.getTracks) {
        st.getTracks().forEach((t) => t.stop());
      }
    });
    boxState.activeStream = null;
    boxState.micStream = null;
    boxState.displayStream = null;

    if (boxState.wakeLock) {
      try {
        await boxState.wakeLock.release();
      } catch (e) {}
      boxState.wakeLock = null;
    }

    if (boxMasterClock) boxMasterClock.classList.remove("recording");
    if (boxStartRecBtn) boxStartRecBtn.disabled = false;
    if (boxCutBlockBtn) boxCutBlockBtn.disabled = true;
    if (boxStopRecBtn) boxStopRecBtn.disabled = true;
    boxState.status = "idle";

    if (!boxState.boxSessionId) return;

    try {
      showBoxAlert("Consolidando todos los bloques y notas en vivo con Apex Summa y Generador de Actas...", "info");
      const res = await fetch(`/api/box/sessions/${boxState.boxSessionId}/finalize`, {
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
        throw new Error(finalized.detail || "Error al finalizar la sesión.");
      }

      state.currentJobId = finalized.job_id;
      state.currentResult = finalized.result;
      state.currentMinutes = finalized.minutes;
      renderResultView(finalized.result);

      if (boxOpenInPlaygroundBtn) {
        boxOpenInPlaygroundBtn.classList.remove("hidden");
      }
      showBoxAlert(
        `¡Sesión finalizada con éxito! ${finalized.result.segments.length} segmentos y ${boxState.notes.length} notas integrados en Apex Summa y Acta Oficial.`,
        "success"
      );
    } catch (err) {
      showBoxAlert(`Error al consolidar sesión: ${err.message}`, "error");
    }
  }

  // Generate a real synthetic WAV audio block in memory so users/evaluators can test block streaming with 1 click
  function createSyntheticWavBlob(durationSec = 4, freqHz = 440) {
    const sampleRate = 16000;
    const numSamples = Math.floor(sampleRate * durationSec);
    const buffer = new ArrayBuffer(44 + numSamples * 2);
    const view = new DataView(buffer);

    function writeStr(offset, str) {
      for (let i = 0; i < str.length; i++) {
        view.setUint8(offset + i, str.charCodeAt(i));
      }
    }

    writeStr(0, "RIFF");
    view.setUint32(4, 36 + numSamples * 2, true);
    writeStr(8, "WAVE");
    writeStr(12, "fmt ");
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true); // PCM
    view.setUint16(22, 1, true); // Mono
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, sampleRate * 2, true);
    view.setUint16(32, 2, true);
    view.setUint16(34, 16, true);
    writeStr(36, "data");
    view.setUint32(40, numSamples * 2, true);

    for (let i = 0; i < numSamples; i++) {
      const t = i / sampleRate;
      const envelope = Math.sin(Math.PI * (i / numSamples));
      const sample = Math.sin(2 * Math.PI * freqHz * t) * 0.35 * envelope;
      view.setInt16(44 + i * 2, Math.max(-1, Math.min(1, sample)) * 32767, true);
    }

    return new Blob([buffer], { type: "audio/wav" });
  }

  async function handleSimulateBoxBlock() {
    try {
      await ensureBoxBackendSession();
      const idx = boxState.blocks.length;
      const wavBlob = createSyntheticWavBlob(4, 440 + (idx % 3) * 110);
      await uploadAndTranscribeBoxBlock(wavBlob, idx, 180.0, "audio/wav");
      if (boxStopRecBtn) boxStopRecBtn.disabled = false;
    } catch (err) {
      showBoxAlert(err.message, "error");
    }
  }

  async function handleAddBoxNote() {
    if (!boxNoteTextInput || !boxNoteTextInput.value.trim()) return;
    const text = boxNoteTextInput.value.trim();
    const category = (boxNoteCategorySelect && boxNoteCategorySelect.value) || "nota";
    const author = (boxNoteAuthorInput && boxNoteAuthorInput.value.trim()) || "Participante";

    // Calculate current timestamp in recording
    let elapsedSec = 0;
    if (boxState.status === "recording" && boxState.startedAtMs) {
      elapsedSec = (Date.now() - boxState.startedAtMs) / 1000;
    } else if (boxState.blocks.length > 0) {
      elapsedSec = boxState.blocks.reduce((acc, b) => acc + (Number(b.duration_sec) || 0), 0);
    }

    try {
      const sessionId = await ensureBoxBackendSession();
      const res = await fetch(`/api/box/sessions/${sessionId}/notes`, {
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
        throw new Error(note.detail || "No se pudo guardar la nota.");
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
      const res = await fetch(`/api/box/sessions/${boxState.boxSessionId}/notes/${noteId}`, {
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
      boxNotesCountBadge.textContent = `${boxState.notes.length} notas`;
    }
    if (!boxNotesListEl) return;
    if (boxState.notes.length === 0) {
      boxNotesListEl.innerHTML = "";
      return;
    }
    boxNotesListEl.innerHTML = boxState.notes
      .slice()
      .reverse()
      .map(
        (n) => `
        <div class="track-item">
          <div class="track-meta">
            <div class="track-name">
              <span class="badge badge-accent">[${escapeHtml(n.timestamp_formatted)}] ${escapeHtml(n.category.toUpperCase())}</span>
              <strong>${escapeHtml(n.author)}:</strong> ${escapeHtml(n.text)}
            </div>
          </div>
          <div class="track-actions">
            <button type="button" class="btn-icon-sm" data-delete-note="${escapeHtml(n.note_id)}" title="Eliminar nota">✕</button>
          </div>
        </div>
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
  if (boxBlockDurationSelect) {
    boxBlockDurationSelect.addEventListener("change", loadBoxOptimalConfig);
  }
  if (boxStartRecBtn) {
    boxStartRecBtn.addEventListener("click", startBoxRecording);
  }
  if (boxCutBlockBtn) {
    boxCutBlockBtn.addEventListener("click", () => rotateBoxRecorderBlock(true));
  }
  if (boxStopRecBtn) {
    boxStopRecBtn.addEventListener("click", stopAndFinalizeBoxRecording);
  }
  if (boxSimulate10hBtn) {
    boxSimulate10hBtn.addEventListener("click", handleSimulateBoxBlock);
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

  // Initial boot
  applyLanguage(state.lang);
  checkSystemHealth();
  loadVoiceProfiles();
  loadBoxOptimalConfig();

  // Support deep linking via ?view=box (e.g. from Chrome Extension or PWA shortcut)
  const urlParams = new URLSearchParams(window.location.search);
  const initialViewParam = urlParams.get("view");
  if (initialViewParam && ["landing", "playground", "box", "portal"].includes(initialViewParam)) {
    switchView(initialViewParam);
  }
})();
