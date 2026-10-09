// Catálogo de agentes que el harness sabe despachar.
// Agregar un agente = una entrada aquí + su id en la variable `env`. Lo que no está aquí no se despacha:
// la fila pasa a Error con "Agente sin configurar".
// Cada agente declara qué repos monta, sus reglas fijas y el JSON con el que debe terminar.
// Credenciales: cada agente usa su propio vault (variable MA_VAULT_<AGENTE>) para que, por ejemplo,
// el Creativo nunca reciba el token de HighLevel. MA_VAULT_IDS queda como vault común de respaldo.

const COMUNES = [
  'Entrega solo a borrador: no publiques, no envíes, no actives nada y no gastes.',
  'No prometas nada que C30 prohíba: sin testimonios, casos, cifras de clientes, porcentajes ni garantías.',
  'Lo que digas que hiciste se comprueba en la herramienta, no en tu respuesta.',
];

const RESPUESTA_DEPLOY = {
  ejemplo: '{"deploy_id":"...","archivos":["..."],"sha1":{"<archivo>":"..."}}',
  claves: ['deploy_id', 'archivos', 'sha1'],
};

export const AGENTES = {
  Creativo: {
    env: 'MA_AGENT_CREATIVO',
    vaultEnv: 'MA_VAULT_CREATIVO',
    repos: ['marca'],
    reglas: [
      'Usa solo las plantillas, reglas y tokens del repo de marca en /workspace/marca.',
      'Sube el resultado a un draft deploy de Netlify; nunca a producción.',
    ],
    respuesta: RESPUESTA_DEPLOY,
  },
  Landing: {
    env: 'MA_AGENT_LANDING',
    vaultEnv: 'MA_VAULT_LANDING',
    repos: ['marca', 'agentes'],
    reglas: [
      'Usa /workspace/agentes/poc-conectores/landing.py con MARCA_REPO=/workspace/marca: solo construir y borrador. Nunca promover.',
      'Solo cambias /landingtest; la raíz de mkt.5cero5.com no se toca.',
    ],
    respuesta: RESPUESTA_DEPLOY,
  },
  CRM: {
    env: 'MA_AGENT_CRM',
    vaultEnv: 'MA_VAULT_CRM',
    repos: ['marca', 'agentes'],
    reglas: [
      'Usa /workspace/agentes/poc-conectores/correo.py con MARCA_REPO=/workspace/marca: armar, verificar, subir y comprobar.',
      'Solo trabajas plantillas de correo. El nombre de cada plantilla empieza con "[agente] ".',
      'No envías correos, no activas workflows y no tocas contactos ni oportunidades.',
    ],
    respuesta: {
      ejemplo: '{"plantilla_id":"...","nombre":"[agente] ...","html_sha1":"..."}',
      claves: ['plantilla_id', 'nombre', 'html_sha1'],
      revisa: r => (String(r.nombre).startsWith('[agente] ') ? null : 'nombre_sin_prefijo_agente'),
    },
  },
  // No lo despacha una fila aprobada a mano: el harness lo abre cuando una campaña pasa a Aprobada
  // (lib/campanas.mjs). Escribe en Notion con la integración de agentes, así que no puede aprobar nada.
  CMO: {
    env: 'MA_AGENT_CMO',
    vaultEnv: 'MA_VAULT_CMO',
    repos: ['marca'],
    reglas: [
      'Solo propones: cada fila que escribes en Aprobaciones va en Estado "Propuesta". Nunca llenas Aprobó ni Aprobado el, no editas la campaña y no tocas otras filas.',
      'Una fila por pieza, exactamente las Piezas de la campaña. Si lleva landing, la landing cuenta como una pieza.',
      'Agente por formato: Correo → CRM; Landing → Landing; Post 4:5, Post 1:1 e Historia 9:16 → Creativo. Si ese agente no está en la lista de disponibles, propón la fila igual y empieza su Brief con "SIN AGENTE TODAVÍA:".',
      'Cada Brief debe bastar para que el agente de esa pieza la haga sin preguntar: objetivo de la pieza, mensaje principal, texto base, CTA y destino, y lo que no se puede decir. Respeta /workspace/marca/reglas.md.',
    ],
    respuesta: {
      ejemplo: '{"campana_id":"...","filas":[{"id":"...","agente":"CRM","trabajo":"..."}],"sin_agente":0}',
      claves: ['campana_id', 'filas'],
      revisa: r => (Array.isArray(r.filas) && r.filas.length > 0 ? null : 'sin_filas'),
    },
  },
};

// Solo entradas propias del catálogo (evita que "constructor" u otra propiedad heredada pase como agente).
export const agenteDe = nombre => (nombre && Object.hasOwn(AGENTES, nombre) ? AGENTES[nombre] : null);

export function mensajeInicial(fila, def) {
  return [
    `Trabajo: ${fila.trabajo}`,
    fila.campana ? `Campaña: ${fila.campana}` : '',
    '',
    'Brief aprobado:',
    fila.brief,
    '',
    'Reglas fijas:',
    ...[...COMUNES, ...def.reglas].map(r => `- ${r}`),
    '',
    `Al terminar, responde solo con un JSON así: ${def.respuesta.ejemplo}`,
  ].join('\n');
}

// Saca el último objeto JSON del texto (acepta ```json ... ```).
export function ultimoJson(texto) {
  const t = String(texto || '');
  for (let fin = t.lastIndexOf('}'); fin >= 0; fin = t.lastIndexOf('}', fin - 1)) {
    for (let ini = t.lastIndexOf('{', fin); ini >= 0; ini = t.lastIndexOf('{', ini - 1)) {
      try { return JSON.parse(t.slice(ini, fin + 1)); } catch {}
    }
  }
  return null;
}

// null si la respuesta tiene el formato pedido; si no, el motivo. No dice si el trabajo está bien: eso es del Verificador.
export function revisaRespuesta(def, texto) {
  if (!def) return 'agente_desconocido';
  const r = ultimoJson(texto);
  if (!r || typeof r !== 'object' || Array.isArray(r)) return 'sin_json';
  const falta = def.respuesta.claves.filter(k => r[k] === undefined || r[k] === '');
  if (falta.length) return `faltan_claves:${falta.join(',')}`;
  return def.respuesta.revisa ? def.respuesta.revisa(r) : null;
}
