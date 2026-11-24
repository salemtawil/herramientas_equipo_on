# Auditoría CSAT desde Chatwoot — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** La auditoría CSAT trae las encuestas de Chatwoot por período, separa la propuesta de la IA de la decisión humana, guarda lo mínimo en Supabase (o nada en modo prueba) y alimenta la sección CSAT del informe semanal.

**Architecture:** Se conserva el `estado` en memoria de `tools/auditoria_csat.py` (dict con `rows`) como centro: todos los cálculos, la IA y los exportes siguen operando sobre filas. Lo nuevo entra por módulos chicos en `utils/` (períodos, conversión Chatwoot→filas, store Supabase/memoria, bloque del informe). En modo guardado, el estado se reconstruye en cada request desde Chatwoot + decisiones guardadas (el temporal de 24 h es solo caché); en modo prueba vive solo en el temporal.

**Tech Stack:** Flask + Jinja, pandas, requests, supabase-py, pytest.

**Spec:** `docs/superpowers/specs/2026-11-24-auditoria-csat-chatwoot-design.md`

## Global Constraints

- UI en español; estilos compartidos en `static/styles.css`; tablas dentro de `table-wrap`; sin SPA ni JS nuevo obligatorio (los presets de período se resuelven en servidor).
- No guardar en Supabase transcripciones ni datos de contacto (nombre, correo, teléfono).
- Comentario de encuesta, evidencia IA y nota del auditor se recortan a 500 caracteres al guardar.
- Retención: 12 semanas (`RETENCION_SEMANAS = 12`), borrando períodos con `fecha_fin` anterior a hoy − 84 días.
- Semántica de decisión: `justificable == "SÍ"` excluye el negativo del CSAT; `"TAL VEZ"`, `"NO"` y vacío cuentan. Solo cuenta la decisión humana (`justificable`), nunca `ia_justificable`.
- La IA nunca sobrescribe una fila con `origen_decision == "humana"`.
- Modo prueba: ninguna llamada al store de Supabase.
- Tests: nunca red ni Supabase reales (lo impone `tests/conftest.py`); usar fakes y `MemoriaCsatStore`.
- Sin variables de entorno nuevas; si se agregara alguna, actualizar `.env.example` y `README.md`.

## Review Focus

1. **Encuesta sin agente asignado** (`assigned_agent: null`): la fila debe quedar como "Sin agente", sin romper resumen por agente ni guardado.
2. **Período sin encuestas**: la pantalla muestra "No hay encuestas en el período" y no crea período en Supabase.
3. **Guardar el formulario con propuestas IA visibles pero sin tocar los selects**: no debe convertir propuestas en decisiones humanas.
4. **Chatwoot o Supabase caídos al abrir una auditoría guardada**: mensaje claro en español, sin traceback, sin borrar decisiones.
5. **Re-traer un período donde una encuesta pasó de 1 a 4**: su negativo guardado se borra y el ajustado se recalcula.

Cada uno tiene su test en la tarea dueña (marcado *[Review Focus N]*).

---

### Task 1: Períodos seleccionables

**Files:**
- Create: `utils/csat_periodos.py`
- Test: `tests/test_csat_periodos.py`

**Interfaces:**
- Produces:
  - `TIPOS_PERIODO: list[tuple[str, str]]` = `[("semana_pasada","Semana pasada (lun–dom)"), ("esta_semana","Esta semana"), ("ultimos_7","Últimos 7 días"), ("mes_pasado","Mes pasado"), ("este_mes","Este mes"), ("personalizado","Personalizado")]`
  - `resolver_periodo(tipo: str, hoy: date, fecha_inicio: str|None = None, fecha_fin: str|None = None) -> tuple[date, date]` — `ValueError` en español si tipo desconocido, personalizado sin fechas o fin < inicio.
  - `periodo_anterior(tipo: str, inicio: date, fin: date) -> tuple[date, date]`
  - `formatear_periodo(inicio: date, fin: date) -> str` → `"dd/mm/aa al dd/mm/aa"`

- [ ] **Step 1: Tests que fallan**

