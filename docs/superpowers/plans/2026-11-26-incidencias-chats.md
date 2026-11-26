# Incidencias de chats — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Herramienta nueva «Incidencias de chats». Revisa todos los chats de Chatwoot creados en un rango de fecha y hora con un motor de reglas propio y muestra dos listas resaltadas, «Reportes de clientes» y «Mala atención». El manager marca cada chat como atendida o como falso positivo. La IA es opcional y solo confirma los chats marcados.

**Architecture:** Hay un módulo puro de reglas (`utils/incidencias_chats_reglas.py`). Un motor por pasos (`utils/incidencias_chats_motor.py`) recorre los estados `listando → evaluando → ia → completado`, igual que `utils/auditoria_chats_motor.py`. El store tiene dos versiones: Supabase en producción y memoria en pruebas y en Modo prueba. El blueprint `tools/incidencias_chats.py` lleva sus templates y `static/incidencias_chats.js`, que consulta el avance de cada paso.

**Tech Stack:** Flask + Jinja, JS sin librerías, Supabase (`supabase-py`, ya instalado), pytest.

**Spec:** `docs/superpowers/specs/2026-11-26-incidencias-chats-design.md`

## Global Constraints

- UI en español, con estilos compartidos en `static/styles.css`. Nada de CSS grande, `<script>` en línea, `onclick` ni `style=""` en los templates (CSP). Sin SPA y sin dependencias nuevas.
- Al tocar CSS o JS hay que subir su número en `ASSET_VERSIONS` de `app.py` (`styles.css` y el nuevo `incidencias_chats.js`).
- Cada tabla va dentro de un `table-wrap`. Sin scroll horizontal global a 375 px. Formularios y barras deben hacer wrap.
- Los secretos se quedan en el backend. Nunca se guardan transcripciones completas. `transcripcion_tmp` solo existe mientras se llama a la IA y se borra después.
- La evidencia pasa siempre por `anonimizar()` y mide como máximo **200** caracteres.
- Valores fijos: rango máximo **72 h**, en Modo prueba **12 h** y **30** chats; presupuesto por paso **8 s**; **3** intentos de lectura por chat; cupo de IA `INCIDENCIAS_CHATS_AI_CUPO_DIARIO` (por defecto **10**); `REGLAS_VERSION = "1"`.
- Zona horaria: `_timezone()` de `utils/chatwoot_reportes.py` (`CHATWOOT_TIMEZONE`).
- No se cambia el comportamiento de `ChatwootClient` existente, de `_es_respuesta_agente`, de `_listar_bandejas` ni de ninguna otra herramienta. A `ChatwootClient` solo se le **agrega** un método.
- Los tests no hacen red ni usan Supabase real (`tests/conftest.py`). La IA se simula con monkeypatch de `motor.completar_json`.
- Las variables nuevas van en `.env.example` y en `README.md`.

## Review Focus

1. **Revisión lanzada a las 18:05 sobre un chat abierto a las 17:58 que todavía espera** → no debe aparecer «Sin atención» ni «Cliente ignorado», porque no superó el umbral. El test está en la Task 1.
2. **Un chat cuya única respuesta saliente es de un bot o un mensaje automático** → cuenta como «Sin atención», y el saludo del bot no cuenta como primera respuesta. El test está en la Task 1.
3. **Dos revisiones que se pisan** → un chat resuelto, con la misma versión de reglas y sin actividad nueva se copia sin releer Chatwoot. Si el chat se reabrió o tuvo actividad, se vuelve a leer. El test está en la Task 4.
4. **Dos pestañas que avanzan la misma revisión** → no se duplican filas y ningún chat se evalúa dos veces. El test está en la Task 4.
5. **Texto del cliente con HTML (`<script>`)** → en la evidencia aparece escapado y el `<mark>` sigue rodeando solo la coincidencia. El test está en la Task 6.

---

### Task 1: Reglas de mala atención

**Files:**
- Create: `utils/incidencias_chats_reglas.py`
- Test: `tests/test_incidencias_chats_reglas.py`

