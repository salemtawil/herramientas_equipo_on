# Auditoría de chats con la rúbrica QA-1.1 y el Manual de Procedimientos v3.0

Fecha: 2026-11-20 · Herramienta existente: `auditoria_chats` (ver `2026-11-19-auditoria-chats-design.md`).

## Intención

Hoy la IA puntúa cada chat con 7 criterios genéricos de 1 a 5. Compinche tiene una rúbrica propia
(QA-1.1, 17 criterios ponderados, fallas críticas, estado final) y un manual de procedimientos
(v3.0, nov 2026). Se quiere que la auditoría evalúe lo que el agente hizo realmente contra esos
procedimientos, con evidencia, para dar al agente feedback concreto: lo que hace bien y lo que debe
mejorar. Un cliente insatisfecho no es por sí solo mala gestión, y la amabilidad no compensa
información errónea.

## Objetivos

- Evaluar cada chat con la rúbrica QA-1.1 (texto completo en la sección «Rúbrica») usando solo las
  secciones del manual que aplican al motivo del chat.
- Puntaje QA 0–100 calculado por el código, no por la IA.
- Estado final por chat: APROBADO, NECESITA MEJORAR, NO APROBADO o PENDIENTE DE REVISIÓN.
- Fallas críticas CR01–CR10 detectadas como sospechas que confirma una persona.
- Feedback por agente basado en los 17 criterios.
- Los lotes antiguos (pauta v1) se siguen viendo como hoy.

## No objetivos

- No se consultan sistemas externos (Compi Town, logs, historial de pagos). Lo que requiera esas
  fuentes queda como NO VERIFICABLE, tal como manda la rúbrica.
- No hay pantalla para subir o editar el manual ni la rúbrica: el manual se carga con un script.
- No se re-auditan automáticamente los lotes v1.

## Anti-objetivos (sería un fracaso aunque funcione)

- Que el manual (documento de uso interno) quede en el repositorio o sea visible para el navegador.
- Que la IA marque NO APROBADO por una falla crítica sin que una persona la confirme.
- Que la IA premie respuestas amables con información incorrecta o acciones no confirmadas.
- Que la auditoría de un chat supere el tiempo de una función de Vercel.

## Enfoques considerados

- **A. Secciones del manual elegidas por la IA (elegido).** Primera llamada corta: la IA identifica
  motivo, procedimientos (P01–P14) y secciones aplicables a partir del índice. Segunda llamada:
  evaluación QA-1.1 con solo esas secciones + las generales. ~5–10 k tokens por chat, 2 llamadas
  por chat (500 RPD de Flash Lite ≈ 250 chats/día; el uso previsto es ~300 chats/semana).
- B. Secciones por palabras clave en el código: 1 llamada, pero falla cuando el cliente no usa las
  palabras esperadas y la evaluación se hace sin el procedimiento correcto.
- C. Manual completo (~40 k tokens) en cada chat: lento, riesgo de timeout, agota el TPM. Descartado.

El usuario eligió A.

## Decisiones del usuario

- Enfoque A.
- Cortes: QA ≥ 85 sin fallas críticas → APROBADO; 70–84 → NECESITA MEJORAR; < 70 o falla crítica
  confirmada → NO APROBADO (conserva su puntaje); falla crítica sospechosa o nada verificable →
  PENDIENTE DE REVISIÓN. (Inicialmente se aprobó también «verificables < 60 % → PENDIENTE»; tras la
  revisión del diseño el usuario eligió quitarla porque sin sistemas externos la mayoría de los
  chats quedarían pendientes. El % verificable se muestra como indicador de confiabilidad.)
- En la revisión humana la persona elige el estado final directamente y eso cierra el chat.
- El estado final reemplaza la valoración buena/regular/mala en los lotes nuevos.
- Feedback por agente por criterio de la rúbrica (A1–F2).

## Diseño

### 1. Manual en Supabase

- Tabla nueva `chat_audit_manual` (RLS activado sin políticas, solo service role):
  `version text`, `codigo text` (p. ej. `1.4.1`), `titulo text`, `texto text`, `orden int`,
  `pk (version, codigo)`.
