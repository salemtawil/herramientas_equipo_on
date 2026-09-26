# herramientas_equipo_on-revision

App Flask con utilidades internas para procesar CSVs, consultar usuarios activos, auditar reportes y administrar breaks reservables.

## Decisión de arquitectura: aplicación pública

La aplicación es pública por decisión definitiva (2026-09-26): cualquier persona que conozca o descubra la URL puede acceder y usar todas sus herramientas, incluidas las que modifican datos, crean Google Sheets o consumen APIs de pago.

- No hay autenticación, login, roles ni permisos, y no se usa Vercel Authentication. Es una decisión aceptada, no un pendiente.
- No hay protección CSRF basada en sesiones.
- La URL no es privada ni está protegida. `noindex`, `robots.txt`, comprobar la cabecera `Origin` o usar una URL difícil de adivinar pueden reducir tráfico accidental, pero **no son control de acceso**.
- Por eso las medidas de protección se centran en limitar el abuso y el coste (tamaños, tiempos, cuotas, confirmaciones, registros sin secretos y alertas de consumo), no en impedir el acceso.

## Correr localmente

1. Crea y activa un entorno virtual.
2. Instala dependencias:

```bash
pip install -r requirements.txt
```

3. Define variables de entorno según las herramientas que vayas a usar.
   En local puedes crear un archivo `.env`; la app lo carga automáticamente al iniciar.
4. Ejecuta la app:

```bash
python app.py
```

La app levanta en modo local con la `FLASK_SECRET_KEY` por defecto de desarrollo si no defines una propia.

## Pruebas

El único comando oficial es pytest:

```bash
pip install pytest
python -m pytest
```

Funciona desde la raíz o desde cualquier otro directorio (`python -m pytest ruta/al/repo/tests`).

- `tests/conftest.py` aísla la suite: no carga el `.env` real, elimina las variables de integraciones y todas las variables `*_PROXY`, usa un store de turnos temporal (nunca `data/turnos_trabajo.json`) y bloquea toda conexión de red que no sea `localhost`. Un test que intente salir a la red falla indicando su nombre.
- **No uses `python -m unittest` directamente**: omite `conftest.py`, así que no hay aislamiento y puede leer el `.env` local, contactar servicios reales y escribir en `data/turnos_trabajo.json`.
- Las pruebas de navegador (`test_usuarios_activos_navegador.py`, `test_navegacion_responsive.py`) usan Playwright, que es opcional y no está en `requirements.txt`. Si no está instalado se omiten. Para activarlas: `pip install playwright` y `python -m playwright install chromium`.
- Para no generar `__pycache__`, se puede ejecutar con `PYTHONDONTWRITEBYTECODE=1`.

## Variables de entorno importantes

Obligatoria en producción:

- `FLASK_SECRET_KEY`

Opcionales según funcionalidad:

