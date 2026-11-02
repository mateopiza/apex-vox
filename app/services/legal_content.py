"""
Policy texts for Apex Vox (privacy, terms, security), in Spanish and English.
They describe what the code actually does; keep them in sync when behaviour changes.
Reviewed facts: retention, processors, limits and security controls in this repository.
Have a lawyer review before relying on them commercially.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from app.config import settings

UPDATED = "2026-11-02"

Section = Tuple[str, List[str]]  # (heading, paragraphs; HTML allowed)


def _ctx() -> Dict[str, str]:
    return {
        "entity": settings.LEGAL_ENTITY_NAME,
        "contact": settings.CONTACT_EMAIL,
        "security": settings.SECURITY_EMAIL,
        "guest_audios": str(settings.GUEST_MAX_AUDIOS_PER_DAY),
        "guest_minutes": f"{settings.GUEST_MAX_AUDIO_MINUTES:.0f}",
        "guest_ttl": str(settings.GUEST_RESULT_TTL_MINUTES),
        "free_hours": f"{settings.FREE_DAILY_HOURS:g}",
        "free_retention": str(settings.FREE_RETENTION_HOURS),
        "trial_days": str(settings.PRO_TRIAL_DAYS),
        "period_days": str(settings.PRO_PERIOD_DAYS),
        "max_ips": str(settings.MAX_IPS_PER_MONTH),
        "session_days": str(settings.SESSION_TTL_DAYS),
    }


PRIVACY_ES: List[Section] = [
    ("Responsable", [
        "{entity} es responsable del tratamiento de los datos personales que se recogen en Apex Vox "
        "(apex-vox.ialabs.app). Para cualquier consulta sobre tus datos escribe a <a href=\"mailto:{contact}\">{contact}</a>."
    ]),
    ("Qué datos tratamos", [
        "<strong>Cuenta:</strong> nombre, correo, idioma preferido y, si usas Google o GitHub, el correo verificado que ese proveedor nos entrega. "
        "Las contraseñas se guardan solo como hash PBKDF2-SHA256 con sal individual.",
        "<strong>Audio y transcripciones:</strong> los archivos que subes, el texto transcrito, los oradores detectados, los resúmenes de Apex Summa y las actas que generes.",
        "<strong>Perfiles de voz:</strong> si registras una muestra, guardamos una huella acústica numérica y el nombre que le asignes, visibles solo para tu cuenta.",
        "<strong>Uso y seguridad:</strong> consumo diario de audio, plan, pagos (referencia, monto y estado; nunca datos de tarjeta) y un hash no reversible de las redes (IP) desde las que usas la cuenta.",
        "<strong>Telegram (opcional):</strong> el identificador del chat que vincules y tu nombre de usuario de Telegram.",
        "<strong>Boletín (opcional):</strong> tu correo y la fecha de confirmación de la suscripción.",
    ]),
    ("Para qué los usamos", [
        "Prestar el servicio de transcripción, identificación de oradores y análisis; aplicar los límites de cada plan; procesar pagos; "
        "proteger las cuentas (por ejemplo, limitar una cuenta a {max_ips} redes por mes para evitar que se comparta); "
        "enviarte correos de la cuenta (bienvenida, recibos, restablecer contraseña) y, solo si te suscribes, el boletín.",
        "No vendemos tus datos ni usamos tus audios para entrenar modelos propios.",
    ]),
    ("Cuánto tiempo los conservamos", [
        "<strong>Sin cuenta:</strong> los audios se borran al terminar la transcripción y el resultado se elimina de la memoria del servidor a los {guest_ttl} minutos. No se guarda historial.",
        "<strong>Plan Gratis:</strong> audios y resultados se conservan {free_retention} horas.",
        "<strong>Apex Pro:</strong> se conservan mientras la cuenta exista o hasta que los elimines.",
        "Los registros de pago se conservan el tiempo que exige la ley contable y tributaria.",
    ]),
    ("Con quién los compartimos (encargados)", [
        "Groq y Deepgram (transcripción y separación de voces), MEGA S4 (almacenamiento de archivos), Supabase (base de datos e inicio de sesión con Google/GitHub), "
        "Bold (pagos), Resend (envío de correos), Telegram (solo si vinculas el bot), Cloudflare (DNS) y Google Fonts (tipografías de la web). "
        "Cada uno trata los datos solo para prestarnos su servicio. Algunos están fuera de Colombia, lo que implica una transferencia internacional de datos.",
    ]),
    ("Tus derechos", [
        "Conforme a la Ley 1581 de 2012 y el Decreto 1377 de 2013 puedes conocer, actualizar, rectificar y suprimir tus datos, revocar la autorización y presentar quejas ante la Superintendencia de Industria y Comercio. "
        "Puedes eliminar tu cuenta y todos sus datos desde tu cuenta (icono de usuario) o escribiéndonos a <a href=\"mailto:{contact}\">{contact}</a>; respondemos en un máximo de 15 días hábiles.",
        "Puedes darte de baja del boletín con el enlace de cada correo.",
    ]),
    ("Cookies y almacenamiento local", [
        "Usamos almacenamiento local del navegador para mantener tu sesión e idioma, y una cookie técnica temporal durante el inicio de sesión con Google o GitHub. No usamos cookies publicitarias.",
    ]),
]

PRIVACY_EN: List[Section] = [
    ("Controller", [
        "{entity} is the controller of the personal data collected in Apex Vox (apex-vox.ialabs.app). Questions about your data: <a href=\"mailto:{contact}\">{contact}</a>."
    ]),
    ("Data we process", [
        "<strong>Account:</strong> name, email, preferred language and, if you use Google or GitHub, the verified email that provider shares. Passwords are stored only as salted PBKDF2-SHA256 hashes.",
        "<strong>Audio and transcripts:</strong> the files you upload, transcribed text, detected speakers, Apex Summa summaries and minutes you generate.",
        "<strong>Voice profiles:</strong> if you enrol a sample we keep a numeric voiceprint and the name you give it, visible only to your account.",
        "<strong>Usage and security:</strong> daily audio usage, plan, payments (reference, amount and status; never card data) and a one-way hash of the networks (IP) your account is used from.",
        "<strong>Telegram (optional):</strong> the chat id you link and your Telegram username.",
        "<strong>Newsletter (optional):</strong> your email and the confirmation date.",
    ]),
    ("Why we use it", [
        "To provide transcription, speaker identification and analysis; apply plan limits; process payments; protect accounts (for example, limiting an account to {max_ips} networks per month to prevent sharing); "
        "send account emails (welcome, receipts, password reset) and, only if you subscribe, the newsletter.",
        "We do not sell your data or use your audio to train our own models.",
    ]),
    ("Retention", [
        "<strong>Without an account:</strong> audio is deleted once transcribed and the result is removed from server memory after {guest_ttl} minutes. No history is kept.",
        "<strong>Free plan:</strong> audio and results are kept for {free_retention} hours.",
        "<strong>Apex Pro:</strong> kept while the account exists or until you delete them.",
        "Payment records are kept as long as accounting and tax law requires.",
    ]),
    ("Processors", [
        "Groq and Deepgram (transcription and voice separation), MEGA S4 (file storage), Supabase (database and Google/GitHub sign-in), Bold (payments), Resend (email), "
        "Telegram (only if you link the bot), Cloudflare (DNS) and Google Fonts (web fonts). Some are outside Colombia, which means an international data transfer.",
    ]),
    ("Your rights", [
        "Under Colombian Law 1581 of 2012 you may access, update, correct and delete your data, withdraw consent and complain to the Superintendencia de Industria y Comercio. "
        "Delete your account and all its data from your account (user icon) or write to <a href=\"mailto:{contact}\">{contact}</a>; we answer within 15 business days.",
        "Unsubscribe from the newsletter with the link in every issue.",
    ]),
    ("Cookies and local storage", [
        "We use browser local storage to keep your session and language, and a temporary technical cookie during Google or GitHub sign-in. No advertising cookies.",
    ]),
]

TERMS_ES: List[Section] = [
    ("El servicio", [
        "Apex Vox transcribe audio, identifica oradores y, en Apex Pro, genera análisis (Apex Summa) y actas. Los resultados se producen con modelos de IA y pueden contener errores: revísalos antes de usarlos en decisiones legales, médicas o financieras.",
    ]),
    ("Planes y límites", [
        "<strong>Sin cuenta:</strong> hasta {guest_audios} audios al día de máximo {guest_minutes} minutos cada uno; sin análisis ni historial.",
        "<strong>Gratis:</strong> {free_hours} horas de audio al día y almacenamiento de {free_retention} horas.",
        "<strong>Apex Pro:</strong> prueba gratis de {trial_days} días, una vez por cuenta y sin tarjeta. Luego, cada pago con Bold ($30.000 COP o $10 USD) activa {period_days} días. No hay renovación ni cobro automático.",
    ]),
    ("Uso de la cuenta", [
        "Las cuentas son personales. Para evitar que se compartan, cada cuenta puede usarse desde un máximo de {max_ips} redes (IP) distintas por mes calendario; una red adicional queda bloqueada hasta el mes siguiente.",
        "Las sesiones vencen a los {session_days} días. Eres responsable de mantener segura tu contraseña.",
        "El bot de Telegram se vincula a un solo chat por suscripción de Apex Pro.",
    ]),
    ("Contenido y permisos", [
        "Conservas todos los derechos sobre tus audios y transcripciones. Declaras tener autorización de las personas grabadas para grabarlas y procesar su voz.",
        "No puedes usar Apex Vox para contenido ilegal, para vigilar a personas sin su consentimiento ni para intentar vulnerar el servicio.",
    ]),
    ("Pagos y reembolsos", [
        "Los pagos se procesan con Bold; no almacenamos datos de tarjeta. Si un cobro fue erróneo escríbenos a <a href=\"mailto:{contact}\">{contact}</a> dentro de los 5 días hábiles siguientes y lo revisaremos conforme al Estatuto del Consumidor (Ley 1480 de 2011).",
    ]),
    ("Suspensión y cambios", [
        "Podemos suspender cuentas que violen estos términos. Avisaremos por correo los cambios relevantes de estos términos o de los precios con al menos 15 días de anticipación.",
    ]),
    ("Responsabilidad", [
        "El servicio se ofrece \"tal cual\". En la medida permitida por la ley, nuestra responsabilidad total se limita a lo que pagaste en los últimos 3 meses.",
        "Estos términos se rigen por las leyes de la República de Colombia.",
    ]),
]

TERMS_EN: List[Section] = [
    ("The service", [
        "Apex Vox transcribes audio, identifies speakers and, on Apex Pro, produces analysis (Apex Summa) and minutes. Results come from AI models and may contain errors: review them before relying on them for legal, medical or financial decisions.",
    ]),
    ("Plans and limits", [
        "<strong>Without an account:</strong> up to {guest_audios} audios per day of at most {guest_minutes} minutes each; no analysis or history.",
        "<strong>Free:</strong> {free_hours} hours of audio per day and {free_retention}-hour storage.",
        "<strong>Apex Pro:</strong> {trial_days}-day free trial, once per account, no card. Then each Bold payment ($30,000 COP or $10 USD) activates {period_days} days. No automatic renewal or charges.",
    ]),
    ("Account use", [
        "Accounts are personal. To prevent sharing, each account may be used from at most {max_ips} different networks (IP) per calendar month; an additional network is blocked until next month.",
        "Sessions expire after {session_days} days. You are responsible for keeping your password safe.",
        "The Telegram bot links to a single chat per Apex Pro subscription.",
    ]),
    ("Content and permissions", [
        "You keep all rights to your audio and transcripts. You confirm you have the consent of the people recorded to record them and process their voice.",
        "You may not use Apex Vox for illegal content, to monitor people without consent or to attack the service.",
    ]),
    ("Payments and refunds", [
        "Payments are processed by Bold; we never store card data. If a charge was wrong, email <a href=\"mailto:{contact}\">{contact}</a> within 5 business days and we will review it under Colombian consumer law (Law 1480 of 2011).",
    ]),
    ("Suspension and changes", [
        "We may suspend accounts that break these terms. We will email relevant changes to these terms or prices at least 15 days in advance.",
    ]),
    ("Liability", [
        "The service is provided \"as is\". To the extent allowed by law, our total liability is limited to what you paid in the last 3 months.",
        "These terms are governed by the laws of the Republic of Colombia.",
    ]),
]

SECURITY_ES: List[Section] = [
    ("Cómo protegemos el servicio", [
        "<strong>Transporte:</strong> todo el tráfico usa HTTPS con certificados Let's Encrypt y HSTS.",
        "<strong>Contraseñas:</strong> PBKDF2-SHA256 con 310.000 iteraciones y sal por usuario. Nunca las vemos ni las guardamos en claro.",
        "<strong>Sesiones:</strong> tokens aleatorios de 256 bits que vencen a los {session_days} días y se revocan al cerrar sesión o al cambiar la contraseña. El identificador de usuario nunca sirve como credencial.",
        "<strong>Uso compartido:</strong> una cuenta puede usarse desde un máximo de {max_ips} redes por mes. Guardamos solo un hash HMAC de cada IP, no la dirección.",
        "<strong>Pagos:</strong> los avisos de Bold se aceptan solo con firma HMAC-SHA256 válida; las referencias son de un solo uso.",
        "<strong>Bot de Telegram:</strong> el webhook exige el token secreto de Telegram; vincular un chat requiere un código de un solo uso que vence en 10 minutos.",
        "<strong>Navegador:</strong> Content-Security-Policy estricta, protección contra clickjacking (X-Frame-Options), nosniff y Referrer-Policy.",
        "<strong>Abuso:</strong> límites de intentos en inicio de sesión, recuperación de contraseña y boletín.",
        "<strong>Datos:</strong> los perfiles de voz, sesiones de subida e historial están aislados por cuenta; los audios de visitantes se borran al terminar.",
        "<strong>Supabase:</strong> las tablas tienen Row Level Security; solo el servidor (service role) accede a los datos.",
    ]),
    ("Reportar una vulnerabilidad", [
        "Si encuentras un problema de seguridad escríbenos a <a href=\"mailto:{security}\">{security}</a> con los pasos para reproducirlo. Respondemos en un máximo de 3 días hábiles.",
        "Mientras investigamos, no accedas a datos de otras personas, no degrades el servicio y no publiques el hallazgo hasta que esté corregido. No emprenderemos acciones legales contra investigaciones de buena fe que respeten estas reglas.",
        "Fuera de alcance: ataques de denegación de servicio, ingeniería social, spam y hallazgos en proveedores externos.",
    ]),
]

SECURITY_EN: List[Section] = [
    ("How we protect the service", [
        "<strong>Transport:</strong> all traffic uses HTTPS with Let's Encrypt certificates and HSTS.",
        "<strong>Passwords:</strong> PBKDF2-SHA256, 310,000 iterations, per-user salt. Never stored or seen in clear text.",
        "<strong>Sessions:</strong> random 256-bit tokens that expire after {session_days} days and are revoked on sign-out or password change. User ids are never accepted as credentials.",
        "<strong>Sharing:</strong> an account can be used from at most {max_ips} networks per month. We store only an HMAC of each IP, not the address.",
        "<strong>Payments:</strong> Bold notifications are accepted only with a valid HMAC-SHA256 signature; references are single-use.",
        "<strong>Telegram bot:</strong> the webhook requires Telegram's secret token; linking a chat needs a one-time code that expires in 10 minutes.",
        "<strong>Browser:</strong> strict Content-Security-Policy, clickjacking protection (X-Frame-Options), nosniff and Referrer-Policy.",
        "<strong>Abuse:</strong> rate limits on sign-in, password recovery and newsletter sign-up.",
        "<strong>Data:</strong> voice profiles, upload sessions and history are isolated per account; visitor audio is deleted once processed.",
        "<strong>Supabase:</strong> tables use Row Level Security; only the server (service role) can access the data.",
    ]),
    ("Reporting a vulnerability", [
        "If you find a security issue email <a href=\"mailto:{security}\">{security}</a> with steps to reproduce. We answer within 3 business days.",
        "While we investigate, do not access other people's data, degrade the service or publish the finding until it is fixed. We will not pursue good-faith research that follows these rules.",
        "Out of scope: denial of service, social engineering, spam and issues in third-party providers.",
    ]),
]

PAGES = {
    "privacidad": {"es": ("Política de privacidad", PRIVACY_ES), "en": ("Privacy policy", PRIVACY_EN)},
    "terminos": {"es": ("Términos del servicio", TERMS_ES), "en": ("Terms of service", TERMS_EN)},
    "seguridad": {"es": ("Política de seguridad", SECURITY_ES), "en": ("Security policy", SECURITY_EN)},
}


def render_page(slug: str, lang: str, asset_version: str) -> str:
    import html as _html

    lang = lang if lang in ("es", "en") else "es"
    title, sections = PAGES[slug][lang]
    ctx = _ctx()
    nav_labels = {
        "es": [("privacidad", "Privacidad"), ("terminos", "Términos"), ("seguridad", "Seguridad")],
        "en": [("privacidad", "Privacy"), ("terminos", "Terms"), ("seguridad", "Security")],
    }[lang]
    nav = "".join(
        f'<a class="legal-tab{" active" if key == slug else ""}" href="/legal/{key}?lang={lang}">{label}</a>'
        for key, label in nav_labels
    )
    other = "en" if lang == "es" else "es"
    body = "".join(
        f"<section class=\"legal-section\"><h2>{_html.escape(h)}</h2>"
        + "".join(f"<p>{p.format(**ctx)}</p>" for p in paras)
        + "</section>"
        for h, paras in sections
    )
    updated = "Última actualización" if lang == "es" else "Last updated"
    back = "Volver a Apex Vox" if lang == "es" else "Back to Apex Vox"
    return f"""<!DOCTYPE html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_html.escape(title)} · Apex Vox</title>