- Script local `scripts/cargar_manual_auditoria.py <pdf> --version 3.0` que extrae el texto del PDF,
  normaliza espacios, lo corta por los encabezados de sección del índice (1.1.1 … 1.14.1 y
  4.1 … 4.5; se omiten Desarrollo y Marketing) y hace upsert con la service role key del `.env`.
  `pypdf` solo se usa en este script local: va en `requirements-dev.txt`, no en `requirements.txt`.
- Variable nueva `AUDITORIA_CHATS_MANUAL_VERSION` (por defecto `3.0`). Actualizar `.env.example` y
  `README.md`.
- Carga inicial (decisión de Claude): el PDF v3.0 ya está disponible localmente; Claude lo corta con
  el mismo código del script y lo carga en producción con el MCP de Supabase, igual que las
  migraciones (columnas nuevas, `check` con `clasificado`, tabla del manual). Orden: migración →
  carga del manual → push del código. El script queda para versiones futuras del manual. Las
  secciones padre sin texto propio (1.7, 1.8, 1.10…) se expanden a sus subsecciones.
- El backend lee el índice (`codigo`, `titulo`) y los textos que necesite; nada se envía al navegador.
- Si la tabla está vacía, crear un lote muestra una advertencia y no deja crearlo.

### 2. Procedimientos y secciones

Mapa fijo en `utils/auditoria_chats_rubrica.py` (de la rúbrica):

| Código | Tema | Secciones |
|---|---|---|
| P01 | Bajo rendimiento | 1.1.4, 1.5.4, 1.6.1 |
| P02 | Sin rechazos o actividad | 1.6.2, 1.6.4 |
| P03 | Pausas y transferencias de días | 1.4.1 |
| P04 | Modificaciones de cuenta | 1.4.2, 1.4.3 |
| P05 | Reembolsos | 1.1.3, 4.3 |
| P06 | Promociones y compensaciones | 1.9.2, 1.9.3 |
| P07 | Precios especiales | 1.9.6, 4.4 |
| P08 | Compipuntos y rachas | 1.9.4, 1.9.5 |
| P09 | Verificaciones de identidad | 1.7 (todas sus subsecciones), 1.8.2 |
| P10 | Advertencias, restricciones y cierres | 1.8 (todas sus subsecciones) |
| P11 | Pagos y disputas | 4.5 |
| P12 | Chispita | 1.10–1.14 |
| P13 | Solicitud de llamada | 1.1.2 |
| P14 | Traspaso de chats | 1.2.5 |

Secciones generales que van siempre: 1.1.1 (atención por chat), 1.1.3 (escalación), 1.1.8 (notas
obligatorias), 1.2.5 (traspaso). La clasificación puede pedir además hasta 4 secciones del índice
(p. ej. 1.1.5 usuarios molestos, 1.1.6 CAPTCHA). Tope total del texto del manual enviado: 30 000
caracteres; si se pasa, se recortan primero las secciones extra, luego las de procedimientos por
orden de aparición, nunca las generales.

### 3. Lectura del chat (transcripción v2)

`construir_transcripcion_v2` en `utils/auditoria_chats_transcripcion.py`:

- Una línea por mensaje: `[m<id> HH:MM:SS] <Autor>: <texto> <etiquetas de adjuntos>`.
  - Autor: `Cliente`, `Agente (<nombre del remitente>)`, `Nota interna (<nombre>)` para mensajes
    privados, `Sistema` para mensajes de actividad (`message_type` 2: asignaciones, traspasos,
    resolución).
- Todo pasa por `anonimizar`. Tope 12 000 caracteres con el mismo recorte inicio + final.
- Se guarda en `transcripcion_tmp` como hoy (se borra al terminar).
- Las reglas de descarte (llamada, sin respuesta escrita) no cambian.

### 4. Tiempos calculados por el código

`metricas_tiempos(mensajes)` devuelve, en segundos y con el id del mensaje que los origina:

- `primera_respuesta`: del primer mensaje del cliente a la primera respuesta escrita de un agente.
- `primera_respuesta_agente`: desde el evento de asignación al agente evaluado (si existe) hasta su
  primera respuesta.
