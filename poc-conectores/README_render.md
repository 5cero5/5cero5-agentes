# Prueba de factibilidad 4 · Claude diseña como código

La prueba contesta una pregunta: ¿un managed agent puede convertir una plantilla HTML con la marca de 5cero5 en un PNG de 1080x1350, dentro de su entorno en la nube, y entregarlo como archivo real?

No necesita llaves de terceros ni vault: no hay secretos. Solo usa tu `ANTHROPIC_API_KEY`.

## Antes de correrla (2 minutos)

Deja estos dos archivos en la misma carpeta `poc-conectores`:

- `prueba_render.py`
- `plantilla_post.html`

## Correrla

En la misma Terminal de las pruebas anteriores (o vuelve a cargar `ANTHROPIC_API_KEY`):

```bash
uv run --with "anthropic>=1.9" --with httpx --with pillow python prueba_render.py --dry-run   # no crea nada
uv run --with "anthropic>=1.9" --with httpx --with pillow python prueba_render.py             # corre la prueba
```

`--with pillow` es para que el script revise los colores del PNG. Sin él la prueba corre, pero omite esa revisión.

## Qué cuenta como "pasó"

El script revisa el archivo, no lo que dijo el agente:

- el PNG existe, lo recupera de la API de archivos de Anthropic y mide exactamente 1080x1350;
- el fondo es papel `#F4F3F0` y aparecen el rosa, el negro, el amarillo y el azul de la marca;
- el titular cabe en la página. Es la señal de que Anton cargó: si la fuente no carga, el navegador usa una de relleno más ancha y el titular se sale.

Además el agente reporta qué fuentes cargaron según el propio navegador (Anton 400, IBM Plex Sans 400 y 700). Eso no se puede verificar desde fuera, así que cuenta como dato, no como prueba.

El PNG queda en `salidas/`. Ábrelo y compáralo a ojo con la marca. Lo que el script no puede juzgar es si la pieza se ve bien.

## Cómo sale el archivo del entorno

La API de archivos de Anthropic no entrega lo que el agente deja en `/mnt/session/outputs/` (en esta beta, el filtro por sesión se rechaza). Por eso el script usa un plan B: el agente abre el PNG con su herramienta de lectura y la imagen viaja en los eventos de la sesión, de donde el script la saca y la revisa. Puede no ser idéntica byte a byte al archivo original.

Para releer una sesión que ya corrió, sin gastar otra:

```bash
uv run --with "anthropic>=1.9" --with httpx --with pillow python prueba_render.py --reverificar sesn_XXXX
```

## Qué aprendimos al prepararla

En una prueba de validación, el navegador renderizó con una fuente de relleno sin avisar, y la revisión interna de fuentes del navegador también decía que todo estaba bien. Por eso el script mira los píxeles y la plantilla escribe en la página qué fuentes cargaron de verdad.

## Lo que puede pasar

Que no pase es un resultado válido. Puede faltar un navegador en el entorno o no poder instalarse, o el archivo puede no llegar por la API de archivos. El script dice cuál fue el caso en la columna de nota y el agente lista lo que intentó.

El entorno sale a internet solo a `raw.githubusercontent.com` (fuentes) y a los sitios de instalación de Playwright, además de pip y npm.

## Qué crea en Anthropic

| Recurso | Nombre | Para qué |
|---|---|---|
| Entorno | `poc-5cero5-render` | Red limitada a las fuentes y a los instaladores |
| Agente | `5cero5 · Creativo (prueba render)` | Descarga las fuentes, renderiza y reporta |

No usa vault. Los IDs quedan en `.estado_render.json`. Para archivar todo: `... prueba_render.py --limpiar`.

## Después

- Esta pieza lleva un recuadro de texto donde irá el logo. El agente no debe redibujar el logo (regla de marca). Falta decidir cómo le llegan los archivos aprobados del logo: subirlos por la API de archivos o incrustarlos en la plantilla.
- La prueba 4b combina esto con una imagen de Higgsfield como fondo.
