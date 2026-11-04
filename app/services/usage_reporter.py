"""
Daily Usage, Cost, Revenue & Bot Notification Service
(app/services/usage_reporter.py)
-----------------------------------------------------
Calculates daily and cumulative metrics for the Audio Transcription & Speaker
Diarization application:
- Audio consumption (seconds, minutes, hours, jobs count, segments count).
- Exact API expenditure (Groq Whisper + Groq Llama 3.3 + Deepgram Nova-2 + Diarization).
- Estimated revenue & net margin (based on configurable price per audio minute/hour).
- Sends formatted daily reports via Telegram Bot API, Webhook (Slack/Discord/n8n/WhatsApp),
  and stores daily JSON/Markdown reports in `outputs/reports/`.
"""

from __future__ import annotations

import datetime
import json
import logging
from pathlib import Path
import os
from typing import Any, Dict, List, Optional

import requests

from app.config import settings
from app.services.audio_engine import format_timestamp_hhmmss

logger = logging.getLogger("app.services.usage_reporter")

# Standard API Pricing (USD per audio minute)
COST_DEEPGRAM_NOVA2_DIARIZE_PER_MIN = float(
    os.getenv("COST_DEEPGRAM_PER_MIN_USD", "0.0063")
)  # $0.0043 base + $0.0020 diarization
COST_GROQ_WHISPER_V3_PER_MIN = float(
    os.getenv("COST_GROQ_WHISPER_PER_MIN_USD", "0.00185")
)  # $0.111 / hour = $0.00185 / min
COST_GROQ_LLM_PER_MIN_AUDIO = float(
    os.getenv("COST_GROQ_LLM_PER_MIN_USD", "0.0002")
)
# Revenue billed/valued per transcribed minute of audio (default $0.05/min = $3.00/hour)
REVENUE_PER_AUDIO_MIN_USD = float(
    os.getenv("REVENUE_PER_MIN_USD", "0.05")
)


def _usage_entry(result_file: Path, data: Dict[str, Any]) -> Dict[str, Any]:
    """Figures for one job. Aggregates only: no account, names or transcript."""
    mtime_local = datetime.datetime.fromtimestamp(result_file.stat().st_mtime).astimezone()
    dur_sec = float(data.get("total_duration_sec") or 0.0)
    dur_min = dur_sec / 60.0
    engine = str(data.get("diarization_engine_used") or "groq_llm").lower()
    segs = data.get("segments") or []

    # Calculate API Cost for this job
    groq_cost = dur_min * (COST_GROQ_WHISPER_V3_PER_MIN + COST_GROQ_LLM_PER_MIN_AUDIO)
    dg_cost = 0.0
    if "deepgram" in engine:
        dg_cost = dur_min * COST_DEEPGRAM_NOVA2_DIARIZE_PER_MIN
        if engine == "deepgram":
            groq_cost = dur_min * COST_GROQ_LLM_PER_MIN_AUDIO

    total_cost = groq_cost + dg_cost
    revenue = dur_min * REVENUE_PER_AUDIO_MIN_USD
    return {
        "job_id": data.get("job_id", result_file.stem),
        "date": mtime_local.strftime("%Y-%m-%d"),
        "timestamp": mtime_local.strftime("%Y-%m-%d %H:%M:%S"),
        "duration_sec": round(dur_sec, 2),
        "duration_min": round(dur_min, 2),
        "duration_formatted": data.get("total_duration_formatted") or format_timestamp_hhmmss(dur_sec),
        "engine": engine,
        "speakers_detected": int(data.get("detected_speakers_count") or 1),
        "segments_count": len(segs),
        "files_count": len(data.get("file_order") or []),
        "cost_groq_usd": round(groq_cost, 4),
        "cost_deepgram_usd": round(dg_cost, 4),
        "cost_total_usd": round(total_cost, 4),
        "revenue_usd": round(revenue, 4),
        "net_margin_usd": round(revenue - total_cost, 4),
    }


def _ledger_path() -> Path:
    return settings.OUTPUT_DIR / "reports" / "usage_ledger.jsonl"


def record_in_ledger(result_file: Path, data: Dict[str, Any]) -> None:
    """Keep a job's figures before retention deletes its files."""
    path = _ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as ledger:
        ledger.write(json.dumps(_usage_entry(result_file, data), ensure_ascii=False) + "\n")


