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

## Deploy en Vercel

Configuracion actual:

- entrypoint: `app.py`
- runtime: `@vercel/python`
- rutas: todo entra por `app.py`

Antes de desplegar:

1. Configura `FLASK_SECRET_KEY` en Vercel.
2. Si usaras `usuarios_a_sheets`, configura `APPS_SCRIPT_WEBHOOK_URL` y, si aplica, `APPS_SCRIPT_WEBHOOK_TOKEN`.
3. Si usaras `usuarios_activos`, configura los tokens de Compinche y Paripe.
4. Si esperas refresco automatico de tokens via Cognito, configura tambien:
   - `AWS_ACCESS_KEY_ID`
   - `AWS_SECRET_ACCESS_KEY`
   - `AWS_DEFAULT_REGION=us-east-1`

## Limitaciones conocidas

- `usuarios_a_sheets` mantiene el resultado intermedio en un payload firmado enviado por formulario. Eso evita depender de memoria compartida entre requests, pero puede crecer con CSVs grandes.
- `usuarios_activos` depende de APIs externas y puede fallar por timeouts o credenciales vencidas.
- El repo contiene una carpeta `tools/trash/` con scripts archivados que no forman parte del runtime activo.