- `APPS_SCRIPT_WEBHOOK_URL`
- `APPS_SCRIPT_WEBHOOK_TOKEN`
- `COMPINCHE_ID_TOKEN`
- `COMPINCHE_REFRESH_TOKEN`
- `COMPINCHE_CLIENT_ID`
- `COMPINCHE_CLIENT_SECRET`
- `COMPINCHE_USERNAME`
- `COMPINCHE_PASSWORD`
- `COMPINCHE_USER_POOL_ID`
- `MULTIADMIN_API_BASE_URL`
- `MULTIADMIN_ID_TOKEN`
- `MULTIADMIN_REFRESH_TOKEN`
- `MULTIADMIN_PROVISIONED_TOKEN`
- `MULTIADMIN_CLIENT_ID`
- `MULTIADMIN_CLIENT_SECRET`
- `MULTIADMIN_USERNAME`
- `MULTIADMIN_PASSWORD`
- `MULTIADMIN_USER_POOL_ID`
- `MULTIADMIN_USERS_SINCE_EXPIRATION`
- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`
- `AWS_DEFAULT_REGION`
- `LOG_LEVEL`
- `MAX_CONTENT_LENGTH` (bytes; por defecto `52428800` = 50 MB)
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `OPENAI_API_KEY`
- `OPENAI_CSAT_MODEL`
- `OPENAI_CSAT_MAX_CASES`
- `OPENAI_WEEKLY_REPORT_MODEL`
- `GEMINI_API_KEY`
- `GEMINI_WEEKLY_REPORT_MODEL`
- `CSAT_AI_PROVIDER`
- `WEEKLY_REPORT_AI_PROVIDER`
- `OLLAMA_BASE_URL`
- `OLLAMA_CSAT_MODEL`
- `OLLAMA_WEEKLY_REPORT_MODEL`
- `CHATWOOT_BASE_URL`
- `CHATWOOT_ACCOUNT_ID`
- `CHATWOOT_API_ACCESS_TOKEN`
- `CHATWOOT_TIMEZONE`

## Deploy en Vercel

Configuración actual:

- entrypoint: `app.py`
- runtime: `@vercel/python`
- rutas: todo entra por `app.py`

Antes de desplegar:

1. Configura `FLASK_SECRET_KEY` en Vercel.
2. Si usarás `usuarios_a_sheets`, configura `APPS_SCRIPT_WEBHOOK_URL` y, si aplica, `APPS_SCRIPT_WEBHOOK_TOKEN`.
3. Si usarás el diagnóstico de promo de Compinche dentro de `usuarios_activos`, configura los tokens de Compinche.
4. Si usarás el módulo `break_admin`, configura:
   - `SUPABASE_URL`
   - `SUPABASE_SERVICE_ROLE_KEY`
5. Para que `turnos_trabajo` guarde cambios compartidos entre admins, ejecuta en Supabase el SQL de `supabase_work_shift_state.sql`.
   Usa las mismas variables:
   - `SUPABASE_URL`
   - `SUPABASE_SERVICE_ROLE_KEY`
6. Si esperas refresco automático del token de Compinche vía Cognito, configura también:
   - `AWS_ACCESS_KEY_ID`
   - `AWS_SECRET_ACCESS_KEY`
   - `AWS_DEFAULT_REGION=us-east-1`
   - `COMPINCHE_USERNAME`
   - `COMPINCHE_PASSWORD`
   - `COMPINCHE_USER_POOL_ID=us-east-1_KRph7TcMm` si el login necesita `ADMIN_USER_PASSWORD_AUTH`.
   - `COMPINCHE_CLIENT_SECRET` solo si el App Client de Cognito usa client secret.
7. Si usaras `usuarios_activos` con datos completos del Multiadmin nuevo, configura al menos una forma de autenticacion:
   - `MULTIADMIN_PROVISIONED_TOKEN`, o
   - `MULTIADMIN_ID_TOKEN` junto con `MULTIADMIN_REFRESH_TOKEN`, o
   - `MULTIADMIN_USERNAME` y `MULTIADMIN_PASSWORD`.
   Si no configuras estas variables, la app usa el endpoint Lambda legado, que solo trae agregados basicos.
8. Si usaras `reporte_agentes` con Chatwoot, configura:
   - `CHATWOOT_BASE_URL` (para Chatpatch: `https://chat.mybrandpatch.com`)
   - `CHATWOOT_ACCOUNT_ID`
   - `CHATWOOT_API_ACCESS_TOKEN`
   - `CHATWOOT_TIMEZONE` (por defecto `America/Caracas`)

## Persistencia en Vercel

En Vercel el sistema de archivos solo es escribible en `/tmp`, que es propio de cada instancia y se pierde al reciclarla.