<link rel="icon" href="/static/favicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;600&amp;family=Share+Tech+Mono&amp;family=IBM+Plex+Mono:wght@400;500&amp;display=swap">
<link rel="stylesheet" href="/static/css/tokens.css?v={asset_version}">
<link rel="stylesheet" href="/static/css/styles.css?v={asset_version}">
</head>
<body class="legal-page">
<header class="app-header"><div class="header-inner">
<a class="brand-title" href="/" aria-label="Apex Vox"><svg class="brand-mark" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M8 0h8v8H8zM0 8h8v8H0zM16 8h8v8h-8zM0 16h24v8H0z"/></svg><span class="brand-wordmark">Apex Vox</span></a>
<nav class="legal-tabs" aria-label="Legal">{nav}</nav>
<a class="lang-btn" href="/legal/{slug}?lang={other}">{other.upper()}</a>
</div></header>
<main class="legal-container">
<p class="overline">{updated}: {UPDATED}</p>
<h1 class="legal-title">{_html.escape(title)}</h1>
{body}
<p><a class="text-link-strong" href="/">{back} &gt;</a></p>
</main>
</body>
</html>"""


def security_txt(base_url: str) -> str:
    return (
        f"Contact: mailto:{settings.SECURITY_EMAIL}\n"
        "Expires: 2027-11-02T00:00:00.000Z\n"
        "Preferred-Languages: es, en\n"
        f"Policy: {base_url}/legal/seguridad\n"
        f"Canonical: {base_url}/.well-known/security.txt\n"
    )
