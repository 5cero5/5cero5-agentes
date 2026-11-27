# herramientas

Herramientas que usan los agentes dentro de su sesión de Managed Agents (el repo se monta en `/workspace/agentes`).

| Archivo | Agente | Qué hace |
|---|---|---|
| `pr_landing.py` | Landing | `nueva` (carpeta desde la plantilla de marca), `revisar` (build del repo de landings + Verificador de marca con navegador) y `abrir` (rama `agente/<slug>-<fecha>` y PR a `main` por la API de GitHub). Solo sube `landings/<slug>/`; nunca toca `main` ni fusiona. |
| `pr_pieza.py` | Creativo | `nueva` (pieza desde la plantilla del formato: post 4:5, post 1:1 o historia 9:16, con o sin foto), `foto` (Higgsfield: una por pieza, dos por sesión, el prompt debe pedir sin texto y sin logos), `llenar` (escribe `copia.json` en los SLOT), `revisar` (render con Playwright y Verificador de marca) y `abrir` (PR a `5cero5-piezas` con `piezas/<campaña>/<pieza>/`: pieza.png, pieza.html, copia.json, pieza.json, informe.json y, si lleva foto, `fotos/` y prompt.txt). Nunca fusiona. |
| `meta_pauta.py` | Pauta | `cuenta` (cuenta activa, en MXN, con o sin límite de gasto; nombre de la página), `plan` (valida nombre, objetivo, presupuesto contra el tope, fechas, público en México, destino https en dominio permitido y sin parámetros, textos sin exclamaciones y piezas fusionadas con informe aprobado del mismo PNG), `crear` (campaña, conjunto, imágenes, creativos con UTMs por `url_tags` y anuncios, todo PAUSED; una sola vez, no duplica nombres) y `comprobar` (lee de regreso en Meta). Su única salida de escritura solo crea en la cuenta dada y siempre en pausa. |
| `higgsfield.py` | Creativo (vía `pr_pieza.py`) | Núcleo Higgsfield sin HTML ni Canva: política del cliente, modelos de lista cerrada, estimate exacto, reserva atómica en el registro duradero, Idempotency-Key, envío, reanudación, descarga validada, copia propia y limpieza. Ver «Higgsfield» abajo. |
| `gh_pr.py` | (común) | API de Git de GitHub: sube una sola carpeta a una rama `agente/*` y abre el PR a `main`. Lo usan las dos herramientas. |

Pruebas: `MARCA_REPO=… LANDINGS_REPO=… python3 test_pr_landing.py` (GitHub falso; necesita Playwright con Chromium y node). 15 comprobaciones.
`MARCA_REPO=… python3 test_pr_pieza.py` (GitHub y Higgsfield falsos; necesita Pillow y Playwright con Chromium). 58 comprobaciones.
`python3 test_higgsfield.py` (GitHub falso con CAS en la ref e Higgsfield falso con Idempotency-Key; cada corrida es un proceso, como una sesión; necesita Pillow). 61 comprobaciones.
`python3 test_meta_pauta.py` (Graph API falsa; sin dependencias). 50 comprobaciones.

## Canva (`pieza_canva.py`, lo usa `pr_pieza.py`)
Piezas del Creativo hechas en Canva (filas con `Canva: sí`; ver harness/README.md). `pr_pieza.py nueva --canva` toma la base aprobada de `canva/recursos.json` del repo de marca; el agente copia la base, cambia solo los textos, guarda, relee y exporta con el MCP de Canva; `canva-importar` baja la exportación original (solo hosts de Canva, sin redirecciones, 15 MB) y escribe `pieza.png` tal cual y `canva.json` (diseño, enlace de edición, elementos, sha256); `revisar` corre `verificador/verificar_canva.py` del repo de marca (sin HTML); `abrir` sube `pieza.png`, `canva.json`, `copia.json`, `pieza.json` e `informe.json`. La ronda (`revisar-pr`, solo Foto = Igual) va en dos pasos sobre el mismo diseño y el mismo PR. Prueba: `MARCA_REPO=../../5cero5-marca python3 test_pieza_canva.py` (necesita la marca con `verificar_canva.py`).

