# Política de Privacidad — Apex Box (Extensión de Chrome)

**Última actualización:** 2 de noviembre de 2026

Esta Política de Privacidad describe cómo la extensión para Google Chrome **Apex Box — Grabador de Reuniones** ("la Extensión"), operada por **Apex Vox / IALabs**, recopila, almacena y utiliza la información cuando usted la instala y utiliza.

---

## 1. Qué datos recopilamos

La Extensión únicamente accede a los datos estrictamente necesarios para grabar las reuniones que el usuario decide iniciar manualmente:

1. **Información de autenticación (`Authentication Info`)**:
   - Cuando inicia sesión en `https://apex-vox.ialabs.app`, la Extensión sincroniza su token de sesión (`apex_vox_token`) desde el almacenamiento local de la aplicación web de Apex Vox hacia el almacenamiento local del navegador (`chrome.storage.local`) para asociar las grabaciones a su cuenta.
2. **Comunicaciones personales / Audio de reuniones (`Personal Communications`)**:
   - Únicamente cuando usted pulsa explícitamente el botón **"● Grabar"** en la pestaña del grabador, la Extensión captura el audio del micrófono de su dispositivo (Modo Presencial) o el audio de la pestaña de videollamada seleccionada junto con su micrófono (Modo Virtual).
   - Se registra también el título opcional que usted asigne a la reunión, el tipo de reunión elegido (`ejecutiva`, `consejo`, `comite`, `asamblea`, `seguimiento`) y la URL de la pestaña de videollamada cuando usted la selecciona explícitamente como fuente en Modo Virtual.
3. **Preferencias locales de configuración**:
   - Último tipo de reunión, modo de grabación (`presencial` o `virtual`) y modelo de transcripción elegido (`Mc-Lewis`, `Mc-Ayrton`, `Mc-Norris`, `Mc-Piastri`).

---

## 2. Cómo se almacenan y transmiten los datos

- **Almacenamiento local (`chrome.storage.local` y `chrome.storage.session`)**:
  Sus preferencias de grabación, el estado de grabación en curso y el token de sesión activo permanecen almacenados localmente en su navegador Chrome.
- **Transmisión cifrada al servidor de Apex Vox (`https://apex-vox.ialabs.app`)**:
  Durante una grabación activa iniciada por usted, el audio se divide en bloques de 3 minutos que se transmiten mediante conexión segura HTTPS (`TLS`) a `https://apex-vox.ialabs.app/api/box/sessions/...` y se liberan inmediatamente de la memoria RAM de su navegador.

---

## 3. Cómo utilizamos los datos

Los datos recopilados se utilizan **exclusivamente** para proporcionar la función única de la Extensión:
- Autenticar su cuenta de usuario en Apex Vox.
- Transcribir el audio de la reunión grabada e identificar a los hablantes.
- Generar automáticamente las notas, el resumen ejecutivo y el acta formal de la reunión dentro de su cuenta de Apex Vox.

---

## 4. Servicios de terceros y compartición de datos

- **No vendemos datos a terceros**: No vendemos, alquilamos ni comercializamos sus datos personales, grabaciones ni transcripciones a terceros bajo ninguna circunstancia.
- **No utilizamos publicidad ni rastreadores**: La Extensión no incluye scripts de analítica de terceros, píxeles de seguimiento ni redes publicitarias, ni recopila su historial general de navegación web.
- **No se utilizan para fines crediticios**: Los datos nunca se utilizan para determinar solvencia crediticia ni para fines de préstamos.

---

## 5. Retención, control del usuario y eliminación de datos

- **Control total de grabación**: La Extensión nunca graba en segundo plano sin su intervención; siempre requiere pulsar el botón **"● Grabar"** y muestra en todo momento un indicador visual `REC` tanto en la pestaña fija como en el icono de la barra de herramientas de Chrome.
- **Cierre de sesión y desinstalación**: Al cerrar sesión en `https://apex-vox.ialabs.app`, el token de sesión se elimina automáticamente de la Extensión. Al desinstalar la Extensión de Chrome, todos los datos guardados en `chrome.storage.local` y `chrome.storage.session` se eliminan de su navegador.
- **Eliminación de reuniones en la nube**: Usted puede consultar, exportar o eliminar sus grabaciones, transcripciones y actas en cualquier momento desde su panel en `https://apex-vox.ialabs.app`.

---

## 6. Cambios en esta Política de Privacidad

Cualquier actualización de esta Política de Privacidad se publicará en esta misma página indicando la fecha de última actualización en la parte superior.

---

## 7. Contacto

Si tiene preguntas sobre esta Política de Privacidad o sobre el tratamiento de sus datos en **Apex Box / Apex Vox**, puede contactarnos a través de:
- **Sitio web**: https://apex-vox.ialabs.app
