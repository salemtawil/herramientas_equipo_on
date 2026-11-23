# Llamadas de Multiadmin e informe PDF — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Traer las llamadas ya analizadas en Multiadmin de los agentes del lote, resumirlas con IA por agente, mostrarlas junto al feedback de mensajes y generar un informe PDF imprimible con logo.

**Architecture:** Cliente HTTP de Multiadmin (reusa el token de `tools/api_multiadmin.py`), módulo `utils/auditoria_llamadas.py` (normalización, emparejamiento, resumen con IA), pasos nuevos en el motor con estado propio de llamadas, dos tablas nuevas en Supabase y una página de informe con hoja de impresión.

**Tech Stack:** Flask, Jinja, Supabase, Gemini (API compatible OpenAI vía `utils/ia_chat.py`), pytest. Sin dependencias nuevas.

**Spec:** `docs/superpowers/specs/2026-11-23-auditoria-llamadas-e-informe-design.md`

## Global Constraints

- Solo llamadas de **los agentes del lote** y **en las fechas del lote**; nunca se guardan otras.
- No se excluyen llamadas sin conversación: se etiquetan `sin_conversacion` (< 60 s o motivo con buzón/contestadora/«no estaba disponible»/«sin conversación»/accidental).
- Nunca se guardan `customerNumber` ni transcripción; los textos de Multiadmin pasan por `anonimizar`.
- No se escribe nada en Multiadmin (solo GET).
- Puntaje de llamadas y QA de chats nunca se combinan en un número.
- Proyecto único `compinche`; base URL `MULTIADMIN_ADMIN_API_URL` (por defecto `https://admin-api.compi.sh`).
- Solo lotes `pauta_version == "QA-1.1"` tienen llamadas e informe.
- CSP: sin scripts en línea, sin `style=""`, sin `onclick`. Subir `ASSET_VERSIONS` si cambian CSS/JS (`styles.css` 27→28, `auditoria_chats.js` 4→5; actualizar tests de versión).
- Commits en español (`feat:`/`fix:`), `git -c core.autocrlf=true`, sin push sin permiso. `python -m pytest` con el Python global.

## Review Focus

1. Un agente de Chatwoot con dos números de Multiadmin: las llamadas de ambos números se asignan a ese agente.
2. Multiadmin falla (401/5xx) a mitad de traer días: `llamadas_estado = error`, los chats siguen y «Traer llamadas» reanuda.
3. El resumen de la IA cita tickets que no están entre las llamadas del agente: se descartan.
4. Llamadas de agentes no seleccionados en el rango: no se guardan; solo cuentan en `llamadas_sin_emparejar` si su número no está emparejado con nadie del lote.
5. El HTML del informe y de la página del lote no contiene teléfonos de clientes.

---

### Task 1: Cliente de llamadas de Multiadmin y verificación real

**Files:**
- Create: `utils/multiadmin_llamadas.py`
- Test: `tests/test_multiadmin_llamadas.py`

**Interfaces:**
- Produces:
  - `MultiadminLlamadasError(Exception)`
  - `listar_llamadas(desde_ms: int, hasta_ms: int, sesion=requests) -> list[dict]` — GET `{base}/projects/compinche/call-analysis?startDate=..&endDate=..`; sigue paginación si la respuesta trae `cursor`/`nextCursor` (enviarlo como `cursor`); 401/403 → reintenta una vez con token renovado; otros errores → `MultiadminLlamadasError` con mensaje en español sin el token.
  - `listar_agentes_llamadas(sesion=requests) -> list[dict]` — `[{agent_number, nombre}]` desde `.../call-analysis/admins`.
  - Headers: los de `api_multiadmin._headers_multiadmin(token)` con `origin`/`referer` `https://admin.compi.sh`.

- [ ] **Step 1 (bloqueante, usuario):** pedir al usuario que ejecute `tools/renovar_tokens_multiadmin.bat` para tener `MULTIADMIN_ID_TOKEN`/`MULTIADMIN_REFRESH_TOKEN` en el `.env` local. Luego un script en el scratchpad llama a `listar_llamadas` (últimas 48 h) y a `listar_agentes_llamadas` e imprime **solo la forma** (claves y tipos, nunca valores). Anotar en el ledger la forma real de `rubric`, `coaching`, `keyPoints`, la paginación y las claves de `admins`. Si el token de la app no sirve para `admin-api.compi.sh`, parar y avisar al usuario.
- [ ] **Step 2: Tests** con una sesión falsa: fechas en ms en la URL; paginación con cursor (2 páginas → items concatenados); 401 → renueva y reintenta una vez; 500 → `MultiadminLlamadasError` sin el token en el mensaje; agentes normalizados.
- [ ] **Step 3:** FAIL → implementar → PASS (`python -m pytest tests/test_multiadmin_llamadas.py -q`).
- [ ] **Step 4:** Commit `feat: cliente de análisis de llamadas de Multiadmin`.

### Task 2: Normalización, emparejamiento y almacenamiento

**Files:**
- Create: `utils/auditoria_llamadas.py`, `tests/test_auditoria_llamadas.py`
- Modify: `utils/auditoria_chats_store.py`, `supabase_chat_audits.sql`, `tests/test_auditoria_chats_store.py`

