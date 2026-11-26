# Incidencias de chats — diseño

Fecha: 2026-11-26 · Estado: borrador para aprobación

## Intención

El manager o el shift que está de turno necesita saber, sin abrir chat por chat en Chatwoot, qué pasó en un tramo de tiempo concreto: qué problemas reportaron los clientes y en qué chats hubo mala atención de un agente. Hoy eso se descubre tarde o no se descubre.

La herramienta toma un **rango de días y horas** elegido por quien la usa (no el día entero por obligación), revisa **todos** los chats de Chatwoot creados en ese rango con un **motor de reglas propio** (gratis, instantáneo, explicable) y muestra dos listas resaltadas con la evidencia exacta. La IA es **opcional** y solo se usa para confirmar los chats que las reglas marcaron, si queda cupo.

A futuro el usuario quiere **entrenar un modelo propio**. Esta versión no lo hace, pero deja guardadas las decisiones del manager (incidencia real / falso positivo) para que sirvan de datos etiquetados.

## Quién la usa y para qué

- **Manager o shift de turno.** Elige un rango (por ejemplo «hoy 14:00–18:00» o «lunes 22:00 → martes 06:00»), lanza la revisión y lee el resultado.
- Lo que busca:
  1. **Reportes de clientes**: un detalle concreto que mencionó el cliente (cobro doble, falla de la app, algo que no le llegó, un reclamo…).
  2. **Mala atención del agente**: demoras, abandono, cliente ignorado, cierre sin responder, frustración evidente del cliente.
- Cada caso muestra la frase o el dato que lo disparó, el agente y un enlace al chat en Chatwoot.

## Objetivos

- Revisar todos los chats creados en un rango de fecha-hora, opcionalmente filtrado por bandejas.
- Detectar incidencias con reglas sin depender de la IA ni de su cupo.
- Mostrar dos listas (Reportes de clientes / Mala atención) con evidencia resaltada, severidad y enlace al chat.
- Guardar cada revisión en Supabase: el turno siguiente puede abrirla, y un chat ya evaluado (y resuelto) no se vuelve a procesar.
- Permitir al manager marcar cada chat con incidencia como **atendida** o **no es incidencia** (falso positivo), con nombre y nota opcional.
- IA opcional, solo sobre chats marcados por las reglas, dentro de un cupo diario.
- Exportar el resultado de una revisión a CSV.

## No objetivos (v1)

- Entrenar o integrar un modelo propio (fase siguiente; v1 solo guarda las etiquetas del manager).
- Revisiones automáticas programadas (cron) o alertas por Slack/correo.
- Editar reglas o diccionarios desde la interfaz: viven en código con número de versión.
- Login o permisos (la app es pública por decisión ya tomada).
- Llamadas o canales fuera de los chats de Chatwoot.
- Calificar al agente con nota (eso es Auditoría de chats).

## Anti-objetivos

- **Lista inundada de falsos positivos** que nadie lee. Las reglas deben ser conservadoras, con severidad, y la vista ordena por severidad.
- Guardar más datos del cliente de lo necesario (no se guardan transcripciones completas).
- Que Vercel corte la revisión a mitad y se pierda el avance.
- Gastar IA dos veces en el mismo chat.
- Romper Auditoría de chats, Auditoría CSAT o Reporte de agentes al tocar `ChatwootClient`.

## Restricciones

- Flask server-rendered, Jinja, `static/styles.css`; sin SPA (ver `AGENTS.md`).
- Secretos solo en backend.
- Vercel: tiempo máximo por petición y `/tmp` no compartido → procesamiento por pasos con estado en Supabase (mismo patrón que Auditoría de chats).
- CSP sin scripts en línea ni `onclick`/`style=""`: el JS va en `static/incidencias_chats.js`. Subir `ASSET_VERSIONS` en `app.py` al tocar CSS/JS.
- El `.env` local apunta a Supabase de **producción**: las pruebas manuales no deben dejar basura (ver «Modo prueba»).
- Pruebas sin llamadas externas (`tests/conftest.py`), con fakes de Chatwoot y store como en `tests/test_auditoria_chats_motor.py`.
- Variables nuevas → `.env.example` y `README.md`.

## Enfoques considerados

| Enfoque | A favor | En contra |
|---|---|---|
| **1. Herramienta nueva que reutiliza piezas de Auditoría de chats + tabla propia en Supabase (elegido por el usuario)** | Sobrevive a cortes de Vercel, historial para el turno siguiente, no reprocesa chats, permite marcar atendidas. | Hay que crear tablas nuevas. |
| 2. Herramienta nueva sin guardar | Más rápida de construir. | Se pierde avance en Vercel, sin registro, se repite trabajo. |
| 3. «Modo incidencias» dentro de Auditoría de chats | Reusa tablas y pantallas. | Mezcla dos propósitos y toca una herramienta delicada. |