```python
from datetime import date
import pytest
from utils.csat_periodos import resolver_periodo, periodo_anterior, formatear_periodo

HOY = date(2026, 11, 25)  # miércoles

@pytest.mark.parametrize("tipo,esperado", [
    ("semana_pasada", (date(2026,11,16), date(2026,11,22))),
    ("esta_semana", (date(2026,11,23), date(2026,11,25))),
    ("ultimos_7", (date(2026,11,19), date(2026,11,25))),
    ("mes_pasado", (date(2026,10,1), date(2026,10,31))),
    ("este_mes", (date(2026,11,1), date(2026,11,25))),
])
def test_resolver_presets(tipo, esperado):
    assert resolver_periodo(tipo, HOY) == esperado

def test_personalizado_y_errores():
    assert resolver_periodo("personalizado", HOY, "2026-11-01", "2026-11-10") == (date(2026,11,1), date(2026,11,10))
    with pytest.raises(ValueError): resolver_periodo("personalizado", HOY)
    with pytest.raises(ValueError): resolver_periodo("personalizado", HOY, "2026-11-10", "2026-11-01")
    with pytest.raises(ValueError): resolver_periodo("otro", HOY)

def test_periodo_anterior():
    assert periodo_anterior("semana_pasada", date(2026,11,16), date(2026,11,22)) == (date(2026,11,9), date(2026,11,15))
    assert periodo_anterior("esta_semana", date(2026,11,23), date(2026,11,25)) == (date(2026,11,16), date(2026,11,22))
    assert periodo_anterior("mes_pasado", date(2026,10,1), date(2026,10,31)) == (date(2026,9,1), date(2026,9,30))
    assert periodo_anterior("este_mes", date(2026,11,1), date(2026,11,25)) == (date(2026,10,1), date(2026,10,31))
    assert periodo_anterior("ultimos_7", date(2026,11,19), date(2026,11,25)) == (date(2026,11,12), date(2026,11,18))
    assert periodo_anterior("personalizado", date(2026,11,1), date(2026,11,10)) == (date(2026,10,22), date(2026,10,31))

def test_formatear_periodo():
    assert formatear_periodo(date(2026,6,1), date(2026,6,7)) == "01/06/26 al 07/06/26"
```

Regla: semanas → semana lun–dom completa previa; meses → mes calendario previo completo; `ultimos_7` y `personalizado` → mismo largo justo antes.

- [ ] **Step 2:** `python -m pytest tests/test_csat_periodos.py -q` → FAIL (módulo no existe).
- [ ] **Step 3:** Implementar en `utils/csat_periodos.py` (solo `datetime`/`calendar`).
- [ ] **Step 4:** Mismo comando → PASS.
- [ ] **Step 5:** `git add utils/csat_periodos.py tests/test_csat_periodos.py && git commit -m "feat: períodos seleccionables para la auditoría CSAT"`

---

### Task 2: Cliente Chatwoot para encuestas CSAT

**Files:**
- Modify: `utils/chatwoot_reportes.py` (clase `ChatwootClient`, junto a `listar_agentes`)
- Test: `tests/test_chatwoot_csat.py`

**Interfaces:**
- Produces (métodos de `ChatwootClient`):
  - `respuestas_csat(since: int, until: int, max_paginas: int = 40) -> list[dict]` — `GET /api/v1/accounts/{id}/csat_survey_responses` con `since`, `until`, `page` (desde 1); se detiene en página vacía o `max_paginas`; deduplica por `id`.
  - `metricas_csat(since: int, until: int) -> dict` — `GET /api/v1/accounts/{id}/csat_survey_responses/metrics`; devuelve `{"total_count": int, "ratings_count": {"1": int, …}}` tal cual.

- [ ] **Step 1: Tests que fallan** (subclase o `monkeypatch` de `client.get` que registra `path`/`params`):

```python
def test_respuestas_csat_pagina_hasta_vacia(): 
    # get devuelve 2 páginas con ids [1,2] y [2,3], luego []
    assert [r["id"] for r in client.respuestas_csat(100, 200)] == [1, 2, 3]
    assert llamadas[0] == ("/api/v1/accounts/2/csat_survey_responses", {"since": "100", "until": "200", "page": 1})

def test_metricas_csat_usa_endpoint_metrics():
    assert client.metricas_csat(100, 200)["total_count"] == 70
```

Construir el cliente con `ChatwootClient(base_url="https://chatwoot.invalid", account_id="2", api_token="x")`.

- [ ] **Step 2:** `python -m pytest tests/test_chatwoot_csat.py -q` → FAIL.
- [ ] **Step 3:** Implementar ambos métodos usando `self.get` y `_normalizar_lista_respuesta`.
- [ ] **Step 4:** PASS. Además `python -m pytest tests/test_chatwoot_reportes.py -q` sigue PASS.
- [ ] **Step 5:** Commit `feat: lectura de encuestas CSAT desde Chatwoot`.