**Interfaces:**
- Consumes: forma real anotada en Task 1.
- Produces:
  - `normalizar_llamada(item: dict) -> dict` — campos del spec §1 (`call_id`, `ticket_id`, `agent_number`, `fecha` ISO, `duracion_seg`, `tipo`, `motivo`, `puntaje`, `sentimiento_agente`, `sentimiento_cliente`, `analitica`, `rubrica` [{nombre, peso, pct, justificacion}], `puntos_clave` [{titulo, texto}], `coaching` {aciertos, mejoras, proximas_acciones}, `sin_conversacion`); sin `customerNumber` ni transcripción; textos anonimizados.
  - `es_sin_conversacion(duracion_seg, motivo) -> bool`.
  - `emparejar(agentes_lote: list[{id, nombre}], agentes_multiadmin: list[{agent_number, nombre}], guardados: dict[agent_number, chatwoot_id]) -> dict[agent_number, chatwoot_id]` — guardados ganan; luego nombre normalizado igual; luego nombre de Chatwoot == primer nombre del de Multiadmin y único.
  - Store (ambas clases): `emparejamientos() -> dict[str, dict]`, `guardar_emparejamiento(agent_number, chatwoot_agente_id, nombre, manual: bool)`, `guardar_llamadas(lote_id, filas)` (upsert por `batch_id,call_id`), `listar_llamadas(lote_id) -> list`, `borrar_llamadas(lote_id, agente_id=None)`.
- SQL: tablas `chat_audit_calls` (id uuid, batch_id fk cascade, agente_id bigint, call_id text, ticket_id bigint, agent_number text, fecha timestamptz, duracion_seg int, tipo text, motivo text, puntaje numeric(5,2), sentimiento_agente text, sentimiento_cliente text, sin_conversacion bool, analitica jsonb, rubrica jsonb, puntos_clave jsonb, coaching jsonb, created_at; unique(batch_id, call_id)) y `chat_audit_agentes_llamadas` (agent_number pk, chatwoot_agente_id bigint, nombre_multiadmin text, manual bool default false, updated_at); RLS sin políticas. Columnas en `chat_audit_batches`: `llamadas_estado text default 'pendiente'`, `llamadas_progreso jsonb`, `llamadas_error text`, `feedback_llamadas jsonb`, `llamadas_sin_emparejar jsonb`.

- [ ] **Step 1: Tests**: normalización elimina teléfono y transcripción y anonimiza; `sin_conversacion` por duración y por palabras; emparejar con guardado manual, nombre exacto, primer nombre único, primer nombre ambiguo (no empareja), dos números → mismo agente; store memoria guarda/lista/borra por agente.
- [ ] **Step 2:** FAIL → implementar → PASS.
- [ ] **Step 3:** Commit `feat: normalización y emparejamiento de llamadas`.

### Task 3: Pasos de llamadas en el motor y resumen con IA

**Files:**
- Modify: `utils/auditoria_chats_motor.py`, `utils/auditoria_llamadas.py`
- Test: `tests/test_auditoria_chats_motor.py`, `tests/test_auditoria_llamadas.py`

**Interfaces:**
- Produces:
  - `construir_mensajes_resumen_llamadas(agente_nombre, llamadas: list) -> list[dict]` (límite de texto ~12 000 caracteres, prioriza las de menor puntaje; incluye `sin_conversacion`).
  - `validar_resumen_llamadas(data, tickets_validos: set[int]) -> dict` — `puntos_fuertes`, `areas_mejora`, `recomendaciones` ([{texto, tickets}] máx. 5), `buzon_voz` {evaluacion, tickets} | None, `resumen`; tickets inválidos descartados.
  - Motor: `_paso_llamadas(store, lote, multiadmin, config_ia) -> dict | None` — si `llamadas_estado` ∈ {pendiente, trayendo}: trae el siguiente día (hora local `_timezone()`), empareja, guarda las de agentes del lote, acumula `llamadas_sin_emparejar`; al pasar el último día → `resumiendo`. En `resumiendo` y solo cuando ya no quedan chats pendientes: resume un agente por paso (usa `_llamar_ia`, mismas reglas de 429/diario/temporal/config/reintentos) → `listo` al terminar. Error de Multiadmin → `error` + `llamadas_error`, devuelve respuesta `llamadas` y no bloquea los chats.
  - `ejecutar_paso(..., multiadmin=None)`: en lotes QA, primero `_paso_llamadas` mientras trae; luego chats como hoy; luego el resumen de llamadas; `fin` solo cuando chats terminados y llamadas en `listo`/`error`. `multiadmin` inyectable (por defecto el módulo de Task 1).
  - `reiniciar_llamadas(store, lote_id, agente_id=None)` — vuelve a `pendiente`, borra llamadas (del agente o todas) y su feedback.
  - `resumen_llamadas_por_agente(llamadas) -> list[dict]` — `{agente_id, llamadas, puntaje_medio, sin_conversacion, entrantes, salientes, peores: [5 de menor puntaje], criterios_bajos: [3 ítems de rúbrica de menor promedio]}`.