**Interfaces:**
- Consumes: `utils/auditoria_chats_transcripcion.py` → `_ordenados`, `_ts_mensaje`, `_es_cliente`, `_asignado_a`, `_texto`, `anonimizar`, `es_llamada`.
- Produces:
  - `REGLAS_VERSION = "1"`, `PRIMERA_RESPUESTA_MAX = 600`, `ESPERA_MAX = 900`, `IGNORADO_MENSAJES = 3`, `IGNORADO_SEGUNDOS = 600`, `SIN_ATENCION_ESPERA = 600`.
  - `es_respuesta_humana(mensaje: dict) -> bool`: verdadero si el mensaje es saliente (`message_type == 1`), no es privado, tiene texto y el remitente es de tipo `user`, leído de `mensaje["sender_type"]` o `mensaje["sender"]["type"]` sin distinguir mayúsculas. Si no hay remitente, o es `agent_bot`, `captain` u otro tipo, devuelve falso.
  - `agente_en(mensajes: list, ts: int, conversacion: dict) -> dict`: devuelve `{"id": int|None, "nombre": str}`. Toma la última asignación (`_asignado_a`) anterior a `ts`. Si no la hay, toma `conversacion["meta"]["assignee"]`. Si tampoco, devuelve `{"id": None, "nombre": "Sin asignar"}`. El `id` se completa con el `sender.id` de una respuesta humana del mismo nombre o con el id del asignado.
  - `reglas_atencion(mensajes: list, conversacion: dict, ahora: int) -> list[dict]`. Cada incidencia es `{"tipo": "atencion", "clave": str, "etiqueta": str, "severidad": "alta"|"media", "evidencia": str, "coincidencia": "", "mensaje_id": int|None, "ts": int, "agente_id": int|None, "agente_nombre": str, "origen": "reglas"}`.
  - Claves y etiquetas: `sin_atencion` «Sin atención» (alta), `cierre_sin_responder` «Cierre sin responder» (alta), `cliente_ignorado` «Cliente ignorado» (media), `primera_respuesta_tardia` «Primera respuesta tardía» (media), `espera_larga` «Espera larga» (media). En chats abiertos, las esperas que siguen en curso se miden hasta `ahora`. `cierre_sin_responder` solo aplica si `conversacion["status"] == "resolved"`. En las reglas de tiempo la evidencia es el dato en minutos, por ejemplo «Primera respuesta a los 23 min».

- [ ] **Step 1: Escribir los tests que fallan** en `tests/test_incidencias_chats_reglas.py`. Cada uno arma sus mensajes con un helper `_m(id, tipo, texto, t, sender_type="user")`:
  - `test_bot_no_cuenta_como_respuesta`: cliente en t=0 y bot (`sender_type="agent_bot"`) en t=5, chat resuelto → hay una incidencia con `clave == "sin_atencion"` y `severidad == "alta"`.
  - `test_mensaje_sin_remitente_es_automatico`: `es_respuesta_humana({"message_type": 1, "content": "Hola"})` devuelve `False`.
  - `test_chat_abierto_reciente_no_se_marca`: cliente en t=0, `status="open"`, `ahora=420` → `reglas_atencion(...) == []`.
  - `test_chat_abierto_esperando_mucho_es_sin_atencion`: lo mismo con `ahora=700` → aparece la clave `sin_atencion`.
  - `test_primera_respuesta_tardia`: cliente en t=0 y agente en t=1380 → aparece `primera_respuesta_tardia` y la evidencia dice «Primera respuesta a los 23 min». Además aparece `espera_larga`, porque 1380 > 900.
  - `test_primera_respuesta_a_tiempo`: agente en t=300 → no aparece ninguna de las dos claves.
  - `test_cliente_ignorado`: tres mensajes del cliente en t=0, 300 y 700 sin respuesta y `ahora=800` → aparece `cliente_ignorado`.
  - `test_cierre_sin_responder_solo_resuelto`: el último mensaje público es del cliente. Con `status="resolved"` aparece `cierre_sin_responder`; con `status="open"` no aparece.
  - `test_agente_por_asignacion`: un mensaje de actividad «Assigned to Ana Pérez by Admin» antes del problema, con `meta.assignee` = Luis → `agente_nombre == "Ana Pérez"`.
  - `test_sin_asignar`: sin asignación ni `assignee` → `agente_nombre == "Sin asignar"`.

- [ ] **Step 2: Ejecutar y comprobar que fallan.** Run: `python -m pytest tests/test_incidencias_chats_reglas.py -q`. Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implementar las constantes y funciones de Interfaces** en `utils/incidencias_chats_reglas.py`. Los mensajes privados y de actividad (`message_type == 2`) se ignoran en todo menos en `agente_en`.

- [ ] **Step 4: Ejecutar y comprobar que pasan.** Run: `python -m pytest tests/test_incidencias_chats_reglas.py -q`. Expected: PASS.

- [ ] **Step 5: Commit.** `git add utils/incidencias_chats_reglas.py tests/test_incidencias_chats_reglas.py` y `git commit -m "feat: reglas de mala atención para Incidencias de chats"`.

---

### Task 2: Reportes de clientes, frustración, CSAT y `evaluar_chat`