---

### Task 3: Separar propuesta de IA y decisión humana (ambos modos)

**Files:**
- Modify: `tools/auditoria_csat.py` — `construir_filas_desde_dataframe` (~l.366), `aplicar_resultado_ia` (~l.701), `auditar_estado_con_ia` (~l.733), `actualizar_estado_desde_formulario` (~l.789), `construir_dataframe_exportable` (~l.1080), `construir_reporte_ia_markdown` (~l.1126), ruta (~l.1220)
- Modify: `templates/auditoria_csat.html` (columna IA ~l.242, select ~l.256, barra de acciones ~l.98)
- Test: `tests/test_auditoria_csat.py`

**Interfaces:**
- Produces: claves nuevas de fila `ia_justificable` (`""|"NO"|"TAL VEZ"|"SÍ"`), `ia_motivo`, `origen_decision` (`""|"humana"|"ia_aceptada"`). `comentario_auditor` es la nota del auditor (ya no se prefija con "IA:").
- Produces: `aceptar_propuestas_ia(estado: dict) -> int` (cuántas filas aceptó).

Comportamiento:
- `aplicar_resultado_ia` escribe solo `ia_*` (incluye `ia_justificable`, `ia_motivo`, `ia_estado="sugerida"`); no toca `justificable`, `motivo_inconformidad`, `comentario_auditor`, `estado_auditoria`, `csat_flag`. `ia_fuente` = `"transcripcion_chatwoot"` si la fila tiene `survey_id` y transcripción, si no el valor actual.
- Candidatos IA: negativos con `ia_justificable` vacío y `origen_decision != "humana"`.
- `actualizar_estado_desde_formulario`: si `justificable`, motivo o nota del form difieren de la fila → aplica y `origen_decision = "humana"` (o `""` si justificable queda vacío); si no difieren, no cambia `origen_decision`.
- `aceptar_propuestas_ia`: para filas con `ia_justificable` y sin `justificable` → copia `ia_justificable`/`ia_motivo`, `origen_decision="ia_aceptada"`, recalcula `estado_auditoria` y `csat_flag`.
- Nueva acción de formulario `aceptar_propuestas_ia` (botón "Aceptar propuestas de la IA") en la ruta.
- Template: la columna IA muestra "Propuesta IA: {{ ia_justificable }} · {{ ia_motivo }}"; el select sigue mostrando solo `justificable`; etiqueta visible de "SÍ" = "SÍ (no atribuible al agente)" con `value="SÍ"`; mostrar insignia de `origen_decision`. Actualizar textos de ayuda (l.94, l.107, l.126) para decir que el ajustado cuenta solo decisiones confirmadas.
- Exportes CSV y markdown agregan `ia_justificable`, `ia_motivo`, `origen_decision`.

- [ ] **Step 1: Tests que fallan**

```python
def test_ia_no_cambia_decision_ni_csat():
    fila = fila_negativa()  # helper: tipo_rating="Negativo", justificable=""
    aplicar_resultado_ia(fila, {"justificable": "SI", "motivo_inconformidad": "CAPTCHA", "confianza": 0.9, "explicacion": "x", "evidencia": "y"}, "m")
    assert fila["ia_justificable"] == "SÍ" and fila["ia_motivo"] == "CAPTCHA"
    assert fila["justificable"] == "" and fila["csat_flag"] == "contabiliza"

def test_aceptar_propuestas_marca_origen():
    estado = {"rows": [fila_con_propuesta("SÍ")]}
    assert aceptar_propuestas_ia(estado) == 1
    assert estado["rows"][0]["justificable"] == "SÍ"
    assert estado["rows"][0]["origen_decision"] == "ia_aceptada"
    assert estado["rows"][0]["csat_flag"] == "excluida_por_justificable_si"

def test_guardar_form_sin_cambios_no_vuelve_humana():  # [Review Focus 3]
    estado = {"rows": [fila_con_propuesta("SÍ")]}
    actualizar_estado_desde_formulario(estado, {"justificable__0": "", "motivo_inconformidad__0": "", "comentario_auditor__0": ""})
    assert estado["rows"][0]["origen_decision"] == "" and estado["rows"][0]["justificable"] == ""

def test_cambio_en_form_es_humana_y_la_ia_no_la_toca():
    estado = {"rows": [fila_negativa()]}
    actualizar_estado_desde_formulario(estado, {"justificable__0": "NO", "motivo_inconformidad__0": "OTRO", "comentario_auditor__0": "nota"})
    assert estado["rows"][0]["origen_decision"] == "humana"
    # auditar_estado_con_ia con proveedor falso (monkeypatch auditar_lote_con_proveedor) → 0 candidatos
```

