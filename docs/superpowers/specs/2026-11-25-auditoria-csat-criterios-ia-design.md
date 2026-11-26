# Auditoría CSAT: criterios del equipo para la IA — Diseño (corto)

Fecha: 2026-11-25 · Aprobado por el usuario («aprobado»).

## Intención

La IA decide si un negativo fue culpa del agente con reglas genéricas y sin saber qué significa
cada motivo. El usuario entregó el **procedimiento de atención por chat** y una **rúbrica de 12
puntos con pesos**; la IA debe usarlos como vara: si el agente siguió el procedimiento y la
molestia viene de algo fuera de su control, el negativo no cuenta en su contra.

## Regla de decisión (aprobada)

- **«Sí fue culpa del agente» (NO)** si rompió una regla fuerte:
  primera respuesta > 5 min (en «He llegado» > 3 min); cerró sin confirmar si el usuario seguía en
  línea o sin despedida, o dejó el chat > 15 min sin respuesta del usuario; dio información
  incorrecta o falsas expectativas; confirmó una falla del sistema sin autorización;
  **o rúbrica < 70%**.
- **«No fue culpa del agente» (SÍ)** si siguió el procedimiento (rúbrica ≥ 70%) y la molestia viene
  del sistema, una política, el resultado (rechazados, llegada no procesada) o el propio usuario;
  también si el usuario cerró antes de 3 min sin respuesta, o si la atención siguió por llamada
  (nota tipo `PMF-XXXXX-NNN`) o por otro canal (enlace `compinche.ladesk.com` o `app.crisp.chat`).
- **«Dudoso» (TAL VEZ)**: sin conversación suficiente, rúbrica entre 60% y 70%, o reglas en conflicto.
- **Atenuantes**: la presentación no se penaliza por ahora; demora, tiempo de resolución o no
  revisar historial/filtros pesan menos si el tono fue empático, la explicación clara y la
  despedida correcta.

## Rúbrica (pesos del usuario)

Presentación inicial 5 · Disposición de ayudar 8 · Empatía 12 · Claridad 9 · Redacción y
ortografía 9 · Escucha activa 8 · Precisión 10 · Manejo de objeciones 9 · Tono 8 · Velocidad 8 ·
Satisfacción del usuario 9 · Cierre 5 = 100.

## Motivos (aprobados con «ok»)

CAPTCHA (no pasa el captcha/verificación) · CORREO (no llegan códigos/notificaciones o cambio de
correo) · MENSAJE DE APAGADO (aviso de que el sistema se apagó/desconectó solo) · BAJO
RENDIMIENTO (captura pocas ofertas/bloques) · SOLICITUD NEGADA (pidió algo que la política no
permite y se negó correctamente) · OTRAS CONSULTAS · NO PUEDE VINCULAR (cuenta de Amazon) ·
SISTEMA NO VISUAL (no visualiza/no refresca rechazados u ofertas) · CHAT SIN SOLICITUD (sin pedido
concreto) · HE LLEGADO (falla/retraso al procesar la llegada) · COLEGA (la molestia es por otro
agente que lo atendió antes) · NO PUEDE INGRESAR (inicio de sesión) · CAMBIO DE FOTO Y … (cambio de
foto/datos del perfil) · OTRO. El motivo dice de qué se queja el cliente; la decisión sale de cómo
atendió el agente.

## Contexto del procedimiento que la IA debe conocer

Resumen del texto del usuario: tiempos de primera respuesta (< 2 min ideal, < 5 min aceptable;
«He llegado» < 3 min); inactividad (preguntar si sigue en línea a los 5–7 min, cerrar con
despedida a los ~10 min adicionales; nunca > 15 min abierto sin respuesta ni cierre sin confirmar
y despedirse); manejo de crisis (no confirmar fallas sin autorización, calma y empatía); pasos de
«He llegado» (intentar procesar, confirmar hora del bloque, recomendar conectarse 15 min antes,
reportar, posible compensación aprobada por el encargado); «No visualiza / No refresca rechazados»
(validar perfil, sostener que el sistema funciona, recomendaciones, refresh preventivo si reincide).

## Diseño

1. **`utils/auditoria_csat_criterios.py`** (nuevo): constantes con la regla, la rúbrica con pesos,
   corte 70% y franja de dudoso 60–70%, atenuantes, definiciones de motivos y el resumen del
   procedimiento; función que arma las instrucciones de la IA. Único lugar a editar si cambia el
   procedimiento.
2. **Conversación completa**: en modo Chatwoot la IA recibe `construir_transcripcion_v2` (notas
   internas, eventos del sistema, hora al segundo) en vez de la versión sin notas. Sigue sin
   guardarse.
3. **Tiempos calculados**: con `periodo_agente` + `metricas_tiempos` (de
   `utils/auditoria_chats_transcripcion.py`) se calculan primera respuesta, esperas largas e
   inactividad/cierre y se pasan a la IA como datos exactos.
4. **Salida de la IA**: además de decisión, motivo, confianza, explicación y evidencia, devuelve
   `puntaje` (0–100) y `reglas_incumplidas` (lista corta).
5. **Ficha**: la caja de la IA muestra «Rúbrica N%» y «Rompió: …» si hay.

## No objetivos

- Editar las reglas desde la pantalla (queda en el archivo).
- Cambiar el esquema de Supabase: `puntaje` y `reglas_incumplidas` viven en el estado de la
  auditoría (*decisión de diseño*); al reabrir una auditoría guardada desde Supabase no se muestran
  (la decisión, el motivo, la confianza y la evidencia sí).
- Re-auditar automáticamente lo ya revisado: las propuestas viejas se conservan.
