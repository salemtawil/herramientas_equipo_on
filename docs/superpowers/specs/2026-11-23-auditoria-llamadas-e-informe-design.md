# Llamadas de Multiadmin en la auditoría e informe PDF del lote

Fecha: 2026-11-23 · Herramienta existente: `auditoria_chats` (pauta QA-1.1, ver
`2026-11-20-auditoria-chats-qa-1-1-design.md`).

## Intención

La empresa ya audita las llamadas con su propia IA en Multiadmin (Análisis de llamadas). Se quiere
que el lote de auditoría muestre, por agente, la atención por **mensajes** (Chatwoot, QA-1.1) y por
**llamadas** (Multiadmin), con un resumen de feedback equivalente para ambos, y descargar al final
un **informe PDF bien elaborado, con el logo de la empresa**, para presentar.

## Objetivos

- Traer **todas** las llamadas analizadas de cada agente del lote en el rango de fechas, incluidas
  las cortas, sin conversación o de buzón de voz (el usuario quiere saber si el agente deja bien el
  mensaje en el buzón).
- Un resumen con IA por agente de sus llamadas: puntos fuertes, áreas de mejora, manejo de buzón de
  voz, cada punto con los tickets donde ocurrió.
- Feedback por agente con dos bloques: Atención por mensajes y Atención por llamadas.
- Página de informe imprimible → «Guardar como PDF», con portada y logo.

## No objetivos

- No se re-auditan las llamadas con la rúbrica QA-1.1: se usa la auditoría de Multiadmin tal cual.
- No se modifica nada en Multiadmin (ni las estrellas de la rúbrica).
- No se guarda la transcripción ni el teléfono del cliente.
- No hay PDF generado en el servidor ni librerías nuevas.

## Anti-objetivos

- Que el puntaje de llamadas se mezcle con el QA de chats en un solo número.
- Que se pierdan llamadas por no emparejar bien al agente sin que la página lo avise.
- Que el informe exponga datos personales de clientes (teléfonos, correos).

## Enfoques

- Llamadas: **traerlas del servicio de Multiadmin** (elegido) frente a subir el CSV (el CSV no
  trae rúbrica, coaching ni transcripción).
- PDF: **A. página de informe con hoja de impresión → «Guardar como PDF»** (elegido; reutiliza el
  patrón del Reporte de agentes, sin dependencias) frente a B. PDF en servidor con `fpdf2`/`reportlab`
  (dependencia nueva, diseño más laborioso, límites de Vercel).

## Decisiones del usuario

- Todas las llamadas del rango, sin muestreo, **sin excluir** las de buzón o sin conversación.
  «Todas» significa todas las de **los agentes seleccionados en el lote** y **en las fechas del
  lote**; no se guardan llamadas de otros agentes.
- La IA resume las llamadas igual que el feedback de mensajes.
- Informe final en PDF, presentable, con logo.

## Lo verificado en Multiadmin (2026-11-23)

- Servicio: `GET https://admin-api.compi.sh/projects/compinche/call-analysis?startDate=<ms>&endDate=<ms>`
  → `{items: [...], count}` (fechas en milisegundos epoch; el código de la página menciona `cursor`
  para paginar). Auth: `Authorization: Bearer <id token de Cognito>` del mismo user pool que ya usa
  la app para Usuarios activos (`tools/api_multiadmin.py`).
- Agentes: `GET .../projects/compinche/call-analysis/admins` (Multiadmin identifica al agente por
  `agentNumber`, un teléfono; el nombre sale de esta lista).
- Campos por llamada (según el código de la página): `callId`, `recordKey`, `ticketId`,
  `agentNumber`, `customerNumber`, `durationSec`, `callType`, `issueType`, `createdAt`,
  `scores.overall`, `sentiment.agent/customer`, analytics (resolución al primer contacto,
  escalada, relación hablar/escuchar, esperas, silencios, intención), `rubric` (12 ítems:
  nombre, peso, porcentaje, justificación), `keyPoints`, `coaching` (`nextActions`, mejoras,
  aciertos) y `transcript`.
- El `ticketId` es el número de conversación de Chatwoot donde quedó la llamada.
- Pendiente de comprobar desde el backend: que el token de la app sirva para `admin-api.compi.sh`
  y la forma exacta de `rubric`, `coaching`, `keyPoints` y la paginación. Es la primera tarea del plan.

## Diseño

### 1. Cliente de Multiadmin para llamadas (`utils/multiadmin_llamadas.py`)

- `listar_llamadas(desde_ms, hasta_ms)` (pagina con `cursor` si viene) y `listar_agentes_llamadas()`.
- Reutiliza el token de `tools/api_multiadmin.py` (renovación incluida). Base URL configurable con
  `MULTIADMIN_ADMIN_API_URL` (por defecto `https://admin-api.compi.sh`). Actualizar `.env.example`
  y `README.md`.
- Un solo proyecto: `compinche` (decisión de Claude: el CSV del usuario muestra que las líneas de
  Paripé y Compinche están todas bajo ese proyecto). Sin soporte multi-proyecto.
- `normalizar_llamada(item)` devuelve solo lo que se guarda (sin `customerNumber` ni transcripción):
  `call_id`, `ticket_id`, `agent_number`, `fecha`, `duracion_seg`, `tipo`, `motivo`, `puntaje`,
  `sentimiento_agente`, `sentimiento_cliente`, `analitica`, `rubrica` [{nombre, peso, pct,
  justificacion}], `puntos_clave` [{titulo, texto}], `coaching` {aciertos[], mejoras[],
  proximas_acciones[]}, `sin_conversacion`.