- [ ] **Step 1: Tests** (store memoria, Multiadmin falso, IA falsa): lote QA de 2 días trae 2 días en 2 pasos y guarda solo llamadas de agentes del lote; número desconocido → `llamadas_sin_emparejar`; Multiadmin 500 → `error` y los chats terminan; resumen descarta tickets inválidos; `fin` solo cuando ambos terminan; cada paso ≤ 1 llamada a la IA; lote v1 no toca llamadas; `reiniciar_llamadas` por agente.
- [ ] **Step 2:** FAIL → implementar → PASS (suite del motor completa).
- [ ] **Step 3:** Commit `feat: llamadas de Multiadmin y su resumen en el motor de lotes`.

### Task 4: Página del lote: llamadas, emparejamiento y feedback en dos bloques

**Files:**
- Modify: `tools/auditoria_chats.py`, `templates/auditoria_chats_lote.html`, `static/styles.css`, `app.py`
- Test: `tests/test_auditoria_chats.py`

**Interfaces:**
- Rutas nuevas: `POST /auditoria-chats/lote/<id>/llamadas` (reiniciar y traer; botón «Traer llamadas»), `POST /auditoria-chats/lote/<id>/emparejar` (form `agent_number`, `agente_id`; guarda manual, `reiniciar_llamadas` del agente).
- `paso` pasa el cliente de Multiadmin a `ejecutar_paso`.
- `ver_lote` (QA) pasa `llamadas_resumen`, `feedback_llamadas`, `llamadas_estado`, `llamadas_sin_emparejar`, `agentes_multiadmin` (solo si hay sin emparejar; error de Multiadmin → aviso).
- Plantilla: sección «Llamadas» (estado, error, botón, tabla por agente con enlaces `#ticket` → `chatwoot.url_conversacion(ticket)`), aviso y formulario de emparejamiento, y en «Feedback por agente» dos bloques «Atención por mensajes» / «Atención por llamadas» (puntos fuertes, áreas de mejora, buzón de voz, recomendaciones, criterios bajos, enlaces por ticket).
- CSS: estilos `.ac-canal*` mínimos; `styles.css` → 28.

- [ ] **Step 1: Tests**: lote QA procesado con Multiadmin e IA falsos muestra «Atención por llamadas», el resumen y enlaces de ticket; no aparece ningún teléfono de cliente; emparejar guarda y reinicia; «Traer llamadas» reinicia; lote v1 sin sección; HTML sin `style="`.
- [ ] **Step 2:** FAIL → implementar → PASS (suite completa).
- [ ] **Step 3:** Commit `feat: llamadas y feedback por canal en la página del lote`.

### Task 5: Informe PDF del lote

**Files:**
- Create: `templates/auditoria_chats_informe.html`, `static/auditoria_informe.css`
- Modify: `tools/auditoria_chats.py`, `templates/auditoria_chats_lote.html`, `static/auditoria_chats.js`, `app.py`
- Test: `tests/test_auditoria_chats.py`

**Interfaces:**
- `GET /auditoria-chats/lote/<id>/informe` (404 si no es QA): plantilla independiente (no extiende `base.html`), enlaza `auditoria_informe.css` con `asset_version`, botón `data-ac-imprimir` (oculto al imprimir) que `auditoria_chats.js` conecta a `window.print()`.
- Contenido: portada (logo `static/informe-logo.svg` si existe, si no `static/system-logos/compinche_48.svg`; título, periodo, agentes, fecha), resumen general, una sección por agente con `page-break-before`, anexo de chats y de llamadas; referencias como enlaces a la ficha del chat y a Chatwoot.
- En la página del lote: botón «Informe PDF».
- Versiones: `auditoria_chats.js` → 5; `auditoria_informe.css` → 1.

- [ ] **Step 1: Tests**: el informe de un lote QA procesado contiene portada, nombre de cada agente, «Atención por mensajes», «Atención por llamadas», el logo y el botón; sin teléfonos; sin scripts en línea ni `style="`; lote v1 → 404.
- [ ] **Step 2:** FAIL → implementar → PASS.
- [ ] **Step 3:** Validación visual: abrir la ruta con datos de prueba en el navegador si hay servidor local; si no, anotarlo.
- [ ] **Step 4:** Commit `feat: informe PDF del lote de auditoría`.

### Task 6: Configuración, documentación y producción

- [ ] **Step 1:** `.env.example` y `README.md`: `MULTIADMIN_ADMIN_API_URL`, cómo se traen las llamadas, emparejamiento e informe.
- [ ] **Step 2:** Aplicar la migración de Task 2 en Supabase (`apply_migration`, `chat_audit_calls_y_llamadas`), verificar columnas, revisar advisors.
- [ ] **Step 3:** Diagnóstico JSON: añadir `llamadas_estado`, `llamadas_error`, conteo de llamadas por agente y `llamadas_sin_emparejar` (sin textos ni teléfonos).
- [ ] **Step 4:** `python -m pytest -q` → PASS. Commit `feat: configuración y documentación de llamadas e informe`. Sin push: preguntar al usuario.
