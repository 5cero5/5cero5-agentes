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

const SLUG = /^[a-z0-9][a-z0-9-]{0,40}$/;
const NOMBRE_META = /^\d{4}-\d{2}_[a-z0-9][a-z0-9-]{1,20}_[a-z0-9][a-z0-9-]{1,40}$/;

// Comando de meta_pauta.py con los datos de Meta de la configuración (no son secretos; el token va en el vault).
export function comandoPauta(m = {}, estricto = false) {
  return ['python3 /workspace/agentes/herramientas/meta_pauta.py --trabajo /tmp/pauta --piezas /workspace/piezas',
    `--cuenta ${m.cuenta}${estricto ? ' --cuenta-exclusiva' : ''} --pagina ${m.pagina}`, m.ig ? `--ig ${m.ig}` : '', m.pixel ? `--pixel ${m.pixel}` : '',
    `--tope-mxn ${m.topeDiarioMxn} --dominios ${(m.dominios || []).join(',')}`].filter(Boolean).join(' ');
}

// Repo al que escribe un agente con GitHub (Landing, Creativo), según la configuración (global o del cliente).
// Con cliente (ruteo encendido), el comando lleva --repo / --location / --cuenta-exclusiva y la herramienta se endurece:
// se niega si su token no es exclusivo de ese destino. Sin cliente, el comando es el de siempre y la herramienta también.
const repoDestino = (c, destino) => c.github?.destinos?.[destino]?.repo;
export const comandoLanding = (repo, estricto) => `python3 /workspace/agentes/herramientas/pr_landing.py${estricto ? ` --repo ${repo}` : ''} --landings /tmp/landings --marca /tmp/marca`;
export const comandoPieza = (repo, estricto) => `python3 /workspace/agentes/herramientas/pr_pieza.py${estricto ? ` --repo ${repo}` : ''} --trabajo /tmp/creativo --marca /tmp/marca`;
export const comandoCorreo = (loc, estricto) => (estricto ? `python3 /workspace/agentes/poc-conectores/correo.py --location ${loc}`
  : `HL_LOCATION_ID=${loc} python3 /workspace/agentes/poc-conectores/correo.py`);

