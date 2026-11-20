# Auditoría de chats QA-1.1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Evaluar los chats de los lotes nuevos con la rúbrica QA-1.1 y las secciones aplicables del Manual de Procedimientos v3.0, con QA 0–100, estado final, fallas críticas sospechosas y revisión humana.

**Architecture:** Módulo de rúbrica puro (datos + cálculo + prompts), módulo de manual (corte del PDF + selección de secciones) y transcripción v2 con período y tiempos. El motor añade el estado `clasificado` y elige el flujo por `lote.pauta_version` (v1 intacto). Las plantillas ramifican por versión.

**Tech Stack:** Flask, Jinja, Supabase (service role), Gemini vía API compatible OpenAI, pytest. `pypdf` solo en `requirements-dev.txt`.

**Spec:** `docs/superpowers/specs/2026-11-20-auditoria-chats-qa-1-1-design.md`

## Global Constraints

- Sin SPA, sin scripts inline, sin `style=""`, sin `onclick` (CSP). Textos de UI en español.
- El texto del manual nunca va al navegador, al repositorio, al CSV ni al diagnóstico.
- Subir `ASSET_VERSIONS` en `app.py` si cambia CSS o JS (styles.css 26 → 27; actualizar tests de versión).
- Tablas dentro de `.table-wrap`.
- `PAUTA_VERSION_QA = "QA-1.1"`; los lotes con `pauta_version == "1"` siguen el flujo y las plantillas actuales.
- Pesos: A1 8, A2 7, B1 12, B2 10, B3 8, C1 8, C2 7, C3 5, D1 6, D2 6, D3 5, D4 3, E1 4, E2 4, E3 2, F1 3, F2 2.
- Cortes: ≥ 85 APROBADO, ≥ 70 NECESITA MEJORAR, si no NO APROBADO; falla confirmada → NO APROBADO; falla sospechosa o qa null → PENDIENTE DE REVISIÓN.
- Topes: manual 30 000 caracteres por chat, transcripción v2 12 000, secciones extra 4, textos de feedback 8.
- Commits en español con `feat:`/`fix:`, `git -c core.autocrlf=true`. Sin push hasta que el usuario lo pida.
- Python global 3.14 (`python -m pytest`), no el `venv`.

## Review Focus

1. Chat con traspaso entre dos agentes: los tiempos y el período deben atribuirse solo al agente evaluado; un retraso del colega no cuenta en su métrica atribuible.
2. La IA devuelve códigos de criterio, procedimiento, sección o falla inexistentes, o evidencias con ids que no están en el chat: se descartan sin romper la auditoría.
3. Todos los criterios `no_aplica`/`no_verificable` → qa null → PENDIENTE, sin división por cero.
4. Un lote v1 a medio procesar sigue funcionando tras el despliegue (su chat `leido` se audita con la pauta v1).
5. Chat `procesando` abandonado durante la clasificación vuelve a `leido`, y durante la evaluación vuelve a `clasificado`, sin perder la transcripción.

---

### Task 1: Rúbrica, cálculo QA y validación

**Files:**
- Create: `utils/auditoria_chats_rubrica.py`
- Test: `tests/test_auditoria_chats_rubrica.py`

