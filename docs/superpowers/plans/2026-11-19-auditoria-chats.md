# Auditoría de chats — plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Herramienta «Auditoría de chats» que toma chats aleatorios de Chatwoot por agente y rango, los audita con IA (Groq por defecto) y permite revisión humana, con historial en Supabase.

**Architecture:** Blueprint Flask nuevo con lógica en módulos pequeños de `utils/`: conector IA compatible con OpenAI, transcripción/anonimización, pauta y validación, almacén (Supabase + memoria para pruebas) y un motor que avanza los lotes **un paso por petición**. Plantillas Jinja + `static/auditoria_chats.js` para repetir pasos sin scripts en línea.

**Tech Stack:** Python 3, Flask, Jinja, `requests`, `supabase` (ya en `requirements.txt`), pytest.

**Spec:** `docs/superpowers/specs/2026-11-19-auditoria-chats-design.md` (leerlo entero antes de empezar; manda sobre este plan si hay duda).

## Global Constraints

- Sin dependencias nuevas. Sin React/Vue/SPA/Tailwind/Bootstrap.
- Textos de UI, nombres y mensajes en español.
- Sin `<script>` en línea, sin `onclick`/`onload`/`onerror`, sin `style=""` en plantillas nuevas (CSP pendiente).
- Estilos en `static/styles.css`; al cambiarlo subir `ASSET_VERSIONS["styles.css"]` de `"23"` a `"24"` en `app.py`; añadir `"auditoria_chats.js": "1"`.
- Secretos solo en el backend; nunca en plantillas ni en respuestas JSON.
- Variables nuevas: `AUDITORIA_CHATS_AI_BASE_URL` (defecto `https://api.groq.com/openai/v1`), `AUDITORIA_CHATS_AI_MODEL` (defecto `openai/gpt-oss-120b`), `AUDITORIA_CHATS_AI_API_KEY` → `.env.example` y `README.md`.
- Las pruebas no hacen red ni tocan Supabase real; añadir `"AUDITORIA_CHATS_"` a `PREFIJOS_DE_CONFIGURACION_REAL` en `tests/conftest.py`.
- Toda tabla dentro de `.table-wrap`. Revisar escritorio y ancho móvil.
- Respetar el final de línea de cada archivo existente (`git -c core.autocrlf=true`). Commits en español con prefijo `feat:`/`test:`. No hacer push.
- Pauta: `PAUTA_VERSION = "1"`; 7 criterios 1–5: `saludo`, `comprension`, `exactitud`, `resolucion`, `tono`, `tiempos`, `cierre`.
- Defectos de lote: 10 chats por agente, máximo 20; rango por defecto lunes–domingo de la semana anterior en `CHATWOOT_TIMEZONE`.
- Cola de revisión: `nota_global <= 3`, `satisfaccion_cliente == "insatisfecho"`, `confianza == "baja"` o `error` → `motivo_revision="marcado"`; del resto, 10 % al azar (mínimo 1 por lote si hay ≥1 auditado no marcado) → `"control"`.
- Transcripción a la IA: máximo 6.000 caracteres (si excede, inicio y final con `[…]` en medio).
- Máximo 2 intentos de IA por chat; luego `estado="error"`.

## Review Focus

