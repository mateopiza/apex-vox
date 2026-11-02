"""
Apex Summa — AI Intelligence, Analytics, Charts, Calendar & Minutes Service
(app/services/apex_summa.py)
---------------------------------------------------------------------------
Part of the Apex Vox Ecosystem:
- Apex Vox: Core Audio Transcription & Speaker Identification (Ready)
- Apex Summa: AI Notes, Executive Summaries, Analytics & Minutes (Developed here)
- Apex Box: Meeting/Call Recording Bot & Hardware (Coming Soon)

Generates the 7-part post-transcription intelligence suite for paid plans:
1. Quién habló más (Dominant speaker & per-speaker talk time, %, words, WPM, turns)
2. De qué se habló (Executive summary & weighted thematic topics)
3. Objetivos (Core goals, agreements & session objectives)
4. Llamados de atención (Critical warnings, bottlenecks, risks & callouts)
5. Próximas tareas en forma de calendario (Scheduled tasks + .ics iCalendar export)
6. Gráficas de la transcripción (Speaker share, timeline density & topic weight datasets)
7. Generador de Actas (Formal minutes: Consejo / Junta Directiva, Comité, Asamblea, etc.)
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import re
from collections import Counter
from typing import Any, Dict, List, Optional

from app.config import settings
from app.models.schemas import (
    ApexSummaReport,
    CalendarTaskItem,
    CalloutItem,
    DiarizedSegment,
    MinutesDocumentResponse,
    MinutesGenerationRequest,
    SpeakerAnalyticsItem,
    TimelineDensityPoint,
    TopicItem,
    TranscriptionChartsData,
    TranscriptionResult,
)
from app.services.audio_engine import format_timestamp_hhmmss

logger = logging.getLogger("app.services.apex_summa")

MINUTES_TEMPLATES_CATALOG: List[Dict[str, str]] = [
    {
        "id": "consejo",
        "title_es": "Acta de Reunión de Consejo / Junta Directiva",
        "title_en": "Board of Directors Meeting Minutes",
        "description_es": "Formato corporativo solemne con quórum, orden del día, deliberaciones, acuerdos de consejo y firmas.",
        "description_en": "Formal corporate board record with quorum, agenda, deliberations, resolutions, and signature blocks.",
    },
    {
        "id": "comite",
        "title_es": "Acta de Comité Ejecutivo y Operativo",
        "title_en": "Executive & Operational Committee Minutes",
        "description_es": "Enfocada en indicadores, avances, bloqueos críticos y asignación de responsables.",
        "description_en": "Focused on KPIs, progress updates, critical blockers, and owner assignments.",
    },
    {
        "id": "asamblea",
        "title_es": "Acta de Asamblea General de Socios",
        "title_en": "General Shareholders Assembly Minutes",
        "description_es": "Estructura estatutaria con verificación de asistentes, votaciones, resoluciones y clausura.",
        "description_en": "Statutory structure with attendee verification, motions, resolutions, and adjournment.",
    },
    {
        "id": "seguimiento",
        "title_es": "Acta de Seguimiento de Proyecto",
        "title_en": "Project Follow-up & Sprint Minutes",
        "description_es": "Ideal para reuniones técnicas o comerciales con entregables, fechas calendario y próximos pasos.",
        "description_en": "Ideal for technical or commercial syncs with deliverables, calendar dates, and next steps.",
    },
    {
        "id": "ejecutiva",
        "title_es": "Minuta Ejecutiva de Decisiones Rápidas",
        "title_en": "Executive Decision Brief",
        "description_es": "Síntesis ejecutiva de 1 página con conclusiones clave, alertas y calendario de tareas.",
        "description_en": "1-page executive synthesis with key takeaways, alerts, and task calendar.",
    },
]

_STOPWORDS_ES_EN = {
    "el", "la", "los", "las", "un", "una", "unos", "unas", "de", "del", "al", "a", "en",
    "con", "por", "para", "sin", "sobre", "entre", "hasta", "desde", "que", "y", "o", "u",
    "pero", "mas", "más", "como", "cómo", "cuando", "donde", "quien", "cual", "este",
    "esta", "estos", "estas", "ese", "esa", "esos", "esas", "aquel", "aquella", "mi",
    "tu", "su", "nuestro", "vuestro", "se", "me", "te", "le", "les", "nos", "lo", "sí",
    "si", "no", "ya", "muy", "también", "tambien", "así", "asi", "todo", "toda", "todos",
    "es", "son", "fue", "era", "ser", "estar", "está", "esta", "están", "hay", "tiene",
    "tienen", "hacer", "hace", "vamos", "voy", "bien", "claro", "hola", "gracias", "bueno",
    "pues", "entonces", "porque", "the", "and", "for", "that", "this", "with", "from",
    "have", "has", "had", "not", "are", "was", "were", "will", "would", "can", "could",
    "should", "about", "into", "your", "our", "their", "they", "them", "what", "when",
}


def compute_speaker_analytics(
    segments: List[DiarizedSegment],
    speaker_roles: Optional[Dict[str, str]] = None,
) -> List[SpeakerAnalyticsItem]:
    """
    Compute exact per-speaker metrics from diarized segments:
    - Total speaking duration (seconds & HH:MM:SS)
    - Percentage of total talk time
    - Total word count, turn count, words per minute (WPM), and average turn length
    Sorted descending by total speaking duration so index 0 is 'Quién habló más'.
    """
    if not segments:
        return []

    roles = speaker_roles or {}
    acc: Dict[str, Dict[str, Any]] = {}

    for seg in segments:
        spk = seg.speaker or "Hablante 1"
        dur = max(0.1, float(seg.end) - float(seg.start))
        words = len((seg.text or "").split())
        if spk not in acc:
            acc[spk] = {"duration": 0.0, "words": 0, "turns": 0}
        acc[spk]["duration"] += dur
        acc[spk]["words"] += words
        acc[spk]["turns"] += 1

    total_talk_sec = max(0.001, sum(v["duration"] for v in acc.values()))
    items: List[SpeakerAnalyticsItem] = []

    for spk, data in acc.items():
        dur = round(data["duration"], 2)
        pct = round((data["duration"] / total_talk_sec) * 100.0, 1)
        words = int(data["words"])
        turns = int(data["turns"])
        wpm = round((words / max(0.1, dur / 60.0)), 1)
        avg_turn = round(dur / max(1, turns), 2)
        items.append(
            SpeakerAnalyticsItem(
                speaker=spk,
                role=roles.get(spk, ""),
                total_duration_sec=dur,
                duration_formatted=format_timestamp_hhmmss(dur),
                talk_percentage=pct,
                word_count=words,
                turn_count=turns,
                words_per_minute=wpm,
                avg_turn_sec=avg_turn,
            )
        )

    items.sort(key=lambda x: (x.total_duration_sec, x.word_count), reverse=True)
    return items


def compute_timeline_density(
    segments: List[DiarizedSegment],
    total_duration_sec: float,
    num_buckets: int = 6,
) -> List[TimelineDensityPoint]:
    """Build chronological activity buckets for the transcription timeline chart."""
    if not segments:
        return []

    max_end = max(float(total_duration_sec or 0.0), max(float(s.end) for s in segments), 1.0)
    bucket_count = min(max(3, num_buckets), max(3, len(segments)))
    bucket_size = max_end / bucket_count

    points: List[TimelineDensityPoint] = []
    for i in range(bucket_count):
        b_start = round(i * bucket_size, 1)
        b_end = round((i + 1) * bucket_size, 1)
        in_bucket = [
            s
            for s in segments
            if (float(s.start) < b_end and float(s.end) >= b_start)
        ]
        words = sum(len((s.text or "").split()) for s in in_bucket)
        spk_counter: Counter[str] = Counter()
        for s in in_bucket:
            spk_counter[s.speaker] += len((s.text or "").split())
        dom_spk = spk_counter.most_common(1)[0][0] if spk_counter else "-"
        label = f"{format_timestamp_hhmmss(b_start)[3:]} - {format_timestamp_hhmmss(b_end)[3:]}"
        points.append(
            TimelineDensityPoint(
                bucket_label=label,
                start_sec=b_start,
                end_sec=b_end,
                word_count=words,
                active_speakers=len(spk_counter),
                dominant_speaker=dom_spk,
            )
        )
    return points


def _extract_heuristic_insights(
    result: TranscriptionResult,
    speaker_stats: List[SpeakerAnalyticsItem],
    lang: str = "es",
) -> Dict[str, Any]:
    """
    Deterministic NLP extraction of topics, objectives, callouts/warnings,
    and calendar tasks from the transcript segments. Used as baseline and
    fallback when Groq API is mocked or offline.
    """
    segments = result.segments or []
    all_text = " ".join(s.text for s in segments)
    tokens = re.findall(r"[a-záéíóúñüA-ZÁÉÍÓÚÑÜ]{4,}", all_text.lower())
    filtered_tokens = [t for t in tokens if t not in _STOPWORDS_ES_EN]
    top_words = [w for w, _ in Counter(filtered_tokens).most_common(12)]

    dominant = speaker_stats[0] if speaker_stats else None
    dom_name = dominant.speaker if dominant else "Hablante 1"
    dom_pct = dominant.talk_percentage if dominant else 100.0
    is_en = (lang or "es").lower().startswith("en")

    # 2. Executive Summary & Topics
    sample_sentences = [s.text.strip() for s in segments[:4] if len(s.text.strip()) > 10]
    joined_preview = " ".join(sample_sentences)[:260]

    if is_en:
        exec_summary = (
            f"Session analyzed across {len(segments)} interventions ({result.total_duration_formatted}) "
            f"with {result.detected_speakers_count} identified speaker(s). "
            f"{dom_name} led the conversation with {dom_pct}% of speaking time. "
            f"Core discussion centered on {', '.join(top_words[:5]) if top_words else 'project execution and coordination'}. "
            f"Key excerpt: \"{joined_preview}\""
        )
    else:
        exec_summary = (
            f"Sesión analizada con {len(segments)} intervenciones ({result.total_duration_formatted}) "
            f"y {result.detected_speakers_count} orador(es) identificado(s). "
            f"{dom_name} lideró la participación con el {dom_pct}% del tiempo hablado. "
            f"Los ejes centrales abordaron {', '.join(top_words[:5]) if top_words else 'el desarrollo de la sesión y acuerdos operativos'}. "
            f" Síntesis inicial: \"{joined_preview}\""
        )

    topics: List[TopicItem] = []
    chunk_size = max(1, len(segments) // 3)
    for idx in range(min(3, max(1, len(segments)))):
        slice_segs = segments[idx * chunk_size : (idx + 1) * chunk_size] or segments[:2]
        slice_text = " ".join(s.text for s in slice_segs)
        slice_words = [
            w
            for w in re.findall(r"[a-záéíóúñü]{4,}", slice_text.lower())
            if w not in _STOPWORDS_ES_EN
        ]
        kw = list(dict.fromkeys(slice_words))[:4] or ["conversación", "análisis"]
        rel = [45, 35, 20][idx] if idx < 3 else 20
        title_kw = kw[0].capitalize() if kw else f"Tema {idx + 1}"
        topics.append(
            TopicItem(
                title=(
                    f"Bloque {idx + 1}: {title_kw} y contexto"
                    if not is_en
                    else f"Topic {idx + 1}: {title_kw} & Context"
                ),
                summary=slice_segs[0].text if slice_segs else exec_summary,
                relevance_pct=rel,
                keywords=kw,
            )
        )

    # 3. Objectives
    objectives: List[str] = []
    obj_triggers = ("objetivo", "meta", "lograr", "proyecto", "acuerdo", "avance", "necesitamos", "vamos", "goal", "plan")
    for s in segments:
        low = s.text.lower()
        if any(t in low for t in obj_triggers) and len(objectives) < 4:
            objectives.append(f"[{s.speaker}] {s.text.strip()}")

    if not objectives:
        if is_en:
            objectives = [
                f"Consolidate key agreements and action items led by {dom_name}.",
                "Validate project timeline, deliverables, and team responsibilities.",
                "Ensure follow-up on critical points raised during the session.",
            ]
        else:
            objectives = [
                f"Consolidar los acuerdos clave y puntos expuestos principalmente por {dom_name}.",
                "Validar el avance, tiempos de entrega y compromisos entre los participantes.",
                "Realizar seguimiento estructurado a las tareas e intervenciones registradas.",
            ]

    # 4. Callouts / Warnings ('Llamados de atención')
    callouts: List[CalloutItem] = []
    warn_triggers = (
        "difícil", "imposible", "problema", "atención", "cuidado", "urgente",
        "error", "riesgo", "retraso", "importante", "falta", "pero", "no se", "desafío",
        "issue", "risk", "urgent", "warning", "blocker",
    )
    for s in segments:
        low = s.text.lower()
        if any(w in low for w in warn_triggers) and len(callouts) < 4:
            callouts.append(
                CalloutItem(
                    title=(
                        f"Punto de atención señalado por {s.speaker}"
                        if not is_en
                        else f"Attention Point raised by {s.speaker}"
                    ),
                    description=s.text.strip(),
                    speaker=s.speaker,
                    timestamp=s.start_formatted,
                    severity="alta" if any(x in low for x in ("imposible", "urgente", "error", "riesgo")) else "media",
                )
            )

    if not callouts and segments:
        first_seg = segments[min(1, len(segments) - 1)]
        callouts.append(
            CalloutItem(
                title=(
                    "Revisión de tiempos y balance de participación"
                    if not is_en
                    else "Review of Timeline & Speaker Balance"
                ),
                description=(
                    f"{dom_name} concentró el {dom_pct}% de la intervención. Verificar validación de acuerdos por todos los participantes. ({first_seg.text})"
                    if not is_en
                    else f"{dom_name} accounted for {dom_pct}% of speaking time. Verify agreement alignment across all participants."
                ),
                speaker=first_seg.speaker,
                timestamp=first_seg.start_formatted,
                severity="media",
            )
        )

    # 5. Upcoming Tasks in Calendar Format ('Próximas tareas en forma de calendario')
    base_date = dt.date.today()
    speakers_list = [s.speaker for s in speaker_stats] or ["Hablante 1"]
    calendar_tasks: List[CalendarTaskItem] = [
        CalendarTaskItem(
            task_id="task_1",
            title=(
                "Validar acta y acuerdos de la sesión"
                if not is_en
                else "Validate meeting minutes and session agreements"
            ),
            description=(
                f"Revisar puntos clave discutidos ({', '.join(top_words[:3]) or 'general'}) y confirmar responsables."
                if not is_en
                else f"Review key points discussed ({', '.join(top_words[:3]) or 'general'}) and confirm owners."
            ),
            assignee=speakers_list[0],
            due_date=(base_date + dt.timedelta(days=1)).isoformat(),
            due_time="10:00",
            priority="alta",
            category="Revisión",
        ),
        CalendarTaskItem(
            task_id="task_2",
            title=(
                "Seguimiento a llamados de atención y pendientes"
                if not is_en
                else "Follow up on callouts and open action items"
            ),
            description=(
                callouts[0].description if callouts else "Verificar cumplimiento de entregables."
            ),
            assignee=speakers_list[min(1, len(speakers_list) - 1)],
            due_date=(base_date + dt.timedelta(days=3)).isoformat(),
            due_time="14:30",
            priority="alta",
            category="Ejecución",
        ),
        CalendarTaskItem(
            task_id="task_3",
            title=(
                "Reunión de control de objetivos y cierre de ciclo"
                if not is_en
                else "Objectives checkpoint & milestone review"
            ),
            description=objectives[0] if objectives else "Evaluación de resultados.",
            assignee="Equipo Completo" if not is_en else "Full Team",
            due_date=(base_date + dt.timedelta(days=7)).isoformat(),
            due_time="09:00",
            priority="media",
            category="Comité",
        ),
    ]

    return {
        "executive_summary": exec_summary,
        "topics": topics,
        "objectives": objectives,
        "callouts": callouts,
        "calendar_tasks": calendar_tasks,
    }


def _enrich_with_groq_llm(
    result: TranscriptionResult,
    speaker_stats: List[SpeakerAnalyticsItem],
    lang: str = "es",
    api_key: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    When a live Groq API key is configured, synthesize executive summary,
    topics, objectives, callouts, and calendar tasks using Groq LLM.
    """
    eff_key = (api_key or settings.GROQ_API_KEY or "").strip()
    if not eff_key or eff_key.startswith("gsk_test") or eff_key.startswith("gsk_valid"):
        return None

    try:
        from groq import Groq

        client = Groq(api_key=eff_key, timeout=25.0)
        transcript_excerpt = (result.full_text or "")[:10000]
        if not transcript_excerpt.strip():
            return None

        today_iso = dt.date.today().isoformat()
        lang_label = "English" if (lang or "es").lower().startswith("en") else "Spanish"
        prompt = f"""Analyze the following diarized transcript and return ONLY a valid JSON object in {lang_label} with these exact keys:
- "executive_summary": string (concise 3-4 sentence summary of what was discussed)
- "topics": array of 3 objects {{"title": string, "summary": string, "relevance_pct": number, "keywords": [string]}}
- "objectives": array of 3-5 strings (clear objectives and goals identified)
- "callouts": array of 2-4 objects {{"title": string, "description": string, "speaker": string, "timestamp": string, "severity": "alta"|"media"}} (warnings, blockers, callouts, or critical attention points)
- "calendar_tasks": array of 3-4 objects {{"task_id": string, "title": string, "description": string, "assignee": string, "due_date": "YYYY-MM-DD" (starting after {today_iso}), "due_time": "HH:MM", "priority": "alta"|"media", "category": string}}

Transcript:
{transcript_excerpt}
"""
        completion = client.chat.completions.create(
            model=settings.DEFAULT_LLM_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "You are Apex Summa, an executive meeting intelligence engine. Output valid JSON only.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        raw_content = completion.choices[0].message.content or "{}"
        parsed = json.loads(raw_content)
        return parsed
    except Exception as exc:
        logger.debug("Apex Summa LLM enrichment fallback to deterministic analyzer: %s", exc)
        return None


def generate_apex_summa_report(
    result: TranscriptionResult,
    language: str = "es",
    api_key: Optional[str] = None,
    is_locked: bool = False,
) -> ApexSummaReport:
    """
    Build the complete 7-part Apex Summa AI intelligence report for a completed transcription.
    """
    lang = (language or result.language or "es").strip().lower()
    if lang not in ("es", "en"):
        lang = "es"

    # 1. Quién habló más (Exact quantitative calculation)
    speaker_stats = compute_speaker_analytics(result.segments, result.speaker_roles)
    dominant_speaker = speaker_stats[0].speaker if speaker_stats else "Hablante 1"
    dominant_pct = speaker_stats[0].talk_percentage if speaker_stats else 100.0

    # 6. Gráficas de la transcripción (Timeline density & distribution)
    timeline_density = compute_timeline_density(
        result.segments, result.total_duration_sec, num_buckets=6
    )

    # 2, 3, 4, 5: Heuristic baseline + optional Groq LLM synthesis
    baseline = _extract_heuristic_insights(result, speaker_stats, lang=lang)
    llm_data = _enrich_with_groq_llm(result, speaker_stats, lang=lang, api_key=api_key)

    exec_summary = baseline["executive_summary"]
    topics = baseline["topics"]
    objectives = baseline["objectives"]
    callouts = baseline["callouts"]
    calendar_tasks = baseline["calendar_tasks"]

    if llm_data:
        if llm_data.get("executive_summary"):
            exec_summary = str(llm_data["executive_summary"])
        if isinstance(llm_data.get("topics"), list) and llm_data["topics"]:
            try:
                topics = [TopicItem(**t) for t in llm_data["topics"][:5]]
            except Exception:
                pass
        if isinstance(llm_data.get("objectives"), list) and llm_data["objectives"]:
            objectives = [str(o) for o in llm_data["objectives"][:6]]
        if isinstance(llm_data.get("callouts"), list) and llm_data["callouts"]:
            try:
                callouts = [CalloutItem(**c) for c in llm_data["callouts"][:5]]
            except Exception:
                pass
        if isinstance(llm_data.get("calendar_tasks"), list) and llm_data["calendar_tasks"]:
            try:
                calendar_tasks = [
                    CalendarTaskItem(
                        task_id=str(t.get("task_id") or f"task_{i+1}"),
                        title=str(t.get("title") or "Tarea"),
                        description=str(t.get("description") or ""),
                        assignee=str(t.get("assignee") or dominant_speaker),
                        due_date=str(t.get("due_date") or dt.date.today().isoformat()),
                        due_time=str(t.get("due_time") or "09:00"),
                        priority=str(t.get("priority") or "alta"),
                        category=str(t.get("category") or "Seguimiento"),
                    )
                    for i, t in enumerate(llm_data["calendar_tasks"][:6])
                ]
            except Exception:
                pass

    charts = TranscriptionChartsData(
        speaker_distribution=speaker_stats,
        timeline_density=timeline_density,
        topic_weights=[
            {"title": t.title, "relevance_pct": t.relevance_pct, "keywords": t.keywords}
            for t in topics
        ],
    )

    templates_list = [
        {
            "id": item["id"],
            "title": item["title_en"] if lang == "en" else item["title_es"],
            "description": item["description_en"] if lang == "en" else item["description_es"],
        }
        for item in MINUTES_TEMPLATES_CATALOG
    ]

    return ApexSummaReport(
        job_id=result.job_id,
        generated_at=dt.datetime.now(dt.timezone.utc).isoformat(),
        language=lang,
        is_locked=is_locked,
        dominant_speaker=dominant_speaker,
        dominant_speaker_pct=dominant_pct,
        speaker_stats=speaker_stats,
        executive_summary=exec_summary,
        topics=topics,
        objectives=objectives,
        callouts=callouts,
        calendar_tasks=calendar_tasks,
        charts=charts,
        available_minutes_templates=templates_list,
    )


def generate_ics_calendar(report: ApexSummaReport) -> str:
    """
    Export Apex Summa's upcoming tasks ('Próximas tareas en forma de calendario')
    as a standard RFC 5545 iCalendar (.ics) file.
    """
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Apex Vox & Apex Summa//Powered by Groq//ES",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]
    now_stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    for task in report.calendar_tasks:
        date_clean = (task.due_date or dt.date.today().isoformat()).replace("-", "")
        time_clean = (task.due_time or "09:00").replace(":", "") + "00"
        dtstart = f"{date_clean}T{time_clean}"
        dtend = f"{date_clean}T100000"
        uid = f"{report.job_id}-{task.task_id}@apexvox.ai"
        summary = f"[Apex Summa] {task.title} ({task.assignee})"
        desc = (task.description or "").replace("\n", " ")

        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:{uid}",
                f"DTSTAMP:{now_stamp}",
                f"DTSTART:{dtstart}",
                f"DTEND:{dtend}",
                f"SUMMARY:{summary}",
                f"DESCRIPTION:Responsable: {task.assignee} | Prioridad: {task.priority} | {desc}",
                "END:VEVENT",
            ]
        )

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def generate_meeting_minutes(
    result: TranscriptionResult,
    report: ApexSummaReport,
    req: MinutesGenerationRequest,
) -> MinutesDocumentResponse:
    """
    Generate formal meeting minutes ('Actas') according to the selected template:
    - consejo: Acta de Reunión de Consejo / Junta Directiva
    - comite: Acta de Comité Ejecutivo y Operativo
    - asamblea: Acta de Asamblea General de Socios
    - seguimiento: Acta de Seguimiento de Proyecto
    - ejecutiva: Minuta Ejecutiva de Decisiones Rápidas
    """
    lang = (req.language or report.language or "es").strip().lower()
    is_en = lang.startswith("en")
    tpl_id = (req.template_type or "consejo").strip().lower()

    tpl_meta = next(
        (t for t in MINUTES_TEMPLATES_CATALOG if t["id"] == tpl_id),
        MINUTES_TEMPLATES_CATALOG[0],
    )
    tpl_title = tpl_meta["title_en"] if is_en else tpl_meta["title_es"]
    org_name = req.organization_name or "Apex Vox Organization"
    meeting_title = req.meeting_title or tpl_title
    now_str = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    attendees_md = "\n".join(
        f"- **{s.speaker}** ({s.talk_percentage}% participación · {s.duration_formatted} · {s.word_count} palabras)"
        for s in report.speaker_stats
    )
    topics_md = "\n".join(
        f"{i+1}. **{t.title}** ({t.relevance_pct}%): {t.summary}"
        for i, t in enumerate(report.topics)
    )
    objectives_md = "\n".join(f"- {obj}" for obj in report.objectives)
    callouts_md = "\n".join(
        f"- **[{c.severity.upper()}] {c.title}** ({c.speaker} @ {c.timestamp}): {c.description}"
        for c in report.callouts
    )
    tasks_table_rows = "\n".join(
        f"| {t.due_date} {t.due_time} | **{t.title}** | {t.assignee} | {t.priority.upper()} | {t.description} |"
        for t in report.calendar_tasks
    )
    notes_block_en = f"## 6. Additional Notes\n{req.custom_notes}\n" if req.custom_notes else ""
    notes_block_es = f"## 6. Observaciones Especiales\n{req.custom_notes}\n" if req.custom_notes else ""

    if is_en:
        md = f"""# {meeting_title}
**Organization:** {org_name}  
**Document Type:** {tpl_title}  
**Date & Time:** {now_str}  
**Reference Job ID:** `{result.job_id}`  
**Total Audio Duration:** {result.total_duration_formatted}  
**Engine:** {result.engine_brand} (Powered by Groq)

---

## 1. Quorum & Identified Participants (Who Spoke the Most)
Dominant Speaker: **{report.dominant_speaker}** ({report.dominant_speaker_pct}% of total speaking time)

{attendees_md}

## 2. Agenda & Key Discussion Topics (What Was Discussed)
{report.executive_summary}

{topics_md}

## 3. Resolutions, Goals & Objectives
{objectives_md}

## 4. Callouts, Warnings & Critical Observations
{callouts_md}

## 5. Action Items & Scheduled Calendar Commitments
| Date & Time | Action Item | Owner / Assignee | Priority | Details |
| :--- | :--- | :--- | :--- | :--- |
{tasks_table_rows}

{notes_block_en}
---

## Formal Signatures & Approval
- **Chair / Dominant Speaker ({report.dominant_speaker}):** ___________________________
- **Secretary / Recorder (Apex Summa AI):** ___________________________
"""
    else:
        md = f"""# {meeting_title}
**Organización:** {org_name}  
**Tipo de Documento:** {tpl_title}  
**Fecha de Emisión:** {now_str}  
**ID de Sesión:** `{result.job_id}`  
**Duración Total Registrada:** {result.total_duration_formatted}  
**Motor de Transcripción:** {result.engine_brand} (Potenciado por Groq)

---

## 1. Verificación de Quórum y Participación (Quién Habló Más)
Orador con Mayor Intervención: **{report.dominant_speaker}** ({report.dominant_speaker_pct}% del tiempo total hablado)

{attendees_md}

## 2. Orden del Día y Desarrollo de la Sesión (De Qué se Habló)
{report.executive_summary}

{topics_md}

## 3. Objetivos, Acuerdos y Resoluciones Adoptadas
{objectives_md}

## 4. Llamados de Atención, Alertas y Salvamentos
{callouts_md}

## 5. Cronograma de Próximas Tareas y Compromisos (Calendario)
| Fecha y Hora | Compromiso / Tarea | Responsable | Prioridad | Detalle |
| :--- | :--- | :--- | :--- | :--- |
{tasks_table_rows}

{notes_block_es}
---

## Constancia y Firmas de Aprobación
En constancia de lo anterior, se firma la presente **{tpl_title}**:

- **Presidente / Vocero Principal ({report.dominant_speaker}):** ___________________________
- **Secretaría Técnica (Generado por Apex Summa IA):** ___________________________
"""

    # Build clean printable HTML version
    html = f"""<div class="minutes-document">
  <div class="minutes-header">
    <h2>{meeting_title}</h2>
    <p><strong>{org_name}</strong> · {tpl_title} · {now_str}</p>
    <p class="minutes-meta">ID: {result.job_id} · Duración: {result.total_duration_formatted} · Motor: {result.engine_brand} (Potenciado por Groq)</p>
  </div>
  <hr/>
  <h3>1. {'Quorum & Speaker Participation' if is_en else 'Verificación de Quórum y Participación (Quién Habló Más)'}</h3>
  <p><strong>{'Dominant Speaker' if is_en else 'Mayor intervención'}:</strong> {report.dominant_speaker} ({report.dominant_speaker_pct}%)</p>
  <ul>
    {''.join(f"<li><strong>{s.speaker}</strong>: {s.talk_percentage}% ({s.duration_formatted}, {s.word_count} palabras)</li>" for s in report.speaker_stats)}
  </ul>
  <h3>2. {'Executive Summary & Topics' if is_en else 'Orden del Día y Desarrollo (De Qué se Habló)'}</h3>
  <p>{report.executive_summary}</p>
  <ol>
    {''.join(f"<li><strong>{t.title}</strong> ({t.relevance_pct}%): {t.summary}</li>" for t in report.topics)}
  </ol>
  <h3>3. {'Objectives & Resolutions' if is_en else 'Objetivos y Acuerdos'}</h3>
  <ul>
    {''.join(f"<li>{o}</li>" for o in report.objectives)}
  </ul>
  <h3>4. {'Callouts & Critical Warnings' if is_en else 'Llamados de Atención'}</h3>
  <ul>
    {''.join(f"<li><strong>[{c.severity.upper()}] {c.title}</strong> ({c.speaker} @ {c.timestamp}): {c.description}</li>" for c in report.callouts)}
  </ul>
  <h3>5. {'Calendar Action Items' if is_en else 'Calendario de Próximas Tareas y Compromisos'}</h3>
  <table class="minutes-table">
    <thead>
      <tr>
        <th>{'Date' if is_en else 'Fecha'}</th>
        <th>{'Task' if is_en else 'Tarea'}</th>
        <th>{'Owner' if is_en else 'Responsable'}</th>
        <th>{'Priority' if is_en else 'Prioridad'}</th>
      </tr>
    </thead>
    <tbody>
      {''.join(f"<tr><td>{t.due_date} {t.due_time}</td><td><strong>{t.title}</strong><br/><small>{t.description}</small></td><td>{t.assignee}</td><td>{t.priority.upper()}</td></tr>" for t in report.calendar_tasks)}
    </tbody>
  </table>
  <div class="minutes-signatures">
    <div>___________________________<br/><strong>{report.dominant_speaker}</strong></div>
    <div>___________________________<br/><strong>Apex Summa · Secretaría</strong></div>
  </div>
</div>"""

    return MinutesDocumentResponse(
        job_id=result.job_id,
        template_type=tpl_id,
        template_title=tpl_title,
        language=lang,
        generated_at=now_str,
        markdown_content=md,
        html_content=html,
    )
