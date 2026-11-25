# Auditoría CSAT automática desde Chatwoot — Diseño

Fecha: 2026-11-24
Herramienta: `auditoria_csat` (`tools/auditoria_csat.py`, `templates/auditoria_csat.html`)
Relacionada: `informe_semanal_cs` (`tools/informe_semanal_cs.py`, `templates/informe_semanal_cs.html`)

## Intención y por qué

El departamento de CS entrega cada semana a gerencia un informe generado con IA
(`informe_semanal_cs`). Su sección **"CSAT y Chats con negativos, Auditoría interna"**
necesita datos reales: CSAT de la semana y de la anterior, distribución de
calificaciones, auditoría de negativos, clasificación, casos relevantes y **CSAT ajustado**.

Hoy el proceso es manual: se descarga el CSV de CSAT desde Chatwoot, se mira el
porcentaje de satisfacción y se revisan los negativos. Algunos negativos **no son
atribuibles al agente** (el usuario se molestó por algo fuera de su control: sistema,
política, captcha, etc.). Esos casos castigan injustamente al agente; al excluirlos, la
satisfacción del período debe subir. Ese es el "CSAT ajustado".

Ya existe conexión directa con Chatwoot, así que el CSV sobra: se elige un rango de
fechas y la herramienta trae las encuestas sola.

## Objetivos

1. Elegir un rango de fechas y traer de Chatwoot todas las encuestas CSAT del período.
2. Para cada negativo, traer la conversación de Chatwoot para que la IA tenga contexto real.
3. La IA **propone** si cada negativo es atribuible o no al agente, con motivo y evidencia;
   **una persona confirma o corrige**. El CSAT ajustado solo descuenta exclusiones confirmadas.
4. Mostrar CSAT real y CSAT ajustado, **general del período y por agente**.
5. Guardar la auditoría del período (mínimo necesario) para que el informe semanal la use
   y pueda comparar con la semana anterior.
6. En el informe semanal, poder elegir una auditoría CSAT guardada; el informe arma con
   ella la sección de CSAT sin copiar/pegar.

## No objetivos

- No guardar transcripciones, fotos ni datos de contacto (nombre, correo, teléfono).
- No escribir nada de vuelta en Chatwoot (no tocar `csat_review_notes`).
- No auditar neutrales ni positivos (igual que hoy: solo negativos 1–2).
- No cambiar la lógica de `auditoria_chats` ni sus tablas.

## Anti-objetivos (sería un fracaso aunque funcione)

- Que el CSAT ajustado suba por decisiones de la IA que nadie confirmó.
- Que el guardado crezca sin límite y compita por espacio en el Supabase compartido.
- Romper el flujo actual: carga → auditoría → resumen → exportes (AGENTS.md lo marca delicado).

## Restricciones

- App Flask monolítica server-rendered, deploy en Vercel (límite de tiempo por request;
  ver commit `1b0183d`). Nada de SPA.
- Secretos de Chatwoot, IA y Supabase solo en servidor.
- Supabase de producción compartido con otros proyectos con mucho tráfico de fotos
  (Storage). Estos datos van a la base de datos, no a Storage, y deben ser mínimos.
- UI en español, estilos en `static/styles.css`, tablas dentro de `table-wrap`.

## Enfoques considerados

- **A. Bloque para copiar.** Auditoría desde Chatwoot sin guardar; al final genera un texto
  que se pega en el informe. Menor cambio, pero la semana anterior hay que traerla a mano.
- **B. Auditoría guardada y conectada (elegido).** Igual, pero cada período auditado se
  guarda en Supabase con guardado mínimo y el informe semanal la selecciona.
- **C. El informe consulta Chatwoot directo.** Descartado: se salta la confirmación humana.

Se eligió **B con guardado mínimo**: solo resumen y negativos, sin transcripciones, con
retención de 12 semanas. Volumen real medido (últimas 4 semanas): 55–85 encuestas y
8–19 negativos por semana. A ~1 KB por negativo, menos de 250 KB retenidos. Ese volumen
(3–4 páginas de 25) se trae en una sola request sin riesgo con el límite de Vercel.

## Lo que se decidió (con el usuario)

- Fuente: Chatwoot por rango de fechas, en lugar del CSV.
- La IA propone; una persona confirma. El ajustado cuenta solo exclusiones confirmadas.
- Se muestra real y ajustado, general y por agente (propuesto y aceptado sin objeción).
- Guardado mínimo en Supabase con retención de 12 semanas.
- La auditoría alimenta la sección CSAT del informe semanal.

## Diseño

### 1. Datos desde Chatwoot (verificado contra la instancia)