- [ ] **Step 2:** `python -m pytest tests/test_auditoria_csat.py -q` → FAIL.
- [ ] **Step 3:** Implementar los cambios descritos.
- [ ] **Step 4:** PASS; `python -m pytest -q` completo sigue PASS (baseline 352).
- [ ] **Step 5:** Commit `fix: la IA de CSAT propone y la persona confirma`.

---

### Task 4: Encuestas de Chatwoot → filas, transcripciones y fusión con lo guardado

**Files:**
- Create: `utils/auditoria_csat_chatwoot.py`
- Test: `tests/test_auditoria_csat_chatwoot.py`

**Interfaces:**
- Consumes: `ChatwootClient.respuestas_csat`, `mensajes_de_conversacion`, `url_conversacion` (Task 2); `construir_transcripcion` de `utils/auditoria_chats_transcripcion.py`; de `tools/auditoria_csat.py`: `parsear_calificacion`, `clasificar_tipo_rating`, `calcular_flag_csat`, `formatear_fecha`, `EXPECTED_COLUMNS`, `MOTIVOS_INCONFORMIDAD`.
- Produces:
  - `filas_desde_encuestas(encuestas: list[dict], chatwoot, tz_name: str) -> list[dict]` — misma forma de fila que `construir_filas_desde_dataframe` (todas sus claves, incluidas las de Task 3 y las `EXPECTED_COLUMNS` con su valor), más `survey_id: int`, `conversation_id: int`, `agente_id: int|None`. `row_id = str(survey_id)`. Agente: `assigned_agent.available_name` o `name`; sin agente → `"Sin agente"`. Fecha desde `created_at` en `tz_name`. Enlace = `chatwoot.url_conversacion(conversation_id)`.
  - `cargar_transcripciones(filas: list[dict], chatwoot, tz_name: str, max_chars: int = 6000) -> list[str]` — rellena `transcripcion_conversacion` de las filas recibidas que no la tengan; devuelve advertencias (una por conversación que falló, sin cortar el resto).
  - `fusionar_guardado(filas: list[dict], negativos_guardados: list[dict]) -> None` — por `survey_id`, copia a filas negativas: `ia_justificable, ia_motivo, ia_confianza, ia_evidencia` → `ia_*`; `decision_final→justificable`, `motivo_final→motivo_inconformidad`, `nota_auditor→comentario_auditor`, `origen_decision`; recalcula `estado_auditoria`/`csat_flag`. Ignora guardados cuyo survey ya no es negativo.
  - `negativos_para_guardar(filas: list[dict]) -> list[dict]` — solo negativos, con exactamente las columnas de `csat_audit_negatives` (Task 5) menos `id/period_id/updated_at`; textos recortados a 500; sin datos de contacto ni transcripción.
  - `resumen_para_guardar(filas: list[dict]) -> dict` — `total_encuestas, ratings_count (dict "1".."5"), csat_real, csat_ajustado, por_agente (lista de construir_resumen_por_agente), negativos_total, negativos_excluidos, negativos_pendientes` usando `construir_metricas` y `construir_resumen_por_agente`.

Importar desde `tools.auditoria_csat` dentro de funciones si hay import circular.

- [ ] **Step 1: Tests que fallan** (encuestas de ejemplo con la forma real verificada: `id, rating, feedback_message, conversation_id, assigned_agent{id,name,available_name}, contact{name,email,phone_number}, created_at`):