1. Agente sin chats en el rango (o menos de N) → el lote sigue con los que haya y lo indica por agente; no falla.
2. Conversación sin mensajes del agente o solo con notas privadas/actividad → se descarta en el muestreo, no se manda a la IA.
3. La IA devuelve JSON con campos faltantes, valores fuera de 1–5 o texto con ```json → se valida, se reintenta una vez y queda `error` con mensaje legible.
4. Groq 429 por minuto frente a 429 por día → el primero devuelve `esperar_segundos` y el navegador reintenta; el segundo deja el lote en `limite_diario` y se puede retomar después.
5. Dos pestañas pulsando «Procesar» a la vez sobre el mismo lote → no se audita el mismo chat dos veces ni se duplican filas (paso toma el siguiente pendiente y marca `procesando` antes de llamar a la IA; `conversation_id` único).

---

### Task 1: Conector de IA compatible con OpenAI

**Files:**
- Create: `utils/ia_chat.py`
- Modify: `tests/conftest.py` (prefijo `AUDITORIA_CHATS_`), `.env.example`, `README.md`
- Test: `tests/test_ia_chat.py`

**Interfaces:**
- Produces:
  - `class IAConfigError(Exception)`, `class IARateLimitError(Exception)` con atributos `esperar_segundos: int` y `diario: bool`, `class IARespuestaError(Exception)`.
  - `obtener_config_ia() -> dict` con claves `base_url`, `model`, `api_key`, `activa: bool` (activa = hay clave).
  - `completar_json(mensajes: list[dict], config: dict, timeout: int = 40) -> dict` — `POST {base_url}/chat/completions` con `model`, `messages`, `temperature: 0.1`, `response_format: {"type": "json_object"}`, cabecera `Authorization: Bearer`. Devuelve el JSON parseado del contenido del primer mensaje (quita cercas ```json si las hay).