- `esperas_largas`: cada vez que el cliente escribió y la siguiente respuesta del agente tardó
  más de 180 s (lista de {desde_id, hasta_id, segundos}).
- `inactividad`: tras el último mensaje del agente, si el cliente no volvió a escribir: segundos
  hasta el seguimiento del agente (si hubo) y hasta el cierre (evento de resolución), y quién cerró.

Chats con varios agentes (de la rúbrica: «identificar al agente responsable y su período de
participación», «considerar las asignaciones y cambios de agente»): el período del agente evaluado va
desde su primer evento de asignación (o su primer mensaje si no hay evento) hasta la siguiente
asignación a otra persona o el cierre. Las métricas se calculan dos veces: la oficial (cualquier
agente) y la atribuible al agente evaluado dentro de su período; solo cuenta su propia respuesta.
La IA recibe el período (ids de inicio y fin) y evalúa los 17 criterios solo sobre ese tramo, usando
el resto como contexto. Los eventos de asignación y cierre se detectan por el remitente de los
mensajes y por el texto de los mensajes de actividad (es/en, tolerante); si no se reconocen, el
período es toda la conversación y se anota `periodo_inferido: false` en el diagnóstico.

Se envían a la IA como bloque «Métricas calculadas»; la IA las usa para E1, E2, E3 y F1 y no
recalcula tiempos.

### 5. Clasificación (llamada 1)

- Estado nuevo de chat `clasificado` entre `leido` y `auditado` (actualizar el `check` de la
  tabla con una migración). Cada paso del lote hace como mucho una llamada a la IA:
  `leido` → clasificar → `clasificado` → evaluar → `auditado`.
- Entrada: índice del manual (código + título), lista P01–P14, transcripción.
- Salida JSON: `motivo_principal`, `motivos_secundarios[]`, `procedimientos[]` (P01–P14, puede ir
  vacío), `secciones_extra[]` (códigos del índice, máx. 4), `servicio` (Compinche, Chispita u otro).
  Códigos desconocidos se descartan.
- Se guarda en `detalle.clasificacion`.
- Errores y reintentos con las mismas reglas que la evaluación (`MAX_INTENTOS_IA`, 429, diario,
  temporal, configuración).

### 6. Evaluación (llamada 2) y cálculo

Mensajes: sistema = rúbrica QA-1.1 completa (texto de la sección «Rúbrica») + reglas de justicia;
usuario = agente evaluado, canal (nombre de la bandeja), clasificación, secciones del manual,
métricas calculadas y transcripción v2.

Salida JSON por criterio (A1…F2): `resultado` ∈ {cumple, parcial, no_cumple, no_aplica,
no_verificable}, `evidencias` (ids `m<id>`), `comentario` (1 frase). Además: `fallas_criticas[]`
({codigo CR01–CR10, evidencias, descripcion}), `cumplimientos[]`, `incumplimientos[]`,
`recomendaciones[]`, `estado_resolucion` ∈ {resuelto, parcial, no_resuelto, no_verificable},
`responsabilidad` ∈ {agente, externa, usuario, compartida, no_determinable},
`satisfaccion_cliente` (mismos valores de hoy), `resumen`, `confianza`.

El código (no la IA) calcula:

- Pesos: A1 8, A2 7, B1 12, B2 10, B3 8, C1 8, C2 7, C3 5, D1 6, D2 6, D3 5, D4 3, E1 4, E2 4,
  E3 2, F1 3, F2 2 (total 100).
- `evaluables` = suma de pesos sin `no_aplica`; `verificables` = evaluables sin `no_verificable`.
- `qa` = obtenidos / verificables × 100 (cumple 100 %, parcial 50 %, no cumple 0 %), redondeado a
  1 decimal. Si `verificables` = 0, `qa` = null.
- `pct_verificable` = verificables / evaluables × 100 (indicador de confiabilidad, se muestra junto
  al QA: «QA 82 · 55 % verificable»; no cambia el estado).
