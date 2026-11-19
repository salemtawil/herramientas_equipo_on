# Auditoría de chats — diseño

Fecha: 2026-11-19 · Estado: borrador para aprobación

## Intención

El equipo de soporte tiene unos 30 agentes respondiendo chats en Chatwoot. Los administradores quieren saber, cada semana, si cada agente atiende bien: si la atención fue buena o mala y si el cliente quedó satisfecho. Hoy no hay forma de hacerlo sin abrir chats uno a uno en Chatwoot.

La herramienta toma una muestra aleatoria de chats por agente dentro de un rango de fechas, los audita con IA según una pauta fija y deja que una persona revise y corrija esa auditoría. El resultado se guarda para poder ver la evolución de cada agente semana a semana.

Restricción de origen: tiene que ser gratis o casi gratis. Por eso se usa el plan gratuito de Groq con un modelo abierto, a través de un conector intercambiable.

## Objetivos

- Auditar unos **10 chats por agente** para los ~30 agentes (≈300 chats por semana), por **bloques**: todos, un turno o un grupo de agentes elegido.
- Muestra **aleatoria** dentro del rango de fechas, **sin repetir** chats ya auditados.
- **IA primero, humano después:** la IA audita todos; una persona revisa los marcados y una muestra de control.
- **Historial** por agente y por semana (Supabase).
- Exportar el resultado de un lote a CSV.
- Coste cero en el plan gratuito de Groq, y cambio de proveedor sin tocar código.

## No objetivos (v1)

- Login, roles o permisos (la app es pública por decisión ya tomada).
- Editar la pauta desde la interfaz: vive en código, con número de versión.
- Entrenar o ajustar un modelo propio.
- Arreglar la IA de Auditoría CSAT (se hará después reutilizando el conector; queda fuera de este trabajo).
- Auditorías programadas automáticamente (cron). Se lanzan a mano.
- Auditar llamadas o mensajes de canales que no sean chats de Chatwoot.

## Anti-objetivos (sería un fracaso aunque funcione)

- Que la herramienta muestre o guarde más datos de clientes de los necesarios.
- Que una petición se quede colgada y Vercel la corte a mitad de lote, perdiendo el avance.
- Que la IA ponga notas sin justificar: cada nota debe venir con motivo y evidencia breve.
- Que la revisión humana sea tan grande que nadie la haga (300 chats a mano).
- Romper el Reporte de agentes u otra herramienta al tocar el cliente de Chatwoot.

## Restricciones

- Flask server-rendered, Jinja, `static/styles.css`; sin SPA ni frameworks (ver `AGENTS.md`).
- Secretos solo en el backend. El navegador nunca ve claves de Chatwoot, Groq ni Supabase.
- Vercel: tiempo máximo por petición y 4,5 MB por petición. `/tmp` no se comparte entre instancias.
- Groq gratis (`openai/gpt-oss-120b`, cifras de terceros a octubre de 2026, confirmar en la consola): 30 peticiones/min, 1.000/día, **8.000 tokens/min**, **200.000 tokens/día**, por organización. Eso da ≈2–3 chats por minuto y ≈60 chats por día. El plan Developer quita el cuello de botella por menos de 1 USD/mes a este volumen.
- La CSP está en Report-Only y hay un pendiente para hacerla obligatoria: **nada de scripts en línea ni `onclick`/`style=""`** en lo nuevo; el JS va en un archivo de `static/`.
- Al cambiar CSS o JS, subir su número en `ASSET_VERSIONS` de `app.py`.
- Variables nuevas → `.env.example` y `README.md`.
- Las pruebas no hacen llamadas externas (`tests/conftest.py`).

## Enfoques considerados

| Enfoque | A favor | En contra |
|---|---|---|
| **A. Supabase + procesamiento chat a chat (elegido)** | Historial, no repite chats, sobrevive a cortes, respeta el tiempo de Vercel y el límite por minuto de Groq. | Hay que crear dos tablas en Supabase. |
| B. Sesión temporal como Auditoría CSAT | Más rápido de construir, no toca Supabase. | Sin historial, repite chats y en Vercel pierde el avance entre peticiones (`/tmp` por instancia). |
| C. Todo en una sola petición | Simple. | Imposible: 300 chats no caben en el tiempo de Vercel ni en el límite por minuto de Groq. |