```python
def test_filas_desde_encuestas():
    filas = filas_desde_encuestas([enc(1, rating=1), enc(2, rating=5)], ChatwootFalso(), "America/Caracas")
    assert filas[0]["row_id"] == "1" and filas[0]["tipo_rating"] == "Negativo"
    assert filas[0]["enlace_conversacion"].endswith("/conversations/501")
    assert filas[1]["tipo_rating"] == "Positivo"

def test_encuesta_sin_agente():  # [Review Focus 1]
    fila = filas_desde_encuestas([enc(3, rating=2, assigned_agent=None)], ChatwootFalso(), "America/Caracas")[0]
    assert fila["agente"] == "Sin agente" and fila["agente_id"] is None

def test_negativos_para_guardar_no_incluye_contacto_ni_transcripcion():
    datos = negativos_para_guardar(filas_con_transcripcion())
    assert all("transcripcion" not in k and "contacto" not in k for k in datos[0])
    assert len(datos[0]["comentario"]) <= 500

def test_fusionar_conserva_decision_humana():
    filas = filas_desde_encuestas([enc(1, rating=1)], ChatwootFalso(), "America/Caracas")
    fusionar_guardado(filas, [{"survey_id": 1, "decision_final": "SÍ", "motivo_final": "CAPTCHA", "origen_decision": "humana", "nota_auditor": "n"}])
    assert filas[0]["justificable"] == "SÍ" and filas[0]["csat_flag"] == "excluida_por_justificable_si"

def test_cargar_transcripciones_sigue_si_una_falla():
    # ChatwootFalso.mensajes_de_conversacion lanza para conversation_id 502
    advertencias = cargar_transcripciones(dos_filas, ChatwootFalso(), "America/Caracas")
    assert len(advertencias) == 1 and dos_filas[0]["transcripcion_conversacion"]
```

- [ ] **Step 2:** `python -m pytest tests/test_auditoria_csat_chatwoot.py -q` → FAIL.
- [ ] **Step 3:** Implementar.
- [ ] **Step 4:** PASS.
- [ ] **Step 5:** Commit `feat: convierte encuestas de Chatwoot en filas de auditoría CSAT`.

---

### Task 5: Store mínimo en Supabase + SQL + retención

**Files:**
- Create: `supabase_csat_audits.sql`, `utils/auditoria_csat_store.py`
- Test: `tests/test_auditoria_csat_store.py`

**Interfaces:**
- SQL (mismo estilo que `supabase_chat_audits.sql`, RLS habilitado sin políticas públicas):
  - `csat_audit_periods(id uuid pk default gen_random_uuid(), tipo_periodo text, fecha_inicio date, fecha_fin date, total_encuestas int, ratings_count jsonb, csat_real numeric, csat_ajustado numeric, por_agente jsonb, negativos_total int, negativos_excluidos int, negativos_pendientes int, created_at timestamptz default now(), updated_at timestamptz default now(), unique(fecha_inicio, fecha_fin))`
  - `csat_audit_negatives(id bigserial pk, period_id uuid references csat_audit_periods(id) on delete cascade, survey_id bigint, conversation_id bigint, agente_id bigint, agente_nombre text, rating int, comentario text, enlace text, fecha timestamptz, ia_justificable text, ia_motivo text, ia_confianza numeric, ia_evidencia text, decision_final text, motivo_final text, origen_decision text, nota_auditor text, updated_at timestamptz default now(), unique(period_id, survey_id))`
- Produces (misma interfaz en `SupabaseCsatStore` y `MemoriaCsatStore`; errores como `AuditoriaCsatStoreError` / `AuditoriaCsatConfigError` con mensaje en español; patrón de `utils/auditoria_chats_store.py`):
  - `guardar_periodo(tipo_periodo: str, inicio: date, fin: date, resumen: dict) -> dict` (upsert por fechas; devuelve fila con `id`)
  - `obtener_periodo(period_id: str) -> dict|None`
  - `buscar_periodo(inicio: date, fin: date) -> dict|None`
  - `listar_periodos(limite: int = 20) -> list[dict]` (más recientes por `fecha_fin`)
  - `negativos(period_id: str) -> list[dict]`
  - `reemplazar_negativos(period_id: str, filas: list[dict]) -> None` (upsert por `survey_id`; borra los del período cuyo `survey_id` no está en `filas`)
  - `borrar_vencidos(hoy: date, semanas: int = 12) -> int`
  - `obtener_store_csat() -> SupabaseCsatStore` (from_env)

- [ ] **Step 1: Tests que fallan** (sobre `MemoriaCsatStore`):