## Higgsfield (núcleo `higgsfield.py`)

Ruta única: la API de Higgsfield con la llave `HIGGSFIELD_API_KEY` del vault del Creativo de cada cliente (saldo API en USD, solo hacia `api.higgsfield.ai`, en encabezados). No se usa el MCP de Higgsfield (OAuth y créditos del plan web: otro producto y otro bolsillo).

Qué pide el brief y qué pasa:

| Brief | Higgsfield |
|---|---|
| `Foto: no` o nada | Ninguna llamada. |
| `Foto: repo:<id>` | Ninguna llamada: la foto del cliente tal cual (`fotos/fotos.json`, uso `directo`). |
| `Foto: sí` | Generar (Soul v2), una por pieza y dos por sesión. |
| `Foto: referencia:<id>` | Editar con la foto del cliente como entrada: `fotos.json` con uso `referencia_ia` y `personas: false`, **y** `referencias_ia: true` en `higgsfield.json`. |
| Ronda `Igual` / `Editar` / `Nueva` | Igual: ninguna llamada, mismos bytes. Editar: la foto actual como entrada. Nueva: generar otra. Siempre sobre el mismo PR. |

Configuración por cliente (lo que tiene que existir antes de la primera foto):
1. `higgsfield.json` en la raíz del repo de marca del cliente (contrato cerrado; importes como texto): `version` 1, `permitido`, `registro_raiz` (paso 4), `tope_usd` (agregado: reservado + consumido de todas las sesiones), `max_usd_por_operacion` (cota de reserva), `generar`, `editar`, `referencias_ia`, `acepta_retencion_uploads_s` (los uploads de Editar y referencia viven hasta 7 días en Higgsfield sin borrado por API: con menos de 604800 no se sube nada). Sin el archivo, no hay Higgsfield.
2. `HIGGSFIELD_API_KEY` en el vault Creativo del cliente, restringida a `api.higgsfield.ai` e inyectada solo en encabezados (`harness/infra/crear_agente_creativo.py` con `HF_API_KEY`, o la consola de Claude). Nunca en Notion, en el chat ni en un archivo.
3. Red del entorno: `api.higgsfield.ai`, el host del CDN de las imágenes y el de la URL firmada de upload (`harness/infra/comun.py`). Un host nuevo no se agrega solo.
4. El registro del cliente, creado UNA vez por una persona (con su token, no el de una sesión): `GITHUB_TOKEN=… python3 herramientas/higgsfield.py iniciar --repo <org>/<repo-de-piezas>`. Imprime `registro_raiz`: se anota en `higgsfield.json` del repo de marca con un PR revisado. Cada lectura comprueba que la punta del registro desciende de esa raíz, así que si lo borran o lo recrean no hay Higgsfield (se restaura, no se recrea). El token de GitHub de la sesión (contents y pull_requests en el repo de piezas) lo escribe después.
5. `--fila <id de la página de Notion>` en el comando del Creativo: lo pone el harness en `comandoPieza` (harness/lib/agentes.mjs) desde la integración con Canva en la rama `creativo`. Sin fila no hay Higgsfield; por eso este núcleo se fusiona junto con ese cambio o después, nunca antes.
6. Recomendado: una regla del repo de piezas que impida borrar `agente/higgsfield` y los push forzados en ella.