Proveedor de IA: Groq gratis (elegido por el usuario) frente a Gemini gratis (usa los datos para mejorar productos), OpenAI (de pago), OpenRouter gratis (~50 peticiones/día, insuficiente) y Ollama (no funciona en Vercel). Se implementa un **conector compatible con la API de OpenAI** (`/chat/completions`), así que Groq, OpenRouter, Ollama, Gemini y OpenAI se cambian solo con variables de entorno.

## Decisiones del usuario

- Herramienta nueva para auditar chats de Chatwoot, de todos los agentes o por bloques.
- ~10 chats por agente, semanal, por turno o por grupo de agentes.
- IA automática + revisión humana.
- IA gratuita: Groq.
- Guardar en Supabase (aceptó la recomendación de A al pedir que se escribiera este diseño).

## Diseño

### Flujo

1. **Crear lote.** El admin elige rango de fechas (por defecto la semana anterior, lunes a domingo, zona `CHATWOOT_TIMEZONE`), alcance (todos los agentes / un turno de *Turnos de trabajo* / agentes marcados a mano) y chats por agente (por defecto 10, máximo 20).
2. **Muestreo.** Por cada agente se listan las conversaciones del rango asignadas a él, se descartan las ya auditadas y las que no tengan mensajes del agente, y se eligen N al azar. Se guardan como filas `pendiente`. Se hace **un agente por petición**.
3. **Auditoría IA.** Cada chat pendiente se procesa en **su propia petición**: se leen sus mensajes en Chatwoot, se arma la transcripción, se envía a la IA y se guarda el resultado. El navegador va pidiendo «siguiente» y muestra el avance. Si Groq responde 429, el servidor devuelve cuánto esperar y el navegador espera y reintenta.
4. **Cola de revisión.** Se marcan para revisión humana: nota global ≤ 3, cliente insatisfecho, IA con confianza baja o error de IA, y además un **10 % al azar** de los demás (muestra de control).
5. **Revisión humana.** El revisor abre el chat, ve la transcripción (leída en vivo desde Chatwoot) junto al resultado de la IA, y confirma o corrige nota, satisfacción y comentario.
6. **Resumen.** Por lote: tabla por agente (chats, nota IA media, nota final media, % satisfechos, marcados). Histórico: nota final media por agente por semana. Export CSV del lote.

### Pantallas (rutas bajo `/auditoria-chats`)

| Ruta | Método | Qué hace |
|---|---|---|
| `/auditoria-chats/` | GET | Formulario de nuevo lote + lista de lotes recientes + estado de la configuración (Chatwoot, IA, Supabase). |
| `/auditoria-chats/lotes` | POST | Crea el lote y redirige a su página. |
| `/auditoria-chats/lote/<id>` | GET | Avance, resumen por agente, cola de revisión, export. |
| `/auditoria-chats/lote/<id>/paso` | POST | Ejecuta **un** paso (muestrear un agente o auditar un chat). Devuelve JSON con el avance; sin JS, redirige a la página del lote. |
| `/auditoria-chats/chat/<audit_id>` | GET / POST | Transcripción + resultado IA + formulario de revisión. |
| `/auditoria-chats/lote/<id>/csv` | GET | Export del lote. |
| `/auditoria-chats/historial` | GET | Nota final media por agente y semana. |

Sin JavaScript la herramienta sigue funcionando: un botón «Procesar siguiente» avanza un paso por clic. Con JavaScript (`static/auditoria_chats.js`), un botón «Procesar lote» repite los pasos solo y se puede pausar. El lote se puede retomar después (el estado está en Supabase).

Boceto de la página del lote:

```
LOTE · Semana 10–16 nov · Turno Mañana · 6 agentes × 10
[■■■■■■■■□□□□] 38 / 60 auditados · 2 errores      [Procesar lote] [Pausar]

AGENTE           CHATS  NOTA IA  NOTA FINAL  SATISFECHOS  POR REVISAR
Ana Pérez          10     4,2      4,0          80 %          2
Luis Gómez         10     3,1      —            50 %          5
...

COLA DE REVISIÓN (14)
#48213  Luis Gómez  Nota IA 2  Insatisfecho  "no se resolvió el cobro"  [Revisar]
```

### Chatwoot

Reutilizar `ChatwootClient` de `utils/chatwoot_reportes.py` (añadir métodos, no cambiar los existentes):

