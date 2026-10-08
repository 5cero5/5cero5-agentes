# Prueba de factibilidad 1 · conectores en la nube

La prueba contesta una pregunta: ¿un managed agent en la nube de Anthropic puede leer HighLevel y escribir en Notion con credenciales de servicio guardadas en un vault, sin ver nunca los tokens?

Si pasa, el esqueleto (corte 1) tiene cómo conectarse, y el mismo patrón se usa para Netlify y Meta Ads.

## Antes de correrla (unos 20 minutos, una sola vez)

1. **Claude Console** (platform.claude.com)
   - Crea el workspace `5cero5-poc`.
   - Ponle un límite de gasto. Te sugiero USD 20 para la prueba; es una propuesta.
   - Crea una API key dentro de ese workspace, llamada `poc-esqueleto`.
2. **HighLevel**, en la subcuenta 5cero5
   - Ve a Configuración → Integraciones privadas → Crear.
   - Nombre: `Agentes 5cero5 · Datos (lectura)`.
   - Permiso: solo **View Opportunities** (`opportunities.readonly`).
   - Copia el token. HighLevel solo lo muestra una vez.
3. **Notion**
   - En notion.so/profile/integrations, crea una integración interna `5cero5 agentes` en el espacio de 5cero5.
   - Capacidades: **leer contenido** e **insertar contenido**. Nada más: sin actualizar, sin comentarios y sin datos de usuarios.
   - Copia el token.
   - En la página **POC 5cero5**, abre ··· → Conexiones y agrega `5cero5 agentes`.

Los dos tokens son de servicio. El de HighLevel pertenece a la subcuenta y el de Notion al espacio de trabajo, no a Bonzo ni a ti.

## Correrla

En la Terminal de tu Mac, desde esta carpeta:

```bash
pip3 install "anthropic>=1.9"

# Pega cada token cuando te lo pida. No se ve en pantalla ni queda en el historial.
read -s ANTHROPIC_API_KEY && export ANTHROPIC_API_KEY
read -s HL_PIT && export HL_PIT
read -s NOTION_TOKEN && export NOTION_TOKEN

python3 prueba_esqueleto.py --dry-run   # opcional: muestra qué va a crear
python3 prueba_esqueleto.py
```

## Qué cuenta como "pasó"

El script revisa en las herramientas, no en lo que dice el agente:

- el número de pipelines que reporta el agente coincide con HighLevel;
- la página "Prueba de conectores · fecha" existe en Notion, debajo de POC 5cero5.

Al final imprime **PASÓ** o **NO PASÓ**, el ID de la sesión y cuánto tardó. Los eventos quedan en `bitacora/`.

Si algo falla, pásame la salida de la Terminal, sin tokens, y lo ajustamos.

## Qué crea en Anthropic

| Recurso | Nombre | Para qué |
|---|---|---|
| Vault | `5cero5` | Guarda las dos credenciales. Nadie puede leerlas de vuelta |
| Credencial | `HIGHLEVEL_PIT` | Solo se sustituye en llamadas a services.leadconnectorhq.com |
| Credencial | `NOTION_TOKEN` | Solo se sustituye en llamadas a api.notion.com |
| Entorno | `poc-5cero5-esqueleto` | Contenedor con red limitada a esos dos dominios |
| Agente | `5cero5 · Datos (prueba)` | Solo lee HighLevel; en Notion solo crea páginas hijas de POC 5cero5 |

Los IDs quedan en `.estado_poc.json`. Si vuelves a correr la prueba, reutiliza todo y solo actualiza los tokens. Para archivarlo todo: `python3 prueba_esqueleto.py --limpiar`.
