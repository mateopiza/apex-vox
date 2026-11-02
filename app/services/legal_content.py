"""
Policy texts for Apex Vox (terms and conditions, Habeas Data policy, privacy, security), in Spanish and English.
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
        "price_usd": f"{settings.PRO_PRICE_USD:g}",
        "promo_pct": str(settings.PROMO_DISCOUNT_PCT),
        "promo_hours": str(settings.PROMO_WINDOW_HOURS),
        "promo_cooldown": str(settings.PROMO_IP_COOLDOWN_DAYS),
        "period_days": str(settings.PRO_PERIOD_DAYS),
        "max_ips": str(settings.MAX_IPS_PER_MONTH),
        "session_days": str(settings.SESSION_TTL_DAYS),
        "renewal_days": str(settings.RENEWAL_REMINDER_DAYS),
        "promo_price": f"{settings.PRO_PRICE_USD * (100 - settings.PROMO_DISCOUNT_PCT) / 100:g}",
        "identity": _identity(),
    }


def _identity() -> str:
    """Identificación del responsable (Decreto 1377 de 2013, art. 13)."""
    import html as _html

    parts = [f"<strong>{_html.escape(settings.LEGAL_ENTITY_NAME)}</strong>"]
    if settings.LEGAL_ENTITY_ID:
        parts.append(f"NIT / C.C.: {_html.escape(settings.LEGAL_ENTITY_ID)}")
    location = ", ".join(x for x in (settings.LEGAL_ADDRESS, settings.LEGAL_CITY) if x)
    if location:
        parts.append(_html.escape(location))
    if settings.LEGAL_PHONE:
        parts.append(f"Tel.: {_html.escape(settings.LEGAL_PHONE)}")
    return " · ".join(parts)


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
        "Groq y Deepgram (transcripción y separación de voces), un proveedor de almacenamiento de objetos en la Unión Europea (archivos), Supabase (base de datos e inicio de sesión con Google/GitHub), "
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
        "Groq and Deepgram (transcription and voice separation), an object-storage provider in the European Union (files), Supabase (database and Google/GitHub sign-in), Bold (payments), Resend (email), "
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
    ("1. Aceptación", [
        "Estos Términos y Condiciones regulan el uso de Apex Vox (apex-vox.ialabs.app), sus extensiones y su bot de Telegram, ofrecidos por {entity}. "
        "Al crear una cuenta, usar el servicio sin cuenta o pagar Apex Pro, aceptas estos términos y la <a href=\"/legal/habeas-data\">Política de Tratamiento de Datos Personales</a>. "
        "Si no estás de acuerdo, no uses el servicio. Debes ser mayor de 18 años o actuar con autorización de tu representante legal.",
    ]),
    ("2. El servicio", [
        "Apex Vox transcribe audio, identifica oradores y, en Apex Pro, genera análisis (Apex Summa), calendarios de tareas y actas. "
        "Los resultados se producen con modelos de inteligencia artificial de terceros y pueden contener errores u omisiones: revísalos antes de usarlos en decisiones legales, médicas, financieras o laborales.",
        "Podemos mejorar, cambiar o retirar funciones. No garantizamos disponibilidad ininterrumpida; haremos esfuerzos razonables para mantener el servicio operativo y avisar de mantenimientos programados.",
    ]),
    ("3. Cuentas", [
        "La información de registro debe ser veraz. Las cuentas son personales e intransferibles: para evitar que se compartan, cada cuenta puede usarse desde un máximo de {max_ips} redes (IP) distintas por mes calendario; una red adicional queda bloqueada hasta el mes siguiente.",
        "Las sesiones vencen a los {session_days} días. Eres responsable de la confidencialidad de tu contraseña y de la actividad de tu cuenta; avísanos de inmediato si sospechas un uso no autorizado.",
        "El bot de Telegram se vincula a un solo chat por cuenta de Apex Pro.",
    ]),
    ("4. Planes y límites", [
        "<strong>Sin cuenta:</strong> hasta {guest_audios} audios al día de máximo {guest_minutes} minutos cada uno; sin análisis ni historial.",
        "<strong>Gratis:</strong> {free_hours} horas de audio al día y almacenamiento de {free_retention} horas.",
        "<strong>Apex Pro:</strong> USD {price_usd} por {period_days} días: transcripción y almacenamiento ilimitados, Apex Summa, actas y bot de Telegram. No hay prueba gratis: el pago activa el periodo.",
        "El uso \"ilimitado\" está sujeto a un uso razonable y personal; podemos limitar usos automatizados o masivos que afecten el servicio para otros usuarios.",
    ]),
    ("5. Precio, pagos y renovación manual", [
        "Los precios se expresan y cobran en dólares estadounidenses (USD) e incluyen los impuestos que correspondan. Tu banco o medio de pago puede aplicar conversión de moneda y comisiones propias.",
        "Los pagos se procesan con Bold mediante enlaces de pago de monto cerrado. No almacenamos datos de tarjetas.",
        "<strong>Sin suscripción ni cobros automáticos:</strong> Bold no permite suscripciones. Cada pago activa {period_days} días de Apex Pro y no se renueva solo. Para continuar, pagas manualmente el siguiente periodo; si pagas antes de que termine, los días se suman al periodo vigente. Te avisamos por correo {renewal_days} días antes del vencimiento.",
        "Al terminar el periodo pagado la cuenta vuelve al plan Gratis; los archivos se conservan según la política de retención de ese plan.",
    ]),
    ("6. Promoción de bienvenida", [
        "Si pagas Apex Pro dentro de las primeras {promo_hours} horas desde la creación de tu cuenta, tu primer periodo tiene {promo_pct}% de descuento (USD {promo_price} en lugar de USD {price_usd}).",
        "La promoción aplica solo al primer periodo de cada cuenta y a una sola cuenta por red (IP) cada {promo_cooldown} días (un trimestre). El precio con descuento lo calcula el servidor al crear el enlace de pago; no es acumulable con otras ofertas ni canjeable por dinero.",
        "Crear cuentas adicionales para obtener la promoción más de una vez es un uso abusivo y puede llevar al cobro de la diferencia o a la suspensión de las cuentas.",
    ]),
    ("7. Retracto, reversión y reembolsos", [
        "<strong>Retracto:</strong> conforme al artículo 47 de la Ley 1480 de 2011 (Estatuto del Consumidor), puedes retractarte dentro de los 5 días hábiles siguientes al pago escribiendo a <a href=\"mailto:{contact}\">{contact}</a>. "
        "La ley exceptúa los servicios cuya prestación comenzó con tu acuerdo; si ya usaste funciones de Apex Pro, el reembolso será proporcional a los días no usados.",
        "<strong>Reversión del pago:</strong> en los casos del artículo 51 de la Ley 1480 de 2011 (fraude, operación no solicitada, servicio no prestado o que no corresponde a lo ofrecido) puedes solicitar la reversión dentro de los 5 días hábiles siguientes a conocer el hecho, ante nosotros y ante el emisor de tu medio de pago.",
        "Los reembolsos aprobados se hacen al mismo medio de pago dentro de los 30 días calendario siguientes.",
    ]),
    ("8. Tu contenido y la autorización de terceros", [
        "Conservas todos los derechos sobre tus audios, transcripciones, notas y actas. Nos otorgas solo la licencia necesaria para procesarlos y prestarte el servicio; no los usamos para entrenar modelos propios.",
        "Declaras que tienes la autorización de las personas grabadas para grabarlas y tratar su voz y lo que dicen, conforme a la ley. Eres responsable del contenido que subes.",
    ]),
    ("9. Uso aceptable", [
        "No puedes usar Apex Vox para: contenido ilegal; grabar o vigilar a personas sin su consentimiento; infringir derechos de autor o de imagen; suplantar a otros; enviar spam; "
        "intentar acceder a cuentas o datos ajenos, eludir límites o pagos, hacer ingeniería inversa, sobrecargar o atacar el servicio.",
    ]),
    ("10. Propiedad intelectual", [
        "La marca Apex Vox, Apex Summa, Apex Box, el software, el diseño y los textos del sitio pertenecen a {entity} o a sus licenciantes. Estos términos no te otorgan derechos sobre ellos más allá del uso del servicio.",
    ]),
    ("11. Suspensión y terminación", [
        "Puedes eliminar tu cuenta en cualquier momento desde \"Mi cuenta\"; se borrarán tus datos según la Política de Tratamiento de Datos. "
        "Podemos suspender o cerrar cuentas que incumplan estos términos, previa notificación cuando sea posible. Los periodos pagados no usados por terminación sin incumplimiento tuyo se reembolsan proporcionalmente.",
    ]),
    ("12. Responsabilidad", [
        "El servicio se presta con la diligencia debida, pero los resultados de IA se ofrecen sin garantía de exactitud. En la medida permitida por la ley, no respondemos por daños indirectos ni lucro cesante, "
        "y nuestra responsabilidad total se limita a lo que pagaste en los últimos 3 meses. Nada de esto limita los derechos irrenunciables que te otorga la Ley 1480 de 2011.",
    ]),
    ("13. Cambios a estos términos", [
        "Avisaremos por correo y en el sitio los cambios relevantes de estos términos o de los precios con al menos 15 días de anticipación. Los cambios de precio no afectan periodos ya pagados.",
    ]),
    ("14. PQR, ley aplicable y jurisdicción", [
        "Peticiones, quejas y reclamos: <a href=\"mailto:{contact}\">{contact}</a>; respondemos dentro de los 15 días hábiles siguientes. También puedes acudir a la Superintendencia de Industria y Comercio (www.sic.gov.co).",
        "Estos términos se rigen por las leyes de la República de Colombia. Las controversias se resolverán ante los jueces competentes de Colombia, sin perjuicio de las acciones de protección al consumidor.",
    ]),
]

TERMS_EN: List[Section] = [
    ("1. Acceptance", [
        "These Terms and Conditions govern the use of Apex Vox (apex-vox.ialabs.app), its extensions and Telegram bot, provided by {entity}. "
        "By creating an account, using the service without one or paying for Apex Pro, you accept these terms and the <a href=\"/legal/habeas-data?lang=en\">Personal Data Processing Policy</a>. "
        "You must be 18 or older or act with the authorization of your legal guardian.",
    ]),
    ("2. The service", [
        "Apex Vox transcribes audio, identifies speakers and, on Apex Pro, produces analysis (Apex Summa), task calendars and minutes. Results come from third-party AI models and may contain errors: review them before relying on them for legal, medical, financial or employment decisions.",
        "We may improve, change or retire features. We do not guarantee uninterrupted availability but make reasonable efforts to keep the service running and announce planned maintenance.",
    ]),
    ("3. Accounts", [
        "Registration data must be accurate. Accounts are personal and non-transferable: each account may be used from at most {max_ips} different networks (IP) per calendar month; an additional network is blocked until next month.",
        "Sessions expire after {session_days} days. You are responsible for your password and the activity on your account.",
        "The Telegram bot links to a single chat per Apex Pro account.",
    ]),
    ("4. Plans and limits", [
        "<strong>Without an account:</strong> up to {guest_audios} audios per day of at most {guest_minutes} minutes each; no analysis or history.",
        "<strong>Free:</strong> {free_hours} hours of audio per day and {free_retention}-hour storage.",
        "<strong>Apex Pro:</strong> USD {price_usd} for {period_days} days: unlimited transcription and storage, Apex Summa, minutes and Telegram bot. There is no free trial: paying activates the period.",
        "\"Unlimited\" means reasonable personal use; we may limit automated or bulk usage that degrades the service for others.",
    ]),
    ("5. Price, payments and manual renewal", [
        "Prices are stated and charged in US dollars (USD) including applicable taxes. Your bank may apply its own currency conversion and fees.",
        "Payments are processed by Bold through closed-amount payment links. We never store card data.",
        "<strong>No subscription, no automatic charges:</strong> Bold does not support subscriptions. Each payment activates {period_days} days of Apex Pro and does not renew by itself. To continue you pay the next period manually; paying early adds the days to the current period. We email you {renewal_days} days before it ends.",
        "When the paid period ends the account returns to the Free plan; files are kept according to that plan's retention.",
    ]),
    ("6. Welcome promo", [
        "If you pay for Apex Pro within {promo_hours} hours of creating your account, your first period is {promo_pct}% off (USD {promo_price} instead of USD {price_usd}).",
        "The promo applies only to each account's first period and to one account per network (IP) every {promo_cooldown} days (one quarter). The discounted price is computed by the server when the payment link is created; it cannot be combined or exchanged for cash.",
        "Creating extra accounts to obtain the promo more than once is abusive and may lead to charging the difference or suspending the accounts.",
    ]),
    ("7. Withdrawal, chargebacks and refunds", [
        "<strong>Withdrawal:</strong> under article 47 of Colombian Law 1480 of 2011 you may withdraw within 5 business days of paying by emailing <a href=\"mailto:{contact}\">{contact}</a>. Services already started with your agreement are excepted by law; if you already used Apex Pro, the refund is proportional to the unused days.",
        "<strong>Payment reversal:</strong> in the cases of article 51 of Law 1480 of 2011 (fraud, unrequested transaction, service not provided or not as offered) you may request a reversal within 5 business days of learning of it, with us and with your card issuer.",
        "Approved refunds are made to the same payment method within 30 calendar days.",
    ]),
    ("8. Your content and third-party consent", [
        "You keep all rights to your audio, transcripts, notes and minutes. You grant us only the license needed to process them and provide the service; we do not use them to train our own models.",
        "You confirm you have the consent of the people recorded to record them and process their voice and words, as required by law. You are responsible for the content you upload.",
    ]),
    ("9. Acceptable use", [
        "You may not use Apex Vox for illegal content; recording or monitoring people without consent; infringing copyright or image rights; impersonation; spam; accessing other accounts or data, bypassing limits or payments, reverse engineering, overloading or attacking the service.",
    ]),
    ("10. Intellectual property", [
        "The Apex Vox, Apex Summa and Apex Box brands, software, design and site texts belong to {entity} or its licensors. These terms grant no rights over them beyond using the service.",
    ]),
    ("11. Suspension and termination", [
        "You can delete your account at any time from \"My account\"; your data is deleted as described in the Data Processing Policy. We may suspend or close accounts that break these terms, with notice when possible. Unused paid days are refunded proportionally if we terminate without breach on your part.",
    ]),
    ("12. Liability", [
        "We provide the service with due care, but AI results carry no accuracy guarantee. To the extent allowed by law we are not liable for indirect damages or lost profits, and our total liability is limited to what you paid in the last 3 months. Nothing here limits your non-waivable rights under Law 1480 of 2011.",
    ]),
    ("13. Changes", [
        "We will announce relevant changes to these terms or prices by email and on the site at least 15 days in advance. Price changes do not affect periods already paid.",
    ]),
    ("14. Complaints, governing law and jurisdiction", [
        "Requests and complaints: <a href=\"mailto:{contact}\">{contact}</a>; we answer within 15 business days. You may also contact Colombia's Superintendencia de Industria y Comercio (www.sic.gov.co).",
        "These terms are governed by the laws of the Republic of Colombia; disputes go before the competent Colombian courts, without prejudice to consumer protection actions.",
    ]),
]

HABEAS_ES: List[Section] = [
    ("1. Marco legal y alcance", [
        "Esta Política de Tratamiento de Datos Personales se adopta en cumplimiento del artículo 15 de la Constitución Política, la Ley Estatutaria 1581 de 2012 y el Decreto 1377 de 2013 (compilado en el Decreto 1074 de 2015). "
        "Aplica a todos los datos personales que Apex Vox recoge a través de su sitio web, extensiones, bot de Telegram y correos.",
    ]),
    ("2. Responsable del tratamiento", [
        "{identity}",
        "Correo para el ejercicio de derechos: <a href=\"mailto:{contact}\">{contact}</a>. Sitio web: apex-vox.ialabs.app.",
    ]),
    ("3. Definiciones", [
        "<strong>Titular:</strong> persona natural cuyos datos se tratan. <strong>Dato personal:</strong> información vinculada a una persona natural determinada o determinable. "
        "<strong>Dato sensible:</strong> el que afecta la intimidad o cuyo uso indebido puede generar discriminación, incluidos los datos biométricos. "
        "<strong>Autorización:</strong> consentimiento previo, expreso e informado del titular. <strong>Tratamiento:</strong> recolección, almacenamiento, uso, circulación o supresión. "
        "<strong>Responsable:</strong> quien decide sobre el tratamiento. <strong>Encargado:</strong> quien trata datos por cuenta del responsable. "
        "<strong>Transferencia / transmisión:</strong> envío de datos a un responsable / encargado, dentro o fuera de Colombia.",
    ]),
    ("4. Principios", [
        "Aplicamos los principios de legalidad, finalidad, libertad, veracidad o calidad, transparencia, acceso y circulación restringida, seguridad y confidencialidad (artículo 4 de la Ley 1581 de 2012). "
        "Solo recogemos los datos necesarios para las finalidades informadas y no los vendemos ni los usamos para entrenar modelos propios.",
    ]),
    ("5. Datos que tratamos", [
        "<strong>De cuenta:</strong> nombre, correo, idioma y, si inicias sesión con Google o GitHub, el correo verificado que ese proveedor entrega. La contraseña se guarda solo como hash PBKDF2-SHA256 con sal.",
        "<strong>Contenido:</strong> audios, transcripciones, oradores detectados, notas, resúmenes de Apex Summa y actas.",
        "<strong>Uso, pagos y seguridad:</strong> consumo diario, plan, pagos (referencia, monto y estado; nunca datos de tarjeta) y un hash no reversible de las redes (IP) usadas, que también sirve para aplicar el límite de una promoción por red cada {promo_cooldown} días.",
        "<strong>Opcionales:</strong> chat y usuario de Telegram si vinculas el bot; correo del boletín si te suscribes.",
    ]),
    ("6. Datos sensibles: la voz", [
        "La voz y la huella vocal pueden ser datos biométricos y, por tanto, sensibles (artículo 5 de la Ley 1581 de 2012). Las transcripciones también pueden revelar información sensible que las personas mencionen.",
        "Su tratamiento es <strong>facultativo</strong>: no estás obligado a autorizarlo, y sin él no podemos transcribir tus audios. La huella vocal (perfiles de voz) solo se crea si tú registras una muestra y se usa únicamente para reconocer oradores en tu cuenta.",
        "Quien sube una grabación declara contar con la autorización de las personas grabadas. Si apareces en una grabación subida por otra persona y quieres ejercer tus derechos, escríbenos.",
    ]),
    ("7. Finalidades", [
        "Prestar la transcripción, identificación de oradores, análisis, actas y almacenamiento; gestionar la cuenta y la autenticación; aplicar los límites de cada plan y de la promoción; procesar pagos y emitir recibos; "
        "enviar correos de servicio (bienvenida, promoción, recibos, avisos de renovación y vencimiento, recuperación de contraseña); prevenir fraude y uso compartido de cuentas; atender PQR; cumplir obligaciones legales, contables y tributarias; "
        "y, solo si te suscribes, enviar el boletín.",
    ]),
    ("8. Autorización", [
        "Al registrarte, iniciar sesión, usar el servicio sin cuenta o subir un audio, otorgas tu autorización previa, expresa e informada para tratar tus datos con estas finalidades, incluida la autorización expresa para los datos sensibles de voz. "
        "Conservamos prueba de la autorización (fecha de registro y aceptación). Puedes revocarla en cualquier momento, salvo cuando exista un deber legal o contractual de conservar los datos.",
    ]),
    ("9. Derechos del titular", [
        "Conforme al artículo 8 de la Ley 1581 de 2012 puedes: conocer, actualizar y rectificar tus datos; solicitar prueba de la autorización; ser informado del uso dado a tus datos; presentar quejas ante la Superintendencia de Industria y Comercio (SIC); "
        "revocar la autorización y/o pedir la supresión de los datos; y acceder gratuitamente a ellos.",
        "También puedes eliminar tu cuenta y todos sus datos directamente desde \"Mi cuenta\".",
    ]),
    ("10. Consultas y reclamos", [
        "<strong>Canal:</strong> <a href=\"mailto:{contact}\">{contact}</a>, indicando nombre, correo de la cuenta, descripción de la solicitud y, si actúas en nombre de otro, el documento que lo acredite.",
        "<strong>Consultas:</strong> se responden en máximo 10 días hábiles desde su recibo, prorrogables hasta 5 días hábiles más informando el motivo (artículo 14).",
        "<strong>Reclamos</strong> (corrección, actualización, supresión o incumplimiento): se responden en máximo 15 días hábiles, prorrogables hasta 8 días hábiles más. Si el reclamo está incompleto pediremos subsanarlo dentro de los 5 días siguientes; si pasan 2 meses sin respuesta, se entenderá desistido (artículo 15).",
        "Solo podrás acudir a la SIC después de agotar este trámite ante nosotros.",
    ]),
    ("11. Encargados y transferencias internacionales", [
        "Compartimos datos solo con proveedores que los tratan por nuestra cuenta: Groq y Deepgram (transcripción), un proveedor de almacenamiento de objetos en la Unión Europea, Supabase (base de datos e inicio de sesión), Bold (pagos), Resend (correos), Telegram (si vinculas el bot), Cloudflare (DNS) y Google Fonts (tipografías). "
        "Varios están fuera de Colombia (por ejemplo, Estados Unidos y la Unión Europea); la transmisión se hace bajo contratos que exigen confidencialidad y seguridad, conforme a los artículos 25 y 26 de la Ley 1581 de 2012.",
    ]),
    ("12. Seguridad", [
        "Aplicamos medidas técnicas y administrativas descritas en la <a href=\"/legal/seguridad\">Política de seguridad</a>: HTTPS, contraseñas con hash, sesiones revocables, aislamiento de datos por cuenta, control de acceso en la base de datos y almacenamiento privado con enlaces temporales.",
    ]),
    ("13. Conservación", [
        "<strong>Sin cuenta:</strong> los audios se borran al terminar y el resultado se elimina de la memoria a los {guest_ttl} minutos. "
        "<strong>Plan Gratis:</strong> audios y resultados por {free_retention} horas. <strong>Apex Pro:</strong> mientras exista la cuenta o hasta que los elimines. "
        "Los registros de pago se conservan el tiempo exigido por la ley contable y tributaria.",
    ]),
    ("14. Menores de edad", [
        "El servicio no está dirigido a menores de 18 años. Si un menor aparece en una grabación, quien la sube debe contar con la autorización de su representante legal y respetar el interés superior del menor.",
    ]),
    ("15. Vigencia y cambios", [
        "Esta política rige desde su publicación. Avisaremos por correo y en el sitio cualquier cambio sustancial antes de aplicarlo. "
        "Las bases de datos se mantendrán mientras subsistan las finalidades descritas. Cuando corresponda, se inscribirán en el Registro Nacional de Bases de Datos de la SIC.",
    ]),
]

HABEAS_EN: List[Section] = [
    ("1. Legal framework and scope", [
        "This Personal Data Processing Policy is adopted under article 15 of the Colombian Constitution, Statutory Law 1581 of 2012 and Decree 1377 of 2013 (compiled in Decree 1074 of 2015). It covers all personal data Apex Vox collects through its website, extensions, Telegram bot and emails.",
    ]),
    ("2. Data controller", [
        "{identity}",
        "Email to exercise your rights: <a href=\"mailto:{contact}\">{contact}</a>. Website: apex-vox.ialabs.app.",
    ]),
    ("3. Principles", [
        "We apply the principles of legality, purpose, freedom, accuracy, transparency, restricted access, security and confidentiality (article 4 of Law 1581 of 2012). We collect only what the stated purposes require, never sell data and never use it to train our own models.",
    ]),
    ("4. Data we process", [
        "<strong>Account:</strong> name, email, language and, with Google or GitHub sign-in, the verified email they share. Passwords are stored only as salted PBKDF2-SHA256 hashes.",
        "<strong>Content:</strong> audio, transcripts, detected speakers, notes, Apex Summa summaries and minutes.",
        "<strong>Usage, payments and security:</strong> daily usage, plan, payments (reference, amount and status; never card data) and a one-way hash of the networks (IP) used, also used to enforce one promo per network every {promo_cooldown} days.",
        "<strong>Optional:</strong> Telegram chat and username if you link the bot; newsletter email if you subscribe.",
    ]),
    ("5. Sensitive data: voice", [
        "Voice and voiceprints may be biometric and therefore sensitive data (article 5 of Law 1581 of 2012); transcripts may also reveal sensitive information. Providing it is <strong>optional</strong>, but without it we cannot transcribe your audio. Voice profiles are created only if you enrol a sample and are used only to recognise speakers in your account.",
        "Whoever uploads a recording confirms they have the consent of the people recorded. If you appear in someone else's recording and want to exercise your rights, contact us.",
    ]),
    ("6. Purposes", [
        "Providing transcription, speaker identification, analysis, minutes and storage; account management and authentication; plan and promo limits; payments and receipts; service emails (welcome, promo, receipts, renewal and expiry notices, password reset); fraud and account-sharing prevention; handling requests; legal, accounting and tax duties; and, only if you subscribe, the newsletter.",
    ]),
    ("7. Authorization", [
        "By registering, signing in, using the service without an account or uploading audio, you give prior, express and informed authorization for these purposes, including express authorization for sensitive voice data. We keep proof of it and you may revoke it at any time, except where a legal or contractual duty requires keeping the data.",
    ]),
    ("8. Your rights", [
        "Under article 8 of Law 1581 of 2012 you may access, update and correct your data; request proof of authorization; be informed of its use; complain to the Superintendencia de Industria y Comercio (SIC); revoke authorization and/or request deletion; and access your data free of charge. You can also delete your account and all its data from \"My account\".",
    ]),
    ("9. Requests and complaints", [
        "Channel: <a href=\"mailto:{contact}\">{contact}</a> with your name, account email and request. Requests are answered within 10 business days (extendable by 5); complaints within 15 business days (extendable by 8). Incomplete complaints must be completed within 5 days; after 2 months without reply they are considered withdrawn. You may go to the SIC after completing this procedure with us.",
    ]),
    ("10. Processors and international transfers", [
        "We share data only with providers acting on our behalf: Groq and Deepgram (transcription), an object-storage provider in the European Union, Supabase (database and sign-in), Bold (payments), Resend (email), Telegram (if you link the bot), Cloudflare (DNS) and Google Fonts. Several are outside Colombia (e.g. the US and the EU); transmissions are covered by confidentiality and security obligations under articles 25 and 26 of Law 1581 of 2012.",
    ]),
    ("11. Security and retention", [
        "Security measures are described in the <a href=\"/legal/seguridad?lang=en\">Security policy</a>. Without an account, audio is deleted once processed and results are removed after {guest_ttl} minutes; Free plan data is kept {free_retention} hours; Apex Pro data while the account exists or until you delete it; payment records as long as the law requires.",
    ]),
    ("12. Minors and changes", [
        "The service is not directed to people under 18. Anyone uploading a recording of a minor must have their legal guardian's authorization. We will announce material changes to this policy by email and on the site before applying them.",
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
    "terminos": {"es": ("Términos y Condiciones", TERMS_ES), "en": ("Terms and Conditions", TERMS_EN)},
    "habeas-data": {
        "es": ("Política de Tratamiento de Datos Personales (Habeas Data)", HABEAS_ES),
        "en": ("Personal Data Processing Policy (Habeas Data)", HABEAS_EN),
    },
    "seguridad": {"es": ("Política de seguridad", SECURITY_ES), "en": ("Security policy", SECURITY_EN)},
}


def render_page(slug: str, lang: str, asset_version: str) -> str:
    import html as _html

    lang = lang if lang in ("es", "en") else "es"
    title, sections = PAGES[slug][lang]
    base = settings.PUBLIC_BASE_URL or "https://apex-vox.ialabs.app"
    ctx = _ctx()
    nav_labels = {
        "es": [("terminos", "Términos"), ("habeas-data", "Habeas Data"), ("privacidad", "Privacidad"), ("seguridad", "Seguridad")],
        "en": [("terminos", "Terms"), ("habeas-data", "Habeas Data"), ("privacidad", "Privacy"), ("seguridad", "Security")],
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
<meta name="description" content="{_html.escape(title)} — Apex Vox ({'transcripción y resumen de reuniones' if lang == 'es' else 'meeting transcription and summaries'}).">
<meta name="robots" content="index, follow">
<link rel="canonical" href="{base}/legal/{slug}?lang={lang}">
<link rel="alternate" hreflang="es" href="{base}/legal/{slug}?lang=es">
<link rel="alternate" hreflang="en" href="{base}/legal/{slug}?lang=en">
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