**Files:**
- Modify: `utils/incidencias_chats_reglas.py`
- Test: `tests/test_incidencias_chats_reglas.py`

**Interfaces:**
- Consumes: Task 1.
- Produces:
  - `CATEGORIAS_CLIENTE: dict[str, dict]`, con la forma `{clave: {"etiqueta": str, "severidad": str, "frases": tuple[str, ...]}}`. Las claves son `cobros` (alta), `fallas_app` (media), `no_recibido` (media), `acceso_cuenta` (media) y `reclamo_formal` (alta). Las frases iniciales son las de la tabla de la spec, escritas sin tildes y en minúsculas. Encima del dict va el comentario `# BORRADOR: validar con el equipo`.
  - `FRASES_FRUSTRACION: tuple[str, ...]`, con «nadie me responde», «pesima atencion», «hablar con un supervisor», «no me ayudan», «muy mal servicio».
  - `normalizar(texto: str) -> str`: minúsculas, sin tildes y con espacios colapsados.
  - `fragmento(texto: str, inicio: int, fin: int, maximo: int = 200) -> str`: devuelve el texto anonimizado, centrado en la coincidencia, con «…» en los bordes cortados.
  - `reglas_cliente(mensajes: list, conversacion: dict) -> list[dict]`. Solo revisa los mensajes de `_es_cliente`. Devuelve como máximo una incidencia por categoría y por chat, la primera que encuentre, con `tipo: "cliente"`, `clave = <categoría>` y `coincidencia` = la frase tal como aparece en el fragmento. La frustración se devuelve como `tipo: "atencion"`, `clave: "frustracion"`, «Frustración del cliente», severidad media.
  - `regla_csat(puntuacion: int|None, conversacion, mensajes) -> list[dict]`: si la puntuación está entre 1 y 2, devuelve `clave: "csat_bajo"` «CSAT bajo» con severidad media y la evidencia «CSAT {n}/5».
  - `evaluar_chat(mensajes: list, conversacion: dict, ahora: int, csat: int|None = None) -> dict`. Devuelve `{"descartado": str|None, "incidencias": list, "resuelto": bool, "agente_id", "agente_nombre"}`. Pone `descartado = "llamada"` si `es_llamada`, y `"sin_cliente"` si no hay mensajes del cliente; en ambos casos devuelve `incidencias: []`. Los valores de `agente_*` vienen de `agente_en(mensajes, ahora, conversacion)`.

- [ ] **Step 1: Escribir los tests que fallan:**
  - `test_cobro_doble_con_tildes_y_mayusculas`: el cliente dice «Me COBRARON dos veces la recarga» → una incidencia `tipo == "cliente"` con `clave == "cobros"`, `severidad == "alta"` y `"COBRARON dos veces" in evidencia`.
  - `test_frase_del_agente_no_cuenta`: el agente dice «no funciona así» → `reglas_cliente(...) == []`.
  - `test_una_por_categoria`: el cliente dice «no funciona» dos veces → hay una sola incidencia `fallas_app`.
  - `test_evidencia_anonimizada_y_recortada`: un texto de 600 caracteres con un correo y la frase en el medio → `len(evidencia) <= 200`, el correo no aparece y el fragmento contiene la frase.
  - `test_frustracion_es_atencion`: el cliente dice «nadie me responde» → aparece `clave == "frustracion"` con `tipo == "atencion"`.
  - `test_csat_bajo`: `regla_csat(2, ...)` da una incidencia; `regla_csat(3, ...)` y `regla_csat(None, ...)` dan `[]`.
  - `test_evaluar_descarta_llamada_y_sin_cliente`.
  - `test_evaluar_junta_todo`: un chat resuelto con cobro, respuesta tardía y CSAT 1 → aparecen las claves `cobros`, `primera_respuesta_tardia` y `csat_bajo`.

- [ ] **Step 2: Ejecutar y comprobar que fallan.** Run: `python -m pytest tests/test_incidencias_chats_reglas.py -q`. Expected: FAIL en los tests nuevos.
- [ ] **Step 3: Implementar.** La búsqueda se hace sobre `normalizar(texto)`. La posición se lleva al texto original, que mide lo mismo si la normalización se hace carácter a carácter: quitar tildes con NFD y descartar los combinantes conservando el índice. Si eso no se puede garantizar, se busca con un regex insensible a tildes armado desde la frase.
- [ ] **Step 4: Ejecutar y comprobar que pasan.** Mismo comando. Expected: PASS.
- [ ] **Step 5: Commit** con el mensaje `"feat: reportes de clientes, frustración y CSAT en Incidencias de chats"`.

---

