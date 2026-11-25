# Auditoría CSAT por fichas — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rehacer la pantalla de Auditoría CSAT como un flujo guiado de 4 pasos con una ficha por negativo, guardado al instante sin recargar y CSAT real vs ajustado siempre visible.

**Architecture:** La lógica de presentación (pasos, KPIs, fichas, pestañas) va a un módulo puro nuevo `utils/auditoria_csat_vista.py` que recibe filas y métricas. `tools/auditoria_csat.py` suma la acción `decidir` (una fila, JSON o HTML) y deja de leer todas las filas del formulario salvo en `guardar_auditoria`. El template se reescribe con un formulario por ficha (funciona sin JS) y `static/auditoria_csat.js` lo mejora: cola de envíos, actualización de la ficha, KPIs, pasos y pestañas, y propagación del `analysis_id` nuevo a todos los formularios.

**Tech Stack:** Flask + Jinja, JS sin librerías, pytest.

**Spec:** `docs/superpowers/specs/2026-11-25-auditoria-csat-fichas-design.md` (boceto aprobado: `.superpowers/brainstorm/68-1795639554/content/csat-fichas.html`).

## Global Constraints

- UI en español; estilos compartidos en `static/styles.css` (sin CSS grande en el template); tema oscuro y tarjetas `card` del admin; sin SPA ni librerías nuevas.
- Valores internos sin cambio: `justificable` ∈ `"" | "NO" | "TAL VEZ" | "SÍ"`; `origen_decision` ∈ `"" | "humana" | "ia_aceptada"`. CSV exportado y bloque del informe sin cambio.
- Textos de decisión en pantalla: `"SÍ"` → «No fue culpa del agente», `"NO"` → «Sí fue culpa del agente», `"TAL VEZ"` → «Dudoso». KPIs: «CSAT real», «CSAT ajustado».
- Confirmada = tiene `justificable` (humana o ia_aceptada). Insignia: «tú» / «aceptado de la IA».
- El estado viaja firmado en `analysis_id`; **cada respuesta trae uno nuevo** y la siguiente petición usa el último.
- Límite 60 s por petición (Vercel). Sin scroll horizontal a 375 px; fichas y barras hacen wrap.
- Sin JS todo sigue funcionando (cada botón envía su formulario y recarga).
- Tests sin red ni Supabase reales.

## Review Focus

1. **Acciones de la barra (IA, aceptar todo, descargas) enviadas sin campos de filas** — no deben borrar decisiones ya tomadas (hoy `actualizar_estado_desde_formulario` corre para todas las acciones). Test en Task 3.
2. **Dos decisiones seguidas encadenando el token devuelto** — ambas quedan guardadas. Test en Task 3.
3. **`decidir` con `row_id` inexistente, fila no negativa o `justificable` inválido** — no cambia nada y avisa (JSON `ok: false`, HTML con advertencia). Test en Task 3.
4. **Supabase falla al decidir** — la decisión queda en el estado firmado y vuelve `advertencia`; no se pierde. Test en Task 3.
5. **Período sin negativos** — pasos 2 y 3 «hecho», sin fichas, mensaje «¡Listo!…». Test en Task 2.

---

### Task 1: El respaldo de la IA recibe el tiempo que sobra

**Files:**
- Modify: `tools/auditoria_csat.py` (`auditar_lote_con_proveedor`, constantes cerca de `CSAT_IA_PRESUPUESTO_SEGUNDOS`)
- Test: `tests/test_auditoria_csat.py`

**Interfaces:** sin cambios de firma.

Regla: con respaldo, el principal usa `CSAT_IA_PRESUPUESTO_SEGUNDOS // 2` (24); el respaldo usa `max(CSAT_IA_RESPALDO_MINIMO_SEGUNDOS, int(CSAT_IA_PRESUPUESTO_SEGUNDOS - transcurrido))` con `CSAT_IA_RESPALDO_MINIMO_SEGUNDOS = 10`, midiendo con `time.monotonic()`. Sin respaldo, el principal usa 48. El resto (mensajes con modelos probados, temporal/diario) igual.

