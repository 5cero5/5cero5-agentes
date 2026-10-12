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

## Agentes (`lib/agentes.mjs`)
El harness solo despacha agentes que están en el catálogo y tienen su id en una variable. Cada uno declara qué repos monta, sus reglas fijas y el JSON con el que termina. Una fila con otro agente (Datos, CMO) pasa a Error sin abrir sesión.

| Agente | Variable | Monta | Termina con |
|---|---|---|---|
| Pauta | MA_AGENT_PAUTA | agentes y piezas (solo lectura) | `campana_meta_id`, `nombre` (AAAA-MM_zona_angulo), `cuenta`, `conjunto_id`, `anuncios` (id, nombre, pieza), `presupuesto_diario_mxn`, `objetivo` |
| Creativo | MA_AGENT_CREATIVO | marca y agentes | `pr_url`, `pr_numero`, `rama` (`agente/…`), `commit`, `campana`, `pieza`, `formato` (post-4x5, post-1x1, historia-9x16), `foto` |
| Landing | MA_AGENT_LANDING | marca, agentes y landings | `pr_url`, `pr_numero`, `rama` (`agente/…`), `commit`, `slug`, `cambios` |
| CRM | MA_AGENT_CRM | marca y agentes | `plantilla_id`, `nombre` (con prefijo `[agente] `), `html_sha1` |
| CMO | MA_AGENT_CMO | marca | `campana_id`, `filas` (al menos una), `sin_agente` |

### Campañas → CMO (`lib/campanas.mjs`)
Cuando Al o Bonzo pasan una campaña de la base Campañas a **Aprobada** (con Aprobó y la última edición suyos, Ruta y Piezas llenas), el disparador:
1. la pasa a **En producción** antes de crear nada, para no despacharla dos veces;
2. crea en Aprobaciones la fila "Desglose · <campaña>" con Agente = CMO, ya **En curso** y ligada a la campaña;
3. abre la sesión del CMO con los datos de la campaña y la lista de agentes con id configurado.

El CMO escribe una fila **Propuesta** por pieza, ligada a la campaña. Escribe con la integración de Notion de los agentes (un bot), así que el harness no despacha ninguna de esas filas hasta que Al o Bonzo las aprueben. Las campañas comparten el cupo diario con las filas.

Al cerrar la sesión del CMO, el harness comprueba en Notion cada fila que el CMO dice que escribió (regla 8): que exista, esté en Propuesta, sin Aprobó, con un agente de pieza y ligada a la campaña. Si todo cuadra, Verificador = Aprobada; si no, Rechazada con el detalle en el informe. La fila del CMO siempre queda en Para revisar.

### Landing → PR en 5cero5-landings
Las landings viven en el repo `5cero5/5cero5-landings` (sitio marketing.5cero5.com), una carpeta por landing. El agente Landing crea o cambia **una** carpeta con `herramientas/pr_landing.py` (nueva, revisar, abrir) y abre un PR a `main` desde una rama `agente/…`. El deploy preview de Netlify es el borrador; publicar es aprobar y fusionar el PR en GitHub, solo Al o Bonzo.

- **Token (GitHub App `5cero5-agentes`, instalada solo en ese repo):** antes de cada sesión de Landing, el disparador saca un token de instalación de 1 hora con permisos `contents` y `pull_requests` de escritura, limitado a ese repo, y lo pone en la credencial `GITHUB_TOKEN` del vault de Landing (solo en encabezados hacia api.github.com). Saca otro, de solo lectura, para montar el repo en `/workspace/landings`, y guarda el sha de `main` en la metadata de la sesión.
- **Al cerrar (regla 8):** el harness comprueba en GitHub que el PR existe, está abierto y sin fusionar, va de `agente/…` a `main`, su commit es el que reportó el agente, solo cambia `landings/<slug>/` y que `main` no se movió durante la sesión. Verificador = Aprobada o Rechazada con el detalle; la fila queda en Para revisar.
- **Mientras no haya protección de `main`** (GitHub Team, pendiente de decidir con Bonzo), un token de escritura de la app podría fusionar: el límite lo ponen el prompt, que el agente solo use `pr_landing.py` y la comprobación de arriba. No se configura la app en el harness hasta decidirlo.

### Creativo → PR en 5cero5-piezas
Cada pieza (post 4:5, post 1:1 o historia 9:16) vive en `piezas/<campaña>/<pieza>/` del repo `5cero5/5cero5-piezas`: pieza.png, pieza.html, copia.json, pieza.json, informe.json (Verificador de marca) y, si lleva foto de Higgsfield, `fotos/` y prompt.txt. El agente la arma con `herramientas/pr_pieza.py` (nueva, foto, llenar, revisar, abrir) y abre un PR a `main` desde `agente/…`. Aprobar = Al fusiona el PR; subirla a Meta la hace Bonzo a mano, con la campaña en pausa.