- [ ] **Step 1: Write failing tests** en `tests/test_ia_chat.py` usando `monkeypatch` sobre `requests.post` (respuesta falsa):
  - `test_config_por_defecto_groq`: sin variables → `base_url == "https://api.groq.com/openai/v1"`, `model == "openai/gpt-oss-120b"`, `activa is False`.
  - `test_completar_json_envia_payload_y_parsea`: verifica URL `.../chat/completions`, `response_format`, Bearer, y que `{"choices":[{"message":{"content":"```json\n{\"a\":1}\n```"}}]}` → `{"a": 1}`.
  - `test_sin_clave_lanza_config_error`.
  - `test_401_lanza_config_error_legible` (mensaje menciona `AUDITORIA_CHATS_AI_API_KEY`).
  - `test_429_por_minuto`: cabecera `retry-after: 7`, cuerpo sin "day" → `IARateLimitError(esperar_segundos=7, diario=False)`.
  - `test_429_por_dia`: cuerpo con `"tokens per day"` (o `TPD`) → `diario=True`.
  - `test_contenido_no_json_lanza_respuesta_error`.
- [ ] **Step 2:** `python -m pytest tests/test_ia_chat.py -v` → FAIL (módulo no existe).
- [ ] **Step 3:** Implementar `utils/ia_chat.py`. Detección diario: `"per day"`, `"tokens per day"` o `"TPD"` en el texto de error (sin distinguir mayúsculas). `esperar_segundos` desde `retry-after` (defecto 20). Añadir prefijo en conftest y las 3 variables en `.env.example` y en la tabla de variables del `README.md` (con nota de activar Zero Data Retention en Groq).
- [ ] **Step 4:** `python -m pytest tests/test_ia_chat.py tests/test_aislamiento_pruebas.py -v` → PASS.
- [ ] **Step 5:** Commit `feat: conector de IA compatible con OpenAI para auditoría de chats`.

### Task 2: Chatwoot — conversaciones, mensajes y transcripción

**Files:**
- Modify: `utils/chatwoot_reportes.py` (solo añadir métodos a `ChatwootClient`)
- Create: `utils/auditoria_chats_transcripcion.py`
- Test: `tests/test_auditoria_chats_transcripcion.py`, añadir casos en `tests/test_chatwoot_reportes.py`

**Interfaces:**
- Produces en `ChatwootClient`:
  - `post(path: str, json: dict, params: dict | None = None) -> dict` (mismo manejo de errores que `get`).
  - `conversaciones_de_agente(agente_id: int, since: int, until: int, page: int = 1) -> list[dict]` — `POST /api/v1/accounts/{id}/conversations/filter?page=N` con payload `{"payload": [{"attribute_key": "assignee_id", "filter_operator": "equal_to", "values": [agente_id], "query_operator": "and"}, {"attribute_key": "created_at", "filter_operator": "is_greater_than", "values": [<fecha since YYYY-MM-DD>], "query_operator": "and"}, {"attribute_key": "created_at", "filter_operator": "is_less_than", "values": [<fecha until+1 día>]}]}`; devuelve la lista normalizada de `data.payload`. Además filtra en Python por `created_at` (epoch) dentro de `[since, until]` como red de seguridad.
  - `mensajes_de_conversacion(conversation_id: int, max_paginas: int = 5) -> list[dict]` — `GET .../conversations/{cid}/messages`, pagina con `before=<id más antiguo>` hasta vacío o `max_paginas`; orden ascendente por `created_at`.
  - `url_conversacion(conversation_id: int) -> str` → `{base_url}/app/accounts/{account_id}/conversations/{cid}`.
- Produces en `utils/auditoria_chats_transcripcion.py`:
  - `anonimizar(texto: str) -> str` — correos → `[correo]`, teléfonos (≥7 dígitos con espacios/guiones/+/paréntesis) → `[teléfono]`, números de ≥8 dígitos seguidos → `[número]`.
  - `mensajes_utiles(mensajes: list[dict]) -> list[dict]` — solo `message_type` 0 (entrante) y 1 (saliente), descarta `private: true` y contenido vacío.
  - `tiene_mensajes_de_agente(mensajes: list[dict]) -> bool`.
  - `construir_transcripcion(mensajes: list[dict], tz_name: str, max_chars: int = 6000) -> str` — líneas `[HH:MM] Cliente: …` / `[HH:MM] Agente: …`, anonimizadas; si excede, primera mitad + `\n[…]\n` + última mitad.

- [ ] **Step 1: Write failing tests**:
  - `test_anonimizar_correo_telefono_numero`: `"Escribe a ana@x.com o al +58 412-555-1234, cédula 12345678"` → contiene `[correo]`, `[teléfono]`, `[número]` y no los originales.
  - `test_mensajes_utiles_descarta_privados_y_actividad` (tipos 2 y 3, `private: True`).
  - `test_construir_transcripcion_formato_y_hora` con `America/Caracas`.
  - `test_construir_transcripcion_recorta_a_6000` → `len <= 6000 + len("\n[…]\n")` y contiene `[…]`.
  - En `test_chatwoot_reportes.py`: `test_conversaciones_de_agente_usa_filter_y_filtra_rango` (monkeypatch `requests.post`; incluye una conversación fuera de rango que se descarta) y `test_mensajes_de_conversacion_pagina_con_before` (dos páginas y una vacía).
- [ ] **Step 2:** Ejecutar ambos archivos → FAIL.
- [ ] **Step 3:** Implementar. Reutilizar `_obtener_timezone` y `_normalizar_lista_respuesta` existentes. No cambiar firmas existentes.
- [ ] **Step 4:** `python -m pytest tests/test_auditoria_chats_transcripcion.py tests/test_chatwoot_reportes.py tests/test_reporte_agentes.py -v` → PASS.
- [ ] **Step 5:** Commit `feat: lectura de conversaciones y transcripción anonimizada de Chatwoot`.

### Task 3: Pauta, mensajes para la IA y validación

**Files:**
- Create: `utils/auditoria_chats_pauta.py`
- Test: `tests/test_auditoria_chats_pauta.py`

**Interfaces:**
- Produces:
  - `PAUTA_VERSION = "1"`, `CRITERIOS: list[tuple[str, str]]` (clave, etiqueta en español) con las 7 claves de Global Constraints.
  - `SATISFACCION = ("satisfecho", "neutral", "insatisfecho", "no_se_puede_saber")`, `RESUELTO = ("si", "no", "parcial")`, `CONFIANZA = ("alta", "media", "baja")`.
  - `construir_mensajes(transcripcion: str, agente_nombre: str) -> list[dict]` — `system` con la pauta, descripción de cada criterio y el esquema JSON exacto a devolver; `user` con la transcripción. Indicar que juzgue solo al agente y que `evidencias` sean citas literales cortas (≤ 20 palabras, máximo 3).
  - `validar_resultado(data: dict) -> dict` — devuelve dict normalizado con `criterios: dict[str,int]`, `nota_global: int`, `satisfaccion_cliente`, `resuelto`, `resumen`, `fortalezas: list[str]`, `mejoras: list[str]`, `evidencias: list[str]`, `confianza`; lanza `ValueError` con mensaje en español si falta algo o está fuera de rango. Acepta números como texto (`"4"`) y normaliza mayúsculas/acentos en enumerados (`"Sí"` → `"si"`).
  - `requiere_revision(resultado: dict | None, hubo_error: bool) -> bool` — reglas de Global Constraints.

- [ ] **Step 1: Write failing tests**: resultado válido completo pasa; `nota_global: 6` → `ValueError`; criterio faltante → `ValueError`; `"Sí"`/`"4"` normalizan; `requiere_revision` verdadero para nota 3, insatisfecho, confianza baja y error; falso para nota 4 satisfecho confianza alta; `construir_mensajes` contiene las 7 claves y `PAUTA_VERSION`.
- [ ] **Step 2:** Ejecutar → FAIL.
- [ ] **Step 3:** Implementar.
- [ ] **Step 4:** `python -m pytest tests/test_auditoria_chats_pauta.py -v` → PASS.
- [ ] **Step 5:** Commit `feat: pauta y validación de la auditoría de chats`.

### Task 4: Almacén (Supabase + memoria) y SQL

**Files:**
- Create: `supabase_chat_audits.sql`, `utils/auditoria_chats_store.py`
- Test: `tests/test_auditoria_chats_store.py`

**Interfaces:**
- Produces:
  - SQL con tablas `chat_audit_batches` y `chat_audits` con las columnas del spec (sección Supabase + `intentos int default 0`, `transcripcion_tmp text`, estado de fila también `procesando` y `leido`), `conversation_id bigint unique`, `batch_id uuid references chat_audit_batches(id) on delete cascade`, índices por `batch_id` y `agente_id`, RLS activado sin políticas (solo service role), igual estilo que `supabase_work_shift_state.sql`.
  - `class AuditoriaChatsError(Exception)`, `class AuditoriaChatsConfigError(AuditoriaChatsError)`.
  - Protocolo común implementado por `SupabaseAuditoriaStore` (patrón de `utils/break_admin_store.py`, `from_env()`) y `MemoriaAuditoriaStore` (para pruebas):
    - `crear_lote(datos: dict) -> dict` · `obtener_lote(lote_id: str) -> dict | None` · `actualizar_lote(lote_id: str, cambios: dict) -> dict` · `listar_lotes(limite: int = 20) -> list[dict]` · `borrar_lote(lote_id: str) -> None`
    - `conversaciones_auditadas(ids: list[int]) -> set[int]`
    - `insertar_chats(filas: list[dict]) -> int` (ignora duplicados por `conversation_id`, devuelve insertados)
    - `tomar_siguiente(lote_id: str, estados: tuple[str, ...], nuevo_estado: str) -> dict | None` — toma la fila más antigua en esos estados y la pasa a `nuevo_estado` de forma condicional (`update … where id = X and estado = <anterior>`; si no actualizó ninguna fila, intenta la siguiente) para evitar doble proceso.
    - `actualizar_chat(chat_id: str, cambios: dict) -> dict` · `obtener_chat(chat_id: str) -> dict | None` · `listar_chats(lote_id: str) -> list[dict]`
    - `chats_para_historial(desde_iso: str) -> list[dict]`
  - `obtener_store()` en el mismo módulo: devuelve `SupabaseAuditoriaStore.from_env()`; las pruebas lo sustituyen con monkeypatch.

- [ ] **Step 1: Write failing tests** sobre `MemoriaAuditoriaStore`: crear/obtener/listar lote; `insertar_chats` ignora `conversation_id` repetido; `tomar_siguiente` no devuelve la misma fila dos veces seguidas; `borrar_lote` elimina sus chats y libera `conversation_id`; `conversaciones_auditadas`. Un test de `SupabaseAuditoriaStore` con cliente falso que verifique que `tomar_siguiente` filtra por estado anterior en el update.
- [ ] **Step 2:** Ejecutar → FAIL.
- [ ] **Step 3:** Implementar ambos almacenes y el SQL.
- [ ] **Step 4:** `python -m pytest tests/test_auditoria_chats_store.py -v` → PASS.
- [ ] **Step 5:** Commit `feat: almacén de auditorías de chats en Supabase`.

### Task 5: Motor de lotes (muestreo y pasos)

**Files:**
- Create: `utils/auditoria_chats_motor.py`
- Test: `tests/test_auditoria_chats_motor.py`

**Interfaces:**
- Consumes: Tasks 1–4; `obtener_turnos_configurados()` de `utils/turnos_trabajo_store.py`; `_indice_agentes` y `ChatwootClient.listar_agentes()`.
- Produces:
  - `rango_semana_anterior(hoy: date, tz_name: str) -> tuple[date, date]`.
  - `resolver_agentes(alcance: str, detalle: dict, agentes_chatwoot: list[dict], turnos: dict[str, list[str]]) -> tuple[list[dict], list[str]]` — `alcance` ∈ `todos`/`turno`/`agentes`; devuelve `[{"id": int, "nombre": str, "turno": str | None}]` y lista de nombres de turno sin cruce (aviso). Cruce por nombre normalizado (minúsculas, sin acentos, espacios simples).
  - `crear_lote(store, *, since: date, until: date, alcance: str, detalle: dict, chats_por_agente: int, agentes: list[dict], config_ia: dict) -> dict` — limita `chats_por_agente` a 1–20; guarda `estado="muestreando"`, `agentes`, `agentes_muestreados=[]`, `modelo`, `pauta_version`.
  - `ejecutar_paso(store, lote_id: str, chatwoot, config_ia: dict, rng: random.Random | None = None) -> dict` — devuelve `{"estado": str, "accion": str, "mensaje": str, "esperar_segundos": int, "progreso": {"total": int, "auditados": int, "errores": int, "pendientes": int}}`. Orden:
    1. Si quedan agentes sin muestrear: muestrea **uno** (páginas de `conversaciones_de_agente` hasta 10 páginas o fin), excluye `conversaciones_auditadas`, mezcla con `rng`, recorre leyendo mensajes hasta juntar N con `tiene_mensajes_de_agente`, como máximo `N*3` lecturas; inserta filas `pendiente`. Si es el último agente, pasa el lote a `auditando`. `accion="muestreo"`.
    2. Si hay fila `pendiente`: `tomar_siguiente(..., ("pendiente",), "procesando")`, lee mensajes, guarda `transcripcion_tmp`, estado `leido`. `accion="lectura"`.
    3. Si hay fila `leido`: `tomar_siguiente(..., ("leido",), "procesando")`, llama a `completar_json(construir_mensajes(...))` y `validar_resultado`. Éxito → `estado="auditado"`, `ia_resultado`, `ia_nota`, `ia_satisfaccion`, `transcripcion_tmp=None`, `por_revisar`/`motivo_revision="marcado"` según `requiere_revision`. `ValueError`/`IARespuestaError` → `intentos+1`; si `< 2` vuelve a `leido`, si no `estado="error"`, `ia_error`, `transcripcion_tmp=None`, `por_revisar=True`. `IARateLimitError` → fila vuelve a `leido`; si `diario`, lote `limite_diario` y `esperar_segundos=0`; si no, `esperar_segundos` del error. `accion="auditoria"`.
    4. Sin nada pendiente: asigna muestra de control (Global Constraints) con `rng`, lote `completado` (o `con_errores` si hay errores). `accion="fin"`.
    - Un lote en `limite_diario` vuelve a `auditando` al primer paso que se ejecute.
    - Antes de elegir qué hacer, las filas `procesando` con `updated_at` de hace más de 120 s (petición cortada por Vercel) vuelven a `leido` si tienen `transcripcion_tmp`, o a `pendiente` si no.
    - Sin `config_ia["activa"]`: el muestreo y la lectura funcionan; el paso de auditoría devuelve `mensaje` de configuración sin tocar filas.
  - `nota_efectiva(chat: dict) -> int | None` — `nota_final` si no es `None`, si no `ia_nota`.
  - `resumen_por_agente(chats: list[dict]) -> list[dict]` — por agente: `chats`, `nota_ia_media`, `nota_efectiva_media`, `pct_satisfechos` (usa `satisfaccion_final` o `ia_satisfaccion`), `por_revisar`, `revisados`.
  - `historial_semanal(chats: list[dict], tz_name: str) -> list[dict]` — por agente y semana ISO (`conversacion_fecha`): `nota_efectiva_media`, `chats`, `pct_revisado`.
  - `filas_csv(lote: dict, chats: list[dict]) -> tuple[list[str], list[list]]` — columnas: conversación, enlace, agente, turno, fecha, estado, nota IA, satisfacción IA, resuelto, 7 criterios, nota final, satisfacción final, revisor, comentario, resumen IA.

- [ ] **Step 1: Write failing tests** con `MemoriaAuditoriaStore`, un `ChatwootFalso` (agentes, conversaciones por agente, mensajes) e IA simulada con monkeypatch sobre `utils.auditoria_chats_motor.completar_json`:
  - `test_rango_semana_anterior` (miércoles 2026-11-19 → 2026-11-09 a 2026-11-15).
  - `test_resolver_agentes_por_turno_y_aviso_sin_cruce`.
  - `test_lote_completo_dos_agentes` → recorre `ejecutar_paso` hasta `accion=="fin"`; 2×N filas `auditado`; ninguna conserva `transcripcion_tmp`.
  - `test_muestreo_excluye_ya_auditados_y_sin_mensajes_de_agente`.
  - `test_agente_con_menos_chats_que_n` no falla.
  - `test_json_invalido_reintenta_una_vez_y_luego_error`.
  - `test_429_minuto_devuelve_espera_y_no_pierde_fila` y `test_429_diario_pone_lote_en_limite_diario_y_se_retoma`.
  - `test_muestra_control_10_por_ciento_minimo_uno` con `random.Random(1)`.
  - `test_fila_procesando_abandonada_se_recupera` (fila `procesando` con `updated_at` de hace 5 min).
  - `test_nota_efectiva_y_resumen` y `test_historial_semanal`.
- [ ] **Step 2:** Ejecutar → FAIL.
- [ ] **Step 3:** Implementar.
- [ ] **Step 4:** `python -m pytest tests/test_auditoria_chats_motor.py -v` → PASS.
- [ ] **Step 5:** Commit `feat: motor de lotes de auditoría de chats`.

### Task 6: Herramienta web — lotes, pasos y navegación

**Files:**
- Create: `tools/auditoria_chats.py`, `templates/auditoria_chats.html`, `templates/auditoria_chats_lote.html`, `static/auditoria_chats.js`
- Modify: `app.py` (registro + `ASSET_VERSIONS`), `utils/navegacion.py`, `templates/inicio.html` si las tarjetas no salen del catálogo, `static/styles.css`, `tests/test_navegacion_responsive.py` (10 → 11 enlaces, `/auditoria-chats/` en rutas, `styles.css?v=24`)
- Test: `tests/test_auditoria_chats.py`

**Interfaces:**
- Consumes: Task 5 (`crear_lote`, `ejecutar_paso`, `resumen_por_agente`, `resolver_agentes`, `rango_semana_anterior`), Task 4 (`obtener_store`), Task 1 (`obtener_config_ia`).
- Produces: `auditoria_chats_bp = Blueprint("auditoria_chats", __name__)` con endpoints:
  - `index` → `GET /auditoria-chats/`: formulario (fechas con defecto semana anterior, alcance con selector de turno y lista de agentes con casillas, chats por agente), lotes recientes, estado de configuración (Chatwoot / IA / Supabase, sin mostrar valores), aviso de privacidad («El texto de los chats se envía al proveedor de IA configurado; correos y teléfonos se ocultan»).
  - `crear` → `POST /auditoria-chats/lotes` → redirect a `ver_lote`.
  - `ver_lote` → `GET /auditoria-chats/lote/<lote_id>`: barra de avance, estado (incluido «Límite diario de la IA alcanzado; retoma mañana»), resumen por agente, cola de revisión, botones «Procesar siguiente» (form POST) y «Procesar lote»/«Pausar» (solo con JS).
  - `paso` → `POST /auditoria-chats/lote/<lote_id>/paso`: con `Accept: application/json` devuelve el dict de `ejecutar_paso`; sin JS, redirect a `ver_lote` con flash del mensaje.
  - Catálogo: `{"endpoint": "auditoria_chats.index", "grupo": "Calidad", "titulo": "Auditoría de chats", "icono": "calidad", "descripcion": "Audita con IA chats aleatorios de cada agente y deja la revisión final a una persona.", "destacada": False}` después de Auditoría CSAT.
- `static/auditoria_chats.js`: en la página del lote, botón `[data-procesar-lote]` llama a `paso` en bucle con `fetch` (POST, `Accept: application/json`), actualiza `[data-progreso]` y el texto de estado, espera `esperar_segundos` cuando venga > 0, se detiene en `fin`, `limite_diario`, error HTTP o «Pausar»; al terminar recarga la página. Sin JS, el formulario «Procesar siguiente» funciona.
- Si Supabase no está configurado: `index` muestra aviso y desactiva el formulario; `crear` y `paso` responden con mensaje de error, nunca 500.

- [ ] **Step 1: Write failing tests** en `tests/test_auditoria_chats.py` con `monkeypatch` de `tools.auditoria_chats.obtener_store` → `MemoriaAuditoriaStore`, Chatwoot falso y IA simulada:
  - `test_index_muestra_formulario_y_aviso_privacidad`.
  - `test_index_sin_supabase_muestra_aviso_y_no_falla` (sin monkeypatch de store, variables vacías → 200 y texto de aviso).
  - `test_crear_lote_redirige_y_lo_guarda`.
  - `test_paso_json_devuelve_progreso` y `test_paso_sin_js_redirige`.
  - `test_html_sin_scripts_en_linea_ni_style` (las plantillas nuevas no contienen `<script>` sin `src`, ` onclick=`, ` style="`).
  - `test_no_expone_clave_ia` (con `AUDITORIA_CHATS_AI_API_KEY=clave-secreta-prueba`, ni el HTML ni el JSON la contienen).
