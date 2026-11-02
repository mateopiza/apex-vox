"""
Transactional email and newsletter contacts through Resend (app/services/email_service.py)
-----------------------------------------------------------------------------------------
- Templates follow the Apex Vox visual language (paper, ink, orange) with inline
  styles and table layout so they render in Gmail, Outlook and Apple Mail.
- Every template exists in Spanish and English; plain-text parts are included.
- Sending is fire-and-forget: failures are logged, never raised to the request.
"""

from __future__ import annotations

import html
import logging
import threading
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import httpx

from app.config import settings

logger = logging.getLogger("app.services.email_service")

RESEND_API = "https://api.resend.com"
_TIMEOUT = httpx.Timeout(10.0, connect=5.0)

# Brand tokens (subset of tokens.css, inlined for email clients)
PAPER = "#f3f3ee"
CARD = "#ffffff"
INK = "#302b28"
TEXT = "#2d2f33"
MUTED = "#69695d"
LINE = "#cecebf"
ORANGE = "#f43e01"
ORANGE_DARK = "#c23101"
SANS = "'Outfit','Helvetica Neue',Helvetica,Arial,sans-serif"
MONO = "'IBM Plex Mono',Menlo,Consolas,monospace"


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

def _esc(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def _mark() -> str:
    """Pixel 'A' brand mark built from table cells (no images to block)."""
    cell = f'<td width="8" height="8" style="width:8px;height:8px;background:{ORANGE};font-size:0;line-height:0;">&nbsp;</td>'
    gap = '<td width="8" height="8" style="width:8px;height:8px;font-size:0;line-height:0;">&nbsp;</td>'
    rows = [(gap, cell, gap), (cell, gap, cell), (cell, cell, cell)]
    body = "".join("<tr>" + "".join(r) + "</tr>" for r in rows)
    return f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;">{body}</table>'


def _button(label: str, url: str) -> str:
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin:28px 0 8px;">'
        f'<tr><td style="border-radius:999px;background:{ORANGE};">'
        f'<a href="{_esc(url)}" style="display:inline-block;padding:13px 26px;font-family:{SANS};font-size:16px;'
        f'font-weight:500;color:#ffffff;text-decoration:none;border-radius:999px;">{_esc(label)}</a>'
        "</td></tr></table>"
    )


def _label(text: str) -> str:
    return (
        f'<p style="margin:0 0 14px;font-family:{MONO};font-size:12px;letter-spacing:0.08em;'
        f'text-transform:uppercase;color:{ORANGE_DARK};">{_esc(text)}</p>'
    )


def _p(text_html: str) -> str:
    return f'<p style="margin:0 0 16px;font-family:{MONO};font-size:15px;line-height:1.5;color:{TEXT};">{text_html}</p>'