Registro duradero: rama `agente/higgsfield` del repo de piezas del cliente (no tiene PR ni toca `main`). Una pieza y etapa (original o `ronda-pr<n>-<head>-Editar|Nueva`) tiene UNA operación; su dueña es la fila de Notion que la reservó.
- `higgsfield/registro.json`: una entrada por operación con `id` (pieza + etapa), `fila`, `estado`, `idempotency_key`, `endpoint`, `cuerpo`, `encabezados` (`Hf-Expires-After: 3600`), `webhook` (null), `cuerpo_sha256`, `cota_usd`, `estimado_usd`, `request_id`, `status_url`, `archivo`, `cargo` (importe y calidad de la evidencia), `borrado`, `limpieza`, `subida` e `historial`.
- `higgsfield/archivos/<sha256>.<ext>`: la copia propia de cada imagen, guardada ANTES del `DELETE /requests/{id}`.
- Cada escritura es un commit encima de la punta y un PATCH de la ref sin forzar: si otra sesión escribió antes, se relee y se vuelve a comprobar el tope. Así dos sesiones no gastan el mismo cupo.

Estados: `reservado` (cota apartada, sin cuerpo) → `listo` (cuerpo, clave y estimate congelados) → `enviado` (request aceptado) → `completed` | `failed` | `nsfw` | `canceled`. Además `incierto` (no se sabe si se aceptó), `conflicto` (422: la clave ya se usó con otros parámetros), `rechazada` (4xx antes de aceptar) y `descartada` (el estimate pasa la cota o el tope). No cuentan contra el tope: `failed`, `nsfw`, `canceled` (sin cobro según la documentación de Higgsfield), `rechazada` y `descartada`.

Reanudar (lo hace la herramienta sola cuando la corrida trae la MISMA `--fila`: el reintento de esa fila de Notion; otra fila para la misma pieza y etapa se detiene sin gastar):
- `completed` con archivo: se baja del registro, cero llamadas a Higgsfield (solo se reintenta el `DELETE` si quedó pendiente).
- `enviado` o `incierto` con `request_id`: se consulta su `status_url`, no se envía nada.
- `listo` o `incierto` sin `request_id`: el MISMO POST con la MISMA clave, endpoint, cuerpo y retención (solo dentro de `HF_VENTANA_REPLAY_H`, 24 h por defecto: no se sabe cuánto dura la clave); Higgsfield devuelve el request original. Un 4xx después de un envío sin respuesta deja la operación `incierto` (sigue contando).
- `reservado`: se vuelve a estimar (y a subir la entrada, si es edición) con la misma clave.
- `failed`, `nsfw`, `canceled`, `conflicto`, `rechazada`, `descartada`: no se pide otra; hace falta una ronda `Nueva` aprobada.

A mano (solo Al o Bonzo, nunca el agente; `iniciar` y `liberar` se niegan con un token de instalación `ghs_…`; no llaman a Higgsfield):
- `python3 herramientas/higgsfield.py estado --repo <repo> [--raiz <registro_raiz>]`: operaciones y USD expuestos.
- `python3 herramientas/higgsfield.py liberar --repo <repo> --operacion <id> --motivo "…"`: una reserva que nunca se envió (`reservado`) pasa a `descartada`.
- Igual con `--confirmo-sin-aceptar`: cierra un `listo` o `incierto` sin `request_id` después de comprobar en Higgsfield que no se aceptó. Con `request_id`, nunca.
- El motivo queda en el historial. Nunca se borran entradas: son la evidencia del gasto.
- Una pieza y etapa ya `completed` no admite otra operación, ni desde otra fila: un trabajo nuevo usa otro slug de pieza desde `nueva`.

Costos y evidencia: `estimado_usd` es el estimate autenticado con el cuerpo exacto, previo al envío (la cifra que la documentación da por autoritativa para la cuenta); no es factura. `GET /models/usage` es analítica que puede ir retrasada; la conciliación final es contra la factura o el saldo de la cuenta API.

Retención: cada request va con `Hf-Expires-After: 3600` y se borra con `DELETE` en cuanto la copia propia está guardada; un fallo queda como `limpieza: pendiente` (Higgsfield lo borra al vencer). Los uploads de entrada no se borran por API: quedan registrados en `subida` con su retención de hasta 7 días.

Composición: la imagen es solo fondo. `--marco <ancho>x<alto>` da el hueco real de la imagen en el diseño (Canva); sin él, se usa el `.foto` de la plantilla HTML. Nunca se cambia de modelo ni de proporción por un error.
