# herramientas_equipo_on-revision

App Flask con utilidades internas para procesar CSVs, consultar usuarios activos, auditar reportes y administrar breaks reservables.

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

```bash
python -m unittest discover -s tests -v
```

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

## Límites de CSV

- Los CSV subidos se validan antes de procesarse con pandas.
- Límite actual del CSV ya leído: `25 MB`.
- En auditoría de salientes, el navegador comprime automáticamente CSV grandes antes de enviarlos a Vercel. También se aceptan archivos `.csv.gz`.
- Si el archivo descomprimido supera ese tamaño, la app devuelve un error funcional antes de intentar procesarlo.