- `sin_conversacion`: duración < 60 s, o el motivo menciona buzón, contestadora, «no estaba
  disponible», «sin conversación» o «accidental». **No excluye**: solo etiqueta.
- Los textos que vienen de Multiadmin pasan por `anonimizar` antes de guardarse.

### 2. Emparejar agentes Chatwoot ↔ Multiadmin

- Tabla `chat_audit_agentes_llamadas` (`agent_number` pk, `chatwoot_agente_id`, `nombre_multiadmin`,
  `manual` bool, `updated_at`), RLS sin políticas. Clave por número de Multiadmin: un agente de
  Chatwoot puede tener varios números (decisión de Claude).
- Automático al procesar el lote: nombre normalizado igual, o el nombre de Chatwoot coincide con el
  primer nombre del de Multiadmin y es único. Lo guardado manualmente siempre gana.
- La página del lote muestra los agentes del lote sin emparejar con un selector de agentes de
  Multiadmin, y un aviso con los números de Multiadmin que tuvieron llamadas en el rango pero no
  están emparejados con nadie (nombre y cantidad, guardado en el lote como
  `llamadas_sin_emparejar` {agent_number: {nombre, llamadas}}). No se guardan esas llamadas.
- Al guardar un emparejamiento se vuelven a traer las llamadas del rango y se regenera
  automáticamente el resumen con IA de los agentes afectados (1 llamada a Gemini por agente).

### 3. Llamadas en el lote

- Tabla `chat_audit_calls` (`id`, `batch_id` fk cascade, `agente_id` Chatwoot, `call_id`, unique
  (`batch_id`, `call_id`), más los campos normalizados de §1). RLS sin políticas.
- Las llamadas tienen su propio estado en el lote, independiente de los chats (decisión de
  Claude): `llamadas_estado` ∈ {pendiente, trayendo, resumiendo, listo, error},
  `llamadas_progreso` (último día traído) y `feedback_llamadas`. Columnas nuevas en
  `chat_audit_batches` con migración.
- En lotes nuevos QA-1.1, `ejecutar_paso` alterna: primero trae llamadas (**un día** del rango por
  paso, para no exceder el tiempo de Vercel), luego los chats, y al final el resumen de llamadas
  (una llamada a Gemini por agente con llamadas; el cupo estimado suma 1 por agente). Si Multiadmin
  falla, `llamadas_estado = error`, se informa y el lote sigue con los chats.
- Los lotes QA-1.1 ya terminados (o con llamadas en error) muestran un botón «Traer llamadas»
  que pone `llamadas_estado = pendiente` y reactiva el bucle de pasos solo para las llamadas.
  Los lotes de la pauta v1 no tienen llamadas ni informe.

### 4. Resumen con IA de las llamadas por agente

- Entrada: por llamada, `ticket`, puntaje, motivo, tipo, `sin_conversacion`, coaching (aciertos,
  mejoras, próximas acciones) y los 3 ítems de rúbrica más bajos con su justificación; límite de
  texto con prioridad a las llamadas de menor puntaje.
- Salida JSON validada: `puntos_fuertes` y `areas_mejora` ([{texto, tickets[]}], máx. 5 cada uno),
  `buzon_voz` {evaluacion, tickets[]} (vacío si no hubo), `recomendaciones` ([{texto, tickets[]}],
  máx. 5), `resumen` (2 frases). Tickets que no existen se descartan.
- Se guarda en el lote (`feedback_llamadas` jsonb, por `agente_id`) con el modelo usado.
- Mismas reglas de error, reintento y cupo que la auditoría de chats.

### 5. Página del lote

- Sección «Llamadas»: por agente, llamadas analizadas, puntaje medio, sin conversación/buzón,
  entrantes/salientes, y las 5 de menor puntaje con enlace (ticket → Chatwoot).
- «Feedback por agente»: dos bloques, «Atención por mensajes» (lo actual) y «Atención por
  llamadas» (resumen de §4 con enlaces por ticket, y criterios de la rúbrica de Multiadmin con
  menor promedio).

### 6. Informe PDF (`/auditoria-chats/lote/<id>/informe`)

- Página independiente con su hoja `static/auditoria_informe.css` (`@page` carta, saltos de
  página, colores con `print-color-adjust: exact`) y botón «Descargar PDF» que abre la impresión
  (JS en `static/auditoria_chats.js`, sin scripts en línea).
- Contenido: **portada** (logo, «Informe de auditoría de calidad», periodo, agentes, fecha de
  generación); **resumen general** (chats auditados, QA medio de chats y estados; llamadas
  analizadas, puntaje medio, buzón/sin conversación); **una página por agente** (indicadores de
  chats y llamadas lado a lado, puntos fuertes, áreas de mejora y recomendaciones de cada canal
  con referencias #chat y #ticket como enlaces, comentarios del revisor); **anexo** con la tabla de
  chats auditados y la de llamadas.
- Logo: `static/system-logos/compinche_48.svg` por defecto; si el usuario entrega un logo
  completo, se agrega como `static/informe-logo.svg` y se usa ese.
- Sin teléfonos ni correos de clientes.

## Queda a criterio de quien construye

- Redacción del prompt del resumen de llamadas y límites de texto.
- Detalle visual del informe dentro del sistema de diseño (colores de estado ya existentes).
- Cómo paginar si la respuesta de Multiadmin trae `cursor`.
