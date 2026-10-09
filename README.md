# 5cero5-agentes

Código de la base de operación de 5cero5: el harness que conecta Notion (plano de control) con Claude Managed Agents, y los scripts de conectores probados en la POC.

El estado del trabajo (tareas, decisiones, aprobaciones) vive en Notion, en el objetivo **"Base de operación: Notion, harness y agentes de Claude"**. Este repo solo guarda código y su documentación.

## Estructura

| Carpeta | Qué es | Pruebas |
|---|---|---|
| `harness/` | Netlify Functions: `disparador` (filas aprobadas → sesión con tope), `webhook-sesion` (cierre de sesión → Notion) y `barrido` (eventos perdidos y timeouts). Ver `harness/README.md`. | `cd harness && npm ci && npm test` |
| `poc-conectores/` | Scripts de las pruebas 1 a 6 de la POC, `landing.py` y `correo.py`. | Necesitan el repo `5cero5-marca` (variable `MARCA_REPO`). |

## Reglas del repo

- **Código propio con lista cerrada.** Excepción a la regla 1 de 5cero5 (decisión del 8 oct de 2026): función `prospecto`, `landing.py`, `correo.py`, `armar_correo.py`, los tres verificadores y las tres funciones del harness. Un cliente nuevo se agrega con configuración, no con código nuevo.
- **Sin secretos.** Llaves y tokens van en las variables de entorno de Netlify o en el vault de Managed Agents. Nunca en el repo ni en el chat.
- **Ramas y commits.** Nada se trabaja directo en `main`: cada cambio va en una rama con commits chicos y se integra con un pull request que revisa Al o Bonzo.
