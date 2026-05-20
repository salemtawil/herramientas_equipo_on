# AGENTS.md

## Proyecto
Este repositorio es una app Flask monolítica, 100% server-rendered.

### Arquitectura real
- Frontend: `templates/` + `static/styles.css`
- Backend HTTP: `app.py`
- Herramientas: `tools/`
- Utilidades: `utils/`
- Deploy: Vercel sobre `app.py`

### Patrón obligatorio para nuevas herramientas
Cuando agregues una herramienta nueva:
1. Crear blueprint en `tools/`
2. Registrar blueprint en `app.py`
3. Crear template Jinja en `templates/`
4. Integrar navegación en `templates/base.html`
5. Agregar card en `templates/inicio.html` si aplica
6. Mantener estilo visual consistente con el admin actual

## Reglas de trabajo
- No crear frontend separado.
- No introducir React, Vue ni SPA.
- No romper herramientas existentes.
- Preferir diffs pequeños y seguros.
- No hacer refactors masivos sin pedirlo.
- Mantener la lógica de negocio intacta salvo que el task lo exija.
- Antes de agregar dependencias nuevas, justificar por qué hacen falta.
- Si agregas variables de entorno nuevas, actualizar `.env.example` y `README.md`.

## UI / UX
- Para cambios visuales o de frontend, priorizar `ui-ux-pro-max`.
- Mantener consistencia con el layout admin actual.
- Todo estilo compartido debe ir preferentemente en `static/styles.css`.
- Evitar CSS grande embebido en templates.
- Las tablas anchas deben usar scroll interno, no romper el layout global.
- Formularios, barras de acciones y grids deben hacer wrap correctamente.

## Metodología
- Para tareas complejas, planificación o cambios grandes, usar `superpowers`.
- Antes de implementar cambios medianos/grandes:
  1. definir plan
  2. identificar impacto
  3. implementar
  4. validar manualmente
- Preferir cambios incrementales.

## Tablas y layout
- Toda tabla debe vivir dentro de un wrapper tipo `table-wrap`.
- Evitar overflow horizontal global.
- Revisar `min-width`, `white-space`, `flex-wrap`, `min-width: 0` y grids antes de tocar más layout.

## Integraciones externas
- No exponer secretos al frontend.
- Toda integración sensible debe pasar por backend Flask.
- Si hay Google / Apps Script / Supabase, mantener claves solo del lado servidor.

## Herramientas existentes delicadas
- `usuarios_activos`: cuidado con estructura JSON consumida por frontend.
- `usuarios_a_sheets`: no romper webhook actual ni flujo de exportación.
- `auditoria_salientes`: mantener clasificación y exportes funcionando.
- `break_admin`: no tocar la app externa `herramientas-agentes`.
- `auditoria_csat`: preservar flujo upload -> auditoría -> resumen -> exportes.

## Validación mínima esperada
Después de cambios:
- Probar importación/compilación de los módulos tocados
- Probar manualmente la ruta principal afectada
- Confirmar que no se rompió navegación del admin
- Si hay tablas o cards, revisar en desktop y ventana angosta

## Preferencias de implementación
- Priorizar claridad sobre abstracción innecesaria
- Preferir helpers simples en `utils/` antes que capas complejas
- Mantener nombres consistentes con el proyecto
- Respetar textos en español para UI del admin