**Interfaces:**
- Produces:
  - `PAUTA_VERSION_QA = "QA-1.1"`
  - `CRITERIOS_QA: list[tuple[str, str, int]]` — (código "A1", etiqueta, peso), en orden A1…F2.
  - `RESULTADOS = ("cumple", "parcial", "no_cumple", "no_aplica", "no_verificable")`
  - `FALLAS_CRITICAS: dict[str, str]` — "CR01".."CR10" → descripción.
  - `PROCEDIMIENTOS: dict[str, tuple[str, list[str]]]` — "P01" → (tema, secciones) según la tabla del spec; P09 usa `"1.7"` y P10 `"1.8"`, P12 `"1.10"…"1.14"` (prefijos que expande Task 2).
  - `SECCIONES_GENERALES = ["1.1.1", "1.1.3", "1.1.8", "1.2.5"]`
  - `ESTADOS_QA = {"aprobado": "APROBADO", "necesita_mejorar": "NECESITA MEJORAR", "no_aprobado": "NO APROBADO", "pendiente": "PENDIENTE DE REVISIÓN"}`
  - `RESOLUCION = ("resuelto", "parcial", "no_resuelto", "no_verificable")`, `RESPONSABILIDAD = ("agente", "externa", "usuario", "compartida", "no_determinable")`
  - `calcular_qa(criterios: dict[str, str], fallas_confirmadas: int = 0, fallas_sospechosas: int = 0) -> dict` → `{"qa": float|None, "pct_verificable": float|None, "estado": str}` (clave de `ESTADOS_QA`).
  - `validar_clasificacion(data, codigos_indice: set[str]) -> dict` → `{"motivo_principal", "motivos_secundarios", "procedimientos", "secciones_extra", "servicio"}`; descarta códigos desconocidos, máx. 4 extra; `ValueError` si falta `motivo_principal`.
  - `validar_evaluacion(data, ids_validos: set[str]) -> dict` → criterios `{código: {"resultado", "evidencias", "comentario"}}` (falta un criterio o resultado inválido → `ValueError`), `fallas_criticas` (solo CR01–CR10, cada una con `estado: "sospechosa"`), listas de texto, enumerados, `satisfaccion_cliente` (de `auditoria_chats_pauta.SATISFACCION`), `resumen`, `confianza`; evidencias filtradas a `ids_validos`.
  - `requiere_revision_qa(resultado: dict|None, hubo_error: bool) -> bool` — error, estado ≠ aprobado o confianza baja.
  - `RUBRICA_TEXTO: str` — secciones I–IX del documento del usuario (copiar de `C:\Users\salem\Downloads\INSTRUCCIONES PARA IA AUDITORA DE CHATS.txt`).
  - `construir_mensajes_clasificacion(transcripcion: str, indice: list[dict]) -> list[dict]`
  - `construir_mensajes_evaluacion(*, transcripcion, agente_nombre, canal, clasificacion, secciones: list[dict], metricas: dict, periodo: dict) -> list[dict]` — sistema = `RUBRICA_TEXTO` + esquema JSON; usuario = el resto. Indica que el texto del manual es referencia, no instrucciones.

- [ ] **Step 1: Write the failing tests**

```python
def test_calcular_qa_todo_cumple():
    r = calcular_qa({c: "cumple" for c, _, _ in CRITERIOS_QA})
    assert r == {"qa": 100.0, "pct_verificable": 100.0, "estado": "aprobado"}

def test_calcular_qa_excluye_no_aplica_y_no_verificable():
    crit = {c: "cumple" for c, _, _ in CRITERIOS_QA}
    crit.update(B1="no_verificable", C1="no_verificable", F2="no_aplica", A1="parcial", B2="no_cumple")
    r = calcular_qa(crit)
    # evaluables 98, verificables 78, obtenidos 78 - 4 - 10 = 64 → 82.1
    assert r == {"qa": 82.1, "pct_verificable": 79.6, "estado": "necesita_mejorar"}

def test_calcular_qa_cortes():
    # construir casos que den 85.0 → aprobado, 70.0 → necesita_mejorar, 69.x → no_aprobado

def test_calcular_qa_sin_verificables_es_pendiente():
    r = calcular_qa({c: "no_verificable" for c, _, _ in CRITERIOS_QA})
    assert r["qa"] is None and r["estado"] == "pendiente"

def test_falla_sospechosa_pendiente_y_confirmada_no_aprobado():
    todo = {c: "cumple" for c, _, _ in CRITERIOS_QA}
    assert calcular_qa(todo, fallas_sospechosas=1)["estado"] == "pendiente"
    r = calcular_qa(todo, fallas_confirmadas=1)
    assert r["estado"] == "no_aprobado" and r["qa"] == 100.0

def test_validar_evaluacion_filtra_evidencias_y_fallas_desconocidas(): ...
def test_validar_evaluacion_criterio_faltante_lanza(): ...
def test_validar_clasificacion_descarta_codigos_desconocidos_y_limita_extra(): ...
def test_requiere_revision_qa(): ...
def test_mensajes_evaluacion_incluyen_rubrica_secciones_y_metricas(): ...
```

- [ ] **Step 2:** `python -m pytest tests/test_auditoria_chats_rubrica.py -q` → FAIL (módulo inexistente).
- [ ] **Step 3:** Implementar el módulo. Redondeo con `round(x, 1)`; validar pesos suman 100 en un test.
- [ ] **Step 4:** Mismo comando → PASS.
- [ ] **Step 5:** Commit `feat: rúbrica QA-1.1 y cálculo del puntaje de calidad`.