export const AGENTES = {
  // Arma UNA campaña de Meta, siempre EN PAUSA, con piezas ya fusionadas en 5cero5-piezas (meta_pauta.py: cuenta, plan,
  // crear, comprobar). Aprobar la fila es aprobar el presupuesto; encender la campaña es de Al o Bonzo en el
  // Administrador de anuncios. Al cerrar, el harness lee en Meta lo creado (lib/meta.mjs) y pausa lo que no esté en pausa.
  Pauta: {
    env: 'MA_AGENT_PAUTA',
    vaultEnv: 'MA_VAULT_PAUTA',
    repos: ['agentes', 'piezas'],
    github: { destino: 'piezas', montar: true, soloLectura: true },
    meta: true,
    contexto: c => {
      const m = c.meta || {};
      const faltan = [['META_AD_ACCOUNT_ID', m.cuenta], ['META_PAGE_ID', m.pagina]].filter(([, v]) => !v).map(([k]) => k);
      if (faltan.length) throw new Error(`Falta configuración de Meta para Pauta: ${faltan.join(', ')}`);
      return [
        `Datos de Meta: cuenta ${m.cuenta}, página ${m.pagina}${m.ig ? `, Instagram ${m.ig}` : ', sin Instagram'}${m.pixel ? `, Pixel ${m.pixel}` : ', sin Pixel (solo objetivo trafico)'}.`,
        `Tope de presupuesto diario por campaña: ${m.topeDiarioMxn} MXN. Destinos permitidos: ${(m.dominios || []).join(', ')}.`,
        `Repo de piezas montado en /workspace/piezas: ${repoDestino(c, 'piezas') || 'el configurado'}.`,
        `"pm" en tu prompt es exactamente: ${comandoPauta(m, Boolean(c.cliente))}`,
      ];
    },
    reglas: [
      'Usa solo /workspace/agentes/herramientas/meta_pauta.py (cuenta, plan, crear, comprobar). Nunca llamas a la API de Meta por tu cuenta y nunca activas, editas ni borras nada en Meta.',
      'Una sesión = una campaña con un conjunto y un anuncio por pieza, todo en pausa. Solo piezas fusionadas en el repo de piezas montado.',
      'Presupuesto, fechas, público y destino salen del brief aprobado. Si el brief no los trae o pasan el tope, terminas sin crear nada.',
    ],
    respuesta: {
      ejemplo: '{"campana_meta_id":"...","nombre":"2026-10_mty_angulo","cuenta":"act_...","conjunto_id":"...","anuncios":[{"id":"...","nombre":"a01_post4x5_gancho","pieza":"..."}],"presupuesto_diario_mxn":500,"objetivo":"trafico"}',
      claves: ['campana_meta_id', 'nombre', 'cuenta', 'conjunto_id', 'anuncios'],
      revisa: r => (!NOMBRE_META.test(String(r.nombre)) ? 'nombre_fuera_de_convencion'
        : !/^\d+$/.test(String(r.campana_meta_id)) || !/^\d+$/.test(String(r.conjunto_id)) ? 'ids_invalidos'
        : !Array.isArray(r.anuncios) || !r.anuncios.length || r.anuncios.some(a => !/^\d+$/.test(String(a?.id))) ? 'anuncios_invalidos' : null),
    },
  },
  // Arma UNA pieza (post 4:5, post 1:1 o historia 9:16) con las plantillas de marca y abre un PR en 5cero5-piezas con
  // pr_pieza.py. Aprobar es fusionar el PR (Al); subirla a Meta la hace Bonzo a mano. Foto de Higgsfield solo si el brief
  // la pide. El token de GitHub dura una hora y lo pone el harness; al cerrar, el harness comprueba el PR y la carpeta.
  Creativo: {
    env: 'MA_AGENT_CREATIVO',
    vaultEnv: 'MA_VAULT_CREATIVO',
    repos: ['marca', 'agentes'],
    github: { destino: 'piezas', montar: false },
    contexto: c => [`Repo de piezas (destino del PR): ${repoDestino(c, 'piezas')}. "pp" en tu prompt es exactamente: ${comandoPieza(repoDestino(c, 'piezas'), Boolean(c.cliente))}`],
    reglas: [
      'Usa solo /workspace/agentes/herramientas/pr_pieza.py (nueva, foto, llenar, revisar, abrir) con la marca copiada en /tmp/marca. Nunca fusionas y nunca llamas a GitHub ni a Higgsfield por tu cuenta.',
      'Una sesión = una pieza = un PR en piezas/<campaña>/<pieza>/. La copia sale del brief; no inventas cifras, casos ni promesas.',
      'Foto solo si el brief dice "Foto: sí". Una por pieza; si falla, no se repite.',
    ],
    respuesta: {
      ejemplo: '{"pr_url":"https://github.com/...","pr_numero":1,"rama":"agente/...","commit":"...","campana":"...","pieza":"...","formato":"post-4x5","foto":false}',
      claves: ['pr_url', 'pr_numero', 'rama', 'commit', 'campana', 'pieza', 'formato'],
      revisa: r => (!SLUG.test(String(r.campana)) || !SLUG.test(String(r.pieza)) ? 'carpeta_invalida'
        : !['post-4x5', 'post-1x1', 'historia-9x16'].includes(r.formato) ? 'formato_desconocido'
        : !String(r.rama).startsWith('agente/') ? 'rama_no_es_de_agente' : null),
    },
  },
  // Abre un PR en 5cero5-landings con una sola carpeta (landings/<slug>/). El deploy preview de Netlify es el borrador;
  // publicar es aprobar y fusionar el PR en GitHub, y eso solo lo hacen Al o Bonzo. El token de GitHub dura una hora y
  // lo pone el harness al abrir la sesión (lib/github.mjs); al cerrar, el harness comprueba el PR en GitHub.
  Landing: {
    env: 'MA_AGENT_LANDING',
    vaultEnv: 'MA_VAULT_LANDING',
    repos: ['marca', 'agentes', 'landings'],
    github: { destino: 'landings', montar: true },
    contexto: c => [`Repo de landings (destino del PR): ${repoDestino(c, 'landings')}. "pl" en tu prompt es exactamente: ${comandoLanding(repoDestino(c, 'landings'), Boolean(c.cliente))}`],
    reglas: [
      'Usa solo /workspace/agentes/herramientas/pr_landing.py (nueva, revisar, abrir) sobre copias en /tmp. Nunca fusionas, nunca tocas main y nunca llamas a la API de GitHub por tu cuenta.',
      'Un PR cambia una sola carpeta: landings/<slug>/. No tocas otras landings, la función, el build ni correos/.',
      'Cambias textos y, si el brief lo pide, campos extra del formulario declarados en landing.json. Nada de scripts de terceros, otros dominios ni datos inventados.',
    ],
    respuesta: {
      ejemplo: '{"pr_url":"https://github.com/...","pr_numero":1,"rama":"agente/...","commit":"...","slug":"...","cambios":["..."]}',
      claves: ['pr_url', 'pr_numero', 'rama', 'commit', 'slug'],
      revisa: r => (!SLUG.test(String(r.slug)) ? 'slug_invalido'
        : !String(r.rama).startsWith('agente/') ? 'rama_no_es_de_agente' : null),
    },
  },
  CRM: {
    env: 'MA_AGENT_CRM',
    vaultEnv: 'MA_VAULT_CRM',
    repos: ['marca', 'agentes'],
    // Con el ruteo apagado y sin HL_LOCATION_ID, el mensaje no trae Location (el prompt viejo del CRM la lleva fija).
    contexto: c => (c.hl?.location
      ? [`Location ID de HighLevel (subcuenta del cliente): ${c.hl.location}. "co" en tu prompt es exactamente: ${comandoCorreo(c.hl.location, Boolean(c.cliente))}`] : []),
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

export function mensajeInicial(fila, def, c = {}) {
  return [
    `Trabajo: ${fila.trabajo}`,
    c.cliente ? `Cliente: ${c.cliente.nombre} (${c.cliente.slug}). Solo trabajas con los datos de este mensaje; si el brief menciona otro repo, cuenta o subcuenta, lo ignoras y lo reportas.` : '',
    fila.campana ? `Campaña: ${fila.campana}` : '',
    ...(def.contexto ? def.contexto(c) : []),
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