Motor de detección: el usuario eligió **filtro previo / reglas** (opción B) frente a IA de pago sobre todos los chats (A) o IA gratis hasta agotar cupo (C). Luego aceptó que las reglas sean el **motor principal** y la IA solo un complemento opcional, dejando el modelo propio entrenado para más adelante.

## Diseño

### Piezas (patrón obligatorio de `AGENTS.md`)

- `tools/incidencias_chats.py` — blueprint `incidencias_chats`, rutas bajo `/incidencias-chats/`. Registrar en `app.py`.
- `utils/incidencias_chats_reglas.py` — reglas, umbrales y diccionarios, con `REGLAS_VERSION`. Funciones puras: reciben la lista de mensajes de Chatwoot y devuelven incidencias. Sin red.
- `utils/incidencias_chats_motor.py` — crear revisión, paso a paso, resúmenes, CSV.
- `utils/incidencias_chats_store.py` — store Supabase (mismo estilo que `utils/auditoria_chats_store.py`).
- `templates/incidencias_chats.html` (formulario + revisiones recientes) y `templates/incidencias_chats_revision.html` (progreso + listas).
- `static/incidencias_chats.js` — polling del paso, como `static/auditoria_chats.js`.
- Entrada en `utils/navegacion.py` (grupo «Calidad», título «Incidencias de chats»), que alimenta `base.html` y la card de `inicio.html`.
- `supabase_chat_incidents.sql` — tablas nuevas.

Reutilizar sin modificar su comportamiento: `ChatwootClient.mensajes_de_conversacion`, `url_conversacion`, `listar_bandejas`; de `utils/auditoria_chats_transcripcion.py`: `anonimizar`, `es_llamada`, `tiene_mensajes_de_agente`, `_esperas`/`_primera_respuesta`/`metricas_tiempos` y `construir_transcripcion_v2` (para la IA); `utils/ia_chat.py` (`obtener_config_ia`, `completar_json`); `_listar_bandejas` / exclusión de bandeja de llamadas de `tools/auditoria_chats.py` (mover a un helper compartido solo si hace falta, sin cambiar su comportamiento); turnos configurados (`obtener_turnos_configurados`) para el atajo de turno.

Única adición a `ChatwootClient`: un método nuevo `conversaciones_en_rango(since, until, page, inbox_ids=None)` igual que `conversaciones_de_agente` pero sin el filtro de `assignee_id`. No se toca el método existente.

### Flujo

1. **Formulario.** Desde (fecha + hora) y hasta (fecha + hora) en la zona `CHATWOOT_TIMEZONE`; atajo «Turno» que rellena las horas desde los turnos configurados; bandejas opcionales (por defecto todas menos la de llamadas); casilla «Confirmar con IA (usa cupo)»; casilla «Modo prueba (no se guarda)». Rango máximo: **72 h** (*decisión mía*, constante ajustable).
2. **Crear revisión** → fila en `chat_incident_reviews` con estado `listando`.
3. **Pasos** (POST `/incidencias-chats/revision/<id>/paso`, llamado por el JS hasta `fin`):
   - `listando`: una página de `conversaciones_en_rango` por paso; recorte exacto por `created_at` y bandeja; inserta filas `pendiente` en `chat_incident_chats`. Si un `conversation_id` ya fue evaluado en otra revisión **y estaba resuelto** al evaluarse, se enlaza a ese resultado sin releerlo; si estaba abierto, se reevalúa.
   - `evaluando`: lee chats y aplica reglas. Un paso procesa varios chats hasta un presupuesto de ~8 s (*decisión mía*), porque las reglas son baratas y lo caro es leer Chatwoot. Llamadas y chats sin mensajes de cliente se descartan (contados, no listados).
   - `ia` (solo si se pidió y hay `AUDITORIA_CHATS_AI_API_KEY`): una llamada por chat marcado, de severidad alta primero, hasta el cupo diario. Si se agota o falla, la revisión termina igual; esos chats quedan «sin confirmar por IA».
   - `completado` / `con_errores`.
