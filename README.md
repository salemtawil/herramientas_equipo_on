# herramientas_equipo_on-revision

App Flask con utilidades internas para procesar CSVs, consultar usuarios activos y enviar resultados a Google Sheets.

## Correr localmente

1. Crea y activa un entorno virtual.
2. Instala dependencias:

```bash
pip install -r requirements.txt
```

3. Define variables de entorno segun las herramientas que vayas a usar.
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

Obligatoria en produccion:

- `FLASK_SECRET_KEY`

Opcionales segun funcionalidad:

- `APPS_SCRIPT_WEBHOOK_URL`
- `APPS_SCRIPT_WEBHOOK_TOKEN`
- `COMPINCHE_ID_TOKEN`
- `COMPINCHE_REFRESH_TOKEN`
- `COMPINCHE_CLIENT_ID`
- `PARIPE_ID_TOKEN`
- `PARIPE_REFRESH_TOKEN`
- `PARIPE_CLIENT_ID`
- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`
- `AWS_DEFAULT_REGION`
- `LOG_LEVEL`
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`

## Deploy en Vercel

Configuracion actual:

- entrypoint: `app.py`
- runtime: `@vercel/python`
- rutas: todo entra por `app.py`

Antes de desplegar:

1. Configura `FLASK_SECRET_KEY` en Vercel.
2. Si usaras `usuarios_a_sheets`, configura `APPS_SCRIPT_WEBHOOK_URL` y, si aplica, `APPS_SCRIPT_WEBHOOK_TOKEN`.
3. Si usaras `usuarios_activos`, configura los tokens de Compinche y Paripe.
4. Si usaras el modulo `break_admin`, configura:
   - `SUPABASE_URL`
   - `SUPABASE_SERVICE_ROLE_KEY`
5. Si esperas refresco automatico de tokens via Cognito, configura tambien:
   - `AWS_ACCESS_KEY_ID`
   - `AWS_SECRET_ACCESS_KEY`
   - `AWS_DEFAULT_REGION=us-east-1`

## Limitaciones conocidas

- `usuarios_a_sheets` y `auditoria_salientes` guardan estado temporal firmado. Si el estado es pequeno, viaja inline; si crece, se apoya en almacenamiento temporal del runtime.
- `auditoria_csat` guarda su analisis temporal en almacenamiento efimero del runtime.
- `usuarios_activos` depende de APIs externas y puede fallar por timeouts o credenciales vencidas.
- El repo contiene una carpeta `tools/trash/` con scripts archivados que no forman parte del runtime activo.

## Limites de CSV

- Los CSV subidos se validan antes de procesarse con pandas.
- Limite actual por archivo: `5 MB`.
- Si el archivo supera ese tamano, la app devuelve un error funcional antes de intentar procesarlo.