- [ ] **Step 1:** Actualizar `test_usa_modelo_de_respaldo_si_el_principal_no_tiene_cupo`: el principal recibe 24 y el respaldo `>= 46` (el falso del principal falla al instante). Nuevo `test_respaldo_recibe_el_minimo_si_el_principal_agoto_el_tiempo`: `monkeypatch` de `csat.time.monotonic` para simular 45 s transcurridos → respaldo recibe 10. Nuevo `test_sin_respaldo_el_principal_usa_todo_el_tiempo` → 48.
- [ ] **Step 2:** `python -m pytest tests/test_auditoria_csat.py -q` → FAIL.
- [ ] **Step 3:** Implementar (`import time` a nivel de módulo para poder parchear `csat.time.monotonic`).
- [ ] **Step 4:** PASS; suite completa PASS (baseline 439).
- [ ] **Step 5:** Commit `fix: el respaldo de la IA de CSAT usa el tiempo que deja el principal`.

---

### Task 2: Módulo de vista (pasos, KPIs, fichas, pestañas)

**Files:**
- Create: `utils/auditoria_csat_vista.py`
- Modify: `tools/auditoria_csat.py` (`construir_contexto_analisis` agrega `"vista"`)
- Test: `tests/test_auditoria_csat_vista.py`

**Interfaces (Produces):**
- `TEXTO_DECISION = {"SÍ": "No fue culpa del agente", "NO": "Sí fue culpa del agente", "TAL VEZ": "Dudoso"}`
- `construir_kpis(metricas: dict) -> dict` con claves `csat_real` (= `metricas["csat_original"]`), `csat_ajustado` (= `csat_actualizado`), `delta` (`round(ajustado - real, 2)`), `excluidos` (= `negativos_si`), `negativos`, `por_confirmar` (negativos sin `justificable`).
- `construir_pasos(filas: list[dict]) -> list[dict]`, 4 dicts en orden con `clave` ∈ `encuestas | ia | confirmar | resultado`, `titulo` («Encuestas», «La IA revisa», «Tú confirmas», «Resultado»), `estado` ∈ `hecho | actual | pendiente`, `detalle`:
  - encuestas: hecho si hay filas; `"{total} encuestas · {neg} negativas"`.
  - ia: M = negativos con `origen_decision != "humana"`; N = de ellos con `ia_justificable`; hecho si `N == M`; `"{N} de {M} con propuesta"` (M = 0 → `"Sin negativos por revisar"`).
  - confirmar: C = negativos con `justificable`; hecho si `C == neg`; `"{C} de {neg} confirmadas"`.
  - resultado: hecho si confirmar está hecho; `"CSAT final e informe"`.
  - `actual` = el primer paso no hecho; el resto no hechos = `pendiente`.
- `construir_fichas(filas: list[dict]) -> list[dict]` solo negativos, orden: sin `justificable` primero, luego por `fecha_iso`. Claves: `row_id`, `agente`, `estrellas` (int 0–5 de `calificacion`), `fecha` (`fecha_registrada`), `comentario`, `conversation_id` (o None), `enlace` (`enlace_conversacion`), `ia` (None o dict `decision`, `texto` = `TEXTO_DECISION[...]`, `motivo`, `confianza`, `evidencia`), `justificable`, `decision_texto`, `motivo` (`motivo_inconformidad` o, si vacío, `ia_motivo`), `nota` (`comentario_auditor`), `origen_texto` («tú» / «aceptado de la IA» / ""), `confirmada` (bool).
- `contar_pestanas(filas: list[dict]) -> dict` `{"por_confirmar", "confirmados", "todos"}` sobre negativos.
- `construir_vista(filas: list[dict], metricas: dict) -> dict` `{"kpis", "pasos", "fichas", "pestanas"}`; `construir_contexto_analisis` la expone como `contexto["vista"]` (llamando `construir_metricas` una sola vez).