### Task 3: Listado en Chatwoot, SQL y store

**Files:**
- Modify: `utils/chatwoot_reportes.py`: agregar el método `conversaciones_en_rango` debajo de `conversaciones_de_agente`.
- Create: `supabase_chat_incidents.sql`, `utils/incidencias_chats_store.py`
- Test: `tests/test_incidencias_chats_store.py`, `tests/test_chatwoot_reportes.py` (agregar un test)

**Interfaces:**
- Produces:
  - `ChatwootClient.conversaciones_en_rango(self, since, until, page=1, inbox_ids=None) -> list`. Es el mismo payload y el mismo relleno de un día por cada lado que `conversaciones_de_agente`, pero **sin** el filtro de `assignee_id`. El recorte exacto lo hace quien llama.
  - SQL, con RLS activado y sin políticas, al estilo de `supabase_chat_audits.sql`:
    - `chat_incident_reviews` con las columnas de la spec, más `csat jsonb` (mapa conversación → puntuación, `null` mientras no se haya pedido) y `csat_error text`. Estados permitidos: `listando`, `evaluando`, `ia`, `completado`, `con_errores`.
    - `chat_incident_chats` con las columnas de la spec, más `intentos int default 0`, `last_activity_at bigint` y `status text`, y **sin** las columnas `decision*`. Índice único en `(review_id, conversation_id)` e índice en `(conversation_id, updated_at)`.
    - `chat_incident_decisions` con `conversation_id bigint primary key`, `decision text check (decision in ('atendida','falso_positivo'))`, `por text`, `nota text`, `review_id uuid` y `decidido_at timestamptz`. La decisión es por conversación, como dice la spec en la precisión 3.
    - `chat_incident_ai_usage` con `fecha date primary key` y `usados int not null default 0`.
  - `utils/incidencias_chats_store.py`, con `IncidenciasError`, `IncidenciasConfigError`, `SupabaseIncidenciasStore`, `MemoriaIncidenciasStore` y `obtener_store()`. Las dos clases tienen esta interfaz:
    - `crear_revision(datos) -> dict`, `obtener_revision(id)`, `actualizar_revision(id, cambios)`, `listar_revisiones(limite=20)`.
    - `insertar_chats(filas) -> int`: hace upsert con `ignore_duplicates` sobre `review_id,conversation_id` y devuelve cuántas filas insertó.
    - `tomar_siguiente(review_id, estados, nuevo_estado) -> dict|None`: toma el chat de forma atómica, igual que en `auditoria_chats_store`.
    - `actualizar_chat(id, cambios)` y `listar_chats(review_id)`.
    - `ultima_evaluacion(conversation_id, excluir_review_id) -> dict|None`: devuelve la fila `evaluado` más reciente de otra revisión.
    - `decisiones(conversation_ids) -> dict[int, dict]` y `guardar_decision(conversation_id, datos)`, que hace upsert.
    - `usos_ia(fecha: date) -> int` y `sumar_uso_ia(fecha: date) -> int`.

- [ ] **Step 1: Escribir los tests que fallan:**
  - `test_conversaciones_en_rango_sin_assignee` en `tests/test_chatwoot_reportes.py`: con `post` simulado, ningún filtro del payload tiene `attribute_key == "assignee_id"` y el último no lleva `query_operator`.
  - En `tests/test_incidencias_chats_store.py`, sobre `MemoriaIncidenciasStore`:
    - `test_insertar_duplicado_no_repite`: insertar dos veces la misma conversación en la misma revisión da 1 y luego 0.
    - `test_tomar_siguiente_no_entrega_dos_veces`.
    - `test_ultima_evaluacion_ignora_misma_revision`.
    - `test_decision_por_conversacion_se_sobrescribe`.
    - `test_usos_ia_por_fecha`.
- [ ] **Step 2: Ejecutar y comprobar que fallan.** Run: `python -m pytest tests/test_incidencias_chats_store.py tests/test_chatwoot_reportes.py -q`. Expected: FAIL.
- [ ] **Step 3: Implementar** el método, el SQL y el store, copiando el estilo de `utils/auditoria_chats_store.py`: `_execute`, `_todas` paginado y los mensajes de error que apuntan a `supabase_chat_incidents.sql`.
- [ ] **Step 4: Ejecutar y comprobar que pasan.** Mismo comando, más `python -m pytest tests/test_auditoria_chats_motor.py -q` para confirmar que Auditoría de chats sigue igual. Expected: PASS.
- [ ] **Step 5: Commit** con el mensaje `"feat: store, SQL y listado por rango para Incidencias de chats"`.

---

### Task 4: Motor por pasos (listar, CSAT, evaluar, reutilizar)