```python
def test_guardar_periodo_es_upsert_por_fechas():
    a = store.guardar_periodo("semana_pasada", d1, d7, {"csat_real": 80.0})
    b = store.guardar_periodo("semana_pasada", d1, d7, {"csat_real": 82.0})
    assert a["id"] == b["id"] and store.obtener_periodo(a["id"])["csat_real"] == 82.0

def test_reemplazar_negativos_borra_los_que_ya_no_vienen():  # [Review Focus 5]
    store.reemplazar_negativos(pid, [{"survey_id": 1}, {"survey_id": 2}])
    store.reemplazar_negativos(pid, [{"survey_id": 1}])
    assert [n["survey_id"] for n in store.negativos(pid)] == [1]

def test_borrar_vencidos_respeta_12_semanas():
    store.guardar_periodo("semana_pasada", date(2026,8,1), date(2026,8,7), {})
    store.guardar_periodo("semana_pasada", date(2026,11,16), date(2026,11,22), {})
    assert store.borrar_vencidos(date(2026,11,25)) == 1
    assert len(store.listar_periodos()) == 1
```

- [ ] **Step 2:** `python -m pytest tests/test_auditoria_csat_store.py -q` → FAIL.
- [ ] **Step 3:** Implementar store y SQL.
- [ ] **Step 4:** PASS.
- [ ] **Step 5:** Commit `feat: guardado mínimo de auditorías CSAT en Supabase`.

---

### Task 6: Pantalla con modo Chatwoot, guardado/prueba y conversación

**Files:**
- Modify: `tools/auditoria_csat.py` (ruta `/auditoria-csat` y nuevas funciones), `templates/auditoria_csat.html`, `static/styles.css` (solo clases nuevas que falten)
- Create: `templates/auditoria_csat_conversacion.html`
- Modify: `README.md` (sección Auditoría CSAT: flujo Chatwoot, modo prueba, ejecutar `supabase_csat_audits.sql`)
- Test: `tests/test_auditoria_csat_ruta.py`

**Interfaces:**
- Consumes: Tasks 1, 2, 4, 5; `obtener_chatwoot()` nuevo en `tools/auditoria_csat.py` = `ChatwootClient(timeout=15)` (como en `tools/auditoria_chats.py:47`); `obtener_store_csat` referenciado por nombre de módulo para poder `monkeypatch`.
- Produces en `estado`: `modo` (`"csv"|"chatwoot"`), `prueba: bool`, `tipo_periodo`, `fecha_inicio`, `fecha_fin` (ISO), `period_id` (vacío en prueba).
- Rutas:
  - `POST /auditoria-csat` con `accion=traer_chatwoot` (campos `tipo_periodo`, `fecha_inicio`, `fecha_fin`, `prueba`): resuelve período (Task 1, `hoy` en `CHATWOOT_TIMEZONE`), rango con `construir_rango_chatwoot_fechas`, `respuestas_csat`, `filas_desde_encuestas`. Si no hay encuestas → advertencia "No hay encuestas en el período" y no guarda *[Review Focus 2]*. Si no es prueba: `buscar_periodo` → `fusionar_guardado` con sus negativos, luego sincroniza.
  - Acciones existentes (`guardar_auditoria`, `auditar_con_ia`, `aceptar_propuestas_ia`, exportes) en modo chatwoot: cargan el estado (ver abajo), aplican, y si no es prueba sincronizan. `auditar_con_ia` llama `cargar_transcripciones` solo para los candidatos antes de la IA.
  - `GET /auditoria-csat?period_id=…`: abre una guardada.
  - `GET /auditoria-csat/conversacion/<int:conversation_id>`: transcripción en vivo (`mensajes_de_conversacion` + `construir_transcripcion`), sin guardar; enlace "Abrir en Chatwoot".
- `sincronizar_periodo(estado: dict) -> None`: `guardar_periodo(…, resumen_para_guardar(rows))`, `reemplazar_negativos(id, negativos_para_guardar(rows))`, `borrar_vencidos(hoy)`; guarda `period_id` en estado. Nunca se llama si `estado["prueba"]`.
- `cargar_estado_chatwoot(form_o_args) -> dict|None`: primero temporal por `analysis_id`; si falta y hay `period_id`, reconstruye (re-trae de Chatwoot con las fechas del período + `fusionar_guardado`). En prueba sin temporal → mismo aviso que hoy ("ya no está disponible…").
- Template: arriba, formulario "Traer de Chatwoot" con select `tipo_periodo` (de `TIPOS_PERIODO`), dos `input type=date` (usados si `personalizado`), casilla "Modo prueba (no se guarda)" y botón principal. Debajo, tabla "Auditorías guardadas" (`listar_periodos`: período, CSAT real, ajustado, pendientes, enlace "Abrir"); si el store no está configurado, aviso y la pantalla sigue funcionando. La carga CSV pasa a un `<details>` "Cargar CSV manualmente". Franja visible "Modo prueba — nada de esto se guarda" cuando `prueba`. Indicador "N negativos sin confirmar — el ajustado aún no es definitivo" y, en el resumen, "Auditados a mano: N · Aceptados de la IA: M" (contando `origen_decision`). Cada fila negativa con enlace "Ver conversación". En modo prueba, botón "Descargar bloque para el informe" (Task 7, acción `descargar_bloque_informe`).
- Errores de Chatwoot/Supabase → `mensaje_error_publico` en `advertencia`, sin traceback *[Review Focus 4]*.

