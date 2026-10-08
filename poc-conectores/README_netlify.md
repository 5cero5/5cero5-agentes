# Prueba de factibilidad 2 · Netlify (API vs MCP)

La prueba contesta dos preguntas. La primera: ¿un managed agent puede listar sitios y crear un deploy en **borrador** en Netlify con una llave del vault, sin publicar nada? La segunda: ¿qué tal lo hace por la API directa comparado con el MCP remoto?

## Antes de correrla (unos 15 minutos)

1. **Activa la verificación en dos pasos** en tu cuenta de Netlify.
2. **Crea un equipo aparte**, por ejemplo `5cero5 agentes`. Dentro, crea un sitio de prueba llamado `poc-5cero5-test` (puede ser un deploy manual con cualquier archivo). El DNS de 5cero5.com no debe estar en este equipo.
3. **Genera un token personal**: Configuración de usuario → Applications → Personal access tokens → New access token.
   - Nombre: `agentes-5cero5-poc`.
   - Vencimiento: 30 días.
   - Ideal: que lo genere `ops@5cero5.com`, miembro solo de ese equipo. Mientras no exista, usa tu usuario y cámbialo antes de encender la campaña.
   - Netlify lo muestra una sola vez.
4. **Copia el Project ID** del sitio de prueba (Configuración del sitio → Site details).

## Correrla

Desde la carpeta `poc-conectores`, con la misma ventana de Terminal de la prueba 1 (o vuelve a cargar `ANTHROPIC_API_KEY`):

```bash
read -s NETLIFY_TOKEN && export NETLIFY_TOKEN
export NETLIFY_SITE_ID=PEGA_AQUI_EL_PROJECT_ID

uv run --with "anthropic>=1.9" --with httpx python prueba_netlify.py --dry-run   # no crea nada
uv run --with "anthropic>=1.9" --with httpx python prueba_netlify.py             # corre las dos variantes
```

Para una sola variante, agrega `--variante api` o `--variante mcp`.

## Qué cuenta como "pasó"

El script revisa en Netlify, no en lo que dice el agente. Una variante pasa si:

- el número de sitios que reporta el agente coincide con el de Netlify;
- el deploy existe, es del sitio de prueba y quedó en estado `ready`;
- el deploy **publicado** del sitio no cambió (el borrador no publicó).

La variante MCP puede fallar por razones legítimas: que el servidor pida OAuth y rechace el token personal, o que sus herramientas no suban archivos. Eso no es un error de la prueba, es la respuesta. El script lo dice en la columna de nota.

Al final imprime una tabla con resultado, tiempo del agente y número de llamadas por variante, y el ID de cada sesión. Los eventos quedan en `bitacora/`.

## Qué crea en Anthropic

| Recurso | Nombre | Para qué |
|---|---|---|
| Vault | El `5cero5` de la prueba 1 | Se reutiliza. Si no existe, crea uno |
| Credencial | `NETLIFY_TOKEN` (variante API) | Variable de entorno limitada a api.netlify.com |
| Credencial | Bearer estático (variante MCP) | Para el servidor MCP remoto de Netlify |
| Entorno | `poc-5cero5-netlify` | Red limitada a api.netlify.com, más el servidor MCP del agente |
| Agentes | `5cero5 · Landing (prueba API)` y `(prueba MCP)` | Uno por variante |

En la variante MCP se apagan tres herramientas que la prueba no necesita: las de extensiones y la de actualizar proyectos.

Los IDs quedan en `.estado_netlify.json`. Para archivar todo: `... prueba_netlify.py --limpiar`. No toca el vault de la prueba 1.