- `GET /api/v1/accounts/{id}/csat_survey_responses?since=&until=&page=` → lista paginada
  (25 por página) con `id`, `rating`, `feedback_message`, `conversation_id`,
  `assigned_agent{id,name,available_name,…}`, `contact{…}`, `created_at` (epoch).
- `GET /api/v1/accounts/{id}/csat_survey_responses/metrics?since=&until=` → `total_count`,
  `ratings_count`, `total_sent_messages_count`. Sirve para validar que la paginación trajo
  todo y para el CSAT real de un período no auditado.
- Agregar al cliente existente en `utils/chatwoot_reportes.py`: `respuestas_csat(since, until)`
  (recorre páginas hasta vacía) y `metricas_csat(since, until)`.
- El rango se arma con `construir_rango_chatwoot_fechas` (fechas inclusivas, zona
  `CHATWOOT_TIMEZONE`).
- Transcripción: solo para negativos, con `mensajes_de_conversacion` +
  `construir_transcripcion` (anonimiza) de `utils/auditoria_chats_transcripcion.py`. Se usa
  en memoria para la IA y **no se guarda**.

### 2. Conversión a filas de la herramienta

Cada encuesta se convierte a la misma fila que hoy produce `construir_filas_desde_dataframe`
(agente, calificación, comentario, enlace, fecha, tipo de rating, justificable, motivo,
campos de IA), con el enlace de `url_conversacion`. Así el resumen, los cálculos
(`calcular_flag_csat`, `construir_resumen_por_agente`, `construir_resumen_por_motivo`), la
IA (`auditar_estado_con_ia`) y los exportes siguen funcionando sin reescribirse.
Se agrega a la fila `survey_id` y `conversation_id` como claves.

### 3. Pantalla de Auditoría CSAT