- **Token:** la misma GitHub App, instalada también en `5cero5-piezas`. Antes de cada sesión, token de escritura de 1 hora limitado a ese repo en la credencial `GITHUB_TOKEN` del vault del Creativo (MA_CRED_GITHUB_CREATIVO). El repo de piezas no se monta.
- **Foto:** solo si el brief dice "Foto: sí". La llave de Higgsfield vive solo en el vault del Creativo (hacia api.higgsfield.ai); `pr_pieza.py` permite una foto por pieza y dos por sesión. El tope real de gasto es el saldo de la API de Higgsfield.
- **Al cerrar (regla 8):** lo mismo que Landing (PR abierto, sin fusionar, rama `agente/…`, commit, solo su carpeta, `main` quieto) y además, en la punta del PR: solo los archivos permitidos, informe.json aprobado y del mismo PNG (sha del blob), formato y foto como dijo el agente, y el PNG mide lo de su formato. Verificador = Aprobada o Rechazada; la fila queda en Para revisar.

### Pauta → campaña en Meta, en pausa
Una sesión arma una campaña de Meta con un conjunto y un anuncio por pieza ya fusionada en `5cero5-piezas`, todo con status PAUSED, con `herramientas/meta_pauta.py` (cuenta, plan, crear, comprobar) por la Marketing API (v25.0). Aprobar la fila es aprobar presupuesto, fechas, público y destino; encender la campaña es de Al o Bonzo en el Administrador de anuncios.

- **Por qué API y no el MCP oficial de Meta:** el MCP (`mcp.facebook.com/ads`) crea en pausa, pero trae `ads_activate_entity` y no tiene herramienta para subir imágenes. Con la API, la única salida de escritura de `meta_pauta.py` solo crea en `/act_<cuenta>/{campaigns,adsets,ads,adcreatives,adimages}` y siempre con PAUSED; no puede activar, editar ni borrar. El MCP queda para reportes.
- **Token:** usuario del sistema del portafolio con `ads_management` (acceso estándar basta para la cuenta propia). Va en el vault de Pauta (META_TOKEN, solo en encabezados hacia graph.facebook.com) y, como variable secreta, en Netlify para la comprobación.
- **Piezas:** el repo `5cero5-piezas` se monta en `/workspace/piezas` con un token de **lectura** de la GitHub App; Pauta no recibe token de escritura de GitHub.
- **Tope:** META_TOPE_DIARIO_MXN (1,500 por omisión) por campaña, en la herramienta y en la comprobación. El freno de fondo es el límite de gasto de la cuenta: sin él, la comprobación avisa.
- **Al cerrar (regla 8, `lib/meta.mjs`):** lee la campaña en Meta: cuenta y página correctas, creada en esta sesión, un conjunto con presupuesto diario dentro del tope, los anuncios que reportó el agente y nada más, destino en META_DOMINIOS y todo en pausa. **Lo que no esté en pausa, el harness lo pausa en ese momento** y la fila sale Rechazada.
- **Fila de Pauta:** la propone el CMO junto con las piezas (una por campaña, si va a Meta, trae Pauta en MXN y el agente está disponible), con presupuesto diario = Pauta ÷ días de vigencia, sin pasar el tope, y "Piezas: todas las de la carpeta". El harness no la despacha mientras alguna fila del Creativo de la misma campaña no esté en Listo (`piezas_pendientes`).
- **Riesgo que queda:** el agente tiene bash y el token sustituido en encabezados hacia graph.facebook.com; si ignorara su prompt podría activar algo durante la sesión. Lo acotan el límite de gasto de la cuenta, el inicio futuro del conjunto que pide el brief, la sesión de 30 minutos como máximo y el freno al cerrar.

Al cerrar la sesión el harness revisa solo el formato de esa respuesta y lo anota en el informe. Si el trabajo está bien lo decide el Verificador o una persona, comprobándolo en la herramienta.