- `listar_agentes()` — ya existe.
- Listar conversaciones de un agente en un rango: `POST /api/v1/accounts/{id}/conversations/filter` con `assignee_id` y `created_at` en el rango, paginado (25 por página). Necesita un método `post`. **Verificar contra la versión de Chatwoot de `chat.mybrandpatch.com`** los operadores de fecha admitidos; si el filtro por fecha no funciona, filtrar por `created_at` en Python y cortar la paginación al salir del rango.
- Mensajes: `GET /api/v1/accounts/{id}/conversations/{cid}/messages`, paginado con `before`. Quedarse con mensajes de cliente y de agente (tipos entrante/saliente), descartar notas privadas y actividad.
- Enlace al chat en Chatwoot para el revisor: `{CHATWOOT_BASE_URL}/app/accounts/{id}/conversations/{cid}`.

Nota: el filtro por `assignee_id` usa el **asignado actual**. Un chat transferido cuenta para quien lo tiene al final. Se acepta en v1 y se muestra en la ayuda.

Turnos: el alcance «turno» toma los nombres de *Turnos de trabajo* y los cruza con los agentes de Chatwoot por nombre, igual que hace el Reporte de agentes. Los nombres que no crucen se listan como aviso.

### IA: conector y pauta

Nuevo `utils/ia_chat.py`: cliente mínimo con `requests` para `POST {base_url}/chat/completions`, `response_format: {"type": "json_object"}`, temperatura baja, timeout, y errores claros (sin clave, 401, 429 con `retry-after`, respuesta no JSON). Reutilizable después por Auditoría CSAT.

Nueva pauta en `utils/auditoria_chats_pauta.py` con `PAUTA_VERSION`. Propuesta (decisión mía, a confirmar):

| Criterio | Escala |
|---|---|
| Saludo y presentación | 1–5 |
| Comprensión del problema | 1–5 |
| Exactitud de la información | 1–5 |
| Resolución | 1–5 |
| Tono y empatía | 1–5 |
| Tiempos de respuesta (según marcas de hora) | 1–5 |
| Cierre | 1–5 |

Salida JSON: puntuación por criterio, `nota_global` 1–5, `satisfaccion_cliente` (satisfecho / neutral / insatisfecho / no_se_puede_saber), `resuelto` (sí / no / parcial), `resumen` (≤ 2 frases), `fortalezas`, `mejoras`, `evidencias` (citas cortas), `confianza` (alta / media / baja). Se valida en Python; si no valida, un reintento y luego `error_ia`.

Transcripción enviada a la IA: líneas `[hh:mm] Cliente:` / `[hh:mm] Agente:`, recortada a ~6.000 caracteres (inicio y final si es más larga), con **correos, teléfonos y números largos reemplazados** por `[correo]`, `[teléfono]`, `[número]` antes de enviarla.

### Supabase

Script nuevo `supabase_chat_audits.sql` (como `supabase_work_shift_state.sql`), ejecutado a mano por el usuario.

`chat_audit_batches`: `id`, `created_at`, `etiqueta`, `since`, `until`, `alcance` (todos / turno / agentes), `alcance_detalle` (json), `chats_por_agente`, `agentes` (json con id y nombre de Chatwoot), `agentes_muestreados` (json), `estado` (muestreando / auditando / limite_diario / completado / con_errores), `modelo`, `pauta_version`.

`chat_audits`: `id`, `batch_id`, `conversation_id` (**único**: no se audita dos veces), `agente_id`, `agente_nombre`, `turno`, `conversacion_fecha`, `estado` (pendiente / auditado / error / revisado), `ia_resultado` (json), `ia_nota`, `ia_satisfaccion`, `ia_error`, `intentos`, `transcripcion_tmp` (solo mientras se procesa; se borra al terminar), `por_revisar`, `motivo_revision` (marcado / control), `revisor`, `nota_final`, `satisfaccion_final`, `comentario_revisor`, `revisado_at`, `created_at`, `updated_at`.

**No se guarda la transcripción** en Supabase: solo el resultado y las citas cortas de evidencia. La transcripción se lee en vivo al revisar.

Acceso desde Python con el patrón de `utils/break_admin_store.py` (cliente `supabase` con service role). Si Supabase no está configurado, la herramienta muestra un aviso y no deja crear lotes (no hay modo temporal).

