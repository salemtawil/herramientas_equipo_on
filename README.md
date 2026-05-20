# herramientas_equipo_on-revision

App Flask con utilidades internas para procesar CSVs, consultar usuarios activos, auditar reportes y administrar breaks reservables.

## Correr localmente

1. Crea y activa un entorno virtual.
2. Instala dependencias:

```bash
pip install -r requirements.txt
```

3. Define variables de entorno según las herramientas que vayas a usar.
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
- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`
- `AWS_DEFAULT_REGION`
- `LOG_LEVEL`
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`

## Deploy en Vercel

Configuración actual:

- entrypoint: `app.py`
- runtime: `@vercel/python`
- rutas: todo entra por `app.py`

Antes de desplegar:

1. Configura `FLASK_SECRET_KEY` en Vercel.
2. Si usarás `usuarios_a_sheets`, configura `APPS_SCRIPT_WEBHOOK_URL` y, si aplica, `APPS_SCRIPT_WEBHOOK_TOKEN`.
3. Si usarás `usuarios_activos`, configura los tokens de Compinche.
4. Si usarás el módulo `break_admin`, configura:
   - `SUPABASE_URL`
   - `SUPABASE_SERVICE_ROLE_KEY`
5. Si esperas refresco automático del token de Compinche vía Cognito, configura también:
   - `AWS_ACCESS_KEY_ID`
   - `AWS_SECRET_ACCESS_KEY`
   - `AWS_DEFAULT_REGION=us-east-1`

## Limitaciones conocidas

- `usuarios_a_sheets` y `auditoria_salientes` guardan estado temporal firmado. Si el estado es pequeño, viaja inline; si crece, se apoya en almacenamiento temporal del runtime.
- `auditoria_csat` guarda su análisis temporal en almacenamiento efímero del runtime.
- `usuarios_activos` depende de APIs externas y puede fallar por timeouts o credenciales vencidas.
- El repo contiene una carpeta `tools/trash/` con scripts archivados que no forman parte del runtime activo.
- Las variables y dependencias asociadas a `Paripe` quedaron fuera de la documentación del runtime activo; hoy solo viven en scripts archivados dentro de `tools/trash/`.

## Límites de CSV

- Los CSV subidos se validan antes de procesarse con pandas.
- Límite actual por archivo: `5 MB`.
- Si el archivo supera ese tamaño, la app devuelve un error funcional antes de intentar procesarlo.