### Task 2: Manual — corte del PDF, selección de secciones y almacenamiento

**Files:**
- Create: `utils/auditoria_chats_manual.py`, `scripts/cargar_manual_auditoria.py`, `requirements-dev.txt`
- Modify: `utils/auditoria_chats_store.py`, `supabase_chat_audits.sql`
- Test: `tests/test_auditoria_chats_manual.py`, `tests/test_auditoria_chats_store.py`

**Interfaces:**
- Consumes: `PROCEDIMIENTOS`, `SECCIONES_GENERALES` (Task 1).
- Produces:
  - `TABLA_MANUAL = "chat_audit_manual"`
  - `cortar_manual(texto: str) -> list[dict]` — `{codigo, titulo, texto, orden}`; normaliza espacios; corta por encabezados `^\d+(\.\d+)+\s` que aparezcan en el índice (págs. 2–4) y en el cuerpo (desde la pág. 5); conserva solo códigos `1.*` y `4.*`; omite el índice.
  - `expandir_codigos(codigos: list[str], disponibles: list[str]) -> list[str]` — un prefijo ("1.7") devuelve la sección y sus subsecciones en orden.
  - `seleccionar_secciones(clasificacion: dict, secciones: list[dict], tope: int = 30000) -> list[dict]` — generales + procedimientos + extra, sin duplicados; recorta extra, luego procedimientos (desde el final), nunca generales.
  - Store (ambas clases): `indice_manual(version) -> list[{codigo, titulo}]` (ordenado), `secciones_manual(version, codigos) -> list[dict]`, `guardar_manual(version, secciones)` (upsert por `version, codigo`).
  - `utils/auditoria_chats_manual.version_manual() -> str` — env `AUDITORIA_CHATS_MANUAL_VERSION`, por defecto `"3.0"`.
  - Script: `python scripts/cargar_manual_auditoria.py <pdf> [--version 3.0] [--dry-run]` imprime cantidad de secciones y caracteres; sin `--dry-run` usa `SupabaseAuditoriaStore.from_env().guardar_manual`.
- SQL (añadir al final de `supabase_chat_audits.sql`):
  - `create table if not exists public.chat_audit_manual (version text not null, codigo text not null, titulo text not null default '', texto text not null default '', orden integer not null default 0, primary key (version, codigo));` + RLS on.
  - `alter table chat_audits add column if not exists ia_qa numeric(4,1), ia_estado text, qa_final numeric(4,1), estado_final text, revision jsonb;`
  - Reemplazar el check de `estado` para incluir `'clasificado'` (`drop constraint if exists chat_audits_estado_check; add constraint ... check (estado in (... 'clasificado' ...))`).

- [ ] **Step 1: Tests** — `cortar_manual` sobre un texto sintético con índice + cuerpo (`"ÍNDICE 1.1 Principios 5 1.1.1 Atención por chat. 5 ... === PAG 5 === 1.1.1 Atención por chat. Objetivo: ..."`) devuelve las secciones con su texto y sin el índice; `expandir_codigos(["1.7"], [...])`; `seleccionar_secciones` respeta orden, tope y que las generales nunca se recortan; store en memoria guarda e indexa.
- [ ] **Step 2:** `python -m pytest tests/test_auditoria_chats_manual.py tests/test_auditoria_chats_store.py -q` → FAIL.
- [ ] **Step 3:** Implementar. Ejecutar el script con `--dry-run` sobre la copia del PDF del scratchpad (`python -I`); comprobar que aparecen 1.1.1, 1.4.1, 1.9.6, 4.3, 4.5 y que ninguna sección supera ~15 000 caracteres (si alguna supera, anotarlo como ruling).
- [ ] **Step 4:** Tests → PASS.
- [ ] **Step 5:** Commit `feat: manual de procedimientos para la auditoría de chats`.

### Task 3: Transcripción v2, período del agente y tiempos

**Files:**
- Modify: `utils/auditoria_chats_transcripcion.py`
- Test: `tests/test_auditoria_chats_transcripcion.py`