Revisor: sin login, campo de texto «Tu nombre» recordado en el navegador (`localStorage`, con try/catch).

### Variables de entorno nuevas

| Variable | Defecto |
|---|---|
| `AUDITORIA_CHATS_AI_BASE_URL` | `https://api.groq.com/openai/v1` |
| `AUDITORIA_CHATS_AI_MODEL` | `openai/gpt-oss-120b` |
| `AUDITORIA_CHATS_AI_API_KEY` | (vacía → la IA queda desactivada con aviso) |

Usa las de Chatwoot y Supabase existentes.

### Integración en la app

- `tools/auditoria_chats.py` (blueprint), registrado en `app.py`.
- `templates/auditoria_chats.html` (+ plantilla de revisión si hace falta), estilos en `static/styles.css`, JS en `static/auditoria_chats.js`; subir `ASSET_VERSIONS`.
- Entrada en `utils/navegacion.py`, grupo **Calidad**, icono existente `calidad` o uno nuevo en `_iconos.html`.
- Tablas dentro de `.table-wrap`; revisar escritorio y móvil.
- Acciones destructivas (si se añade borrar lote) con confirmación, como el resto.

### Pruebas

- Unitarias con respuestas simuladas de Chatwoot y de la IA: muestreo aleatorio con semilla, exclusión de ya auditados, armado y recorte de transcripción, anonimización, validación del JSON de la IA, reglas de la cola de revisión, manejo de 429.
- Almacén de Supabase simulado (las pruebas no tocan Supabase real).
- Rutas: crear lote, paso sin JS, revisión, CSV.
- `python -m pytest` y `pyflakes` en verde.

## Decisiones tomadas tras la revisión del diseño

Marcadas como decisión de Claude; el usuario puede cambiarlas.

1. **Plan gratuito y lotes de varios días.** Con ~60 chats/día, un lote de 300 tarda unos 5 días. El lote guarda un estado `limite_diario` cuando Groq devuelve 429 por tokens del día: la página muestra «Límite diario de la IA alcanzado; retoma mañana» y el botón sigue funcionando al día siguiente. El 429 por minuto sí se espera y se reintenta solo. Se recomienda usar lotes por turno o grupo (~60 chats) para que cada uno quepa en un día. Si se pasa al plan Developer, no cambia nada del código.
2. **Nota de los chats no revisados.** Se calcula una **nota efectiva** = `nota_final` si fue revisado, si no `ia_nota` (no se escribe en `nota_final`). Resumen e historial usan la nota efectiva y muestran aparte la nota IA y el % revisado, para que el historial no quede sesgado hacia los chats malos.
3. **Tiempo de Vercel.** `vercel.json` usa `builds` sin `maxDuration`, así que hay que asumir un límite corto. Cada chat se procesa en **dos pasos** (leer mensajes de Chatwoot → llamar a la IA); la transcripción preparada se guarda temporalmente en la fila (`transcripcion_tmp`) y se **borra** al guardar el resultado. El reintento por JSON inválido es un paso más, no dentro de la misma petición (máximo 2 intentos, luego `error`).
4. **Turno congelado.** Al crear el lote se guarda la lista de agentes y su turno en ese momento (`agentes`, `turno`). Cambios posteriores en Turnos de trabajo no afectan a lotes ya creados.
5. **Errores y borrado.** Un chat en `error` se puede reintentar (misma fila). Borrar un lote (con confirmación) borra sus filas y libera esos chats para futuros muestreos. `conversation_id` sigue siendo único entre todas las filas.
6. **Privacidad con Groq.** No hay bloqueo en la herramienta: se anonimizan correos, teléfonos y números largos, y el README indica activar Zero Data Retention en Groq antes de usarla. La pantalla principal recuerda que el texto de los chats se envía al proveedor configurado.

## Para quien lo construya

- Orden sugerido: conector IA → métodos nuevos de Chatwoot → tablas y almacén → muestreo → auditoría paso a paso → pantallas → revisión → resumen/historial/CSV.
- Comprobar en `chat.mybrandpatch.com` el filtro de conversaciones y el formato de mensajes antes de construir sobre ellos.
- Confirmar en la consola de Groq los límites reales y activar Zero Data Retention.
- Detalles de interfaz, nombres internos y textos de ayuda quedan a su criterio dentro del sistema visual v23.