**Files:**
- Create: `utils/incidencias_chats_motor.py`
- Test: `tests/test_incidencias_chats_motor.py`

**Interfaces:**
- Consumes: las Tasks 1 a 3, `ChatwootClient.mensajes_de_conversacion`, `ChatwootClient.respuestas_csat`, y las claves de conversación y puntuación que usa `utils/auditoria_csat_chatwoot.filas_desde_encuestas`.
- Produces:
  - `MAX_HORAS = 72`, `PRESUPUESTO_PASO = 8.0`, `MAX_INTENTOS = 3`, `MAX_PAGINAS_LISTADO = 200`.
  - `crear_revision(store, *, since: int, until: int, bandejas: list[int], usar_ia: bool, creado_por: str) -> dict`. Lanza `ValueError` con un mensaje en español si `until <= since` o si el rango supera `MAX_HORAS`.
  - `ejecutar_paso(store, review_id, chatwoot, config_ia, ahora=None, reloj=time.monotonic) -> dict`. Devuelve `{"accion": str, "estado": str, "mensaje": str, "esperar_segundos": int, "progreso": {"total", "evaluados", "descartados", "con_incidencias", "errores"}}`. Las acciones posibles son `csat`, `listado`, `evaluacion`, `ia`, `espera`, `error` y `fin`. El orden de un paso es:
    1. recuperar los chats que quedaron en `procesando` (abandonados);
    2. si `csat is None`, una llamada a `respuestas_csat(since, until + 3 días)`; si falla, se guarda `csat = {}` y `csat_error`;
    3. si el estado es `listando`, una página de `conversaciones_en_rango` con el recorte exacto por `created_at` y bandeja; cuando una página llega vacía (o se llega a `MAX_PAGINAS_LISTADO`), el estado pasa a `evaluando`;
    4. si el estado es `evaluando`, se toman chats `pendiente` hasta agotar `PRESUPUESTO_PASO`, se lee cada uno y se aplica `evaluar_chat`;
    5. el paso de IA (Task 5);
    6. al terminar, el estado queda en `completado`, o en `con_errores` si algún chat quedó en `error`.
  - Reutilización: al insertar desde el listado, si `ultima_evaluacion` es una fila `resuelto=True` con la misma `reglas_version`, el `status` del listado es `"resolved"` y el `last_activity_at` coincide, la fila nueva se inserta directamente como `evaluado` con las `incidencias`, el `ia_estado` y el `ia_resultado` copiados.
  - Errores de lectura: se suma un intento y el chat vuelve a `pendiente`; al llegar a `MAX_INTENTOS` queda en `error`. `reintentar_errores(store, review_id) -> int` devuelve esos chats a `pendiente` con los intentos en 0.
  - `listas_revision(chats: list, decisiones: dict, agente: str = "", clave: str = "") -> dict`. Devuelve `{"cliente": [fila], "atencion": [fila], "agentes": [str], "claves": [(clave, etiqueta)]}`, con las filas ordenadas por severidad (alta primero) y después por `ts`. Cada fila es `{**incidencia, "conversation_id", "chat_id", "status", "ia_estado", "ia_motivo", "decision", "antes", "marca", "despues"}`; `antes`, `marca` y `despues` salen de partir `evidencia` por `coincidencia`, y si no hay coincidencia, `marca` queda vacía.
  - `filas_csv(revision, chats, decisiones, url_conversacion) -> list[list]`, con una fila por incidencia y las columnas: Chat, Enlace, Fecha, Agente, Tipo, Categoría, Severidad, Evidencia, IA, Decisión, Decidido por, Nota. Las celdas pasan por la misma protección contra fórmulas que `_celda_segura` en `auditoria_chats_motor`.
  - `revision_en_memoria(chatwoot, *, since, until, bandejas, maximo=30) -> dict`. Usa un `MemoriaIncidenciasStore`, no usa IA y corre pasos hasta terminar, dejando de listar en cuanto tiene `maximo` chats. Devuelve `{"revision", "chats", "parcial": bool, "vistos": int}`.