def _read_ledger() -> List[Dict[str, Any]]:
    path = _ledger_path()
    if not path.exists():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            entries.append(json.loads(line))
        except ValueError:
            logger.warning("Skipping an unreadable line in the usage ledger")
    return entries


def compute_usage_report(target_date: Optional[str] = None) -> Dict[str, Any]:
    """
    Scan all completed jobs in `outputs/*_result.json` and compute both:
    - Today's (or `target_date` YYYY-MM-DD) metrics
    - All-time cumulative metrics
    """
    now_local = datetime.datetime.now().astimezone()
    date_str = target_date or now_local.strftime("%Y-%m-%d")

    out_dir = settings.OUTPUT_DIR
    result_files = sorted(out_dir.glob("*_result.json"))

    daily_jobs: List[Dict[str, Any]] = []
    all_jobs: List[Dict[str, Any]] = []
    seen = set()

    for rf in result_files:
        try:
            data = json.loads(rf.read_text(encoding="utf-8"))
            entry = _usage_entry(rf, data)
        except Exception as exc:
            logger.warning("Skipping unreadable result file %s: %s", rf.name, exc)
            continue
        seen.add(entry["job_id"])
        all_jobs.append(entry)
        if entry["date"] == date_str:
            daily_jobs.append(entry)

    # Jobs whose files retention already deleted count through their aggregates.
    for entry in _read_ledger():
        if entry["job_id"] not in seen:
            seen.add(entry["job_id"])
            all_jobs.append(entry)
            if entry["date"] == date_str:
                daily_jobs.append(entry)

    def _summarize(items: List[Dict[str, Any]]) -> Dict[str, Any]:
        tot_sec = sum(x["duration_sec"] for x in items)
        tot_min = tot_sec / 60.0
        dg_sec = sum(x["duration_sec"] for x in items if "deepgram" in x["engine"])
        c_groq = sum(x["cost_groq_usd"] for x in items)
        c_dg = sum(x["cost_deepgram_usd"] for x in items)
        c_tot = sum(x["cost_total_usd"] for x in items)
        rev = sum(x["revenue_usd"] for x in items)
        margin = rev - c_tot
        return {
            "jobs_count": len(items),
            "total_duration_sec": round(tot_sec, 2),
            "total_duration_min": round(tot_min, 2),
            "total_duration_hours": round(tot_min / 60.0, 2),
            "total_duration_formatted": format_timestamp_hhmmss(tot_sec),
            "deepgram_duration_min": round(dg_sec / 60.0, 2),
            "total_segments": sum(x["segments_count"] for x in items),
            "cost_groq_usd": round(c_groq, 4),
            "cost_deepgram_usd": round(c_dg, 4),
            "cost_total_usd": round(c_tot, 4),
            "revenue_estimated_usd": round(rev, 2),
            "net_margin_usd": round(margin, 2),
        }

    daily_summary = _summarize(daily_jobs)
    cumulative_summary = _summarize(all_jobs)

    report = {
        "report_date": date_str,
        "generated_at": now_local.isoformat(),
        "pricing_rates_usd_per_min": {
            "deepgram_nova2_diarize": COST_DEEPGRAM_NOVA2_DIARIZE_PER_MIN,
            "groq_whisper_v3": COST_GROQ_WHISPER_V3_PER_MIN,
            "revenue_tariff_per_min": REVENUE_PER_AUDIO_MIN_USD,
        },
        "daily": daily_summary,
        "cumulative": cumulative_summary,
        "daily_jobs": daily_jobs,
    }
    return report


