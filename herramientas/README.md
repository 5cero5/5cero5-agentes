# herramientas

Herramientas que usan los agentes dentro de su sesión de Managed Agents (el repo se monta en `/workspace/agentes`).

| Archivo | Agente | Qué hace |
|---|---|---|
| `pr_landing.py` | Landing | `nueva` (carpeta desde la plantilla de marca), `revisar` (build del repo de landings + Verificador de marca con navegador) y `abrir` (rama `agente/<slug>-<fecha>` y PR a `main` por la API de GitHub). Solo sube `landings/<slug>/`; nunca toca `main` ni fusiona. |

Pruebas: `MARCA_REPO=… LANDINGS_REPO=… python3 test_pr_landing.py` (GitHub falso; necesita Playwright con Chromium y node). 15 comprobaciones.