**Interfaces:**
- Produces:
  - `construir_transcripcion_v2(mensajes, tz_name, max_chars=12000) -> str` — líneas `[m<id> HH:MM:SS] Autor: texto [etiquetas]`; autores `Cliente`, `Agente (<sender.name>)`, `Nota interna (<sender.name>)`, `Sistema`; todo anonimizado; mismo recorte inicio+final.
  - `ids_mensajes(mensajes) -> set[str]` — `{"m<id>"}` de los mensajes incluidos.
  - `periodo_agente(mensajes, agente_id: int, agente_nombre: str) -> dict` — `{"desde": "m<id>"|None, "hasta": "m<id>"|None, "inferido": bool}`; inicio = mensaje de actividad de asignación que nombra al agente (regex es/en tolerante: «asignad[oa] a», «assigned to», «self-assigned») o su primer mensaje saliente (`sender.id == agente_id`); fin = siguiente asignación a otra persona o resolución; `inferido=False` si no hay ninguna señal (todo el chat).
  - `metricas_tiempos(mensajes, periodo, agente_id) -> dict` — `primera_respuesta` {segundos, desde, hasta}, `primera_respuesta_agente`, `esperas_largas` (lista, >180 s, solo respuestas del agente evaluado dentro del período), `esperas_largas_oficiales` (cualquier agente), `inactividad` {segundos_hasta_seguimiento, segundos_hasta_cierre, cerro: "agente"|"cliente"|"sistema"|None}.

- [ ] **Step 1: Tests** con mensajes sintéticos (incluye `sender: {"id", "name"}`, `private`, `message_type` 2): formato de líneas con segundos y notas internas; anonimización; período con traspaso (agente 1 asignado, luego asignación a agente 2) → `hasta` en el evento de traspaso; sin eventos → `inferido` False; primera respuesta 90 s; espera de 200 s del colega no aparece en `esperas_largas` del evaluado pero sí en las oficiales; inactividad con seguimiento a los 300 s y cierre a los 900 s.
- [ ] **Step 2:** `python -m pytest tests/test_auditoria_chats_transcripcion.py -q` → FAIL.
- [ ] **Step 3:** Implementar; la v1 (`construir_transcripcion`) no cambia.
- [ ] **Step 4:** PASS.
- [ ] **Step 5:** Commit `feat: transcripción con identificadores, período del agente y tiempos`.

### Task 4: Motor — flujo QA-1.1 (lectura, clasificación, evaluación)

**Files:**
- Modify: `utils/auditoria_chats_motor.py`
- Test: `tests/test_auditoria_chats_motor.py`

**Interfaces:**
- Consumes: Tasks 1–3.
- Produces:
  - `crear_lote(...)` usa `pauta_version = PAUTA_VERSION_QA` y guarda `alcance_detalle["bandejas_nombres"]` si se recibe en `detalle`. Lanza `AuditoriaChatsError("El manual de procedimientos no está cargado.")` si `store.indice_manual(version_manual())` está vacío; guarda `lote["manual_version"]` dentro de `alcance_detalle`.
  - `ESTADOS_PENDIENTES` incluye `"clasificado"`.
  - `_leer_chat` en lotes QA guarda `transcripcion_v2` en `transcripcion_tmp` y en `detalle`: `periodo`, `metricas`, `ids` (lista de ids válidos) — sin texto.
  - `_clasificar_chat(store, lote, config_ia)` — `leido` → `procesando` → `clasificado` con `detalle.clasificacion`; mismos manejos de 429/diario/temporal/config/reintentos que `_auditar_chat`.
  - `_evaluar_chat_qa(store, lote, config_ia)` — `clasificado` → `procesando` → `auditado`/`error`; arma secciones con `seleccionar_secciones`; guarda `ia_resultado` (incluye `pauta_version`, `modelo`, `qa`, `pct_verificable`, `estado`), `ia_qa`, `ia_estado`, `ia_satisfaccion`, `ia_nota=None`, `por_revisar` con `requiere_revision_qa`.
  - `ejecutar_paso`: en lotes QA, orden por paso: evaluar un `clasificado`, si no clasificar un `leido`, si no leer un `pendiente`. Lotes v1 sin cambios.
  - `_recuperar_abandonados`: `procesando` → `clasificado` si hay `detalle.clasificacion` y transcripción, `leido` si hay transcripción, si no `pendiente`.