- [ ] **Step 1: Tests** (`tests/test_auditoria_csat_vista.py`, filas armadas a mano con `tipo_rating`, `justificable`, `ia_justificable`, `origen_decision`, `calificacion`, `fecha_iso`):
  - `test_pasos_en_curso`: 3 negativos (1 humana NO, 1 con propuesta, 1 sin nada) + 2 positivos → detalles `"5 encuestas · 3 negativas"`, `"1 de 2 con propuesta"`, `"1 de 3 confirmadas"`; estados `hecho, actual, pendiente, pendiente`.
  - `test_pasos_sin_negativos` *[Review Focus 5]*: solo positivos → ia y confirmar `hecho`, resultado `hecho`, `construir_fichas == []`.
  - `test_fichas_orden_y_textos`: pendiente antes que confirmada; ficha con `ia_justificable="SÍ"` → `ia["texto"] == "No fue culpa del agente"`; confirmada con `origen_decision="ia_aceptada"` → `origen_texto == "aceptado de la IA"`; motivo vacío toma `ia_motivo`.
  - `test_kpis`: métricas `{"csat_original": 77.33, "csat_actualizado": 80.1, "negativos_si": 3, "negativos": 14}` + filas → `delta == 2.77`, `excluidos == 3`.
  - `test_contexto_incluye_vista`: `construir_contexto_analisis({"rows": filas})["vista"]` tiene las 4 claves.
- [ ] **Step 2:** `python -m pytest tests/test_auditoria_csat_vista.py -q` → FAIL.
- [ ] **Step 3:** Implementar (módulo sin imports de `tools`).
- [ ] **Step 4:** PASS; suite completa PASS.
- [ ] **Step 5:** Commit `feat: vista por pasos y fichas de la auditoría CSAT`.

---

### Task 3: Acción `decidir` y acciones que no tocan filas

**Files:**
- Modify: `tools/auditoria_csat.py` (ruta, `sincronizar_periodo`, `persistir_estado`, nueva `aplicar_decision`)
- Test: `tests/test_auditoria_csat_ruta.py`

**Interfaces:**
- Consumes: `construir_vista`, `TEXTO_DECISION` (Task 2); `quiere_json`, `persistir_estado`, `cargar_estado_chatwoot` existentes.
- Produces:
  - `aplicar_decision(estado: dict, row_id: str, justificable: str, motivo: str, nota: str) -> str` → `""` si aplicó, o el error en español (`"No se encontró ese negativo."`, `"Elige una decisión válida."`). Solo filas `tipo_rating == "Negativo"`; `justificable` vía `normalizar_justificable` y no vacío; motivo fuera de `MOTIVOS_INCONFORMIDAD` → `""`; `nota` ≤ 500; fija `origen_decision="humana"`, `estado_auditoria`, `csat_flag`.
  - `sincronizar_periodo(estado, retencion=True)` y `persistir_estado(estado, retencion=True)`: con `retencion=False` no llama `borrar_vencidos`.
  - `POST /auditoria-csat` `accion=decidir` (campos `analysis_id`, `period_id` opcional, `row_id`, `justificable`, `motivo`, `nota`): aplica, `persistir_estado(estado, retencion=False)`.
    - JSON: `{"ok": bool, "error": str, "advertencia": str, "analysis_id": str, "ficha": <dict de construir_fichas para esa fila>, "kpis": {...}, "pasos": [...], "pestanas": {...}}`; con error, `ok: false` y estado sin cambios (igual devuelve `analysis_id` recibido).
    - HTML: la página completa (advertencia si hubo error).
  - En la ruta, `actualizar_estado_desde_formulario` solo se llama para `accion == "guardar_auditoria"`.