## Instalación (Netlify)
1. Proyecto nuevo y separado de mkt.5cero5.com, ligado al repo privado `5cero5/5cero5-agentes` con **Base directory = `harness`** (el código vive en esta carpeta del repo, no en un repo `5cero5-harness` aparte).
2. Variables de entorno (Site configuration > Environment variables, marcar como secretas):
   ANTHROPIC_API_KEY, ANTHROPIC_WEBHOOK_SIGNING_KEY, NOTION_TOKEN, NOTION_APROBADORES (ids de usuario de Notion de Al y Bonzo, separados por coma), MA_ENVIRONMENT_ID, MA_VAULT_IDS, MA_AGENT_CREATIVO, MA_AGENT_LANDING, MA_AGENT_CRM, MA_AGENT_CMO, GH_REPO_URL (repo de marca), GH_AGENTES_URL (este repo, para landing.py y correo.py), GH_REPO_READ_TOKEN (fine-grained, solo lectura, con acceso a los dos repos; si prefieres uno por repo, GH_AGENTES_READ_TOKEN). Vault por agente: MA_VAULT_CREATIVO, MA_VAULT_LANDING, MA_VAULT_CRM, MA_VAULT_CMO (cada uno solo con las credenciales de ese agente; si falta, se usa MA_VAULT_IDS). Landing (GitHub App): GH_APP_ID, GH_APP_INSTALLATION_ID, GH_APP_PRIVATE_KEY (secreta; la llave .pem completa, sirve con saltos de línea o con \\n) y MA_CRED_GITHUB_LANDING (la imprime `crear_agente_landing.py`); opcionales GH_LANDINGS_URL y GH_LANDINGS_REPO. Creativo (misma App): MA_CRED_GITHUB_CREATIVO (la imprime `crear_agente_creativo.py`); opcional GH_PIEZAS_REPO. Pauta: MA_AGENT_PAUTA, MA_VAULT_PAUTA, META_AD_ACCOUNT_ID, META_PAGE_ID, opcionales META_IG_USER_ID y META_PIXEL_ID (los imprime `crear_agente_pauta.py`), META_TOPE_DIARIO_MXN, META_DOMINIOS (marketing.5cero5.com por omisión), GH_PIEZAS_URL; y META_TOKEN como secreta. Opcionales: NOTION_CAMPANAS_ID (data source de Campañas), TOPE_DEFAULT_USD, TOPE_MAX_USD, MAX_SESIONES_DIA, MAX_INTENTOS, MAX_MINUTOS_SESION, VERIFICADOR_ACTIVO, HARNESS_PAUSA.
3. Notion: compartir la base Aprobaciones con la integración "5cero5 agentes" (Connections).
4. Deploy a producción (las funciones programadas solo corren en deploys publicados).
5. Claude Console > Webhooks: registrar `https://<sitio-harness>.netlify.app/api/webhook-sesion` con los eventos `session.status_idled`, `session.status_terminated` y `session.budget_reached` (los `session.thread_*` no hacen falta: se ignoran). Copiar la signing key a ANTHROPIC_WEBHOOK_SIGNING_KEY y volver a hacer deploy.
   La URL debe ser pública: en Project configuration > General > Visitor access, sin protección. Ojo: el equipo de Netlify puede traer protección por defecto para proyectos nuevos; con ella el webhook recibe la página de login en vez del aviso. Prueba: `curl -s -X POST https://<sitio-harness>.netlify.app/api/webhook-sesion -d '{}'` debe responder `firma inválida`.
6. Probar: fila de prueba con brief corto, Aprobó=tú, Estado=Aprobado; en Netlify > Functions > disparador > Run now.

## Alta de agentes (`infra/`)
`crear_agente_crm.py`, `crear_agente_cmo.py`, `crear_agente_landing.py`, `crear_agente_creativo.py` y `crear_agente_pauta.py` crean el vault, la credencial y el agente en Managed Agents, y reaplican la red del entorno común (`infra/comun.py`, lista HOSTS). Se corren desde la Terminal de Al con los secretos en variables (instrucciones en cada script); los ids quedan en `infra/estado-*.json`, que no se versiona. Los prompts viven en `agentes/*.md`. El entorno común lleva `httpx` y `playwright` (pip); el Chromium del Verificador de landing lo baja cada sesión del agente Landing desde los hosts de Playwright que están en HOSTS.

## Pruebas
`npm ci && npm test` (77 casos con mocks de Notion, Anthropic, GitHub y la Graph API de Meta).

## Qué NO está probado
Desplegado en Netlify el 8 oct de 2026 y corrido solo con HARNESS_PAUSA=1 (el disparador respondió HARNESS_PAUSA). Todavía no se ha despachado ninguna fila real de Notion ni abierto una sesión desde el harness. Pendiente de verificar en vivo: forma exacta del payload del webhook (el código asume data.id = id de sesión, data.type = tipo) y que `last_edited_by` refleje a quien cambió el Estado. Los nombres de eventos se confirmaron en la consola el 8 oct de 2026.

## Pendiente de diseño
Verificador: hoy `VERIFICADOR_ACTIVO` solo cambia el estado a "Verificando"; no hay código que lo ejecute. Sin él, todo pasa a "Para revisar" con Verificador=Pendiente y revisión humana. Decisión abierta: portar el Verificador a JS (con las 24 pruebas de paridad) o correrlo fuera de Netlify.