- Arriba: **selector de período** con opciones (decidido por el usuario: "varias opciones
  para seleccionar"): *Semana pasada (lun–dom)*, *Esta semana (lun–hoy)*, *Últimos 7 días*,
  *Mes pasado*, *Este mes* y *Personalizado* (fecha inicio / fecha fin). Al elegir una
  opción se completan las fechas; el botón "Traer encuestas de Chatwoot" es la acción principal.
  Se guarda el tipo de período (`tipo_periodo`) junto con las fechas.
- Lista de auditorías guardadas recientes (período, CSAT real, ajustado, negativos
  pendientes) para retomarlas.
- La carga por CSV queda como opción secundaria ("Cargar CSV manualmente") para no romper
  el flujo existente; ese modo sigue usando el estado temporal de 24 h y no se guarda.
- El resto de la pantalla (resumen, tabla de negativos, IA, confirmar, exportes) se mantiene.
- Indicador visible: "N negativos sin confirmar — el ajustado aún no es definitivo".

### 4. Confirmación humana

Hoy `aplicar_resultado_ia` escribe la respuesta de la IA directo en `fila["justificable"]`,
que es lo que usa `calcular_flag_csat`; o sea, la IA ya excluye negativos sola. Esto cambia
**en ambos modos (Chatwoot y CSV)** *(decisión de diseño, no del usuario)*: el resultado de la IA va a
campos `ia_*` y `justificable` pasa a ser solo la decisión de la persona. Los exportes
incluyen ambas columnas.

Cada negativo tiene dos capas: **propuesta IA** (`ia_justificable`, motivo, confianza,
evidencia) y **decisión final** (la que elige la persona en la tabla y guarda). El
ajustado usa solo la decisión final. Una propuesta de la IA no cambia la decisión final
por sí sola; la persona puede aceptar todas las propuestas con un botón
"Aceptar propuestas de la IA" o editarlas una a una.

**Auditoría humana** (pedido del usuario): cualquier negativo se puede auditar a mano, con
o sin propuesta de la IA. Desde la fila se abre la conversación (traída en vivo de Chatwoot,
sin guardarla), y la persona elige la decisión y el motivo y escribe una **nota del auditor**
(≤500). Cada negativo registra el origen de su decisión: `origen_decision` = `ia_aceptada`
| `humana` | vacío (pendiente). La IA nunca sobrescribe una decisión humana. El resumen
y el bloque del informe distinguen cuántos se auditaron a mano y cuántos se aceptaron de la IA.

Semántica (se mantiene la actual): decisión final "SÍ" = no atribuible, se excluye del
CSAT; "TAL VEZ" y "NO" cuentan como negativo; sin decisión = cuenta como negativo.

### 5. Guardado mínimo en Supabase

Nuevo archivo SQL `supabase_csat_audits.sql` (mismo patrón que `supabase_chat_audits.sql`)
y nuevo módulo `utils/auditoria_csat_store.py` (mismo patrón Supabase + memoria para tests).

Tabla `csat_audit_periods`:
`id`, `fecha_inicio`, `fecha_fin` (únicos juntos), `total_encuestas`, `ratings_count` (json),
`csat_real`, `csat_ajustado`, `por_agente` (json con real/ajustado por agente),
`negativos_total`, `negativos_excluidos`, `negativos_pendientes`, `created_at`, `updated_at`.

Tabla `csat_audit_negatives`:
`id`, `period_id`, `survey_id` (único por período), `conversation_id`, `agente_id`,
`agente_nombre`, `rating`, `comentario` (texto de la encuesta, recortado a 500), `enlace`,
`fecha`, `ia_justificable`, `ia_motivo`, `ia_confianza`, `ia_evidencia` (≤500),
`decision_final`, `motivo_final`, `origen_decision`, `nota_auditor` (≤500), `updated_at`.

No se guardan transcripciones ni datos de contacto. Positivos y neutrales solo se guardan
como conteos dentro del período.

- Guardado automático *(decisión de diseño)*: al traer de Chatwoot se crea o actualiza el período, y cada
  acción (IA, guardar decisiones) escribe en Supabase; no se usa el estado temporal en
  modo Chatwoot. Un período con pendientes no es engañoso porque el ajustado solo descuenta
  confirmados; la lista y el selector del informe muestran "N pendientes".
- Re-traer un período ya guardado *(decisión de diseño)*: Chatwoot es la fuente de verdad. Se actualizan
  conteos, se agregan negativos nuevos y se conservan las decisiones de los que siguen
  negativos; los negativos que ya no vuelven o subieron a 3+ se borran.
- Retención: al guardar, borrar períodos con `fecha_fin` de hace más de 12 semanas
  (cascada sobre sus negativos).

### 5b. Pruebas sin guardar (pedido del usuario: no almacenar basura)

- **Modo prueba en la pantalla**: casilla "Modo prueba (no se guarda)" junto al selector
  de período. Con ella todo funciona igual (Chatwoot, IA, auditoría humana, resumen,
  exportes), pero el estado vive en el almacenamiento temporal de 24 h que ya usa el modo
  CSV (`utils/estado_temporal.py`), nunca en Supabase. La pantalla muestra una franja
  "Modo prueba — nada de esto se guarda". Las pruebas no aparecen en la lista de guardadas
  ni en el selector del informe; para probar el informe, la auditoría de prueba ofrece
  "Descargar bloque para el informe" (texto) que se puede subir como archivo adicional.
  Limitación conocida: en Vercel el estado temporal puede perderse entre requests (ya
  pasa hoy con el CSV); en local es estable.
- **Tests automáticos**: usan el store en memoria y respuestas de Chatwoot/IA simuladas;
  nunca tocan Supabase ni Chatwoot reales (seguir el patrón de `tests/test_aislamiento_pruebas.py`).

### 6. Informe semanal

- En `informe_semanal_cs.html`, un selector "Auditoría CSAT" con los períodos guardados
  (opcional).
- Al generar, se arma un bloque de texto estructurado con: período, total de encuestas,
  distribución, CSAT real, CSAT ajustado, por agente, negativos por motivo, excluidos,
  pendientes y 3–5 casos relevantes (comentario + motivo + evidencia corta).
- **Período anterior** según el tipo: semana → la semana lun–dom previa; mes → el mes
  calendario previo; últimos 7 días / personalizado → el rango del mismo largo justo antes.
  Si existe una auditoría guardada con esas fechas exactas, se usan sus datos (incluido el
  ajustado); si no, se calcula el real con `metricas_csat` y el bloque aclara "sin auditoría".
  Se permiten períodos que se solapen; cada uno es independiente.
- Al elegir una auditoría, si el campo libre `periodo` del informe está vacío, se completa
  con sus fechas (dd/mm/aa al dd/mm/aa).
- El bloque se agrega a los datos que ya recibe `build_weekly_report_prompt`, para que la
  IA redacte la sección. Si hay negativos pendientes, el bloque lo dice y el informe muestra
  una advertencia en pantalla.

### 7. Configuración

Usa variables existentes (`CHATWOOT_*`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, IA de
CSAT). Si se agrega alguna nueva (p. ej. retención en semanas), actualizar `.env.example` y
`README.md`.

## Lo que queda al criterio de quien construya

- División exacta de funciones y nombres internos, respetando los del proyecto.
- Cuántos negativos procesa la IA por clic para entrar en el límite de Vercel (hoy
  `OPENAI_CSAT_MAX_CASES`); si conviene traer transcripciones en el mismo paso de IA.
- Diseño visual fino de la pantalla, siguiendo el admin actual.
- Formato exacto del bloque de texto para el informe.
- Tests: cliente Chatwoot con respuestas simuladas, conversión a filas, cálculo del
  ajustado (solo confirmados), store en memoria, retención y armado del bloque del informe.