- `estado`: falla crítica confirmada → NO APROBADO; falla sospechosa o qa null → PENDIENTE DE
  REVISIÓN; qa ≥ 85 → APROBADO; qa ≥ 70 → NECESITA MEJORAR;
  si no → NO APROBADO.
- Toda falla que reporte la IA queda `sospechosa`; solo una persona la confirma o la descarta.
- Las evidencias que citen ids que no existen en el chat se descartan.

Se guarda en `ia_resultado` (con `pauta_version = "QA-1.1"` y el modelo) y en columnas nuevas
`ia_qa numeric(4,1)` e `ia_estado text`. `ia_nota` queda null en los chats v2. `ia_satisfaccion`
se sigue llenando.

`requiere_revision` v2: estado distinto de APROBADO, confianza baja o error. La muestra de control
del 10 % sigue igual.

### 7. Revisión humana v2

En la página del chat v2:

- Tabla de los 17 criterios: resultado de la IA, comentario y evidencias (enlace al mensaje en la
  transcripción).
- Por cada falla sospechosa: confirmar o descartar.
- El revisor puede corregir el resultado de cualquier criterio; el QA se recalcula con las mismas
  reglas y el estado final se precarga con el estado recalculado. El revisor elige el estado final
  (APROBADO, NECESITA MEJORAR o NO APROBADO) y eso cierra el chat (`estado = revisado`); si
  confirma una falla crítica, el estado final es NO APROBADO. Nombre obligatorio, comentario
  opcional como hoy.
- Se guarda en columnas nuevas `qa_final numeric(4,1)`, `estado_final text`, y el detalle en
  `revision` jsonb (criterios corregidos y fallas confirmadas/descartadas).
- Estado efectivo = el del revisor si existe, si no el de la IA. Igual para el QA.

### 8. Página del lote v2

- «Todos los chats»: columnas Estado (APROBADO… con color), QA, Motivo, Satisfacción, Resumen.
- «Feedback por agente»: conteo por estado, QA medio, fallas críticas confirmadas,
  puntos fuertes = 3 criterios con mayor % de cumplimiento (cumple = 1, parcial = 0,5, sobre los
  verificables) con ≥ 80 %; áreas de mejora = 3 con menor % y < 80 %; textos de
  `cumplimientos`, `incumplimientos` y `recomendaciones` (sin duplicados, máx. 8 cada uno);
  comentarios del revisor.
- «Resumen por agente» con QA medio en lugar de nota.
- Las páginas de lotes v1 se renderizan como hoy (la plantilla decide por `lote.pauta_version`).

### 9. Exportes, diagnóstico e historial

- CSV v2: id, agente, fecha, motivo, procedimientos, QA IA, estado IA, QA final, estado final, los
  17 resultados, fallas, satisfacción, revisor, comentario. Celdas protegidas contra fórmulas.
- Diagnóstico JSON: añade `clasificacion`, `ia_qa`, `ia_estado`, resultados por criterio y
  códigos de falla; sigue sin texto del cliente ni del manual.
- Historial semanal: columna QA medio para chats v2; los v1 siguen con nota media.

### 10. Cupo y tiempos de Vercel

- El contador de cupo diario de la pantalla de creación cuenta 2 llamadas por chat en lotes v2.
- `vercel.json`: `"config": {"maxDuration": 60}` en el build de `app.py` para que una llamada con
  10 k tokens no se corte.

### Rúbrica

El texto de la rúbrica QA-1.1 (secciones I–IX del documento «INSTRUCCIONES PARA IA AUDITORA DE
CHATS») se copia a `utils/auditoria_chats_rubrica.py` como constante y se usa como prompt de sistema
de la evaluación. No contiene datos sensibles. Los pesos y cortes del cálculo se definen en código
en el mismo módulo.

## Queda a criterio de quien construye

- Redacción exacta de los prompts y del esquema JSON de ejemplo.
- Cómo detectar los encabezados de sección en el PDF (el índice está en las páginas 2–4).
- Estilos de las etiquetas de estado (reutilizar `.ac-valoracion--*`).
- Orden de columnas y textos de ayuda en las tablas.
