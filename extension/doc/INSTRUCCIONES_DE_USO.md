# Instrucciones de Uso — Apex Box (Extensión de Chrome)

Este documento explica cómo **probar la extensión en tu navegador**, cómo **usarla para grabar reuniones (presenciales o virtuales)** y cómo **subirla a Google Chrome Web Store**.

---

## 1. Cómo instalarla y probarla en Google Chrome (Modo Desarrollador)

1. Abre Google Chrome y escribe en la barra de direcciones:
   `chrome://extensions`
2. Activa el interruptor **Modo de desarrollador** (arriba a la derecha).
3. Haz clic en el botón **Cargar descomprimida** (arriba a la izquierda).
4. Selecciona una de estas dos carpetas según lo que quieras probar:
   - **Para probar la versión lista para la tienda (producción)**:
     `/home/iamdexter/Documentos/transcripcion/extension/versionenvio`
   - **Para desarrollo local (permite cambiar entre `localhost:8000` y la nube)**:
     `/home/iamdexter/Documentos/transcripcion/extension`
5. Fija el icono naranja de **Apex Box** en tu barra de herramientas de Chrome haciendo clic en el icono del rompecabezas (🧩 Extensiones) → clic en el pin 📌 junto a **Apex Box — Grabador de Reuniones**.

---

## 2. Cómo usar la extensión para grabar una reunión

### Paso previo: Iniciar sesión
1. Haz clic en el icono de **Apex Box** en la barra de Chrome; se abrirá una **pestaña fija** a la izquierda de tu navegador (`Apex Box · Grabador`).
2. Si aún no has iniciado sesión, pulsa el botón verde **«Iniciar sesión en Apex Vox»** (o entra en `https://apex-vox.ialabs.app` e inicia sesión).
3. En cuanto inicies sesión en la web, la extensión detectará tu cuenta automáticamente (sin que tengas que copiar tokens ni recargar) y mostrará tu correo y tu plan activo.

---

### Opción A: Grabar una Reunión Presencial (solo micrófono)
1. Haz clic en el icono de **Apex Box** para ir a la pestaña fija del grabador.
2. Configura los datos de la reunión:
   - **Tipo de reunión**: *Ejecutiva*, *Consejo / Junta directiva*, *Comité*, *Asamblea* o *Seguimiento* (esto define la plantilla del acta).
   - **Título**: Ej. *Comité semanal de ventas*.
   - **Tipo de grabación**: Selecciona **Presencial**.
   - **Modelo**: Elige el motor de transcripción/diarización (*Mc-Lewis*, *Mc-Ayrton*, *Mc-Norris* o *Mc-Piastri*).
3. Pulsa **«● Grabar»** (si es la primera vez, acepta el permiso de micrófono en Chrome).
4. Verás la onda de sonido en verde (`● Captando sonido`) y el reloj avanzando. En el icono de la extensión aparecerá el tiempo transcurrido en rojo (o `MUDO` en ámbar si detecta más de 15 segundos de silencio).
5. Al terminar la reunión, pulsa **«■ Detener»**.

---

### Opción B: Grabar una Videollamada / Reunión Virtual (Google Meet, Zoom Web, Teams Web, Webex)
1. **Muy importante**: Primero entra en la pestaña donde está la videollamada (por ejemplo, la pestaña de Google Meet o Teams).
2. **Estando dentro de la pestaña de la videollamada**, haz clic en el icono naranja de **Apex Box** en la barra superior de Chrome.
   - Esto registra esa pestaña como la fuente de audio de la reunión y te lleva automáticamente a la pestaña fija de **Apex Box** con el modo **Virtual** preseleccionado y el título autocompletado.
3. Verifica que debajo de **Virtual** diga:
   `Graba el audio de «Google Meet / Zoom / Teams…» + tu micrófono.`
4. Pulsa **«● Grabar»**:
   - Seguirá escuchándose el audio de la videollamada con normalidad.
   - En pantalla verás **dos barras de nivel independientes**: `Reunión` (lo que hablan los demás en la llamada) y `Micrófono` (lo que hablas tú).
   - Cada **3 minutos** se sube automáticamente un bloque al servidor y se libera la memoria RAM para que puedas grabar reuniones largas sin cortes.
5. Cuando termine la videollamada, ve a la pestaña fija de **Apex Box** y pulsa **«■ Detener»**.

---

### Paso final: Obtener las Notas, Resumen y Acta
Al pulsar **«■ Detener»**, la extensión sube el último bloque pendiente y muestra la tarjeta **«Reunión lista»**:
- Haz clic en **«Ver notas, resumen y acta ↗»** para abrir directamente el resultado en Apex Vox.
- O haz clic en **«Copiar»** para compartir el enlace directo de la reunión.

---

## 3. Cómo enviar la extensión a Google Chrome Web Store

1. **Archivo que debes subir**:
   No comprimas toda la carpeta `extension/`. Usa únicamente el paquete limpio que ya está generado en:
   `/home/iamdexter/Documentos/transcripcion/extension/versionenvio/apex-box-v3.2.0-chrome-webstore.zip`
2. **Si modificas algo en `versionenvio/` y necesitas regenerar el ZIP**:
   Ejecuta en la terminal:
   ```bash
   /home/iamdexter/Documentos/transcripcion/extension/scripts/package-extension.sh
   ```
3. **Textos, capturas de pantalla y justificaciones de permisos para el formulario de Google**:
   Abre el documento [GUIA_CONFIGURACION_Y_ENVIO_CWS.md](./GUIA_CONFIGURACION_Y_ENVIO_CWS.md) y utiliza las imágenes de la carpeta `doc/assets/` (`store-icon-128x128.png`, `screenshot-1-grabador-1280x800.png`, `screenshot-2-resultado-acta-1280x800.png` y `small-promo-tile-440x280.png`).
