# Prueba de factibilidad 3 · Higgsfield por API

La prueba contesta una pregunta: ¿un managed agent puede generar una imagen en Higgsfield por su API, con la llave guardada en el vault, y entregar un archivo real? De paso mide cuánto cuesta una imagen y qué dominio sirve los archivos.

## Antes de correrla (unos 10 minutos)

1. **Entra a la consola de la API**: open.higgsfield.ai. Es un producto aparte de tu suscripción de higgsfield.ai.
2. **Carga saldo**. La API cobra de un saldo propio en dólares, con recarga mínima de USD 5. Los créditos de tu suscripción no sirven aquí. Solo se cobran las generaciones que terminan bien.
3. **Anota tu saldo antes de la prueba.** Sirve para calcular el costo de una imagen.
4. **Crea una llave de API** (sección de llaves, `open.higgsfield.ai/api-keys`). La documentación dice que la llave completa aparece una sola vez. Cópiala entera, tal como sale: si viene en dos partes (`ID` y `secreto`), pégalas unidas con dos puntos, `ID:secreto`.

## Correrla

Desde la carpeta `poc-conectores`, en la misma Terminal (o vuelve a cargar `ANTHROPIC_API_KEY`):

```bash
read -s HF_API_KEY && export HF_API_KEY

uv run --with "anthropic>=1.9" --with httpx python prueba_higgsfield.py --dry-run   # no crea nada ni gasta
uv run --with "anthropic>=1.9" --with httpx python prueba_higgsfield.py             # genera UNA imagen
```

## Qué cuenta como "pasó"

El script revisa en Higgsfield y en el archivo, no en lo que dice el agente:

- la solicitud figura como `completed` en Higgsfield;
- la URL de la imagen abre y es una imagen de verdad (tipo `image/*` y más de 10 KB).

Guarda la imagen en la carpeta `salidas/` para que la veas. Imprime también el dominio que sirve los archivos. Si el agente tiene que descargarlos algún día, ese dominio se agrega a la red de su entorno.

Si el agente envía más de una solicitud de generación, el script avisa: pudo cobrarse más de una imagen.

## Después

Anota tu saldo de nuevo. La diferencia es el costo de una imagen con Soul V2.

## Variante MCP

Después de la prueba por API, corre la misma prueba por el MCP de Higgsfield. Usa la misma llave, guardada en el vault como Bearer:

```bash
uv run --with "anthropic>=1.9" --with httpx python prueba_higgsfield.py --variante mcp
```

Antes, anota tus **créditos de la web** (higgsfield.ai) además del saldo de la API. Si el MCP funciona, la imagen podría cobrarse de los créditos de tu suscripción y no del saldo de la API. Es una hipótesis: la prueba la comprueba.

Que falle es un resultado válido. El servidor puede exigir OAuth y rechazar la llave de API; el script lo dice en la columna de nota. En esa variante el agente solo puede usar cuatro herramientas del MCP (generar imagen, esperar trabajos, consultar generaciones y mostrar trabajo). Todas las demás, incluida la publicación en TikTok, quedan apagadas.

El script no puede consultar en Higgsfield el trabajo del MCP, porque no pasa por la API. En esa variante solo verifica que el archivo exista y sea una imagen.

Para correr las dos seguidas: `--variante ambas`. Se envía una sola solicitud por variante.

## Qué crea en Anthropic

| Recurso | Nombre | Para qué |
|---|---|---|
| Vault | El `5cero5` de la prueba 1 | Se reutiliza. Si no existe, crea uno |
| Credencial | `HIGGSFIELD_API_KEY` | Variable de entorno limitada a api.higgsfield.ai, en el encabezado |
| Entorno | `poc-5cero5-higgsfield` | Red limitada a api.higgsfield.ai |
| Agente | `5cero5 · Creativo (prueba)` | Envía una sola solicitud y espera el resultado |

Los IDs quedan en `.estado_higgsfield.json`. Para archivar todo: `... prueba_higgsfield.py --limpiar`. No toca el vault de la prueba 1.