- [ ] **Step 1: Tests** (con `MemoriaAuditoriaStore`, manual sintético guardado y `completar_json` parcheado que responde según el mensaje de sistema): lote QA completo de un agente termina con chats `auditado` con `ia_qa` y `ia_estado`; cada paso hace ≤ 1 llamada; crear lote sin manual lanza; 429 diario en la clasificación pone `limite_diario` y no pierde la fila; abandono en `procesando` con clasificación vuelve a `clasificado`; lote v1 existente sigue auditándose con la pauta v1.
- [ ] **Step 2:** `python -m pytest tests/test_auditoria_chats_motor.py -q` → FAIL en los nuevos.
- [ ] **Step 3:** Implementar reutilizando `_llamar_ia` y extrayendo el manejo común de errores de `_auditar_chat` a un helper.
- [ ] **Step 4:** PASS (incluidos los tests v1 existentes).
- [ ] **Step 5:** Commit `feat: flujo de clasificación y evaluación QA-1.1 en el motor`.

### Task 5: Resúmenes, feedback, historial, CSV y diagnóstico v2

**Files:**
- Modify: `utils/auditoria_chats_motor.py`, `tools/auditoria_chats.py` (diagnóstico)
- Test: `tests/test_auditoria_chats_motor.py`, `tests/test_auditoria_chats.py`

**Interfaces:**
- Produces:
  - `qa_efectivo(chat) -> float|None` (`qa_final` si existe, si no `ia_qa`), `estado_efectivo(chat) -> str|None` (`estado_final` o `ia_estado`).
  - `resumen_por_agente(chats)` añade `qa_media` y `estados` (conteo por clave de `ESTADOS_QA`); campos v1 intactos.
  - `feedback_por_agente_qa(chats) -> list[dict]` — `{agente_id, agente_nombre, auditados, qa_media, estados, fallas_confirmadas, puntos_fuertes, areas_mejora, cumplimientos, incumplimientos, recomendaciones, comentarios}`; `puntos_fuertes`/`areas_mejora` = `{codigo, etiqueta, pct}` con % de cumplimiento (cumple 1, parcial 0,5) sobre resultados verificables, usando los criterios corregidos por el revisor si existen; fuertes ≥ 80 % (máx. 3, desc.), mejora < 80 % (máx. 3, asc.).
  - `historial_semanal` añade `qa_media` por fila.
  - `filas_csv` ramifica por `lote["pauta_version"]`: columnas v2 del spec §9, con `_celda_segura`.
  - Diagnóstico: añade por chat `ia_qa`, `ia_estado`, `qa_final`, `estado_final`, `clasificacion` (códigos y motivo), resultados por criterio (sin comentarios), códigos de falla, `periodo` y `metricas`.

- [ ] **Step 1: Tests** de `feedback_por_agente_qa` (3 chats, uno revisado con criterio corregido), `qa_efectivo`/`estado_efectivo`, CSV v2 encabezados y celda protegida, diagnóstico sin texto del manual ni de la transcripción.
- [ ] **Step 2:** FAIL. **Step 3:** Implementar. **Step 4:** PASS.
- [ ] **Step 5:** Commit `feat: resúmenes, feedback y exportes de la pauta QA-1.1`.

### Task 6: Revisión humana v2

**Files:**
- Modify: `tools/auditoria_chats.py` (`ver_chat`, `revisar`), `templates/auditoria_chats_chat.html`
- Test: `tests/test_auditoria_chats.py`

**Interfaces:**
- Formulario v2: `revisor` (obligatorio), `criterio_<código>` (select con `RESULTADOS`, precargado con el de la IA), `falla_<CRxx>` ∈ {confirmada, descartada}, `estado_final` ∈ {aprobado, necesita_mejorar, no_aprobado}, `satisfaccion_final`, `comentario_revisor`.
- `revisar` en chats QA: recalcula con `calcular_qa`; si hay alguna falla confirmada fuerza `no_aprobado`; guarda `estado=revisado`, `qa_final`, `estado_final`, `revision={"criterios": {...solo los cambiados}, "fallas": {...}}`, `revisor`, `satisfaccion_final`, `comentario_revisor`, `revisado_at`.
- `ver_chat` en chats QA pasa `criterios_qa`, `resultados`, `estados_qa`, `estado_recalculado` (para precargar). La transcripción visible añade `id="m<id>"` en cada mensaje para enlazar evidencias.
- Plantilla v2: tabla de 17 criterios (código, etiqueta, peso, resultado IA, comentario, evidencias como enlaces `#m<id>`), bloque de fallas sospechosas, QA + `% verificable`, estado con etiqueta de color, motivo/procedimientos, cumplimientos/incumplimientos/recomendaciones, resolución y responsabilidad. Chats v1 sin cambios.

