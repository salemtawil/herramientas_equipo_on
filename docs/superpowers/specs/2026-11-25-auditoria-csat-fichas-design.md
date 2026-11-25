# Auditoría CSAT: rediseño con revisión por fichas — Diseño

Fecha: 2026-11-25
Herramienta: `auditoria_csat` (`tools/auditoria_csat.py`, `templates/auditoria_csat.html`, `static/auditoria_csat.js`, `static/styles.css`)
Boceto aprobado: `.superpowers/brainstorm/68-1795639554/content/csat-fichas.html`

## Intención y por qué

La herramienta ya funciona por detrás (Chatwoot por período, IA por pasos, decisión humana,
Supabase, modo prueba, informe semanal), pero la pantalla no se entiende. Caso real: la IA revisó
los 14 negativos, terminó y el usuario vio que «no cambió nada»: las propuestas estaban escondidas
en una tabla abajo y los contadores de arriba solo cuentan decisiones confirmadas. La página tiene
11 bloques seguidos sin un orden claro.

El usuario quiere una pantalla **profesional, amigable y entendible**: que en todo momento se vea
en qué paso se está, qué propuso la IA y qué falta confirmar, y que el CSAT ajustado cambie a la
vista al confirmar.

## Objetivos

1. Una pantalla guiada en 4 pasos visibles: **1. Encuestas → 2. La IA revisa → 3. Tú confirmas → 4. Resultado**, cada uno con su avance.
2. **CSAT real vs CSAT ajustado** grandes arriba, con la diferencia («▲ 2.8») y por qué cambió.
3. **Una ficha por negativo** (calificación 1–2) con: agente, estrellas, fecha, comentario del cliente
   destacado, enlace «Ver conversación», **propuesta de la IA en lenguaje claro**
   («La IA cree: NO fue culpa del agente · Motivo · % seguro» + evidencia), botones de decisión con
   palabras y nota del auditor.
4. Pestañas **Por confirmar (N) · Confirmados (N) · Todos (N)**.
5. **Guardar cada decisión al instante, sin recargar** (enfoque elegido): la ficha pasa a
   Confirmados y los KPIs y los pasos se actualizan en el momento.
6. Lo secundario abajo y plegado: Resultado (por agente, motivos, gráficos, hallazgos, descargas),
   Auditorías guardadas y Cargar CSV.
7. Incluido: el **modelo de respaldo recibe el tiempo que sobra** cuando el principal falla rápido.

## No objetivos

- No cambiar cómo se traen las encuestas, cómo audita la IA, qué se guarda en Supabase, el modo
  prueba ni el informe semanal.
- No cambiar los valores internos (`justificable` = `"NO" | "TAL VEZ" | "SÍ"`, `origen_decision`),
  el CSV exportado ni el bloque del informe.
- No convertir la app en SPA ni agregar librerías de frontend.

## Anti-objetivos

- Que una decisión se pierda o se aplique a la ficha equivocada (p. ej. por clics rápidos seguidos).
- Que la pantalla diga algo distinto de lo que se guardó (KPIs que no coinciden con Supabase).
- Que sin JavaScript la herramienta deje de servir.

## Restricciones

- Flask server-rendered, Jinja, estilos compartidos en `static/styles.css` (sin CSS grande en el
  template), UI en español, consistente con el admin (tema oscuro actual; tarjetas `card`).
- Vercel: varios servidores; el estado de la auditoría viaja firmado en la página
  (`analysis_id` = token de `guardar_estado_temporal`). **Cada respuesta trae un token nuevo** y la
  siguiente petición debe usar el último.
- Límite de 60 s por petición (`vercel.json`).
- Ancho de celular: fichas y barras hacen wrap; sin scroll horizontal de página.

## Enfoques considerados

- **A. Guardado al instante sin recargar (elegido por el usuario).** JS envía la decisión, el
  servidor responde JSON con el estado nuevo, la ficha y los KPIs se actualizan. Sin JS, el botón
  envía el formulario y recarga (degradación).
- **B. Cada botón recarga la página.** Más simple, pero 14 recargas y se pierde la posición; va
  contra «amigable». Descartado.

## Diseño

### Estructura de la página (de arriba abajo)

1. **Barra superior**: título, frase («Revisa los negativos y descubre cuáles no fueron culpa del
   agente»), selector de período (+ fechas si «Personalizado»), casilla Modo prueba, botón
   «Traer encuestas». Si hay una auditoría abierta, muestra su período y si está guardada o en prueba.
2. **Pasos (4 tarjetas)**, cada uno con estado hecho / en curso / pendiente:
   - 1. Encuestas: «75 traídas · 14 negativas».
   - 2. La IA revisa: «N de M con propuesta» (M = negativos que no decidió una persona).
   - 3. Tú confirmas: «N de 14 confirmadas».
   - 4. Resultado: «CSAT final e informe» (hecho cuando no quedan negativos por confirmar).
3. **KPIs**: CSAT real, CSAT ajustado (con ▲/▼ y «sin N negativos que no fueron culpa del agente»),
   Negativos, Por confirmar.
4. **Barra de acciones de la revisión**: pestañas; botón «🤖 Revisar con IA los que faltan» (el
   proceso por pasos actual, con su texto de avance) y «Aceptar todo lo que propuso la IA».
5. **Fichas** (solo negativos; orden: por confirmar primero, luego por fecha).
6. **Resultado** (`<details>`): CSAT por agente (real vs ajustado), motivos, gráficos y hallazgos
   existentes, y las descargas (CSV auditado, reporte para IA, bloque para el informe en modo prueba).