- [ ] **Step 2:** Ejecutar → FAIL.
- [ ] **Step 3:** Implementar blueprint, plantillas (extienden `base.html`, paneles y `.table-wrap` del sistema v23), JS, estilos mínimos en `styles.css`, registro en `app.py`, catálogo y ajuste de `test_navegacion_responsive.py`.
- [ ] **Step 4:** `python -m pytest -q` → todo PASS (salvo pruebas de navegador omitidas por falta de Playwright). `python -m pyflakes app.py tools/*.py utils tests` → sin avisos.
- [ ] **Step 5:** Commit `feat: herramienta de auditoría de chats (lotes y procesamiento)`.

### Task 7: Revisión humana, historial, CSV y borrado

**Files:**
- Create: `templates/auditoria_chats_chat.html`, `templates/auditoria_chats_historial.html`
- Modify: `tools/auditoria_chats.py`, `static/auditoria_chats.js`, `static/styles.css` (si hace falta; la versión ya quedó en `"24"` en Task 6 y no se vuelve a subir en esta rama; sí subir `auditoria_chats.js` a `"2"`), `README.md` (sección de la herramienta y pasos: ejecutar `supabase_chat_audits.sql`, crear clave en Groq, activar Zero Data Retention)
- Test: `tests/test_auditoria_chats.py`