- `turnos_trabajo` usa Supabase si `TURNOS_TRABAJO_STORAGE=supabase`, o si esa variable no existe y están `SUPABASE_URL` y `SUPABASE_SERVICE_ROLE_KEY`. Con `TURNOS_TRABAJO_STORAGE=local`, o sin esas dos variables, guarda en `/tmp/turnos_trabajo.json`: fuera de Vercel la pantalla muestra «Local»; en Vercel muestra «Almacenamiento temporal» y un aviso. Si Supabase está configurado pero falla, guarda en `/tmp`, muestra «Almacenamiento temporal» y un aviso de que Supabase no respondió.
- `break_admin` exige `SUPABASE_URL` y `SUPABASE_SERVICE_ROLE_KEY`; sin ellas muestra un error de configuración y no guarda nada.
- El snapshot de `usuarios_activos` y los análisis temporales de `auditoria_csat`, `auditoria_salientes` y `usuarios_a_sheets` viven en el directorio temporal del runtime. En una instancia nueva, `usuarios_activos` muestra el estado inicial hasta que alguien pulse «Actualizar datos».

## Endurecimiento de la app pública (lote 5a)

Estas medidas reducen riesgos accidentales y de navegador. **No son control de acceso**: la app sigue siendo pública.

- Cabeceras en todas las respuestas: `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`, `X-Frame-Options: SAMEORIGIN` y un `Permissions-Policy` que desactiva cámara, micrófono, geolocalización, pagos, USB y similares (la app no usa ninguno).
- `X-Robots-Tag: noindex, nofollow, noarchive` en HTML, JSON y descargas, `<meta name="robots">` en las plantillas y `/robots.txt` con `Disallow: /`. Solo piden a los buscadores que no indexen; cualquiera con la URL puede entrar igual.
- `Content-Security-Policy-Report-Only`: solo observa, no bloquea nada y no envía reportes a ningún servidor. Hoy registraría los `<script>` en línea de las plantillas, los `onclick`/`onload` de Usuarios activos y los `style=""` que dibujan barras en Reporte de agentes y Auditoría CSAT. Hay que moverlos a `static/` antes de pasar a una CSP que bloquee.
- No se envía HSTS: antes hay que confirmar que el dominio definitivo y todos sus subdominios sirven solo HTTPS.
- Caché: HTML, JSON y descargas llevan `Cache-Control: no-store`. `styles.css` y `app.js` pedidos con su versión actual (`?v=`, ver `ASSET_VERSIONS` en `app.py`) llevan `public, max-age=31536000, immutable` y `Vercel-CDN-Cache-Control: public, max-age=86400`; cualquier otra versión, o un archivo estático sin versión, lleva `no-cache`. En Vercel `/static/` lo sirve la misma función de Flask (por `vercel.json`), así que estas cabeceras son las que aplican. **Al cambiar `styles.css` o `app.js`, sube su número en `ASSET_VERSIONS`.**
- Confirmación explícita (diálogo accesible; sin JavaScript el formulario se envía como antes) para eliminar una reserva, desactivar turnos y horarios de breaks, limpiar asignaciones, vaciar agentes y crear un Google Sheet. Limpiar y vaciar siguen exigiendo escribir `SI`/`BORRAR`.
- Los formularios `POST` bloquean el doble envío mientras la petición está en curso; conservan el nombre y valor del botón pulsado y, en las descargas, se liberan a los pocos segundos.
- `/usuarios-activos/compinche/promo-diagnostico` solo acepta `POST` (un `GET` devuelve `405` sin llamar a servicios externos). La respuesta JSON no cambió.
- Almacenamiento de turnos: al arrancar se registra el modo (`local`, `temporal`, `supabase` o `fallback`) sin URL, claves ni texto de excepciones. En Panel principal, Turnos de trabajo y Reporte de agentes aparece un aviso si en Vercel se guarda en `/tmp` porque Supabase no está configurado, o si Supabase falló y se usó `/tmp`.

### Límites: situación actual y propuesta (pendiente de aprobación)