def _layout(lang: str, preheader: str, overline: str, title: str, body_html: str, footer_note: str = "") -> str:
    base = settings.PUBLIC_BASE_URL or "https://apex-vox.ialabs.app"
    tagline = "Potenciado por Groq" if lang == "es" else "Powered by Groq"
    default_note = (
        "Recibes este correo por tu cuenta en Apex Vox."
        if lang == "es"
        else "You are receiving this email because of your Apex Vox account."
    )
    return f"""<!DOCTYPE html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light">
<title>{_esc(title)}</title>
</head>
<body style="margin:0;padding:0;background:{PAPER};">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;">{_esc(preheader)}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:{PAPER};">
<tr><td align="center" style="padding:32px 16px;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:560px;">
    <tr><td style="padding:0 4px 20px;">
      <table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>
        <td style="vertical-align:middle;padding-right:10px;">{_mark()}</td>
        <td style="vertical-align:middle;font-family:{SANS};font-size:20px;font-weight:500;letter-spacing:-0.03em;color:{INK};">Apex Vox</td>
      </tr></table>
    </td></tr>
    <tr><td style="background:{CARD};border:1px solid {LINE};border-radius:10px;padding:32px 28px;">
      {_label(overline)}
      <h1 style="margin:0 0 18px;font-family:{SANS};font-size:28px;line-height:1.1;font-weight:500;letter-spacing:-0.023em;color:{INK};">{_esc(title)}</h1>
      {body_html}
    </td></tr>
    <tr><td style="padding:20px 4px 0;font-family:{MONO};font-size:12px;line-height:1.5;color:{MUTED};">
      {_esc(footer_note or default_note)}<br>
      <a href="{_esc(base)}" style="color:{MUTED};">apex-vox.ialabs.app</a> · {_esc(tagline)}
    </td></tr>
  </table>
</td></tr>
</table>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Templates  ->  (subject, html, text)
# ---------------------------------------------------------------------------

def _app_url(path: str = "/") -> str:
    base = settings.PUBLIC_BASE_URL or "https://apex-vox.ialabs.app"
    return f"{base}{path}"


def _fmt_date(iso_value: Optional[str], lang: str) -> str:
    if not iso_value:
        return ""
    return str(iso_value)[:10]


def _fmt_datetime(iso_value: Optional[str], lang: str) -> str:
    """Fecha y hora en hora de Colombia (UTC-5), p. ej. "02/11/2026 18:30 (hora de Colombia)"."""
    import datetime as _dt

    if not iso_value:
        return ""
    try:
        value = _dt.datetime.fromisoformat(str(iso_value).replace("Z", "+00:00"))
    except ValueError:
        return str(iso_value)[:16]
    if value.tzinfo is None:
        value = value.replace(tzinfo=_dt.timezone.utc)
    local = value.astimezone(_dt.timezone(_dt.timedelta(hours=-5)))
    if lang == "en":
        return local.strftime("%b %d, %Y %H:%M") + " (Colombia time, UTC-5)"
    return local.strftime("%d/%m/%Y %H:%M") + " (hora de Colombia)"


def _usd(amount: float) -> str:
    value = float(amount)
    return f"USD {value:.0f}" if value.is_integer() else f"USD {value:.2f}"


def _prices() -> Tuple[str, str, int]:
    regular = float(settings.PRO_PRICE_USD)
    promo = round(regular * (100 - settings.PROMO_DISCOUNT_PCT) / 100, 2)
    return _usd(regular), _usd(promo), settings.PROMO_DISCOUNT_PCT


def _rules_note(lang: str) -> str:
    """Reglas de la promoción y del cobro, iguales en todos los correos de facturación."""
    regular, promo, pct = _prices()
    days, hours, cooldown = settings.PRO_PERIOD_DAYS, settings.PROMO_WINDOW_HOURS, settings.PROMO_IP_COOLDOWN_DAYS
    if lang == "en":
        items = [
            f"Apex Pro costs <strong>{regular}</strong> for {days} days. Paying activates the month.",
            f"Welcome promo: <strong>{pct}% off the first month ({promo})</strong> if you pay within the first {hours} hours after creating your account.",
            f"One promo per network (IP) every {cooldown} days (one quarter). It applies only to the first month.",
            "Bold does not support subscriptions: nothing is charged automatically. Each month you renew manually from your account.",
        ]
    else:
        items = [
            f"Apex Pro cuesta <strong>{regular}</strong> por {days} días. El pago activa el mes.",
            f"Promoción de bienvenida: <strong>{pct}% de descuento en el primer mes ({promo})</strong> si pagas dentro de las primeras {hours} horas desde que creaste tu cuenta.",
            f"Una sola promoción por red (IP) cada {cooldown} días (un trimestre). Aplica solo al primer mes.",
            "Bold no permite suscripciones: no se cobra nada automáticamente. Cada mes renuevas de forma manual desde tu cuenta.",
        ]
    lis = "".join(
        f'<li style="margin:0 0 8px;font-family:{MONO};font-size:13px;line-height:1.5;color:{TEXT};">{i}</li>'
        for i in items
    )
    return (
        f'<div style="margin:22px 0 4px;padding:14px 16px;border:1px solid {LINE};border-radius:8px;background:{PAPER};">'
        + _label("Cómo funciona" if lang != "en" else "How it works")
        + f'<ul style="margin:0;padding-left:18px;">{lis}</ul></div>'
    )


def _rules_text(lang: str) -> str:
    regular, promo, pct = _prices()
    days, hours, cooldown = settings.PRO_PERIOD_DAYS, settings.PROMO_WINDOW_HOURS, settings.PROMO_IP_COOLDOWN_DAYS
    if lang == "en":
        return (f"- Apex Pro: {regular} for {days} days; paying activates the month.\n"
                f"- {pct}% off the first month ({promo}) if you pay within {hours} h of creating your account.\n"
                f"- One promo per network (IP) every {cooldown} days.\n"
                "- Bold has no subscriptions: nothing is charged automatically; renew manually each month.")
    return (f"- Apex Pro: {regular} por {days} días; el pago activa el mes.\n"
            f"- {pct}% de descuento en el primer mes ({promo}) si pagas dentro de las {hours} h siguientes a crear tu cuenta.\n"
            f"- Una promoción por red (IP) cada {cooldown} días.\n"
            "- Bold no permite suscripciones: no se cobra nada automáticamente; renuevas manualmente cada mes.")


def render_welcome(name: str, lang: str = "es", promo_ends_at: Optional[str] = None) -> Tuple[str, str, str]:
    """Bienvenida: plan gratis + promoción de las primeras 24 horas."""
    url = _app_url("/?view=portal")
    regular, promo, pct = _prices()
    ends = _fmt_datetime(promo_ends_at, lang)
    if lang == "en":
        subject = f"Welcome to Apex Vox: {pct}% off Apex Pro for 24 hours"
        body = (
            _p(f"Hi {_esc(name)}, your account is ready.")
            + _p("You have <strong>2 hours of transcription per day</strong>, ordered multi-audio uploads, "
                 "speaker identification and exports to TXT, SRT, VTT, JSON, CSV and Markdown.")
            + _p(f"Want the full Apex Summa report, minutes and unlimited transcriptions? Activate "
                 f"<strong>Apex Pro for {promo}</strong> instead of {regular} if you pay before "
                 f"<strong>{_esc(ends)}</strong>.")
            + _button(f"Activate Apex Pro for {promo}", url)
            + _rules_note("en")
        )
        text = (f"Hi {name}, your Apex Vox account is ready: 2 hours of transcription per day.\n\n"
                f"Apex Pro for {promo} (instead of {regular}) if you pay before {ends}.\n\n{_rules_text('en')}\n\n{url}")
        return subject, _layout("en", f"{pct}% off your first month until {ends}.", "Welcome", "Your account is ready.", body), text
    subject = f"Bienvenido a Apex Vox: {pct}% de descuento en Apex Pro por 24 horas"
    body = (
        _p(f"Hola {_esc(name)}, tu cuenta está lista.")
        + _p("Tienes <strong>2 horas de transcripción al día</strong>, subida de varios audios en orden, "
             "identificación de oradores y exportación a TXT, SRT, VTT, JSON, CSV y Markdown.")
        + _p(f"¿Quieres el informe completo de Apex Summa, actas y transcripciones ilimitadas? Activa "
             f"<strong>Apex Pro por {promo}</strong> en lugar de {regular} si pagas antes del "
             f"<strong>{_esc(ends)}</strong>.")
        + _button(f"Activar Apex Pro por {promo}", url)
        + _rules_note("es")
    )
    text = (f"Hola {name}, tu cuenta de Apex Vox está lista: 2 horas de transcripción al día.\n\n"
            f"Apex Pro por {promo} (en lugar de {regular}) si pagas antes del {ends}.\n\n{_rules_text('es')}\n\n{url}")
    return subject, _layout("es", f"{pct}% de descuento en tu primer mes hasta el {ends}.", "Bienvenida", "Tu cuenta está lista.", body), text


def render_promo_reminder(name: str, promo_ends_at: Optional[str], lang: str = "es") -> Tuple[str, str, str]:
    """La promoción de bienvenida termina en pocas horas."""
    url = _app_url("/?view=portal")
    regular, promo, pct = _prices()
    ends = _fmt_datetime(promo_ends_at, lang)
    if lang == "en":
        subject = f"Last hours: Apex Pro for {promo} ends soon"
        body = (
            _p(f"Hi {_esc(name)}, your welcome promo ends on <strong>{_esc(ends)}</strong>.")
            + _p(f"Pay now and your first month of Apex Pro costs <strong>{promo}</strong> instead of {regular} "
                 f"({pct}% off). After that the price is {regular} per month.")
            + _button(f"Pay {promo} now", url)
            + _rules_note("en")
        )
        text = f"Hi {name}, your promo ends on {ends}: Apex Pro for {promo} instead of {regular}.\n\n{_rules_text('en')}\n\n{url}"
        return subject, _layout("en", f"{pct}% off ends on {ends}.", "Promo", "Your promo ends soon.", body), text
    subject = f"Últimas horas: Apex Pro por {promo} termina pronto"
    body = (
        _p(f"Hola {_esc(name)}, tu promoción de bienvenida termina el <strong>{_esc(ends)}</strong>.")
        + _p(f"Paga ahora y tu primer mes de Apex Pro cuesta <strong>{promo}</strong> en lugar de {regular} "
             f"({pct}% de descuento). Después, el precio es {regular} al mes.")
        + _button(f"Pagar {promo} ahora", url)
        + _rules_note("es")
    )
    text = f"Hola {name}, tu promoción termina el {ends}: Apex Pro por {promo} en lugar de {regular}.\n\n{_rules_text('es')}\n\n{url}"
    return subject, _layout("es", f"El {pct}% de descuento termina el {ends}.", "Promoción", "Tu promoción termina pronto.", body), text


def render_renewal_reminder(name: str, pro_until: Optional[str], lang: str = "es") -> Tuple[str, str, str]:
    """El mes pagado está por terminar: la renovación es manual."""
    url = _app_url("/?view=portal")
    regular, _, _ = _prices()
    until = _fmt_datetime(pro_until, lang)
    if lang == "en":
        subject = "Your Apex Pro month ends soon — renew manually"
        body = (
            _p(f"Hi {_esc(name)}, your Apex Pro access ends on <strong>{_esc(until)}</strong>.")
            + _p(f"Bold does not charge automatically. To keep Apex Pro, pay <strong>{regular}</strong> for "
                 f"{settings.PRO_PERIOD_DAYS} more days; if you pay early, the days are added to the current period.")
            + _button(f"Renew for {regular}", url)
        )
        text = f"Hi {name}, Apex Pro ends on {until}. Nothing is charged automatically: renew for {regular}.\n\n{url}"
        return subject, _layout("en", f"Apex Pro ends on {until}.", "Renewal", "Your month ends soon.", body), text
    subject = "Tu mes de Apex Pro termina pronto: renueva manualmente"
    body = (
        _p(f"Hola {_esc(name)}, tu acceso a Apex Pro termina el <strong>{_esc(until)}</strong>.")
        + _p(f"Bold no cobra automáticamente. Para seguir con Apex Pro, paga <strong>{regular}</strong> por "
             f"{settings.PRO_PERIOD_DAYS} días más; si pagas antes, los días se suman al periodo actual.")
        + _button(f"Renovar por {regular}", url)
    )
    text = f"Hola {name}, Apex Pro termina el {until}. No se cobra automáticamente: renueva por {regular}.\n\n{url}"
    return subject, _layout("es", f"Apex Pro termina el {until}.", "Renovación", "Tu mes termina pronto.", body), text


def render_expired(name: str, lang: str = "es") -> Tuple[str, str, str]:
    """El mes pagado terminó: la cuenta vuelve al plan gratis."""
    url = _app_url("/?view=portal")
    regular, _, _ = _prices()
    if lang == "en":
        subject = "Your Apex Pro month has ended"
        body = (
            _p(f"Hi {_esc(name)}, your Apex Pro month has ended and your account is back on the free plan "
               "(2 hours per day, 24-hour storage).")
            + _p(f"Reactivate Apex Pro whenever you want: <strong>{regular}</strong> for {settings.PRO_PERIOD_DAYS} days, no automatic charges.")
            + _button(f"Reactivate for {regular}", url)
        )
        text = f"Hi {name}, your Apex Pro month has ended. Reactivate for {regular}.\n\n{url}"
        return subject, _layout("en", "Your account is back on the free plan.", "Plan", "Your month has ended.", body), text
    subject = "Tu mes de Apex Pro terminó"
    body = (
        _p(f"Hola {_esc(name)}, tu mes de Apex Pro terminó y tu cuenta volvió al plan gratis "
           "(2 horas al día y almacenamiento de 24 horas).")
        + _p(f"Reactiva Apex Pro cuando quieras: <strong>{regular}</strong> por {settings.PRO_PERIOD_DAYS} días, sin cobros automáticos.")
        + _button(f"Reactivar por {regular}", url)
    )
    text = f"Hola {name}, tu mes de Apex Pro terminó. Reactívalo por {regular}.\n\n{url}"
    return subject, _layout("es", "Tu cuenta volvió al plan gratis.", "Plan", "Tu mes terminó.", body), text


def render_meeting_ready(name: str, title: str, duration: str, link: str, lang: str = "es") -> Tuple[str, str, str]:
    """El bot terminó: enlace con transcripción, notas, resumen y acta."""
    if lang == "en":
        subject = f"Your meeting is ready: {title}"
        body = (
            _p(f"Hi {_esc(name)}, the Apex Vox bot recorded <strong>{_esc(title)}</strong> ({_esc(duration)}).")
            + _p("The transcript, summary and minutes are ready.")
            + _button("Open meeting", link)
        )
        return subject, _layout("en", f"{title} is ready.", "Meeting", "Your meeting is ready.", body), f"{title} is ready: {link}"
    subject = f"Tu reunión está lista: {title}"
    body = (
        _p(f"Hola {_esc(name)}, el bot de Apex Vox grabó <strong>{_esc(title)}</strong> ({_esc(duration)}).")
        + _p("Ya tienes la transcripción, el resumen y el acta.")
        + _button("Abrir reunión", link)
    )
    return subject, _layout("es", f"{title} está lista.", "Reunión", "Tu reunión está lista.", body), f"{title} está lista: {link}"


def render_payment_confirmed(name: str, pro_until: Optional[str], amount_display: str, reference: str, lang: str = "es") -> Tuple[str, str, str]:
    url = _app_url("/")
    until = _fmt_date(pro_until, lang)
    rows = [
        ("Referencia" if lang == "es" else "Reference", reference),
        ("Monto" if lang == "es" else "Amount", amount_display),
        ("Apex Pro hasta" if lang == "es" else "Apex Pro until", until),
    ]
    table = (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="border-top:1px solid {LINE};margin:4px 0 8px;">'
        + "".join(
            f'<tr><td style="padding:10px 0;border-bottom:1px solid {LINE};font-family:{MONO};font-size:12px;'
            f'letter-spacing:0.06em;text-transform:uppercase;color:{MUTED};">{_esc(k)}</td>'
            f'<td align="right" style="padding:10px 0;border-bottom:1px solid {LINE};font-family:{MONO};font-size:14px;color:{TEXT};">{_esc(v)}</td></tr>'
            for k, v in rows
        )
        + "</table>"
    )
    if lang == "en":
        subject = "Payment received — Apex Pro is active"
        body = (
            _p(f"Thanks, {_esc(name)}. We received your Bold payment.") + table
            + _p("Nothing renews automatically: we will email you a few days before your month ends.")
            + _button("Open Apex Vox", url)
        )
        text = f"Thanks {name}. Payment {reference} received ({amount_display}). Apex Pro until {until}.\n\n{url}"
        return subject, _layout("en", f"Apex Pro until {until}.", "Receipt", "Payment received.", body), text
    subject = "Pago recibido — Apex Pro activo"
    body = (
        _p(f"Gracias, {_esc(name)}. Recibimos tu pago con Bold.") + table
        + _p("Nada se renueva automáticamente: te escribiremos unos días antes de que termine tu mes.")
        + _button("Abrir Apex Vox", url)
    )
    text = f"Gracias {name}. Pago {reference} recibido ({amount_display}). Apex Pro hasta el {until}.\n\n{url}"
    return subject, _layout("es", f"Apex Pro activo hasta el {until}.", "Recibo", "Pago recibido.", body), text


def render_password_reset(name: str, reset_url: str, ttl_minutes: int, lang: str = "es") -> Tuple[str, str, str]:
    if lang == "en":
        subject = "Reset your Apex Vox password"
        body = (
            _p(f"Hi {_esc(name)}, we received a request to reset your password.")
            + _button("Choose a new password", reset_url)
            + _p(f"The link expires in {ttl_minutes} minutes and works once. If you didn't ask for this, ignore this email — your password stays the same.")
        )
        text = f"Reset your Apex Vox password (valid {ttl_minutes} min):\n{reset_url}\n\nIf you didn't ask for this, ignore this email."
        return subject, _layout("en", "Use this link to choose a new password.", "Security", "Reset your password.", body), text
    subject = "Restablece tu contraseña de Apex Vox"
    body = (
        _p(f"Hola {_esc(name)}, recibimos una solicitud para restablecer tu contraseña.")
        + _button("Elegir una nueva contraseña", reset_url)
        + _p(f"El enlace vence en {ttl_minutes} minutos y sirve una sola vez. Si no lo pediste, ignora este correo: tu contraseña no cambia.")
    )
    text = f"Restablece tu contraseña de Apex Vox (válido {ttl_minutes} min):\n{reset_url}\n\nSi no lo pediste, ignora este correo."
    return subject, _layout("es", "Usa este enlace para elegir una nueva contraseña.", "Seguridad", "Restablece tu contraseña.", body), text


def render_newsletter_confirm(confirm_url: str, lang: str = "es") -> Tuple[str, str, str]:
    if lang == "en":
        subject = "Confirm your Apex Vox newsletter subscription"
        body = (
            _p("One click and you're in: product launches, guides and what's new in Apex Vox, Apex Summa and Apex Box.")
            + _button("Confirm subscription", confirm_url)
            + _p("If you didn't sign up, ignore this email and you won't hear from us.")
        )
        text = f"Confirm your Apex Vox newsletter subscription:\n{confirm_url}"
        return subject, _layout("en", "Confirm to start receiving the newsletter.", "Newsletter", "Confirm your subscription.", body,
                                "You are receiving this email because this address was entered on apex-vox.ialabs.app."), text
    subject = "Confirma tu suscripción al boletín de Apex Vox"
    body = (
        _p("Un clic y listo: lanzamientos, guías y novedades de Apex Vox, Apex Summa y Apex Box.")
        + _button("Confirmar suscripción", confirm_url)
        + _p("Si no te suscribiste, ignora este correo y no volverás a saber de nosotros.")
    )
    text = f"Confirma tu suscripción al boletín de Apex Vox:\n{confirm_url}"
    return subject, _layout("es", "Confirma para empezar a recibir el boletín.", "Boletín", "Confirma tu suscripción.", body,
                            "Recibes este correo porque esta dirección se ingresó en apex-vox.ialabs.app."), text


def render_newsletter_welcome(unsubscribe_url: str, lang: str = "es") -> Tuple[str, str, str]:
    url = _app_url("/")
    if lang == "en":
        subject = "You're subscribed to the Apex Vox newsletter"
        body = (
            _p("Subscription confirmed. We write when there is something worth reading: new engines, Apex Summa features and the Apex Box launch.")
            + _button("Visit Apex Vox", url)
            + _p(f'You can <a href="{_esc(unsubscribe_url)}" style="color:{ORANGE_DARK};">unsubscribe</a> at any time.')
        )
        text = f"You're subscribed to the Apex Vox newsletter.\nUnsubscribe: {unsubscribe_url}"
        return subject, _layout("en", "Subscription confirmed.", "Newsletter", "You're subscribed.", body,
                                "You subscribed to the Apex Vox newsletter."), text
    subject = "Ya estás suscrito al boletín de Apex Vox"
    body = (
        _p("Suscripción confirmada. Escribimos cuando hay algo que vale la pena: nuevos motores, funciones de Apex Summa y el lanzamiento de Apex Box.")
        + _button("Visitar Apex Vox", url)
        + _p(f'Puedes <a href="{_esc(unsubscribe_url)}" style="color:{ORANGE_DARK};">darte de baja</a> cuando quieras.')
    )
    text = f"Ya estás suscrito al boletín de Apex Vox.\nDarte de baja: {unsubscribe_url}"
    return subject, _layout("es", "Suscripción confirmada.", "Boletín", "Ya estás suscrito.", body,
                            "Te suscribiste al boletín de Apex Vox."), text


def render_newsletter_broadcast_shell(lang: str = "es") -> str:
    """Base layout for Resend Broadcasts; Resend fills {{{RESEND_UNSUBSCRIBE_URL}}}."""
    body = (
        _p("Escribe aquí el contenido de esta edición." if lang == "es" else "Write this edition's content here.")
        + _button("Abrir Apex Vox" if lang == "es" else "Open Apex Vox", _app_url("/"))
        + _p(
            ('<a href="{{{RESEND_UNSUBSCRIBE_URL}}}" style="color:%s;">Darte de baja</a>' if lang == "es"
             else '<a href="{{{RESEND_UNSUBSCRIBE_URL}}}" style="color:%s;">Unsubscribe</a>') % ORANGE_DARK
        )
    )
    return _layout(
        lang,
        "Novedades de Apex Vox" if lang == "es" else "What's new in Apex Vox",
        "Boletín" if lang == "es" else "Newsletter",
        "Novedades de Apex Vox" if lang == "es" else "What's new in Apex Vox",
        body,
        "Te suscribiste al boletín de Apex Vox." if lang == "es" else "You subscribed to the Apex Vox newsletter.",
    )


# ---------------------------------------------------------------------------
# Resend API
# ---------------------------------------------------------------------------

def _headers() -> Dict[str, str]:
    return {"Authorization": f"Bearer {settings.RESEND_API_KEY}", "Content-Type": "application/json"}


def send_email(to: str, rendered: Tuple[str, str, str], tags: Optional[List[Dict[str, str]]] = None,
               headers: Optional[Dict[str, str]] = None) -> bool:
    """Send one email synchronously. Returns True on success; never raises."""
    if not settings.is_email_configured:
        logger.info("Email not sent (RESEND_API_KEY missing): %s", rendered[0])
        return False
    subject, html_body, text_body = rendered
    payload: Dict[str, Any] = {
        "from": settings.EMAIL_FROM,
        "to": [to],
        "subject": subject,
        "html": html_body,
        "text": text_body,
    }
    if settings.EMAIL_REPLY_TO:
        payload["reply_to"] = settings.EMAIL_REPLY_TO
    if tags:
        payload["tags"] = tags
    if headers:
        payload["headers"] = headers
    try:
        with httpx.Client(timeout=_TIMEOUT) as client:
            resp = client.post(f"{RESEND_API}/emails", json=payload, headers=_headers())
        if resp.status_code >= 400:
            logger.warning("Resend rejected '%s': %s %s", subject, resp.status_code, resp.text[:200])
            return False
        return True
    except httpx.HTTPError as exc:
        logger.warning("Resend unreachable for '%s': %s", subject, exc)
        return False


def send_async(to: str, rendered: Tuple[str, str, str], **kwargs: Any) -> None:
    """Send in a daemon thread so requests never wait on email delivery."""
    if not to:
        return
    if not settings.is_email_configured:
        send_email(to, rendered, **kwargs)  # logs and returns immediately
        return
    threading.Thread(target=send_email, args=(to, rendered), kwargs=kwargs, daemon=True).start()


def upsert_newsletter_contact(email: str, first_name: str = "") -> bool:
    """Add a confirmed subscriber to the newsletter segment and opt them into the topic."""
    if not settings.is_email_configured:
        return False
    contact: Dict[str, Any] = {"email": email, "unsubscribed": False}
    if first_name:
        contact["first_name"] = first_name
    if settings.RESEND_NEWSLETTER_SEGMENT_ID:
        contact["segments"] = [{"id": settings.RESEND_NEWSLETTER_SEGMENT_ID}]
    if settings.RESEND_NEWSLETTER_TOPIC_ID:
        contact["topics"] = [{"id": settings.RESEND_NEWSLETTER_TOPIC_ID, "subscription": "opt_in"}]
    try:
        with httpx.Client(timeout=_TIMEOUT) as client:
            resp = client.post(f"{RESEND_API}/contacts", json=contact, headers=_headers())
            if resp.status_code < 400:
                return True
            # Existing contact: re-subscribe, then make sure segment + topic are set.
            target = quote(email, safe="")
            client.patch(f"{RESEND_API}/contacts/{target}", json={"unsubscribed": False}, headers=_headers())
            if settings.RESEND_NEWSLETTER_SEGMENT_ID:
                client.post(f"{RESEND_API}/contacts/{target}/segments/{settings.RESEND_NEWSLETTER_SEGMENT_ID}", headers=_headers())
            if settings.RESEND_NEWSLETTER_TOPIC_ID:
                client.patch(
                    f"{RESEND_API}/contacts/{target}/topics",
                    json=[{"id": settings.RESEND_NEWSLETTER_TOPIC_ID, "subscription": "opt_in"}],
                    headers=_headers(),
                )
            return True
    except httpx.HTTPError as exc:
        logger.warning("Resend contact sync failed: %s", exc)
        return False


def unsubscribe_newsletter_contact(email: str) -> bool:
    if not settings.is_email_configured:
        return False
    target = quote(email, safe="")
    try:
        with httpx.Client(timeout=_TIMEOUT) as client:
            if settings.RESEND_NEWSLETTER_TOPIC_ID:
                client.patch(
                    f"{RESEND_API}/contacts/{target}/topics",
                    json=[{"id": settings.RESEND_NEWSLETTER_TOPIC_ID, "subscription": "opt_out"}],
                    headers=_headers(),
                )
            if settings.RESEND_NEWSLETTER_SEGMENT_ID:
                client.delete(
                    f"{RESEND_API}/contacts/{target}/segments/{settings.RESEND_NEWSLETTER_SEGMENT_ID}",
                    headers=_headers(),
                )
        return True
    except httpx.HTTPError as exc:
        logger.warning("Resend unsubscribe failed: %s", exc)
        return False
