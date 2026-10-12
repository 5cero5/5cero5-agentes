# herramientas

Herramientas que usan los agentes dentro de su sesión de Managed Agents (el repo se monta en `/workspace/agentes`).

| Archivo | Agente | Qué hace |
|---|---|---|
| `pr_landing.py` | Landing | `nueva` (carpeta desde la plantilla de marca), `revisar` (build del repo de landings + Verificador de marca con navegador) y `abrir` (rama `agente/<slug>-<fecha>` y PR a `main` por la API de GitHub). Solo sube `landings/<slug>/`; nunca toca `main` ni fusiona. |
| `pr_pieza.py` | Creativo | `nueva` (pieza desde la plantilla del formato: post 4:5, post 1:1 o historia 9:16, con o sin foto), `foto` (Higgsfield: una por pieza, dos por sesión, el prompt debe pedir sin texto y sin logos), `llenar` (escribe `copia.json` en los SLOT), `revisar` (render con Playwright y Verificador de marca) y `abrir` (PR a `5cero5-piezas` con `piezas/<campaña>/<pieza>/`: pieza.png, pieza.html, copia.json, pieza.json, informe.json y, si lleva foto, `fotos/` y prompt.txt). Nunca fusiona. |
| `meta_pauta.py` | Pauta | `cuenta` (cuenta activa, en MXN, con o sin límite de gasto; nombre de la página), `plan` (valida nombre, objetivo, presupuesto contra el tope, fechas, público en México, destino https en dominio permitido y sin parámetros, textos sin exclamaciones y piezas fusionadas con informe aprobado del mismo PNG), `crear` (campaña, conjunto, imágenes, creativos con UTMs por `url_tags` y anuncios, todo PAUSED; una sola vez, no duplica nombres) y `comprobar` (lee de regreso en Meta). Su única salida de escritura solo crea en la cuenta dada y siempre en pausa. |
| `gh_pr.py` | (común) | API de Git de GitHub: sube una sola carpeta a una rama `agente/*` y abre el PR a `main`. Lo usan las dos herramientas. |

Pruebas: `MARCA_REPO=… LANDINGS_REPO=… python3 test_pr_landing.py` (GitHub falso; necesita Playwright con Chromium y node). 15 comprobaciones.
`MARCA_REPO=… python3 test_pr_pieza.py` (GitHub y Higgsfield falsos; necesita Pillow y Playwright con Chromium). 29 comprobaciones.
`python3 test_meta_pauta.py` (Graph API falsa; sin dependencias). 50 comprobaciones.