- [ ] **Step 1: Escribir los tests que fallan.** Usar un `ChatwootFalso` con `conversaciones_en_rango(since, until, page, inbox_ids=None)` paginado de 25 en 25, `mensajes_de_conversacion` y `respuestas_csat`. El `reloj` falso avanza 1 s por llamada.
  - `test_rango_invalido`: `until <= since` lanza `ValueError`, y 73 h también.
  - `test_recorte_exacto_por_created_at_y_bandeja`: las conversaciones fuera de rango o de otra bandeja no se insertan.
  - `test_corre_hasta_fin`: 30 chats, uno de ellos con cobro → el estado final es `completado`, `con_incidencias == 1` y `descartados` cuenta las llamadas.
  - `test_presupuesto_por_paso`: con un reloj que avanza 3 s, un paso evalúa como mucho 3 chats.
  - `test_reutiliza_resuelto_sin_releer`: una segunda revisión con el mismo chat resuelto, sin actividad nueva → `chatwoot.lecturas` no contiene ese id y las incidencias son iguales.
  - `test_relee_si_hubo_actividad`: el mismo caso con otro `last_activity_at` → el chat se lee.
  - `test_dos_pestanas`: dos `ejecutar_paso` alternados sobre la misma revisión → no se duplican `conversation_id` y cada chat se lee una sola vez.
  - `test_error_de_lectura_tres_intentos`: tras 3 fallos el chat queda en `error`, la revisión termina `con_errores` y `reintentar_errores` lo devuelve a `pendiente`.
  - `test_csat_falla_sigue`: si `respuestas_csat` lanza una excepción, la revisión completa igual y `csat_error` no queda vacío.
  - `test_listas_orden_y_marca`: una alta queda antes que una media, y `antes + marca + despues == evidencia`.
  - `test_revision_en_memoria_parcial`: con 40 chats y `maximo=30` → `parcial is True` y `len(chats) == 30`.
- [ ] **Step 2: Ejecutar y comprobar que fallan.** Run: `python -m pytest tests/test_incidencias_chats_motor.py -q`. Expected: FAIL.
- [ ] **Step 3: Implementar** según Interfaces. `ahora` vale `int(time.time())` cuando se recibe `None`.
- [ ] **Step 4: Ejecutar y comprobar que pasan.** Mismo comando. Expected: PASS.
- [ ] **Step 5: Commit** con el mensaje `"feat: motor por pasos de Incidencias de chats"`.

---

### Task 5: IA opcional con cupo diario

**Files:**
- Modify: `utils/incidencias_chats_motor.py`
- Test: `tests/test_incidencias_chats_motor.py`

**Interfaces:**
- Consumes: `utils/ia_chat.completar_json`, `IARateLimitError`, `IAConfigError`, `IARespuestaError`, y `construir_transcripcion_v2(mensajes, tz_name, max_chars=12000)`.
- Produces:
  - `cupo_ia() -> int`: lee `INCIDENCIAS_CHATS_AI_CUPO_DIARIO`, con 10 por defecto y 10 si el valor no es válido.
  - Durante `evaluando`, si `revision["usar_ia"]` está activo y el chat tiene incidencias, se guarda `transcripcion_tmp` y `ia_estado = "pendiente"`. Si no, `ia_estado = None`.
  - Paso `ia`: cuando ya no quedan chats `pendiente` y existe algún chat con `ia_estado="pendiente"`, se elige primero el de severidad alta. Si `usos_ia(hoy) >= cupo_ia()` o `config_ia["activa"]` es falso, todos los pendientes pasan a `ia_estado="sin_cupo"` y se sigue adelante.
  - La salida de la IA debe ser `{"incidencias": [{"indice": int, "confirmada": bool, "motivo": str}], "resumen": str, "incidencias_extra": [{"tipo": "cliente"|"atencion", "etiqueta": str, "evidencia": str}]}`. Se guarda en `ia_resultado`. Las extra se agregan a `incidencias` con `origen: "ia"`, `severidad: "media"` y la evidencia pasada por `fragmento`. Después se pone `ia_estado="hecha"`, se borra `transcripcion_tmp` y se llama a `sumar_uso_ia(hoy)`.
  - Errores: con un `IARateLimitError` diario → `sin_cupo` para todos los pendientes. Si no es diario → acción `espera` con los `esperar_segundos` del error. Con un `IAConfigError` o `IARespuestaError` → `ia_estado="error"` en ese chat, se borra `transcripcion_tmp` y la revisión sigue. **Ningún** error de IA deja la revisión sin terminar.
  - El prompt va en la constante `PROMPT_IA`, en español. Pide confirmar cada incidencia numerada, no inventar, citar texto del chat y responder solo en JSON.

- [ ] **Step 1: Escribir los tests que fallan:**
  - `test_ia_confirma_y_borra_transcripcion`: con `completar_json` simulado → `ia_estado == "hecha"`, `transcripcion_tmp is None` y `usos_ia(hoy) == 1`.
  - `test_ia_respeta_cupo`: con `INCIDENCIAS_CHATS_AI_CUPO_DIARIO=1` y dos chats marcados → una sola llamada, y el otro queda en `sin_cupo`.
  - `test_ia_alta_primero`.
  - `test_ia_limite_diario_termina`: `IARateLimitError(diario=True)` → la revisión queda `completado` y los pendientes en `sin_cupo`.
  - `test_ia_error_de_respuesta_no_bloquea`.
  - `test_sin_usar_ia_no_llama`: con `usar_ia=False` → `completar_json` no se llama nunca y no se guarda ninguna transcripción.
  - `test_incidencia_extra_de_ia`.