- [ ] **Step 1: Tests que fallan** (Flask test client; `monkeypatch` de `obtener_chatwoot` → fake con `respuestas_csat`, `mensajes_de_conversacion`, `url_conversacion`; `obtener_store_csat` → `MemoriaCsatStore`; IA con `auditar_lote_con_proveedor` falso):

```python
def test_traer_chatwoot_guarda_periodo(cliente, store):
    r = cliente.post("/auditoria-csat", data={"accion": "traer_chatwoot", "tipo_periodo": "semana_pasada"})
    assert r.status_code == 200 and len(store.listar_periodos()) == 1

def test_modo_prueba_no_toca_store(cliente, monkeypatch):
    monkeypatch.setattr(herramienta, "obtener_store_csat", lambda: pytest.fail("no debe usarse"))
    r = cliente.post("/auditoria-csat", data={"accion": "traer_chatwoot", "tipo_periodo": "semana_pasada", "prueba": "1"})
    assert "Modo prueba" in r.get_data(as_text=True)

def test_periodo_sin_encuestas(cliente, store, chatwoot_vacio):  # [Review Focus 2]
    r = cliente.post(...)
    assert "No hay encuestas en el período" in r.get_data(as_text=True) and store.listar_periodos() == []

def test_reabrir_guardada_sin_temporal_reconstruye_decisiones(cliente, store):
    # traer, guardar decisión SÍ, limpiar temporal, GET ?period_id= → select con SÍ seleccionado

def test_chatwoot_caido_muestra_aviso(cliente, chatwoot_que_falla):  # [Review Focus 4]
    r = cliente.post(...)
    assert r.status_code == 200 and "Traceback" not in r.get_data(as_text=True)

def test_retraer_borra_negativo_que_subio(cliente, store, chatwoot_mutable):  # [Review Focus 5]
    # 1ª vez rating 1 → 1 negativo; 2ª vez el mismo survey rating 4 → 0 negativos y csat_ajustado recalculado

def test_ver_conversacion_no_guarda(cliente, store):
    r = cliente.get("/auditoria-csat/conversacion/501")
    assert r.status_code == 200 and store.listar_periodos() == []

def test_csv_sigue_funcionando(cliente):
    # POST accion=analizar_csv con CSV mínimo de EXPECTED_COLUMNS → 200 y "CSV cargado"
```

- [ ] **Step 2:** `python -m pytest tests/test_auditoria_csat_ruta.py -q` → FAIL.
- [ ] **Step 3:** Implementar ruta, funciones, templates, README.
- [ ] **Step 4:** PASS; suite completa PASS.
- [ ] **Step 5: Verificación manual** (local, `.env` real, **modo prueba**): traer "Semana pasada"; confirmar que el total coincide con `metricas_csat` y que "Ver conversación" abre la conversación correcta (valida que `conversation_id` de la encuesta es el `display_id` que usan mensajes y URL). Revisar en ventana angosta que tablas y formulario hacen wrap. Navegación del admin intacta.
- [ ] **Step 6:** Commit `feat: auditoría CSAT trae encuestas de Chatwoot con modo prueba`.

---

### Task 7: Bloque para el informe semanal

**Files:**
- Create: `utils/auditoria_csat_informe.py`
- Modify: `tools/informe_semanal_cs.py` (`informe_semanal_cs` ~l.466, `build_weekly_report_prompt` ~l.193), `templates/informe_semanal_cs.html` (junto a `periodo`, l.48), `tools/auditoria_csat.py` (acción `descargar_bloque_informe`)
- Test: `tests/test_auditoria_csat_informe.py`, `tests/test_informe_semanal_cs.py`