7. **Auditorías guardadas** (`<details>`) y **Cargar CSV manualmente** (`<details>`).

Sin auditoría abierta: solo la barra superior, una explicación corta de los 4 pasos y las
guardadas desplegadas.

### Ficha

- Encabezado: agente, estrellas (1–5), fecha; a la derecha «Ver conversación ↗» (ruta existente
  `/auditoria-csat/conversacion/<id>`, nueva pestaña) o el enlace del CSV si no hay conversación.
- Comentario del cliente destacado (o «Sin comentario»).
- Caja IA si hay propuesta: «🤖 La IA cree: **NO fue culpa del agente**» (para `ia_justificable`
  SÍ) / «**Sí fue culpa del agente**» (NO) / «**Dudoso**» (TAL VEZ), motivo, % de confianza y
  evidencia. Sin propuesta: «La IA todavía no la revisó».
- Decisión con tres botones: **✓ No fue culpa del agente** (`SÍ`), **✗ Sí fue culpa del agente**
  (`NO`), **? Dudoso** (`TAL VEZ`); el que coincide con la IA se marca como sugerido. Selector de
  motivo (precargado con el de la IA) y nota del auditor.
- Confirmada: ficha compacta con insignia «✓ Confirmado: <decisión> · tú / aceptado de la IA»,
  motivo, nota y enlace «cambiar» que la reabre.

### Guardado al instante

- Nueva acción `decidir` en `POST /auditoria-csat` con `analysis_id`, `period_id`, `row_id`,
  `justificable`, `motivo`, `nota`. Aplica la decisión **solo a esa fila** (misma regla de
  `origen_decision = "humana"`), persiste (temporal firmado + Supabase si no es prueba) y responde:
  - JSON (si `Accept: application/json`): `analysis_id` nuevo, KPIs, conteos de pasos y pestañas,
    datos de la ficha y `advertencia` si falló Supabase.
  - HTML (sin JS): la página completa con la ficha ya confirmada.
- JS: los envíos se hacen **en cola, uno a la vez**, siempre con el último `analysis_id`. Mientras
  se guarda, la ficha muestra «Guardando…»; si falla, vuelve a su estado y muestra el error.
- «Aceptar todo» y «Revisar con IA» siguen siendo acciones del servidor; al terminar recargan con
  `ver_estado` (ya existe).

### Respaldo de la IA

En `auditar_lote_con_proveedor`, el modelo de respaldo recibe el tiempo restante del presupuesto
(`CSAT_IA_PRESUPUESTO_SEGUNDOS` menos lo que tardó el principal), con un mínimo razonable, en vez de
la mitad fija.

### Textos

Desaparecen de la pantalla «NO / TAL VEZ / SÍ justificable», «CSAT actualizado» y «Resumen inicial
automático». Se usa: «Sí fue culpa del agente», «Dudoso», «No fue culpa del agente», «CSAT real»,
«CSAT ajustado». Los resúmenes por agente y motivos usan las mismas palabras.

## Decisiones del usuario

- Revisión **por fichas**, una por negativo (no tabla mejorada).
- El boceto `csat-fichas.html`, tal cual («me gusta, hazlo así»).
- **Guardado al instante sin recargar.**

## Decisiones de diseño (no del usuario)

- Solo los negativos tienen ficha; positivos y neutrales se ven en conteos, gráficos y por agente.
  Hoy la tabla lista todas las filas con filtros; esos filtros por columna desaparecen.
- Se incluye el arreglo del tiempo del respaldo.
- Sin JS, cada botón de ficha envía el formulario y recarga.
- **Confirmada = tiene `justificable`**, sea `origen_decision` «humana» o «ia_aceptada» (aceptar la
  IA es una acción de la persona). Pasos y pestañas: «Por confirmar» = negativos sin `justificable`;
  «Confirmados» = con `justificable`. Paso 2 «La IA revisa»: «N de M con propuesta», donde M =
  negativos sin decisión humana y N = cuántos de ellos tienen `ia_justificable`. La insignia dice
  «tú» o «aceptado de la IA».
- **«cambiar»** solo reabre la ficha en pantalla; lo guardado (y los KPIs) no cambia hasta pulsar
  un botón de decisión. Desde las fichas no se vuelve a «pendiente».
- **Motivo y nota se guardan con el botón de decisión.** Para editarlos en una ficha confirmada:
  «cambiar», ajustar y pulsar el botón (el de la decisión actual queda resaltado).
- **Modo CSV también usa fichas** y guardado al instante (solo estado firmado, sin Supabase);
  `period_id` es opcional en `decidir`.
- **En «Por confirmar», la ficha confirmada se queda en su lugar** en versión compacta hasta
  cambiar de pestaña o recargar (la lista no salta bajo el cursor); los contadores sí cambian al
  instante. Sin pendientes: «¡Listo! No quedan negativos por confirmar» y enlace a Resultado.
- **`decidir` guarda sin la limpieza de retención** (`borrar_vencidos` solo al traer o con las
  demás acciones) y reutiliza el guardado actual del período (≈15 filas, una escritura por clic).

## Lo que queda al criterio de quien construya

- Nombres de funciones, clases CSS y la división exacta entre template parciales.
- Colores e iconos dentro de la paleta del admin.
- Cómo se ven los gráficos existentes dentro de Resultado.
- Tests: acción `decidir` (JSON y HTML, una sola fila, origen humana, Supabase o prueba),
  conteos de pasos, render de fichas en sus tres estados, respaldo con tiempo restante, y que el
  flujo CSV siga funcionando.