- [ ] **Step 2: Ejecutar y comprobar que fallan.** Run: `python -m pytest tests/test_incidencias_chats_motor.py -q`. Expected: FAIL en los tests nuevos.
- [ ] **Step 3: Implementar.**
- [ ] **Step 4: Ejecutar y comprobar que pasan.** Expected: PASS.
- [ ] **Step 5: Commit** con el mensaje `"feat: confirmación opcional con IA en Incidencias de chats"`.

---

### Task 6: Blueprint, pantallas, JS y navegación

**Files:**
- Create: `tools/incidencias_chats.py`, `templates/incidencias_chats.html`, `templates/incidencias_chats_revision.html`, `static/incidencias_chats.js`
- Modify: `app.py` (import, `register_blueprint`, y `ASSET_VERSIONS` con `"incidencias_chats.js": "1"` y `styles.css` subido en uno), `utils/navegacion.py` (entrada nueva), `static/styles.css` (solo las clases nuevas que hagan falta, con el prefijo `ic-`)
- Test: `tests/test_incidencias_chats.py`

**Interfaces:**
- Consumes: Tasks 3 a 5, `HORARIOS_TURNOS_CHATWOOT` y `_timezone`/`_obtener_timezone` de `utils/chatwoot_reportes.py`, `_listar_bandejas` de `tools/auditoria_chats.py` (importado sin cambios), y `mensaje_error_publico`.
- Produces: el blueprint `incidencias_chats_bp`. Para los tests expone `obtener_store()`, `obtener_chatwoot()` y `obtener_config_ia`, que se pueden reemplazar con monkeypatch. Rutas:
  - `GET /incidencias-chats/` → `index`. Muestra el formulario con estos campos: `desde_fecha`, `desde_hora`, `hasta_fecha`, `hasta_hora`, un selector de turno con `data-desde` y `data-hasta` (el JS rellena las horas; sin JS los campos se escriben a mano), las casillas `bandejas`, `usar_ia`, `prueba` y `creado_por`. Debajo van las últimas 20 revisiones. Si falta Supabase, se muestra el aviso y Modo prueba queda disponible. Si falta Chatwoot, se muestra el aviso y el formulario se desactiva.
  - `POST /incidencias-chats/revisiones` → `crear`. Si hay errores de validación, hace flash y redirect a `index`. Con `prueba`, el rango máximo es 12 h y se llama a `motor.revision_en_memoria`, que renderiza `incidencias_chats_revision.html` en modo lectura con el aviso «Modo prueba: no se guarda» y, cuando corresponde, «Resultado parcial: 30 de al menos N chats». En los demás casos se llama a `motor.crear_revision` y se redirige a `ver`.
  - `GET /incidencias-chats/revision/<review_id>` → `ver`, que acepta `?agente=&clave=`. Muestra contadores, el aviso «No se pudo leer el CSAT; se omitió la regla CSAT bajo» si hay `csat_error`, la etiqueta «abierto» en chats con `status != "resolved"`, barra de progreso (`data-ic-paso-url` mientras no haya terminado), las dos tablas en `table-wrap`, filtros por GET y el enlace al CSV. Si la revisión no existe, responde 404.
  - `POST /incidencias-chats/revision/<review_id>/paso` → `paso`. Con `Accept: application/json` devuelve JSON; si no, flash y redirect.
  - `POST /incidencias-chats/conversacion/<int:conversation_id>/decision` → `decidir`. Recibe `decision` (`atendida`|`falso_positivo`), `por` (obligatorio, hasta 80 caracteres), `nota` (hasta 500), `review_id` y los filtros para volver. Guarda una cookie `ic_por` por 180 días. Responde JSON `{"ok": bool, "mensaje": str}` o redirect a `ver`.
  - `POST /incidencias-chats/revision/<review_id>/reintentar-errores` y `GET /incidencias-chats/revision/<review_id>/csv`. El CSV se llama `incidencias_<desde>_<hasta>.csv` y se codifica `utf-8-sig`.
  - Evidencia en el template: `{{ fila.antes }}<mark>{{ fila.marca }}</mark>{{ fila.despues }}`, con autoescape y **sin** `|safe`.
  - Entrada en `utils/navegacion.py`: `{"endpoint": "incidencias_chats.index", "prefijo": "incidencias_chats.", "grupo": "Calidad", "titulo": "Incidencias de chats", "icono": "calidad", "descripcion": "Revisa los chats de un rango de horas y resalta reportes de clientes y mala atención.", "destacada": False}`, colocada después de Auditoría de chats.
  - `static/incidencias_chats.js` se encarga de tres cosas: el relleno de las horas por turno; un bucle que llama a `paso` con `fetch` y `Accept: application/json`, actualiza la barra, respeta `esperar_segundos` y recarga la página al llegar a `fin`; y el envío de decisiones sin recargar, que actualiza la celda de estado. Todo funciona también sin JS.