def format_report_message(report: Dict[str, Any]) -> str:
    """Format the daily usage/cost/revenue report as a clean Markdown/Telegram message."""
    d = report["daily"]
    c = report["cumulative"]
    date_str = report["report_date"]

    lines = [
        f"📊 *REPORTE DIARIO DE CONSUMO, GASTO E INGRESOS — {date_str}*",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        "🔹 *RESUMEN DEL DÍA*",
        f"• *Trabajos procesados:* `{d['jobs_count']}`",
        f"• *Audio transcrito hoy:* `{d['total_duration_formatted']}` (`{d['total_duration_min']:.2f} min` / `{d['total_duration_hours']:.2f} h`)",
        f"• *Minutos en Deepgram hoy:* `{d['deepgram_duration_min']:.2f} min`",
        f"• *Segmentos generados:* `{d['total_segments']}`",
        "",
        "💸 *GASTO EN APIS (HOY)*",
        f"• *Groq (Whisper + Llama 3.3):* `${d['cost_groq_usd']:.4f} USD`",
        f"• *Deepgram (Nova-2 + Diarización):* `${d['cost_deepgram_usd']:.4f} USD`",
        f"• *Gasto Operativo Total (Hoy):* *`${d['cost_total_usd']:.4f} USD`*",
        "",
        "💰 *INGRESOS Y MARGEN ESTIMADO (HOY)*",
        f"• *Ingreso estimado (${report['pricing_rates_usd_per_min']['revenue_tariff_per_min']:.2f}/min):* `${d['revenue_estimated_usd']:.2f} USD`",
        f"• *Margen Neto (Ingreso - Gasto):* *`${d['net_margin_usd']:.2f} USD`*",
        "",
        "📈 *ACUMULADO HISTÓRICO TOTAL*",
        f"• *Trabajos totales:* `{c['jobs_count']}` (`{c['total_duration_min']:.2f} min` / `{c['total_duration_hours']:.2f} h`)",
        f"• *Consumo total Deepgram:* `{c['deepgram_duration_min']:.2f} min` (`${c['cost_deepgram_usd']:.2f} USD`)",
        f"• *Consumo total Groq:* `${c['cost_groq_usd']:.2f} USD`",
        f"• *Gasto Total Acumulado:* `${c['cost_total_usd']:.2f} USD`",
        f"• *Ingreso Total Estimado:* `${c['revenue_estimated_usd']:.2f} USD` (Margen: `${c['net_margin_usd']:.2f} USD`)",
    ]
    return "\n".join(lines)


def send_daily_bot_notification(report: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Persist the daily report to `outputs/reports/` and dispatch it via configured
    Telegram Bot and/or Webhook (Slack, Discord, n8n, WhatsApp gateway).
    """
    rep = report or compute_usage_report()
    message_text = format_report_message(rep)

    reports_dir = settings.OUTPUT_DIR / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    date_str = rep["report_date"]

    json_path = reports_dir / f"report_{date_str}.json"
    md_path = reports_dir / f"report_{date_str}.md"
    json_path.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(message_text + "\n", encoding="utf-8")

    delivery_status: Dict[str, Any] = {
        "saved_json": str(json_path),
        "saved_markdown": str(md_path),
        "telegram_sent": False,
        "webhook_sent": False,
    }

    # Destinos solo desde la configuración del servidor (nunca desde la petición).
    tg_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    tg_chat = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    wh_url = os.getenv("REPORT_WEBHOOK_URL", "").strip()

    if tg_token and tg_chat:
        try:
            tg_url = f"https://api.telegram.org/bot{tg_token}/sendMessage"
            r = requests.post(
                tg_url,
                json={
                    "chat_id": tg_chat,
                    "text": message_text,
                    "parse_mode": "Markdown",
                },
                timeout=15.0,
            )
            delivery_status["telegram_sent"] = r.status_code == 200
            delivery_status["telegram_status_code"] = r.status_code
        except Exception as exc:  # noqa: BLE001 — el detalle va al log, no a la respuesta
            logger.warning("Daily report: Telegram delivery failed (%s)", type(exc).__name__)
            delivery_status["telegram_error"] = "delivery_failed"

    if wh_url:
        try:
            r = requests.post(
                wh_url,
                json={"text": message_text, "content": message_text, "report": rep},
                timeout=15.0,
            )
            delivery_status["webhook_sent"] = 200 <= r.status_code < 300
            delivery_status["webhook_status_code"] = r.status_code
        except Exception as exc:  # noqa: BLE001
            logger.warning("Daily report: webhook delivery failed (%s)", type(exc).__name__)
            delivery_status["webhook_error"] = "delivery_failed"

    return {
        "report": rep,
        "formatted_message": message_text,
        "delivery": delivery_status,
    }