**Interfaces:**
- Consumes: Task 5 (`nota_efectiva`, `historial_semanal`, `filas_csv`), Task 2 (`mensajes_de_conversacion`, `mensajes_utiles`, `url_conversacion`).
- Produces endpoints:
  - `ver_chat` → `GET /auditoria-chats/chat/<chat_id>`: transcripción leída en vivo (mensajes útiles, sin anonimizar, porque la ve el admin) a la izquierda o arriba; resultado IA (criterios, nota, satisfacción, resuelto, resumen, fortalezas, mejoras, evidencias, confianza, error si hubo) y enlace «Abrir en Chatwoot»; formulario de revisión: `revisor` (texto, recordado con `localStorage` desde el JS, con try/catch), `nota_final` (1–5), `satisfaccion_final`, `comentario_revisor`. Enlace al siguiente chat por revisar del lote.
  - `revisar` → `POST /auditoria-chats/chat/<chat_id>`: valida, guarda `estado="revisado"`, `revisado_at`, redirige al siguiente por revisar o al lote.
  - `reintentar` → `POST /auditoria-chats/chat/<chat_id>/reintentar`: solo si `estado="error"`; pone `estado="pendiente"`, `intentos=0`, `ia_error=None`, y el lote a `auditando`.
  - `exportar_csv` → `GET /auditoria-chats/lote/<lote_id>/csv` con `filas_csv`, UTF-8 con BOM, nombre `auditoria_chats_<since>_<until>.csv`.
  - `borrar_lote` → `POST /auditoria-chats/lote/<lote_id>/borrar` con el diálogo de confirmación existente (`data-confirm`/patrón de `app.js` que ya usan otras acciones destructivas).
  - `historial` → `GET /auditoria-chats/historial`: últimas 8 semanas, tabla agente × semana con nota efectiva media y % revisado.

- [ ] **Step 1: Write failing tests**: `test_ver_chat_muestra_resultado_ia_y_formulario`; `test_revisar_guarda_y_redirige_al_siguiente`; `test_revisar_rechaza_nota_fuera_de_rango`; `test_reintentar_solo_en_error`; `test_csv_columnas_y_bom`; `test_borrar_lote_libera_conversaciones`; `test_historial_usa_nota_efectiva`; `test_borrar_tiene_confirmacion` (el form lleva el atributo de confirmación usado por `app.js`).
- [ ] **Step 2:** Ejecutar → FAIL.
- [ ] **Step 3:** Implementar.
- [ ] **Step 4:** `python -m pytest -q` y `python -m pyflakes app.py tools/*.py utils tests` → PASS.
- [ ] **Step 5:** Validación manual (con `venv` recreado y `.env` con Chatwoot, Supabase y clave de Groq): crear un lote pequeño (1 agente × 2 chats), procesarlo con «Procesar lote» y con «Procesar siguiente», revisar un chat, exportar CSV, ver historial; comprobar en escritorio y a 375 px que no hay desbordamiento horizontal y que la navegación sigue bien.
- [ ] **Step 6:** Commit `feat: revisión humana, historial y exportación en auditoría de chats`.