No se cambió ningún límite. En Vercel el cuerpo de cada petición está limitado a 4,5 MB (respuesta `413 FUNCTION_PAYLOAD_TOO_LARGE` de la plataforma, antes de llegar a Flask).

| Límite | Máximo actual | Uso esperado | Propuesta | Impacto | Variable | Respuesta HTTP |
| --- | --- | --- | --- | --- | --- | --- |
| Cuerpo total de la petición | 50 MB en Flask; 4,5 MB efectivos en Vercel | CSV de pocos MB | 5 MB | Local se comporta igual que Vercel | `MAX_CONTENT_LENGTH` | 413 (HTML o JSON) |
| Campos de formulario sin archivo | 8 MB | Textos del informe y estados firmados | Sin cambio | — | `MAX_FORM_MEMORY_SIZE` | 413 |
| CSV descomprimido | 25 MB | < 5 MB | Sin cambio | — | (constante en `utils/archivos.py`) | Error en pantalla |
| Archivos de Informe Semanal CS | 40 MB por archivo, sin límite de cantidad | 1–3 archivos | 4 MB en total y 5 archivos | Menos coste de IA por envío | nueva, a definir | 413 / error en pantalla |
| Casos de CSAT auditados con IA | 10 por pulsación | 5–10 | Sin cambio; considerar tope diario | Coste de OpenAI | `OPENAI_CSAT_MAX_CASES` | Mensaje en pantalla |
| Rango de fechas de Chatwoot | Sin máximo | 1–7 días | 31 días | Evita consultas largas | nueva, a definir | Error en pantalla |
| Duración de la función | 300 s (Hobby y Pro por defecto) | < 60 s | Sin cambio | — | `vercel.json` | 504 de Vercel |

## Conectar IA para Informe Semanal CS

Opción recomendada para Vercel: Gemini API.

```env
GEMINI_API_KEY=tu_api_key
WEEKLY_REPORT_AI_PROVIDER=gemini
GEMINI_WEEKLY_REPORT_MODEL=gemini-2.5-flash
```

En Vercel, configura esas mismas variables como Environment Variables.

Para usar OpenAI en local, crea `.env` en la raíz del proyecto:

```env
OPENAI_API_KEY=tu_api_key
WEEKLY_REPORT_AI_PROVIDER=openai
OPENAI_WEEKLY_REPORT_MODEL=gpt-4.1-mini
```

Luego reinicia Flask.

También puedes usar Ollama local:

```env
WEEKLY_REPORT_AI_PROVIDER=ollama
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_WEEKLY_REPORT_MODEL=qwen2.5:7b
```

## Limitaciones conocidas

- `usuarios_a_sheets` y `auditoria_salientes` guardan estado temporal firmado. Si el estado es pequeño, viaja inline; si crece, se apoya en almacenamiento temporal del runtime.
- `auditoria_csat` guarda su análisis temporal en almacenamiento efímero del runtime.
- `auditoria_csat` puede auditar negativas pendientes con IA si `OPENAI_API_KEY` está configurada o si `CSAT_AI_PROVIDER=ollama` apunta a un Ollama local. La IA usa transcripción del CSV cuando existe; si el CSV solo trae un link privado, audita con el comentario disponible hasta conectar una API backend que entregue el transcript completo.
- `informe_semanal_cs` genera informes con Gemini si `GEMINI_API_KEY` está configurada y `WEEKLY_REPORT_AI_PROVIDER=gemini`. También puede usar OpenAI u Ollama. Si no hay proveedor de IA, devuelve una base editable con las secciones obligatorias. En esta V1 extrae texto de PDF, TXT, Markdown, CSV, JSON y logs; imágenes y hojas de cálculo quedan marcadas como recibidas sin extracción.
- Ollama local no corre dentro de Vercel ni puede usar el `127.0.0.1` de una computadora personal desde producción. Para Vercel, usa OpenAI u otro proveedor cloud, o expón un servidor Ollama propio con URL segura y accesible desde Vercel.
- `usuarios_activos` puede consultar la API nueva de Multiadmin si hay token o credenciales configuradas; sin esas variables cae al endpoint Lambda legado. El diagnóstico de promo de Compinche y los datos completos de Multiadmin dependen de credenciales/tokens.
- El repo contiene una carpeta `tools/trash/` con scripts archivados que no forman parte del runtime activo.
- Las variables y dependencias asociadas a `Paripe` quedaron fuera de la documentación del runtime activo; hoy solo viven en scripts archivados dentro de `tools/trash/`.