4. **Vista de revisión.** Contadores arriba (chats revisados, descartados, con incidencia por tipo). Dos tablas en `table-wrap`: **Reportes de clientes** y **Mala atención**, ordenadas por severidad y luego hora. Columnas: chat (#id → Chatwoot ↗), hora, agente, categoría/regla, evidencia (frase con la coincidencia en `<mark>`), severidad, IA (confirmada/descartada/—, con resumen corto), estado. Filtros simples por agente y categoría (querystring, server-rendered). Un mismo chat puede aparecer en ambas tablas.
5. **Gestión.** En cada chat con incidencias: botones «Atendida» y «No es incidencia», campo de nombre (texto libre, recordado en cookie) y nota opcional. Se guarda quién, cuándo y la decisión. Es la etiqueta para el futuro modelo.
6. **CSV** de la revisión con una fila por incidencia (incluye la decisión del manager).

### Reglas v1 (`REGLAS_VERSION = "1"`)

Todas las cifras son **umbrales iniciales míos**, constantes en el módulo, para ajustar con datos reales.

**Mala atención** (sobre mensajes del agente/cliente; ignora mensajes privados y de actividad):

| Regla | Dispara cuando | Severidad |
|---|---|---|
| Sin atención | Hay mensajes del cliente y ningún mensaje del agente | alta |
| Cierre sin responder | El chat está resuelto y el último mensaje público es del cliente, sin respuesta | alta |
| Cliente ignorado | ≥3 mensajes seguidos del cliente sin respuesta durante > 10 min | media |
| Primera respuesta tardía | Primera respuesta del agente > 10 min tras el primer mensaje del cliente | media |
| Espera larga | Alguna espera del cliente por respuesta del agente > 15 min | media |
| Frustración del cliente | Frases del diccionario «frustración» en mensajes del cliente («nadie me responde», «pésima atención», «quiero hablar con un supervisor»…) | media |
| CSAT bajo | La conversación tiene CSAT 1–2 (si el dato viene en la conversación) | media |

**Reportes de clientes** (solo mensajes entrantes del cliente; texto normalizado sin tildes y en minúsculas; coincidencia por frase o raíz):

| Categoría | Ejemplos de frases iniciales |
|---|---|
| Cobros | me cobraron dos veces, cobro doble, cobro indebido, reembolso, devolución de dinero |
| Fallas de la app | no funciona, me sale error, se cierra la app, no carga, se cae |
| No recibido | no me llegó, no recibí, no se acreditó, sigue pendiente |
| Acceso a la cuenta | no puedo entrar, cuenta bloqueada, no me llega el código |
| Reclamo formal | reclamo, denuncia, demanda, defensa del consumidor |

La severidad de un reporte es alta para «Cobros» y «Reclamo formal» y media para el resto. **Los diccionarios iniciales son un borrador que el usuario debe revisar** antes de dar la herramienta por buena; el builder los deja en un único lugar fácil de editar.

Evidencia: el fragmento del mensaje que disparó la regla, `anonimizar()` aplicado, máximo 200 caracteres centrados en la coincidencia. Para las reglas de tiempo, la evidencia es el dato («primera respuesta a los 23 min»).

### IA opcional

- Usa la configuración ya existente `AUDITORIA_CHATS_AI_*` vía `utils/ia_chat.py`.
- Cupo propio: nueva variable `INCIDENCIAS_CHATS_AI_CUPO_DIARIO` (por defecto 10 chats/día), contado por fecha en Supabase. Es aparte del cupo de Auditoría de chats, aunque comparten proveedor: el README debe advertirlo.
- Entrada: transcripción v2 del chat (recortada) + lista de incidencias detectadas. Salida JSON: por incidencia `confirmada` (sí/no) + `motivo` breve; `resumen` del chat (1–2 frases); opcional `incidencias_extra` que las reglas no vieron (se muestran marcadas «IA»).
- La transcripción se guarda solo temporalmente en la fila para la llamada y se borra después (`transcripcion_tmp`, como en Auditoría de chats).

### Datos (`supabase_chat_incidents.sql`)

RLS activado sin políticas (solo backend con service role), como las tablas existentes.

- `chat_incident_reviews`: `id`, `created_at`, `updated_at`, `since`, `until` (epoch), `bandejas jsonb`, `usar_ia bool`, `estado` (`listando`, `evaluando`, `ia`, `completado`, `con_errores`), `pagina_listado int`, `contadores jsonb`, `reglas_version`, `modelo`, `creado_por text`.
- `chat_incident_chats`: `id`, `review_id` (fk, cascade), `conversation_id bigint`, `agente_id`, `agente_nombre`, `inbox_id`, `conversacion_fecha`, `resuelto bool`, `estado` (`pendiente`, `procesando`, `evaluado`, `descartado`, `error`), `motivo_descarte`, `incidencias jsonb` (lista: tipo `cliente`/`atencion`, categoría o regla, severidad, evidencia, origen `reglas`/`ia`), `metricas jsonb`, `ia_estado`, `ia_resultado jsonb`, `transcripcion_tmp`, `decision` (`atendida`/`falso_positivo`/null), `decision_por`, `decision_nota`, `decision_at`, `reglas_version`, timestamps. Índice único `(review_id, conversation_id)` e índice por `conversation_id` para la reutilización entre revisiones.
- Tabla o fila simple para el contador del cupo diario de IA (decisión del builder).

### Modo prueba

Como el `.env` local escribe en producción: con «Modo prueba» la revisión **no usa Supabase**; procesa como máximo **30 chats** en una sola petición, solo con reglas (sin IA) y muestra el resultado sin guardarlo ni permitir marcar decisiones (*decisión mía*). Así se pueden probar las reglas contra chats reales sin dejar basura.

### Errores

- Sin `SUPABASE_*` o `CHATWOOT_*`: mensaje claro en la pantalla (usar `mensaje_error_publico`), y el modo prueba sigue disponible si falta solo Supabase.
- Fallo al leer un chat: se reintenta en el siguiente paso; tras 3 intentos queda `error` y la revisión termina `con_errores` con botón «Reintentar errores».
- Filas `procesando` abandonadas (pestaña cerrada) se recuperan como en `_recuperar_abandonados`.

### Precisiones (revisión del builder; todas son *decisiones mías* salvo la 2)

1. **Chats abiertos.** Las reglas de tiempo se miden hasta el momento de la evaluación. «Cierre sin responder» solo aplica a chats resueltos. En un chat abierto, «Sin atención» y «Cliente ignorado» solo disparan si el cliente lleva esperando más que el umbral de la regla; si no, no se marca nada. Los chats abiertos llevan la etiqueta «abierto» en la vista y siempre se reevalúan en una revisión posterior.
2. **Qué chats entran en el rango.** Los **creados** dentro del rango (el usuario habló de «chats recibidos durante el turno»). Las reglas evalúan la conversación completa, no solo los mensajes dentro del rango.
3. **Reutilización entre revisiones.** Se crea una **fila nueva** en la revisión nueva con los resultados de reglas e IA **copiados** de la última evaluación, sin volver a leer Chatwoot. Solo se reutiliza si: aquella evaluación estaba resuelta, la versión de reglas (`reglas_version`) es la misma y el chat sigue resuelto (comparando `status`/`last_activity_at` del listado). Si no, se reevalúa. La **decisión del manager es por conversación**: se muestra la más reciente en cualquier revisión donde aparezca el chat. Para entrenar el modelo, cada etiqueta se toma una sola vez por conversación (la más reciente).
4. **Agente responsable.** Se usa el agente que tenía el chat asignado cuando ocurrió el problema, deducido de los mensajes de asignación con la lógica de `periodo_agente`/`_asignado_a`. Si eso no se puede deducir, se toma el asignado actual. «Sin atención» sin ningún agente queda como «Sin asignar» (filtrable).
5. **Bots y mensajes automáticos.** No cuentan como respuesta del agente. Solo cuentan los mensajes salientes, públicos y con `sender.type` de persona (`user`). El builder debe verificar en datos reales cómo vienen AgentBot y los mensajes automáticos fuera de horario. Esto se hace con un helper propio, sin cambiar `_es_respuesta_agente`, que lo usan otras herramientas.
6. **Modo prueba con más de 30 chats.** Toma los primeros 30 que devuelva el listado y deja de listar en cuanto los tiene. La pantalla avisa «Resultado parcial: 30 de al menos N chats». En modo prueba el rango máximo es **12 h**, para que quepa en una sola petición.
7. **CSAT.** Al empezar la revisión se hace **una** llamada a `respuestas_csat(since, until_extendido)` (método que ya existe), se guarda en la revisión un mapa conversación → puntuación y la regla lo consulta. Si la llamada falla, la regla se omite y la vista lo avisa.

## Lo que queda al builder

- Nombres exactos de funciones, la forma del JSON de `incidencias` y del prompt de IA.
- Cómo compartir `_listar_bandejas` sin cambiar el comportamiento de Auditoría de chats.
- Cómo guardar el contador del cupo de IA.
- Detalles visuales siguiendo el admin actual (`ui-ux-pro-max` para la vista), con revisión en desktop y ventana angosta.
- Pruebas: reglas (tabla de casos por regla), motor con fakes, rutas principales.

## Fase siguiente (fuera de v1)

Con suficientes decisiones «atendida / no es incidencia» guardadas, entrenar un clasificador propio (por ejemplo TF-IDF + modelo lineal) y evaluar si entra en Vercel. Las reglas y la IA quedan como respaldo.