- [ ] **Step 1: Tests** (con fixtures existentes `cliente`, `store`, `chatwoot`, helpers `_traer`, `_hidden`):
  - `test_decidir_json_guarda_una_fila`: traer 2 negativos; `decidir` row 1 `SÍ` motivo `CAPTCHA` nota `n` con `Accept: application/json` → `ok`, `ficha["confirmada"]`, `kpis["por_confirmar"] == 1`, `pestanas["confirmados"] == 1`; en `store.negativos(pid)` row 1 `decision_final == "SÍ"`, `origen_decision == "humana"`, row 2 sin decisión.
  - `test_dos_decisiones_encadenadas` *[Review Focus 2]*: segunda con el `analysis_id` devuelto → ambas guardadas.
  - `test_decidir_invalido_no_cambia_nada` *[Review Focus 3]*: `row_id` inexistente, fila positiva y `justificable=""` → `ok: false` con error en español y store sin cambios.
  - `test_decidir_sin_js_recarga_con_ficha_confirmada`: sin `Accept` → 200 y el HTML contiene «Confirmado».
  - `test_decidir_con_supabase_caido_conserva_la_decision` *[Review Focus 4]*: `store.reemplazar_negativos` lanza → `ok: true`, `advertencia` no vacía, y `herramienta.cargar_analisis(resp["analysis_id"])` (en `app.app_context()`) tiene la decisión.
  - `test_acciones_sin_filas_no_borran_decisiones` *[Review Focus 1]*: decidir row 1; luego `aceptar_propuestas_ia` y `descargar_csv_auditado` enviando solo `analysis_id`/`period_id` → la decisión sigue (store y CSV).
  - `test_decidir_no_aplica_retencion`: `store.borrar_vencidos` con contador → 0 llamadas en `decidir`.
- [ ] **Step 2:** `python -m pytest tests/test_auditoria_csat_ruta.py -q` → FAIL.
- [ ] **Step 3:** Implementar.
- [ ] **Step 4:** PASS; suite completa PASS.
- [ ] **Step 5:** Commit `feat: decidir un negativo a la vez en la auditoría CSAT`.

---

### Task 4: Pantalla nueva (template + estilos)

**Files:**
- Modify: `templates/auditoria_csat.html` (reescritura del bloque de contenido; se conserva el `<script>` de filtros solo si algo lo usa, si no se elimina)
- Modify: `static/styles.css` (clases nuevas con prefijo `csat-`), `app.py` (`ASSET_VERSIONS["styles.css"]` +1)
- Test: `tests/test_auditoria_csat_ruta.py`

**Interfaces:**
- Consumes: `contexto.vista` (Task 2), acción `decidir` (Task 3), ruta `auditoria_csat.conversacion_csat`.
- Produces (contrato con Task 5; atributos exactos):
  - KPIs: `[data-csat-kpi="csat_real|csat_ajustado|delta|excluidos|negativos|por_confirmar"]`.
  - Pasos: `[data-csat-paso="<clave>"]` con clase `is-hecho|is-actual|is-pendiente` y hijo `[data-csat-paso-detalle]`.
  - Pestañas: botones `[data-csat-pestana="por_confirmar|confirmados|todos"]` con `[data-csat-pestana-conteo]`.
  - Ficha: `<form method="post" class="csat-ficha" data-csat-ficha data-row-id="…" data-confirmada="0|1">` con hidden `accion=decidir`, `analysis_id`, `period_id`, `row_id`; botones `name="justificable"` valores `SÍ`, `NO`, `TAL VEZ` (el de la IA con clase `is-sugerido`, el de la decisión actual con `is-actual`); `select name="motivo"`; `textarea name="nota"`; zona `[data-csat-ficha-estado]` para «Guardando…»/errores; versión compacta `[data-csat-ficha-resumen]` y botón `[data-csat-cambiar]`.
  - Barra de acciones: `<form method="post" data-csat-acciones>` con hidden `analysis_id`/`period_id` y botones `auditar_con_ia` (`data-csat-ia`), `aceptar_propuestas_ia`, descargas; `[data-csat-ia-estado]` como hoy.
  - Vacío sin pendientes: `[data-csat-listo]` «¡Listo! No quedan negativos por confirmar» con enlace a `#csat-resultado`.

Estructura y textos según el spec (barra superior; 4 pasos; 4 KPIs con «▲/▼ delta» y «Sin N negativos que no fueron culpa del agente»; pestañas + acciones; fichas; `<details id="csat-resultado">` con por agente, motivos, gráficos, hallazgos y descargas; `<details>` guardadas; `<details>` CSV). Sin auditoría abierta: barra superior, explicación de los 4 pasos y guardadas abiertas. Sin JS, todas las fichas se muestran (pendientes primero) y las pestañas quedan como encabezado con conteos.

