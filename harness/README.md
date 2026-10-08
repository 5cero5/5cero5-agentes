# Harness 5cero5 (Netlify Functions)

Lo que hace: lee la base Aprobaciones de Notion, y cuando Al o Bonzo aprueban una fila, abre una sesión de Managed Agents con tope de gasto. Cuando la sesión termina, escribe el resultado en Notion. No publica nada, no gasta en Meta, no marca nada como "Listo".

## Piezas
- `disparador` (cada 15 min): filas con Estado=Aprobado válidas -> reclama (En curso, Intentos+1) -> crea sesión -> guarda id de sesión.
- `webhook-sesion` (POST /api/webhook-sesion): recibe el aviso de Anthropic, verifica firma, cierra la fila (Para revisar, o Verificando si VERIFICADOR_ACTIVO=1; Error si tope o fallo).
- `barrido` (cada hora, minuto 7): red de seguridad para avisos perdidos (el webhook no reenvía lo viejo) y timeouts.

## Guardrails (en código, probados)
- Solo despacha si Aprobó y la última edición de la fila son de un id en NOTION_APROBADORES (un agente no se autoaprueba).
- Tope por sesión (default 2 USD, máximo 5 aunque Notion pida más). Máximo MAX_SESIONES_DIA por día. MAX_INTENTOS por fila.
- Se reclama la fila antes de crear la sesión; nada se reintenta solo tras un error.
- HARNESS_PAUSA=1 apaga el despacho sin tocar código.
- Pasar de MAX_MINUTOS_SESION: se interrumpe y queda en Error.

## Instalación (Netlify)
1. Proyecto nuevo y separado de mkt.5cero5.com, ligado a un repo `5cero5-harness` (privado). Sube esta carpeta.
2. Variables de entorno (Site configuration > Environment variables, marcar como secretas):
   ANTHROPIC_API_KEY, ANTHROPIC_WEBHOOK_SIGNING_KEY, NOTION_TOKEN, NOTION_APROBADORES (ids de usuario de Notion de Al y Bonzo, separados por coma), MA_ENVIRONMENT_ID, MA_VAULT_IDS, MA_AGENT_CREATIVO, MA_AGENT_LANDING, GH_REPO_URL, GH_REPO_READ_TOKEN (solo lectura, solo repo de marca). Opcionales: TOPE_DEFAULT_USD, TOPE_MAX_USD, MAX_SESIONES_DIA, MAX_INTENTOS, MAX_MINUTOS_SESION, VERIFICADOR_ACTIVO, HARNESS_PAUSA.
3. Notion: compartir la base Aprobaciones con la integración "5cero5 agentes" (Connections).
4. Deploy a producción (las funciones programadas solo corren en deploys publicados).
5. Claude Console > Webhooks: registrar `https://<sitio-harness>.netlify.app/api/webhook-sesion`, eventos de sesión (idled, budget_reached, terminated); copiar la signing key a la variable. La URL debe ser pública: no pongas contraseña a este proyecto.
6. Probar: fila de prueba con brief corto, Aprobó=tú, Estado=Aprobado; en Netlify > Functions > disparador > Run now.

## Pruebas
`npm install && npm test` (19 casos con mocks de Notion y de Anthropic).

## Qué NO está probado
Nada se ha corrido contra Notion, Anthropic ni Netlify reales. Pendiente de verificar en vivo: forma exacta del payload del webhook (el código asume data.id = id de sesión, data.type = tipo), que `last_edited_by` refleje a quien cambió el Estado, y los nombres de eventos registrados en la consola.

## Pendiente de diseño
Verificador: hoy `VERIFICADOR_ACTIVO` solo cambia el estado a "Verificando"; no hay código que lo ejecute. Sin él, todo pasa a "Para revisar" con Verificador=Pendiente y revisión humana. Decisión abierta: portar el Verificador a JS (con las 24 pruebas de paridad) o correrlo fuera de Netlify.