- [ ] **Step 1: Tests**: GET de un chat QA muestra «A1» y el QA; POST con criterio corregido recalcula `qa_final`; falla confirmada → `estado_final` no_aprobado aunque se envíe aprobado; sin revisor → aviso y no guarda; chat v1 sigue aceptando `nota_final`.
- [ ] **Step 2:** FAIL. **Step 3:** Implementar. **Step 4:** PASS.
- [ ] **Step 5:** Commit `feat: revisión humana de la pauta QA-1.1`.

### Task 7: Páginas de lote, creación y estilos

**Files:**
- Modify: `templates/auditoria_chats_lote.html`, `templates/auditoria_chats.html`, `templates/auditoria_chats_historial.html`, `tools/auditoria_chats.py` (`index`, `crear`, `ver_lote`, `historial`), `static/styles.css`, `app.py`
- Test: `tests/test_auditoria_chats.py`, `tests/test_endurecimiento_5a.py`, `tests/test_navegacion_responsive.py`

**Interfaces:**
- `ver_lote` pasa `es_qa = lote.pauta_version == PAUTA_VERSION_QA`, `feedback_qa`, `estados_qa`; la plantilla ramifica: «Todos los chats» con Estado, QA (`82,1 · 80 % verificable`), Motivo, Satisfacción, Resumen; «Feedback por agente» v2; «Resumen por agente» con QA medio y conteo de estados.
- `index`: aviso si el manual no está cargado; el cupo estimado cuenta 2 llamadas por chat. `crear` pasa `bandejas_nombres` en `detalle` y muestra el error de manual faltante con `flash`.
- Historial muestra QA medio cuando existe.
- CSS: `.ac-valoracion--aprobado`, `--necesita_mejorar`, `--no_aprobado`, `--pendiente` reutilizando los tokens de éxito/aviso/peligro/borde; `styles.css` → `"27"`.

- [ ] **Step 1: Tests**: lote QA procesado muestra «APROBADO» o «NECESITA MEJORAR», «Feedback por agente» y todos los `#conversation_id`; lote v1 sigue mostrando «Buena atención»; índice sin manual muestra el aviso; tests de versión a 27.
- [ ] **Step 2:** FAIL. **Step 3:** Implementar. **Step 4:** `python -m pytest -q` → todo PASS.
- [ ] **Step 5:** Validación manual con el servidor local y la store en memoria si es posible (desktop y ventana angosta); si no, anotarlo.
- [ ] **Step 6:** Commit `feat: páginas de la auditoría de chats con la pauta QA-1.1`.

### Task 8: Configuración, documentación y producción

**Files:**
- Modify: `vercel.json`, `.env.example`, `README.md`
- Producción (Supabase MCP, proyecto `hjclfzjamxojmqcxmmsh`)

- [ ] **Step 1:** `vercel.json`: añadir `"config": {"maxDuration": 60}` al build de `app.py`. Validar JSON.
- [ ] **Step 2:** `.env.example` y `README.md`: `AUDITORIA_CHATS_MANUAL_VERSION`, cómo cargar el manual con el script, la pauta QA-1.1 y que cada chat usa 2 llamadas.
- [ ] **Step 3:** Aplicar la migración SQL de Task 2 con `apply_migration` (`chat_audits_qa_1_1`); verificar columnas y el check con `list_tables`/`execute_sql`; revisar `get_advisors` (seguridad).
- [ ] **Step 4:** Cargar el manual v3.0 en producción: generar las secciones con `cortar_manual` desde la copia local del PDF y hacer upsert con `execute_sql` en bloques (texto escapado con dollar-quoting). Verificar `select count(*), sum(length(texto)) from chat_audit_manual where version='3.0'`.
- [ ] **Step 5:** `python -m pytest -q` → PASS. Commit `feat: configuración y documentación de la pauta QA-1.1`. No hacer push: preguntar al usuario.
