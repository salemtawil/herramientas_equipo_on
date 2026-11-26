# Criterios del equipo para la IA de CSAT — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** La IA de la Auditoría CSAT decide cada negativo con el procedimiento y la rúbrica del equipo, viendo la conversación completa con tiempos calculados, y devuelve puntaje y reglas incumplidas.

**Architecture:** Un módulo de criterios (`utils/auditoria_csat_criterios.py`) concentra reglas, rúbrica, motivos y procedimiento y arma las instrucciones. `cargar_transcripciones` pasa a la transcripción v2 y calcula métricas de tiempo por fila. `tools/auditoria_csat.py` incluye esas métricas en el caso, amplía el esquema y guarda `ia_puntaje`/`ia_reglas`. La vista y la ficha los muestran.

**Tech Stack:** Python/Flask, Jinja, pytest.

**Spec:** `docs/superpowers/specs/2026-11-25-auditoria-csat-criterios-ia-design.md`

## Global Constraints

- Regla, rúbrica (pesos), corte 70%, franja 60–70%, atenuantes y definiciones de motivos: copiar verbatim del spec.
- Valores internos sin cambio (`justificable`, `MOTIVOS_INCONFORMIDAD` con sus 14 nombres exactos); esquema de Supabase sin cambio.
- Transcripción y métricas solo en memoria para la IA; la transcripción se sigue limpiando tras la IA.
- Presupuesto de IA y límite 60 s sin cambio. Tests sin red.

## Review Focus

1. **Conversación sin respuesta del agente / agente sin mensajes** → métricas con `None`, sin excepción; el caso se arma igual. Test en Task 2.
2. **IA que devuelve `puntaje` fuera de rango o texto, o `reglas_incumplidas` no lista** → se normaliza (0–100 entero o vacío; lista de ≤ 5 textos cortos). Test en Task 1.
3. **Fila CSV (sin `conversation_id`)** → sin métricas, la IA usa la transcripción del CSV como hoy. Test en Task 2.
4. **Auditoría reabierta desde Supabase** → ficha sin puntaje/reglas no rompe. Test en Task 3.

---

### Task 1: Módulo de criterios, instrucciones y salida ampliada

**Files:** Create `utils/auditoria_csat_criterios.py`; Modify `tools/auditoria_csat.py` (`construir_instrucciones_auditoria_ia`, `construir_payload_lote_auditoria_ia`, `esquema_auditoria_ia`, `aplicar_resultado_ia`, filas iniciales en `construir_filas_desde_dataframe`), `utils/auditoria_csat_chatwoot.py` (claves iniciales de fila); Test `tests/test_auditoria_csat_criterios.py`, `tests/test_auditoria_csat.py`.

**Interfaces (Produces):**
- `RUBRICA: list[tuple[str, int]]` (12 puntos, suma 100), `CORTE_RUBRICA = 70`, `FRANJA_DUDOSO = (60, 70)`, `DEFINICIONES_MOTIVOS: dict[str, str]` (las 14 claves exactas de `MOTIVOS_INCONFORMIDAD`), `construir_instrucciones() -> str`.
- Esquema por caso suma `puntaje` (number 0–100) y `reglas_incumplidas` (array de strings), ambos requeridos.
- `aplicar_resultado_ia` guarda `fila["ia_puntaje"]` (int 0–100 o `""`) y `fila["ia_reglas"]` (lista ≤ 5 strings ≤ 160 c/u); filas nuevas inician ambas vacías.
- El payload del lote incluye `"definiciones_motivos": DEFINICIONES_MOTIVOS`.

- [ ] **Step 1: Tests:** `test_rubrica_suma_100`; `test_definiciones_cubren_todos_los_motivos` (mismas claves que `MOTIVOS_INCONFORMIDAD`); `test_instrucciones_contienen_reglas_clave` (contienen «5 min», «3 min», «15 min», «70%», «PMF», «ladesk», «crisp», «Dudoso»/«TAL VEZ»); `test_aplicar_resultado_normaliza_puntaje_y_reglas` (`puntaje=135`→100, `"abc"`→`""`, reglas no lista→`[]`, 7 reglas→5) *[Review Focus 2]*; `test_payload_incluye_definiciones`.
- [ ] **Step 2:** FAIL. **Step 3:** Implementar (las instrucciones explican también que `metricas_tiempo` viene en segundos y que las notas internas pueden traer códigos de llamada/enlaces de otros canales). **Step 4:** PASS + suite completa.
- [ ] **Step 5:** Commit `feat: criterios del equipo para la IA de la auditoría CSAT`.

### Task 2: Conversación completa y tiempos calculados

**Files:** Modify `utils/auditoria_csat_chatwoot.py` (`cargar_transcripciones`), `tools/auditoria_csat.py` (`construir_caso_auditoria_ia`, `CSAT_IA_MAX_TRANSCRIPT_CHARS = 12000`, limpieza tras la IA también de `metricas_tiempo`); Test `tests/test_auditoria_csat_chatwoot.py`, `tests/test_auditoria_csat.py`.

**Interfaces:** `cargar_transcripciones(filas, chatwoot, tz_name, max_chars=12000)` usa `construir_transcripcion_v2` y fija `fila["metricas_tiempo"] = metricas_tiempos(mensajes, periodo_agente(mensajes, agente_id, agente), agente_id, agente)`; ante error en métricas deja `{}` sin cortar. `construir_caso_auditoria_ia` agrega `"metricas_tiempo"` si existe.

- [ ] **Step 1: Tests:** transcripción incluye «Nota interna» con un `PMF-` simulado; métricas con primera respuesta en segundos; conversación sin respuesta del agente → sin excepción, `primera_respuesta` `None` *[Review Focus 1]*; fila CSV sin `conversation_id` → caso sin `metricas_tiempo` *[Review Focus 3]*; tras `auditar_con_ia` (ruta) el estado no conserva transcripción ni métricas.
- [ ] **Step 2–4:** FAIL → implementar → PASS + suite.
- [ ] **Step 5:** Commit `feat: la IA de CSAT ve notas internas y tiempos calculados`.

### Task 3: Mostrar puntaje y reglas en la ficha

**Files:** Modify `utils/auditoria_csat_vista.py` (`ia` suma `puntaje`, `reglas`), `templates/auditoria_csat.html` (caja IA: «Rúbrica N%» y «Rompió: a; b»), `static/auditoria_csat.js` solo si reconstruye la caja IA; Test `tests/test_auditoria_csat_vista.py`, `tests/test_auditoria_csat_ruta.py`.

- [ ] **Step 1: Tests:** ficha con `ia_puntaje=58`, `ia_reglas=["primera respuesta de 7 min"]` → HTML con «Rúbrica 58%» y «Rompió: primera respuesta de 7 min»; ficha sin esos campos (como tras reabrir de Supabase) → sin «Rúbrica» y sin error *[Review Focus 4]*.
- [ ] **Step 2–4:** FAIL → implementar → PASS + suite; `node --check` si se tocó JS.
- [ ] **Step 5:** Commit `feat: la ficha muestra la rúbrica y las reglas incumplidas`.
