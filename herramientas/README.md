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
`MARCA_REPO=… python3 test_pr_pieza.py` (GitHub y Higgsfield falsos; necesita Pillow y Playwright con Chromium). 55 comprobaciones.
`python3 test_higgsfield.py` (GitHub falso con CAS en la ref e Higgsfield falso con Idempotency-Key; cada corrida es un proceso, como una sesión; necesita Pillow). 47 comprobaciones.
`python3 test_meta_pauta.py` (Graph API falsa; sin dependencias). 50 comprobaciones.

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
1. `higgsfield.json` en la raíz del repo de marca del cliente (contrato cerrado; importes como texto): `version` 1, `permitido`, `tope_usd` (agregado: reservado + consumido de todas las sesiones), `max_usd_por_operacion` (cota de reserva), `generar`, `editar`, `referencias_ia`, `acepta_retencion_uploads_s` (los uploads de Editar y referencia viven hasta 7 días en Higgsfield sin borrado por API: con menos de 604800 no se sube nada). Sin el archivo, no hay Higgsfield.
2. `HIGGSFIELD_API_KEY` en el vault Creativo del cliente, restringida a `api.higgsfield.ai` e inyectada solo en encabezados (`harness/infra/crear_agente_creativo.py` con `HF_API_KEY`, o la consola de Claude). Nunca en Notion, en el chat ni en un archivo.
3. Red del entorno: `api.higgsfield.ai`, el host del CDN de las imágenes y el de la URL firmada de upload (`harness/infra/comun.py`). Un host nuevo no se agrega solo.
4. El token de GitHub de la sesión (el de siempre: contents y pull_requests en el repo de piezas del cliente) escribe el registro.

Registro duradero: rama `agente/higgsfield` del repo de piezas del cliente (no tiene PR ni toca `main`).
- `higgsfield/registro.json`: una entrada por operación con `id` (fila de Notion + pieza + etapa), `estado`, `idempotency_key`, `endpoint`, `cuerpo`, `encabezados` (`Hf-Expires-After: 3600`), `webhook` (null), `cuerpo_sha256`, `cota_usd`, `estimado_usd`, `request_id`, `status_url`, `archivo`, `cargo` (importe y calidad de la evidencia), `borrado`, `limpieza`, `subida` e `historial`.
- `higgsfield/archivos/<sha256>.<ext>`: la copia propia de cada imagen, guardada ANTES del `DELETE /requests/{id}`.
- Cada escritura es un commit encima de la punta y un PATCH de la ref sin forzar: si otra sesión escribió antes, se relee y se vuelve a comprobar el tope. Así dos sesiones no gastan el mismo cupo.

Estados: `reservado` (cota apartada, sin cuerpo) → `listo` (cuerpo, clave y estimate congelados) → `enviado` (request aceptado) → `completed` | `failed` | `nsfw` | `canceled`. Además `incierto` (no se sabe si se aceptó), `conflicto` (422: la clave ya se usó con otros parámetros), `rechazada` (4xx antes de aceptar) y `descartada` (el estimate pasa la cota o el tope). No cuentan contra el tope: `failed`, `nsfw`, `canceled` (sin cobro según la documentación de Higgsfield), `rechazada` y `descartada`.

Reanudar (lo hace la herramienta sola si la corrida trae `--fila`, el id de la página de Notion; un reintento de la misma fila es la misma operación):
- `completed` con archivo: se baja del registro, cero llamadas a Higgsfield (solo se reintenta el `DELETE` si quedó pendiente).
- `enviado` o `incierto` con `request_id`: se consulta su `status_url`, no se envía nada.
- `listo` o `incierto` sin `request_id`: el MISMO POST con la MISMA clave, endpoint, cuerpo y retención; Higgsfield devuelve el request original.
- `reservado`: se vuelve a estimar (y a subir la entrada, si es edición) con la misma clave.
- `failed`, `nsfw`, `canceled`, `conflicto`, `rechazada`, `descartada`: no se pide otra; hace falta una ronda `Nueva` aprobada.
- Sin `--fila` no se retoma: si ya hay una operación de esa pieza y etapa, se detiene sin gastar.

A mano (solo Al o Bonzo, con un commit en `agente/higgsfield` que diga por qué): liberar una reserva que nunca se envió (`reservado` → `descartada`) o cerrar un `incierto` después de confirmar en Higgsfield, con su `request_id`, si se aceptó. Nunca borrar entradas: el historial es la evidencia del gasto.

Costos y evidencia: `estimado_usd` es el estimate autenticado con el cuerpo exacto, previo al envío (la cifra que la documentación da por autoritativa para la cuenta); no es factura. `GET /models/usage` es analítica que puede ir retrasada; la conciliación final es contra la factura o el saldo de la cuenta API.

Retención: cada request va con `Hf-Expires-After: 3600` y se borra con `DELETE` en cuanto la copia propia está guardada; un fallo queda como `limpieza: pendiente` (Higgsfield lo borra al vencer). Los uploads de entrada no se borran por API: quedan registrados en `subida` con su retención de hasta 7 días.

Composición: la imagen es solo fondo. `--marco <ancho>x<alto>` da el hueco real de la imagen en el diseño (Canva); sin él, se usa el `.foto` de la plantilla HTML. Nunca se cambia de modelo ni de proporción por un error.