- [ ] **Step 1: Tests:**
  - `test_pagina_muestra_pasos_kpis_y_fichas`: traer (2 negativos, 1 positivo) → HTML contiene `data-csat-paso="confirmar"`, `data-csat-kpi="csat_ajustado"`, 2 `data-csat-ficha`, «No fue culpa del agente», y no contiene «SÍ justificable» ni «CSAT actualizado».
  - `test_ficha_con_propuesta_ia_en_lenguaje_claro`: con propuesta `SÍ` → «La IA cree» y «No fue culpa del agente» dentro de la ficha.
  - `test_pagina_sin_auditoria_explica_los_pasos`: GET sin estado → «Tú confirmas» y sin `data-csat-ficha`.
  - `test_csv_usa_fichas`: CSV con 1 negativo → 1 `data-csat-ficha` y `period_id` vacío.
- [ ] **Step 2:** FAIL. **Step 3:** Implementar. **Step 4:** PASS; suite completa PASS (ajustar tests existentes que dependan de la tabla vieja solo en selectores, sin cambiar lo que verifican).
- [ ] **Step 5: Verificación visual:** servidor local con datos simulados (como en PRs anteriores: Chatwoot/IA falsos, sin Supabase, Modo prueba) y navegador a escritorio y 375 px: sin scroll horizontal, fichas legibles, resultado plegado.
- [ ] **Step 6:** Commit `feat: pantalla de la auditoría CSAT por pasos y fichas`.

---

### Task 5: JavaScript — guardado al instante, pestañas y token

**Files:**
- Modify: `static/auditoria_csat.js`, `app.py` (`ASSET_VERSIONS["auditoria_csat.js"]` +1)

**Interfaces:** Consumes el contrato de atributos de Task 4 y el JSON de `decidir` (Task 3).

Comportamiento:
- Al pulsar un botón de decisión en una ficha: `preventDefault`, encolar `{form, justificable}`; la cola envía **de a uno** (`fetch` POST `FormData(form)` + `justificable`, `Accept: application/json`) usando el **último `analysis_id`** conocido.
- Tras cada respuesta: escribir `analysis_id` en **todos** los `input[name="analysis_id"]` de la página; con `ok` → ficha a compacta (`data-confirmada="1"`, resumen con decisión, motivo, nota, insignia «tú»), actualizar KPIs, pasos (clases + detalle), conteos de pestañas y mostrar `[data-csat-listo]` si `por_confirmar == 0`; `advertencia` visible arriba si viene. Con `ok: false` o error de red → la ficha vuelve a su estado y muestra el error.
- La ficha confirmada **no se oculta** en «Por confirmar» hasta cambiar de pestaña.
- Pestañas: filtran por `data-confirmada`; por defecto «Por confirmar» (si no hay pendientes, «Todos»).
- `[data-csat-cambiar]` reabre la ficha (sin enviar nada).
- El botón de IA existente sigue igual pero usa el formulario `[data-csat-acciones]` y, al terminar, `ver_estado` con el último token.
- Si `fetch` no existe o falla la carga del script, los formularios se envían normal.

- [ ] **Step 1:** `node --check static/auditoria_csat.js` → OK.
- [ ] **Step 2: Verificación en navegador** con el servidor local simulado (Modo prueba): confirmar 3 fichas rápido seguidas → las 3 quedan confirmadas tras recargar (`ver_estado`), KPIs y «Por confirmar» bajan en vivo, pestañas filtran, «cambiar» reabre, «Revisar con IA» sigue funcionando después de decidir (usa el token nuevo). Probar también con JS desactivado (un clic recarga con la ficha confirmada).
- [ ] **Step 3:** Suite completa PASS.
- [ ] **Step 4:** Commit `feat: guardado al instante de las decisiones en la auditoría CSAT`.

---

### Task 6: Limpieza y documentación

**Files:**
- Modify: `tools/auditoria_csat.py` (eliminar del contexto lo que el template ya no usa, p. ej. `filtros`, solo si ningún test/plantilla lo usa), `README.md` (sección Auditoría CSAT: flujo por pasos y fichas, botones con palabras)

- [ ] **Step 1:** `grep` de cada clave del contexto en templates/tests; quitar solo las no usadas.
- [ ] **Step 2:** Actualizar README.
- [ ] **Step 3:** Suite completa PASS.
- [ ] **Step 4:** Commit `docs: auditoría CSAT por fichas en el README`.