**Interfaces:**
- Consumes: store (Task 5), `periodo_anterior`/`formatear_periodo` (Task 1), `metricas_csat` (Task 2), `calcular_csat`.
- Produces:
  - `construir_bloque_csat(periodo: dict, negativos: list[dict], anterior: dict) -> str` — texto con, en este orden, líneas que empiezan exactamente: `"Período auditado: "`, `"Total de encuestas: "`, `"Distribución: "`, `"CSAT real: "`, `"CSAT ajustado: "`, `"Por agente:"`, `"Negativos por motivo:"`, `"Negativos excluidos (no atribuibles al agente): "`, `"Auditados a mano: "`, `"Aceptados de la IA: "`, `"Negativos pendientes de confirmar: "`, `"Casos relevantes:"` (3–5 excluidos o NO, con comentario, motivo y evidencia/nota), `"Período anterior: "`. Porcentajes con `%`.
  - `datos_periodo_anterior(store, chatwoot, periodo: dict, tz_name: str) -> dict` — `{"periodo": str, "csat_real": float, "csat_ajustado": float|None, "total": int, "auditado": bool}`; si `buscar_periodo` encuentra las fechas exactas usa lo guardado; si no, `metricas_csat` (positivos = ratings 4 y 5 / total) y `auditado=False`; si Chatwoot falla, `{"periodo":…, "error": "sin datos"}`.
  - `bloque_desde_estado(estado: dict, chatwoot, tz_name: str) -> str` — para modo prueba, usa `resumen_para_guardar` + `negativos_para_guardar` sin store (anterior solo vía `metricas_csat`).
- Informe: select `auditoria_csat_id` ("Sin auditoría CSAT" + `listar_periodos`, mostrando "dd/mm/aa al dd/mm/aa — N pendientes"); si el store no está configurado, el select no aparece. Al generar con selección: `datos["auditoria_csat"] = construir_bloque_csat(...)`; si `periodo` vacío se llena con `formatear_periodo`; si hay pendientes, agregar a `warnings` "La auditoría CSAT tiene N negativos sin confirmar." El prompt agrega una sección `Auditoría CSAT (datos confirmados):` con el bloque o "Sin auditoría CSAT seleccionada." y la regla: usar esos datos tal cual para la sección "CSAT y Chats con negativos, Auditoría interna". `generar_informe_fallback` considera `auditoria_csat` como dato de CSAT.

- [ ] **Step 1: Tests que fallan**

```python
def test_bloque_contiene_real_ajustado_y_pendientes():
    texto = construir_bloque_csat(periodo_80_85, negativos_ejemplo, {"periodo": "09/11/26 al 15/11/26", "csat_real": 78.0, "csat_ajustado": None, "total": 60, "auditado": False})
    assert "CSAT real: 80.0%" in texto and "CSAT ajustado: 85.0%" in texto
    assert "Negativos pendientes de confirmar: 1" in texto and "sin auditoría" in texto

def test_anterior_usa_guardado_si_existe(store): ...
def test_anterior_sin_guardado_usa_metricas(chatwoot_falso): # ratings {"1":10,"5":40} → csat_real 80.0
def test_informe_con_auditoria_incluye_bloque_en_prompt(cliente, store, monkeypatch):
    # monkeypatch generate_weekly_report para capturar datos; POST con auditoria_csat_id → "CSAT ajustado:" en datos["auditoria_csat"] y periodo rellenado
def test_informe_sin_supabase_sigue_funcionando(cliente):  # store no configurado → 200, sin select
```

- [ ] **Step 2:** `python -m pytest tests/test_auditoria_csat_informe.py tests/test_informe_semanal_cs.py -q` → FAIL.
- [ ] **Step 3:** Implementar.
- [ ] **Step 4:** PASS; suite completa PASS.
- [ ] **Step 5: Verificación manual:** en local, generar un informe seleccionando una auditoría guardada de prueba creada en un Supabase de desarrollo **o** usando el bloque descargado del modo prueba como archivo adicional; revisar que la sección CSAT cita los números del bloque.
- [ ] **Step 6:** Commit `feat: el informe semanal usa la auditoría CSAT guardada`.

---

### Despliegue (manual, fuera de las tareas)

Ejecutar `supabase_csat_audits.sql` en el proyecto de producción **solo con el visto bueno del usuario**, antes de desplegar en Vercel. No requiere variables nuevas.