## Auditoría de salientes

- La herramienta espera un CSV ya filtrado a llamadas salientes.
- Agrupa casos por agente, número normalizado y una ventana de `10 minutos` desde la primera llamada.
- Una llamada se considera contestada si trae fecha de contestación (`dateAnswered` o alias equivalente) o si dura más de `75 segundos`.
- Desde el segundo intento, una duración entre `15` y `75 segundos` se marca como voicemail probable y cuenta como cumplimiento completo.
- El segundo intento sin voicemail cuenta como cumplimiento solo si dura entre el mínimo configurable en pantalla y `14 segundos`; el mínimo por defecto es `10 segundos`.
- Filas con agente, número, fecha o duración insuficiente quedan como `No auditable` y no entran en el denominador del cumplimiento.
- Duplicados exactos por agente, número, fecha, duración y `TicketId` quedan como `No auditable` para evitar falsos segundos intentos.
- La pantalla muestra reconciliación de filas recibidas, filas válidas usadas, duplicados, no auditables y casos finales. También permite descargar la reconciliación y los casos no auditables.
- La pantalla marca alertas de casos raros cuando un agente llama más de `3` veces al mismo número dentro de `10 minutos`.
- Si faltan columnas opcionales como `TicketId` o fecha de contestación, la herramienta advierte que la trazabilidad o la clasificación tendrá menos evidencia.
- La asignación de turno usa coincidencia exacta de nombre y luego coincidencias flexibles por primer nombre/prefijo según la configuración de turnos.

## Reporte de agentes con Chatwoot

- El botón "Buscar stats diarias" consulta Chatwoot desde el backend usando `CHATWOOT_API_ACCESS_TOKEN`; el token no se expone al frontend.
- La consulta usa el rango completo de la fecha seleccionada según `CHATWOOT_TIMEZONE`.
- La integración usa el reporte de voz de Chatwoot/Chatpatch: `GET /custom/api/v1/accounts/:account_id/call_stats`.
- En la tabla existente, `Llamadas` corresponde a contestadas + perdidas, `Salientes` a llamadas salientes, `Perdidas` a llamadas perdidas, `Mins llamadas` a minutos entrantes y `Mins salientes` a minutos salientes.
- El flujo manual por CSV se mantiene como respaldo.

## Límites de CSV

- Los CSV subidos se validan antes de procesarse con pandas.
- Límite actual del CSV ya leído: `25 MB`.
- En auditoría de salientes, el navegador comprime automáticamente CSV grandes antes de enviarlos a Vercel. También se aceptan archivos `.csv.gz`.
- Si el archivo descomprimido supera ese tamaño, la app devuelve un error funcional antes de intentar procesarlo.

## Límite total de subida

- `MAX_CONTENT_LENGTH` limita el tamaño total de cada petición (archivos + campos del formulario). Valor por defecto: `52428800` bytes (50 MB), suficiente para los límites por archivo de CSV (25 MB) e Informe Semanal CS (40 MB).
- Si se supera, Flask responde `413` con un mensaje en español: una página de error en las vistas HTML y `{"success": false, "error": "..."}` en las rutas JSON.
- En Vercel la plataforma aplica además su propio límite de cuerpo de petición (unos 4,5 MB en funciones serverless), que se aplica antes de llegar a Flask; por eso la auditoría de salientes comprime los CSV en el navegador.
