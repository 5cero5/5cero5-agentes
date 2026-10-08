# Prueba de factibilidad 5 · Repo de marca montado en la sesión

La prueba contesta una pregunta: ¿un managed agent puede recibir el repositorio privado `5cero5-marca` montado en su contenedor, leer las reglas, llenar la plantilla con un texto nuevo y entregar una pieza con las fuentes y el logo de la marca?

## Antes de correrla (unos 10 minutos)

1. **Revisa el repo en GitHub.** En la raíz deben estar `VERSION`, `reglas.md`, `tokens.json` y las carpetas `plantillas/`, `fonts/` y `logos/`. La guía de marca que subiste puede ir en cualquier carpeta aparte.
2. **Crea un token de solo lectura**, limitado a ese repo:
   - GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token.
   - Resource owner: la cuenta u organización dueña del repo.
   - Expiration: 30 días.
   - Repository access: **Only select repositories** → `5cero5-marca`.
   - Permissions → Repository permissions → **Contents: Read-only**. Nada más.
   - Ideal: que lo genere la cuenta de `ops@5cero5.com`. Mientras no exista, usa la tuya y cámbialo antes de encender la campaña.
   - GitHub lo muestra una sola vez. Si la organización exige aprobar tokens, apruébalo en Settings de la organización.
3. **Copia la URL del repo**, como `https://github.com/TU-ORG/5cero5-marca`.

## Correrla

Desde la carpeta `poc-conectores`, en la misma Terminal (o vuelve a cargar `ANTHROPIC_API_KEY`). Deja `prueba_render.py` en la misma carpeta:

```bash
read -s GH_TOKEN && export GH_TOKEN
export GH_REPO_URL=https://github.com/TU-ORG/5cero5-marca

uv run --with "anthropic>=1.9" --with httpx --with pillow python prueba_repo.py --dry-run   # no crea nada
uv run --with "anthropic>=1.9" --with httpx --with pillow python prueba_repo.py
```

## Qué cuenta como "pasó"

El script compara contra GitHub y contra los píxeles, no contra lo que dijo el agente:

- El agente reporta el contenido de `VERSION`, y coincide con el de GitHub. Si no lo leyó del repo, no puede adivinarlo.
- Cita tres reglas de `reglas.md` (una de las prohibiciones duras, una de Tipografía y una de Logo) y las tres existen textualmente en GitHub.
- La imagen mide 1080x1350, tiene fondo papel y los colores de la marca, y el titular cabe (señal de que Anton cargó).
- El logo aparece en el pie: papel adentro y el rosa de la C en su zona.

Guarda la pieza en `salidas/`. Debe decir **SEIS LICENCIAS, NO.** con tu logo abajo a la izquierda. Ábrela y dime si se ve como la marca.

## Lo que puede pasar

Que no pase es un resultado válido. Puede que el montaje del repo privado falle (token, permisos, URL), que el agente no vea `/workspace/marca`, o que el agente no pueda escribir en su copia. El script imprime lo que el agente reportó y la nota dice cuál fue el caso.

## Qué crea en Anthropic

| Recurso | Nombre | Para qué |
|---|---|---|
| Entorno | `poc-5cero5-repo` | Sin salida a internet: el repo lo monta la plataforma |
| Agente | `5cero5 · Creativo (prueba repo)` | Lee el repo, llena la plantilla y entrega la pieza |

El token viaja solo al crear la sesión y la API no lo devuelve. No se guarda en disco ni en el vault. Los IDs quedan en `.estado_repo.json`. Para archivar todo: `... prueba_repo.py --limpiar`.