- [ ] **Step 1: Escribir los tests que fallan** en `tests/test_incidencias_chats.py`, con fixtures que reemplazan `obtener_store` por un `MemoriaIncidenciasStore` y `obtener_chatwoot` por un falso:
  - `test_index_carga_y_aparece_en_navegacion`: GET responde 200 y el HTML contiene «Incidencias de chats» y `href="/incidencias-chats/"`.
  - `test_crear_rango_invalido_avisa`: hasta antes que desde → redirect y flash.
  - `test_crear_y_avanzar_hasta_fin`: POST crear, luego `paso` en JSON hasta `fin`, luego GET `ver` → aparecen las dos tablas y el `#id` del chat con cobro.
  - `test_evidencia_escapada`: si el cliente escribe `<script>x</script> me cobraron dos veces`, la página muestra `&lt;script&gt;` y `<mark>me cobraron dos veces</mark>`.
  - `test_decision_guarda_por_conversacion_y_cookie`: queda guardada la decisión con `por` y la respuesta trae `Set-Cookie: ic_por=`.
  - `test_decision_sin_nombre_rechazada`.
  - `test_modo_prueba_no_usa_store`: con `obtener_store` reemplazado por algo que lanza una excepción, POST con `prueba=1` responde 200 y muestra «Modo prueba: no se guarda».
  - `test_csv`: el content-type es `text/csv`, existe la cabecera «Evidencia» y hay una fila por incidencia.
  - `test_revision_inexistente_404`.
- [ ] **Step 2: Ejecutar y comprobar que fallan.** Run: `python -m pytest tests/test_incidencias_chats.py -q`. Expected: FAIL.
- [ ] **Step 3: Implementar** las rutas, los templates (extienden `base.html` y reutilizan las clases `card`, `table-wrap` y de botones del admin; para la vista se puede consultar `ui-ux-pro-max`), el JS y los registros.
- [ ] **Step 4: Ejecutar** `python -m pytest -q` (la suite completa). Expected: PASS, sin tests rotos en otras herramientas.
- [ ] **Step 5: Commit** con el mensaje `"feat: pantallas de Incidencias de chats"`.

---

### Task 7: Documentación y validación manual

**Files:**
- Modify: `.env.example` (agregar `INCIDENCIAS_CHATS_AI_CUPO_DIARIO=10` con un comentario), `README.md` (una sección «Incidencias de chats»)

La sección del README explica:
- qué hace la herramienta;
- que hay que ejecutar `supabase_chat_incidents.sql` una vez;
- las reglas y los umbrales, y dónde se editan (`utils/incidencias_chats_reglas.py`);
- que los diccionarios son un borrador;
- el Modo prueba;
- que la IA comparte proveedor con Auditoría de chats aunque cada una tenga su propio cupo.

- [ ] **Step 1: Escribir la documentación.**
- [ ] **Step 2: Compilar.** Run: `python -m py_compile tools/incidencias_chats.py utils/incidencias_chats_reglas.py utils/incidencias_chats_motor.py utils/incidencias_chats_store.py`. Expected: sin salida.
- [ ] **Step 3: Validación manual en el navegador**, siempre en **Modo prueba**, porque el `.env` local apunta a Supabase de producción:
  - recorrer el rango de un turno reciente de unas 4 h;
  - revisar las dos tablas, los filtros, el CSV y que la navegación del admin siga funcionando;
  - revisar desktop y 375 px sin scroll horizontal global;
  - ver cómo llegan en los datos reales el `sender_type` o `sender.type` de los bots y de los mensajes automáticos (spec, precisión 5) y ajustar `es_respuesta_humana` si hace falta.
- [ ] **Step 4: Commit** con el mensaje `"docs: Incidencias de chats en README y .env.example"`.
- [ ] **Step 5: Avisar al usuario** que ejecute `supabase_chat_incidents.sql` en el editor SQL de Supabase antes de usar el modo normal.
