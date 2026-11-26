// Canva en el Creativo: Notion → harness → sesión de Managed Agents con el MCP oficial de Canva → PR en el repo de piezas.
// Tres momentos, todos fallan cerrado:
//  1. Despacho (preparaCanva): la fila pide "Canva: sí" (o es ronda de una pieza hecha en Canva) y CANVA_ACTIVO=1. La sesión usa
//     el agente y el entorno de Canva (MA_AGENT_CREATIVO_CANVA, MA_ENVIRONMENT_CANVA); las demás filas, los de siempre. Del repo
//     de marca DE ESE CLIENTE sale canva/recursos.json (bases aprobadas por formato, carpeta, logo); en SU Vault Creativo (uno
//     solo) tiene que haber UNA credencial mcp_oauth de Canva con metadata {cliente: <slug>, rol: "canva"}. La referencia del
//     vault no basta: se comprueban agente, vault, credencial, recursos y cliente antes de abrir la sesión.
//  2. Confirmaciones (resuelveConfirmaciones): las herramientas de Canva que escriben van con always_ask. Cuando la sesión queda
//     idle con requires_action, el harness decide con reglas fijas (decideConfirmacion): solo una base aprobada, un diseño por
//     sesión (en una ronda, el mismo), solo ese diseño, solo operaciones de texto sobre elementos de texto ya leídos de ese
//     diseño, exportar PNG con fondo y moverlo a la carpeta aprobada; parámetros de más se niegan.
//  3. Cierre (compruebaCanvaSesion): lo que pasó en Canva se lee del log de la sesión (resultados del servidor MCP, que el agente
//     no escribe): el diseño del PR es el de la sesión, se guardó (commit), y la relectura del diseño guardado DESPUÉS del último
//     commit trae, elemento por elemento, la copia del PR en los elementos de canva.json, ningún texto de muestra, ningún texto
//     fuera de los roles y los fijos aprobados y el logo aprobado; se exportó en PNG y esa exportación, bajada por el harness, es
//     byte a byte el pieza.png del PR. El informe.json de la sesión es una revisión previa; esto es lo que decide.
import { createHash } from 'node:crypto';
import CANVA from '../agentes/canva.json' with { type: 'json' };
import { gh, marcaParaLeer, tokenInstalacion } from './github.mjs';

export { CANVA };
export const CANVA_URL = CANVA.servidor.url;
export const CANVA_NOMBRE = CANVA.servidor.name;
const DISENO = /^D[A-Za-z0-9_-]{10}$/;
const ID = /^[A-Za-z0-9_-]{3,80}$/;
const FORMATOS = ['post-4x5', 'post-1x1', 'historia-9x16'];
const ROLES = ['kicker', 'titular', 'subtitulo', 'nota'];
const CREAN = ['copy-design', 'create-design-from-brand-template'];
const MAX_EXPORT = 15 * 1024 * 1024;
const TIPOS_TEXTO = ['', 'text', 'richtext', 'rich_text', 'textbox', 'text_box'];
// Parámetros que se aceptan por herramienta con permiso (lo demás se niega: no hay atajos por parámetros nuevos).
const PARAMS = {
  'copy-design': ['design_id', 'page_numbers', 'user_intent'],
  'create-design-from-brand-template': ['brand_template_id', 'page_numbers', 'user_intent'],
  'edit-design': ['transaction_id', 'page_index', 'operations', 'finalize', 'is_editable', 'is_empty', 'is_responsive', 'user_intent'],
  'export-design': ['design_id', 'format', 'user_intent'],
  'move-item-to-folder': ['item_id', 'to_folder_id', 'user_intent'],
};
const FORMATO_EXPORT = ['type', 'width', 'height', 'export_quality', 'lossless', 'transparent_background', 'pages', 'as_single_image'];

export class ErrorCanva extends Error {
  constructor(m, motivo = 'canva') { super(m); this.motivo = motivo; }
}

// Línea "Canva: …" del brief, en su propia línea (como "Foto: sí"). 'si', 'no', 'ilegible' (hay línea y no se entiende: falla
// cerrado, nunca se hace en HTML sin avisar) o null (no hay línea).
export function lineaCanva(brief) {
  const m = String(brief || '').match(/^\s*[-*]?\s*\**\s*Canva\s*\**\s*:\s*\**\s*(.*)$/mi);
  if (!m) return null;
  const v = m[1].replace(/[*_.\s]+$/g, '').trim().toLowerCase();
  if (/^s[ií]$/.test(v)) return 'si';
  if (/^no$/.test(v)) return 'no';
  return 'ilegible';
}
export const canvaDelBrief = brief => lineaCanva(brief) === 'si';
const fotoDelBrief = brief => /^\s*[-*]?\s*Foto\s*:\s*(s[ií](?![a-záéíóúñ])|repo:|referencia:)/mi.test(String(brief || ''));

// Normalización de URLs de servidor MCP igual que el vault: esquema y host en minúsculas, sin puerto por omisión ni / final.
export function normalizaUrl(u) {
  try {
    const x = new URL(u);
    const defecto = (x.protocol === 'https:' && x.port === '443') || (x.protocol === 'http:' && x.port === '80');
    return `${x.protocol}//${x.hostname.toLowerCase()}${x.port && !defecto ? `:${x.port}` : ''}${x.pathname.replace(/\/+$/, '')}`;
  } catch { return ''; }
}

export function idDeDiseno(x) {
  const s = String(x || '');
  if (DISENO.test(s)) return s;
  const m = s.match(/canva\.com\/design\/(D[A-Za-z0-9_-]{10})(?:[/?#]|$)/);
  return m ? m[1] : null;
}

// ---------------------------------------------------------------- 1. despacho
// canva/recursos.json del repo de marca del cliente. Solo se aceptan recursos con habilitado=true (los aprueba Al o Bonzo en un PR).
export function validaRecursos(d, repo = 'el repo de marca') {
  if (!d || typeof d !== 'object' || d.version !== 1) throw new ErrorCanva(`canva/recursos.json de ${repo} no es versión 1`, 'canva_sin_recursos');
  if (d.habilitado !== true) throw new ErrorCanva(`canva/recursos.json de ${repo} no está habilitado: faltan recursos aprobados de Canva`, 'canva_sin_recursos');
  const bases = {}, textos = {};
  for (const f of FORMATOS) {
    const b = d.formatos?.[f]?.base;
    if (!b?.id) continue;
    const ok = b.tipo === 'design' ? DISENO.test(b.id) : b.tipo === 'brand_template' ? ID.test(b.id) : false;
    if (!ok) throw new ErrorCanva(`canva/recursos.json de ${repo}: base inválida para ${f} (${b.tipo}:${b.id})`, 'canva_sin_recursos');
    bases[f] = [b.tipo, b.id];
    textos[f] = d.formatos[f].textos || {};
  }
  if (!Object.keys(bases).length) throw new ErrorCanva(`canva/recursos.json de ${repo} no trae ninguna base aprobada`, 'canva_sin_recursos');
  if (!ID.test(String(d.carpeta_id || ''))) throw new ErrorCanva(`canva/recursos.json de ${repo}: falta carpeta_id (carpeta compartida con quien aprueba)`, 'canva_sin_recursos');
  // logo_asset_id es opcional (no se ve en la interfaz de Canva): si está, se exige en la relectura; si no, queda el cotejo de
  // píxeles del logo en el pie del Verificador, que también bloquea.
  if (d.logo_asset_id && !ID.test(String(d.logo_asset_id))) throw new ErrorCanva(`canva/recursos.json de ${repo}: logo_asset_id inválido`, 'canva_sin_recursos');
  const fijos = (Array.isArray(d.textos_fijos) ? d.textos_fijos : []).filter(x => typeof x === 'string');
  return { bases, textos, fijos, carpeta: d.carpeta_id, logo: d.logo_asset_id || '', kit: ID.test(String(d.brand_kit_id || '')) ? d.brand_kit_id : '' };
}

export async function recursosCanva({ c, fetchImpl = fetch }) {
  // La misma rama que se monta en la sesión (GH_REPO_REF en un piloto; si no, la principal).
  const { repo, token, ref } = await marcaParaLeer({ c, fetchImpl });
  let x;
  try { x = await gh(fetchImpl, 'GET', `/repos/${repo}/contents/canva/recursos.json${ref ? `?ref=${encodeURIComponent(ref)}` : ''}`, token); }
  catch (e) { throw new ErrorCanva(`El repo de marca ${repo} no tiene canva/recursos.json (${e.status || e.message})`, 'canva_sin_recursos'); }
  let d;
  try { d = JSON.parse(Buffer.from(String(x.content || ''), 'base64').toString('utf8')); }
  catch { throw new ErrorCanva(`canva/recursos.json de ${repo} no es JSON válido`, 'canva_sin_recursos'); }
  return { repo, ...validaRecursos(d, repo) };
}

// La credencial de Canva vive en el Vault Creativo DEL CLIENTE: una sola por cliente, reutilizada en todas sus piezas.
export async function credencialCanva({ client, vault, slug }) {
  if (!vault) throw new ErrorCanva(`Canva: falta el Vault Creativo de ${slug}`, 'canva_sin_credencial');
  let v;
  try { v = await client.beta.vaults.retrieve(vault); }
  catch (e) { throw new ErrorCanva(`Canva: no se pudo leer el vault ${vault} (${e.status || e.message})`, 'canva_sin_credencial'); }
  if (v.archived_at || v.metadata?.cliente !== slug || v.metadata?.rol !== 'creativo') {
    throw new ErrorCanva(`Canva: el vault ${vault} no es el Vault Creativo de ${slug} (metadata cliente=${v.metadata?.cliente || 'vacío'}, rol=${v.metadata?.rol || 'vacío'})`, 'canva_sin_credencial');
  }
  const deCanva = [];
  for await (const cr of client.beta.vaults.credentials.list(vault)) {
    if (!cr.archived_at && cr.auth?.type === 'mcp_oauth' && normalizaUrl(cr.auth?.mcp_server_url) === normalizaUrl(CANVA_URL)) deCanva.push(cr);
  }
  if (!deCanva.length) throw new ErrorCanva(`Canva: el Vault Creativo de ${slug} no tiene la credencial mcp_oauth de Canva (infra/canva_oauth.py --cliente ${slug})`, 'canva_sin_credencial');
  if (deCanva.length > 1) throw new ErrorCanva(`Canva: el Vault Creativo de ${slug} tiene ${deCanva.length} credenciales de Canva; tiene que haber una`, 'canva_sin_credencial');
  const cr = deCanva[0];
  if (cr.metadata?.cliente !== slug || cr.metadata?.rol !== 'canva') {
    throw new ErrorCanva(`Canva: la credencial ${cr.id} no es de ${slug}/canva (metadata cliente=${cr.metadata?.cliente || 'vacío'}, rol=${cr.metadata?.rol || 'vacío'})`, 'canva_sin_credencial');
  }
  return { id: cr.id, cuenta: String(cr.metadata?.canva_cuenta || '') };
}

// El agente de Canva tiene que declarar SOLO el servidor de Canva y la lista cerrada de agentes/canva.json (permisos mínimos en
// la plataforma, no solo en infra/). Si alguien le cambió la configuración, no se abre la sesión.
export async function verificaAgenteCanva({ client, agente }) {
  let a;
  try { a = await client.beta.agents.retrieve(agente); }
  catch (e) { throw new ErrorCanva(`Canva: no se pudo leer el agente ${agente} (${e.status || e.message})`, 'canva_sin_configurar'); }
  const servidores = a.mcp_servers || [];
  if (servidores.length !== 1 || servidores[0].name !== CANVA_NOMBRE || normalizaUrl(servidores[0].url) !== normalizaUrl(CANVA_URL)) {
    throw new ErrorCanva(`Canva: el agente ${agente} no declara solo el servidor de Canva`, 'canva_sin_configurar');
  }
  const ts = (a.tools || []).filter(t => t.type === 'mcp_toolset');
  const t = ts[0];
  const pol = c => c?.permission_policy?.type;
  const esperado = new Map([...CANVA.herramientas.lectura.map(n => [n, 'always_allow']), ...CANVA.herramientas.con_permiso.map(n => [n, 'always_ask'])]);
  const configs = new Map((t?.configs || []).filter(c => c.enabled !== false).map(c => [c.name, pol(c) || pol(t?.default_config)]));
  const bien = ts.length === 1 && t.mcp_server_name === CANVA_NOMBRE && t.default_config?.enabled === false
    && configs.size === esperado.size && [...esperado].every(([n, p]) => configs.get(n) === p);
  if (!bien) throw new ErrorCanva(`Canva: el agente ${agente} no tiene la lista cerrada de herramientas de agentes/canva.json (corre crear_agente_creativo.py --canva --actualizar-agente)`, 'canva_sin_configurar');
}

// pieza.json de la punta del PR de una ronda (solo lectura): de ahí sale si la pieza es de Canva y su diseño.
async function piezaDeLaRonda({ c, ronda, fetchImpl }) {
  const g = c.github || {};
  const repo = g.destinos?.piezas?.repo;
  const { token } = await tokenInstalacion({ appId: g.appId, pem: g.privateKey, installationId: g.installationId, repo, permisos: { contents: 'read' }, fetchImpl });
  try {
    const x = await gh(fetchImpl, 'GET', `/repos/${repo}/contents/piezas/${ronda.campana}/${ronda.pieza}/pieza.json?ref=${ronda.head}`, token);
    return JSON.parse(Buffer.from(String(x.content || ''), 'base64').toString('utf8'));
  } catch (e) { throw new ErrorCanva(`No se pudo leer pieza.json del PR #${ronda.pr} (${e.status || e.message})`); }
}

// null si la fila no es de Canva; si lo es, lo que va en la sesión ({ b, f, l, k, d, cr } + agente y entorno) o ErrorCanva.
// cli: el cliente de la fila (ya resuelto para los aprobadores). c: la configuración con lo del cliente.
export async function preparaCanva({ client, c, fila, cli, fetchImpl = fetch }) {
  let design = null;
  if (fila.ronda) {
    // Con CANVA_ACTIVO apagado, la ronda sigue exactamente como antes (sin la lectura extra en GitHub). Si la pieza era de Canva,
    // la sesión no puede escribir en Canva (sin la metadata canva el harness niega todo) y al cerrar sale Rechazada.
    if (!c.canvaActivo) return null;
    const meta = await piezaDeLaRonda({ c, ronda: fila.ronda, fetchImpl });
    if (meta?.fuente !== 'canva') return null;
    design = idDeDiseno(meta.canva?.design_id);
    if (!design) throw new ErrorCanva('Ronda de una pieza de Canva sin design_id válido en pieza.json');
  } else {
    const l = lineaCanva(fila.brief);
    if (l === 'ilegible') throw new ErrorCanva('La línea "Canva:" del brief no se entiende: tiene que decir "Canva: sí" o "Canva: no" en su propia línea', 'canva_brief');
    if (l !== 'si') return null;
  }
  if (!c.canvaActivo) throw new ErrorCanva('La fila pide Canva y CANVA_ACTIVO está apagado: no se despacha (lo enciende Al en el harness)', 'canva_apagado');
  // Foto con Canva: se integra con el núcleo de Higgsfield en otra rama. Mientras, falla cerrado (no se cobra nada).
  if (fila.ronda ? fila.ronda.foto !== 'Igual' : fotoDelBrief(fila.brief)) {
    throw new ErrorCanva('Canva con foto todavía no está habilitado en el harness: la pieza va sin foto o con Foto en la ronda = Igual', 'canva_foto');
  }
  const agente = c.canva?.agente, entorno = c.canva?.entorno;
  if (!agente || !entorno) throw new ErrorCanva('Canva sin configurar: faltan MA_AGENT_CREATIVO_CANVA y MA_ENVIRONMENT_CANVA (los imprime crear_agente_creativo.py --canva)', 'canva_sin_configurar');
  await verificaAgenteCanva({ client, agente });
  const rec = await recursosCanva({ c, fetchImpl });
  // La sesión recibe exactamente estos vaults (parametrosSesion): tiene que ser uno, el Vault Creativo del cliente.
  const vaults = c.vaultsPorAgente?.Creativo?.length ? c.vaultsPorAgente.Creativo : (c.vaultIds || []);
  if (vaults.length !== 1) throw new ErrorCanva(`Canva: la sesión del Creativo llevaría ${vaults.length} vaults; tiene que ser uno, el Vault Creativo de ${cli.slug}`, 'canva_sin_credencial');
  const cred = await credencialCanva({ client, vault: vaults[0], slug: cli.slug });
  const canva = { v: 1, b: rec.bases, f: rec.carpeta, ...(rec.logo ? { l: rec.logo } : {}), ...(rec.kit ? { k: rec.kit } : {}), ...(design ? { d: design } : {}), cr: cred.id };
  if (JSON.stringify(canva).length > 512) throw new ErrorCanva('Los recursos de Canva no caben en la metadata de la sesión (máximo 512 caracteres)');
  return { ...canva, agente, entorno, textos: rec.textos, marca: rec.repo, cuenta: cred.cuenta };
}

// Lo que viaja en la metadata de la sesión (una sola clave, "canva"): el harness lo vuelve a leer al confirmar y al cerrar.
export const metadataCanva = canva => JSON.stringify({ v: 1, b: canva.b, f: canva.f, ...(canva.l ? { l: canva.l } : {}), ...(canva.k ? { k: canva.k } : {}),
  ...(canva.d ? { d: canva.d } : {}), cr: canva.cr });
export function leeMetaCanva(metadata) {
  try {
    const m = JSON.parse(metadata?.canva || '');
    return m && m.v === 1 && m.b && typeof m.b === 'object' ? m : null;
  } catch { return null; }
}

// ---------------------------------------------------------------- lectura del log de la sesión
// Bloques de un resultado MCP → valores (JSON si el texto lo es; si no, el texto).
function valores(content) {
  return (Array.isArray(content) ? content : []).map(b => {
    if (b?.type !== 'text') return b;
    try { return JSON.parse(b.text); } catch { return b.text; }
  });
}
// Visita cada hoja con la clave que la contiene (en una lista, la clave de la lista).
function recorre(o, f, k = null) {
  if (Array.isArray(o)) o.forEach(v => recorre(v, f, k));
  else if (o && typeof o === 'object') for (const [kk, v] of Object.entries(o)) recorre(v, f, kk);
  else f(k, o);
}
const deClave = (vals, clave) => { const out = []; recorre(vals, (k, v) => { if (k === clave && typeof v === 'string') out.push(v); }); return out; };
const cadenas = vals => { const out = []; recorre(vals, (_k, v) => { if (typeof v === 'string') out.push(v); }); return out; };
const normT = t => String(t || '').replace(/\s+/g, ' ').trim().toLowerCase();
const une = v => (Array.isArray(v) ? v.map(x => String(x).trim()).filter(Boolean).join(' ') : String(v || ''));

// Elementos de un resultado de read-design: { textos: Map(id → texto), tipos: Map(id → tipo), assets: Set }. Solo objetos con id
// de elemento (locator_id, element_id o id); el título y otros metadatos del diseño no cuentan como texto. La forma exacta de
// read-design se confirma en vivo; es la misma lógica que verificar_canva.py.
export function elementosDe(vals) {
  const textos = new Map(), tipos = new Map(), assets = new Set();
  const anda = o => {
    if (Array.isArray(o)) { o.forEach(anda); return; }
    if (!o || typeof o !== 'object') return;
    const id = ['locator_id', 'element_id', 'id'].map(k => o[k]).find(v => typeof v === 'string' && v);
    const tipo = String(o.type ?? '').toLowerCase();
    let txt = null;
    for (const k of ['text', 'plain_text', 'content']) {
      const v = o[k];
      if (typeof v === 'string') { txt = v; break; }
      if (Array.isArray(v) && v.length && v.every(x => typeof x === 'string')) { txt = v.join('\n'); break; }
    }
    if (id && tipo) tipos.set(id, tipo);
    if (id && txt !== null && TIPOS_TEXTO.includes(tipo)) { textos.set(id, txt); tipos.set(id, tipo || 'text'); }
    for (const k of ['asset_id', 'media_id', 'image_id']) if (typeof o[k] === 'string' && o[k]) assets.add(o[k]);
    Object.values(o).forEach(anda);
  };
  anda(vals);
  return { textos, tipos, assets };
}
// Un elemento por su locator completo (PBxxx-LByyy) o por la parte final (LByyy), como lo acepta read-design.
function porId(mapa, loc) {
  const l = String(loc || '');
  if (!l) return undefined;
  if (mapa.has(l)) return l;
  return [...mapa.keys()].find(k => k.endsWith(`-${l}`) || l.endsWith(`-${k}`));
}

// Diseño nuevo que nombra un resultado de copy-design (design_id, id dentro de "design" o enlace /design/D…), sin el de origen.
// Solo si es UNO: un resultado ambiguo no hace "propio" a ningún diseño (y al cerrar no hay diseño de la sesión).
function disenoNuevo(vals, origen) {
  const out = new Set();
  recorre(vals, (k, v) => { if (typeof v === 'string' && (k === 'design_id' || k === 'id') && DISENO.test(v)) out.add(v); });
  for (const s of cadenas(vals)) { const d = idDeDiseno(s); if (d && s.includes('canva.com/design/')) out.add(d); }
  out.delete(origen);
  return out.size === 1 ? [...out][0] : null;
}

export function historiaCanva(eventos) {
  const usos = new Map(), orden = [], confirmados = new Map();
  for (const ev of eventos) {
    if (ev.type === 'agent.mcp_tool_use' && ev.mcp_server_name === CANVA_NOMBRE) {
      const u = { id: ev.id, name: ev.name, input: ev.input || {}, permiso: ev.evaluated_permission, resultado: null, error: null };
      usos.set(ev.id, u); orden.push(u);
    } else if (ev.type === 'agent.mcp_tool_result' && usos.has(ev.mcp_tool_use_id)) {
      const u = usos.get(ev.mcp_tool_use_id);
      u.resultado = valores(ev.content); u.error = ev.is_error === true;
    } else if (ev.type === 'user.tool_confirmation') confirmados.set(ev.tool_use_id, ev.result);
  }
  const disenos = [], transacciones = new Map(), elementos = new Map();
  for (const u of orden) {
    if (u.error || !u.resultado) continue;
    if (CREAN.includes(u.name)) { const d = disenoNuevo(u.resultado, idDeDiseno(u.input.design_id) || u.input.brand_template_id); if (d) disenos.push(d); }
    if (u.name === 'read-design') {
      const d = idDeDiseno(u.input.design_id);
      if (!d) continue;
      for (const tx of deClave(u.resultado, 'transaction_id')) transacciones.set(tx, d);
      // Tipos de elementos vistos en cualquier lectura de ese diseño (para saber cuáles son de texto al aprobar una edición).
      const e = elementosDe(u.resultado);
      const prev = elementos.get(d) || new Map();
      for (const [k, t] of e.tipos) prev.set(k, t);
      elementos.set(d, prev);
    }
  }
  return { orden, confirmados, disenos: [...new Set(disenos)], transacciones, elementos };
}

async function eventosDe(client, sessionId) {
  const out = [];
  for await (const ev of client.beta.sessions.events.list(sessionId, { limit: 100 })) out.push(ev);
  return out;
}

// ---------------------------------------------------------------- 2. confirmaciones
// Regla fija por herramienta. { result: 'allow' } o { result: 'deny', deny_message }. ctx: { meta, hist, ahora }.
// ctx.ahora: confirmaciones que se están enviando en este mismo lote (para no permitir dos copias a la vez).
export function decideConfirmacion(uso, { meta, hist, ahora = new Map() }) {
  const no = m => ({ result: 'deny', deny_message: `Harness 5cero5: ${m}` });
  const si = { result: 'allow' };
  if (uso.mcp_server_name !== CANVA_NOMBRE) return no('esta herramienta no tiene regla de aprobación en el harness');
  if (!meta) return no('esta sesión no se despachó como Canva');
  const inp = uso.input || {};
  const extra = Object.keys(inp).filter(k => !(PARAMS[uso.name] || []).includes(k));
  if (PARAMS[uso.name] && extra.length) return no(`parámetros no permitidos en ${uso.name}: ${extra.join(', ')}`);
  const propios = new Set([...(meta.d ? [meta.d] : []), ...hist.disenos]);
  const yaCreo = hist.orden.some(u => CREAN.includes(u.name) && u.id !== uso.id && (hist.confirmados.get(u.id) === 'allow' || ahora.get(u.id) === 'allow'));
  const bases = Object.values(meta.b || {});
  switch (uso.name) {
    case 'copy-design':
    case 'create-design-from-brand-template': {
      if (meta.d) return no('en una ronda se edita el mismo diseño: no se crea otro');
      if (yaCreo) return no('una pieza = un diseño: ya se creó uno en esta sesión');
      const tipo = uso.name === 'copy-design' ? 'design' : 'brand_template';
      const id = uso.name === 'copy-design' ? idDeDiseno(inp.design_id) : String(inp.brand_template_id || '');
      if (!bases.some(([t, b]) => t === tipo && b === id)) return no('solo se parte de una base aprobada en canva/recursos.json del cliente');
      if (inp.page_numbers !== undefined && !(Array.isArray(inp.page_numbers) && inp.page_numbers.length === 1 && inp.page_numbers[0] === 1)) return no('solo la página 1 de la base');
      return si;
    }
    case 'edit-design': {
      const d = hist.transacciones.get(String(inp.transaction_id || ''));
      if (!d || !propios.has(d)) return no('la transacción no es del diseño de esta sesión (ábrela con read-design open_transaction sobre ese diseño)');
      if (inp.finalize !== undefined && !['keep_open', 'commit', 'cancel'].includes(inp.finalize)) return no('finalize desconocido');
      const ops = Array.isArray(inp.operations) ? inp.operations : [];
      const malas = [...new Set(ops.map(o => o?.type).filter(t => !CANVA.operaciones_edicion.includes(t)))];
      if (malas.length) return no(`operación no permitida: ${malas.join(', ')}. Solo ${CANVA.operaciones_edicion.join(', ')} sobre textos; colores, fuentes, logo, título y posiciones los fija la base`);
      // Solo sobre elementos de TEXTO que ya se leyeron de ese diseño (nunca el logo, una imagen o algo que no se ha visto).
      const tipos = hist.elementos.get(d) || new Map();
      const fuera = ops.filter(o => { const k = porId(tipos, o?.locator_id); return !k || !TIPOS_TEXTO.includes(tipos.get(k)) || tipos.get(k) === ''; })
        .map(o => o?.locator_id || '(sin locator)');
      if (fuera.length) return no(`solo se editan elementos de texto leídos de este diseño; no: ${fuera.slice(0, 4).join(', ')}`);
      return si;
    }
    case 'export-design': {
      if (!propios.has(idDeDiseno(inp.design_id))) return no('solo se exporta el diseño de esta sesión');
      const f = inp.format || {};
      if (f.type !== 'png') return no('se exporta en PNG');
      if (f.transparent_background === true) return no('se exporta con fondo (transparent_background=false)');
      const raros = Object.keys(f).filter(k => !FORMATO_EXPORT.includes(k));
      if (raros.length) return no(`opciones de exportación no permitidas: ${raros.join(', ')}`);
      return si;
    }
    case 'move-item-to-folder': {
      if (!propios.has(idDeDiseno(inp.item_id))) return no('solo se mueve el diseño de esta sesión');
      if (String(inp.to_folder_id || '') !== meta.f) return no('solo a la carpeta aprobada en canva/recursos.json');
      return si;
    }
    default: return no(`${uso.name} no está en la lista de herramientas de Canva del Creativo`);
  }
}

// Sesión idle con requires_action: decide cada pendiente y la deja seguir. null si la sesión no espera confirmaciones.
// Idempotente: lo ya confirmado no se vuelve a enviar (webhook duplicado o barrido).
// confirmar=false (sesión que ya pasó del tope de minutos): no aprueba nada; solo dice que espera.
export async function resuelveConfirmaciones({ client, sessionId, session, confirmar = true }) {
  const eventos = await eventosDe(client, sessionId);
  const meta = leeMetaCanva(session?.metadata);
  const estados = eventos.filter(e => e.type === 'session.status_idle' || e.type === 'session.status_running');
  const ultimo = estados.at(-1);
  // En una sesión de Canva, si el log aún no trae el idle que reporta la sesión (desfase), no se cierra: se espera al siguiente aviso.
  if (meta && ultimo?.type !== 'session.status_idle') return 'sin_evento_idle';
  if (ultimo?.type !== 'session.status_idle' || ultimo.stop_reason?.type !== 'requires_action') return null;
  if (!confirmar) return 'vencida';
  const hist = historiaCanva(eventos);
  const porId = new Map(eventos.filter(e => ['agent.mcp_tool_use', 'agent.tool_use'].includes(e.type)).map(e => [e.id, e]));
  const ya = new Set(eventos.filter(e => e.type === 'user.tool_confirmation').map(e => e.tool_use_id));
  const ahora = new Map(), envio = [];
  for (const id of ultimo.stop_reason.event_ids || []) {
    const uso = porId.get(id);
    if (ya.has(id) || !uso || uso.evaluated_permission === 'deny') continue;
    const d = uso.type === 'agent.mcp_tool_use' ? decideConfirmacion(uso, { meta, hist, ahora })
      : { result: 'deny', deny_message: 'Harness 5cero5: esta herramienta no tiene regla de aprobación en el harness' };
    ahora.set(id, d.result);
    envio.push({ type: 'user.tool_confirmation', tool_use_id: id, ...d });
  }
  if (!envio.length) return 'sin_pendientes';
  await client.beta.sessions.events.send(sessionId, { events: envio });
  return envio.map(e => `${porId.get(e.tool_use_id)?.name}:${e.result}`).join(',');
}

// ---------------------------------------------------------------- 3. cierre
const sha256 = b => createHash('sha256').update(b).digest('hex');
export const hostsExport = c => (c?.canvaExportHosts?.length ? c.canvaExportHosts : CANVA.hosts_export).map(h => String(h).toLowerCase());

function urlsExport(vals, hosts) {
  return cadenas(vals).filter(s => { try { const u = new URL(s); return u.protocol === 'https:' && hosts.includes(u.hostname.toLowerCase()); } catch { return false; } });
}

// Baja la exportación sin credenciales, sin seguir redirecciones, solo de hosts de Canva permitidos, con tope de 15 MB (se corta
// al pasarlo, sin bajar el resto) y 20 s.
export async function bajaExport(url, hosts, fetchImpl = fetch) {
  const u = new URL(url);
  if (u.protocol !== 'https:' || !hosts.includes(u.hostname.toLowerCase())) throw new Error(`host no permitido: ${u.hostname}`);
  const r = await fetchImpl(url, { redirect: 'error', signal: AbortSignal.timeout(20000) });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  if (Number(r.headers?.get?.('content-length') || 0) > MAX_EXPORT) throw new Error('más de 15 MB');
  if (r.body?.getReader) {
    const partes = []; let n = 0;
    const lector = r.body.getReader();
    for (;;) {
      const { done, value } = await lector.read();
      if (done) break;
      n += value.length;
      if (n > MAX_EXPORT) { await lector.cancel(); throw new Error('más de 15 MB'); }
      partes.push(Buffer.from(value));
    }
    return Buffer.concat(partes);
  }
  const buf = Buffer.from(await r.arrayBuffer());
  if (buf.length > MAX_EXPORT) throw new Error('más de 15 MB');
  return buf;
}

// La relectura del log, elemento por elemento, contra el PR y los recursos aprobados (las mismas reglas que verificar_canva.py).
export function revisaLectura({ vals, canva, copia, textosMuestra = {}, fijos = [], logo = '' }) {
  const problemas = [];
  const { textos, assets } = elementosDe(vals);
  if (!textos.size) return ['la relectura de Canva no trae elementos de texto legibles'];
  const el = canva?.elementos || {};
  const usados = new Set();
  for (const rol of ROLES) {
    const esperado = normT(une(copia?.[rol]));
    const k = porId(textos, el[rol]);
    if (!el[rol] || k === undefined) { if (esperado) problemas.push(`la relectura no trae el elemento de ${rol} (${el[rol] || 'sin elemento en canva.json'})`); continue; }
    if (usados.has(k)) problemas.push(`${rol} comparte elemento con otro rol`);
    usados.add(k);
    if (normT(textos.get(k)) !== esperado) problemas.push(`${rol} guardado en Canva no es la copia del PR`);
  }
  const fijosN = new Set(fijos.map(normT));
  const muestras = new Set(Object.values(textosMuestra).filter(x => typeof x === 'string' && x.trim()).map(normT));
  const extra = [...textos].filter(([k, t]) => !usados.has(k) && normT(t) && !fijosN.has(normT(t)));
  if (extra.length) problemas.push(`textos en Canva fuera de los roles y de los fijos aprobados: ${extra.slice(0, 3).map(([, t]) => JSON.stringify(String(t).slice(0, 40))).join(', ')}`);
  const quedan = [...textos].filter(([, t]) => muestras.has(normT(t)));
  if (quedan.length) problemas.push(`siguen textos de muestra de la base: ${quedan.slice(0, 3).map(([, t]) => JSON.stringify(String(t).slice(0, 40))).join(', ')}`);
  if (logo && !assets.has(logo)) problemas.push(`la relectura de Canva no trae el logo aprobado (${logo})`);
  return problemas;
}

// pieza: { meta (pieza.json), canva (canva.json), png (Buffer), copia } de la punta del PR (compruebaPieza).
export async function compruebaCanvaSesion({ client, sessionId, session, pieza, c, fetchImpl = fetch }) {
  const meta = leeMetaCanva(session?.metadata);
  if (!meta) return { problemas: ['la pieza es de Canva y la sesión no se despachó como Canva'], resumen: '' };
  const problemas = [];
  const hist = historiaCanva(await eventosDe(client, sessionId));
  const cj = pieza.canva || {};
  const pos = u => hist.orden.indexOf(u);
  const esperado = meta.d || (hist.disenos.length === 1 ? hist.disenos[0] : null);
  if (!esperado) problemas.push(hist.disenos.length > 1 ? `la sesión creó ${hist.disenos.length} diseños (una pieza = un diseño)`
    : 'el log de la sesión no muestra el diseño creado desde la base (copy-design) ni el de la ronda');
  else if (cj.design_id !== esperado || pieza.meta?.canva?.design_id !== esperado) problemas.push(`canva.json/pieza.json dicen ${cj.design_id}, la sesión trabajó ${esperado}`);
  if (meta.d && hist.orden.some(u => CREAN.includes(u.name) && u.resultado && !u.error)) problemas.push('ronda: se creó otro diseño en vez de editar el mismo');
  if (!meta.d) {
    const b = meta.b?.[pieza.meta?.formato];
    if (!b || cj.base?.tipo !== b[0] || cj.base?.id !== b[1]) problemas.push(`la base de canva.json (${cj.base?.tipo}:${cj.base?.id}) no es la aprobada para ${pieza.meta?.formato}`);
    const origen = hist.orden.find(u => CREAN.includes(u.name) && u.resultado && !u.error);
    const desde = origen && (origen.name === 'copy-design' ? idDeDiseno(origen.input.design_id) : origen.input.brand_template_id);
    if (origen && (!b || desde !== b[1])) problemas.push('el diseño no salió de la base aprobada de su formato');
  }
  // Guardado y relectura posterior, elemento por elemento (lo que decide; no el archivo que escribió el agente).
  const commits = hist.orden.filter(u => u.name === 'edit-design' && u.input.finalize === 'commit' && u.resultado && !u.error
    && hist.transacciones.get(String(u.input.transaction_id || '')) === esperado);
  const ultimo = commits.at(-1);
  if (!ultimo) problemas.push('no hay commit del diseño (edit-design con finalize=commit): los cambios no quedaron guardados');
  const lectura = hist.orden.filter(u => u.name === 'read-design' && u.resultado && !u.error && idDeDiseno(u.input.design_id) === esperado
    && !u.input.transaction_id && !u.input.open_transaction && (!ultimo || pos(u) > pos(ultimo))).at(-1);
  if (!lectura) problemas.push('no hay relectura del diseño guardado (read-design sin transacción) después del último commit');
  else {
    let rec = null;
    try { rec = await recursosCanva({ c, fetchImpl }); } catch (e) { problemas.push(`no se pudieron leer los recursos aprobados para cotejar la relectura (${e.message})`); }
    if (rec) problemas.push(...revisaLectura({ vals: lectura.resultado, canva: cj, copia: pieza.copia, textosMuestra: rec.textos[pieza.meta?.formato] || {},
      fijos: rec.fijos, logo: meta.l || '' }));
  }
  // Exportación PNG después del último commit, cotejada byte a byte con el PR.
  const ex = hist.orden.filter(u => u.name === 'export-design' && u.resultado && !u.error && idDeDiseno(u.input.design_id) === esperado
    && u.input.format?.type === 'png' && (!ultimo || pos(u) > pos(ultimo))).at(-1);
  let cotejo = 'sin exportación';
  if (!ex) problemas.push('no hay exportación PNG del diseño después del último commit');
  else {
    const hosts = hostsExport(c);
    const urls = urlsExport(ex.resultado, hosts);
    if (!urls.length) { problemas.push(`la exportación no trae una URL de ${hosts.join(', ')}`); cotejo = 'sin URL permitida'; }
    else {
      try {
        const bytes = await bajaExport(urls[0], hosts, fetchImpl);
        if (!pieza.png || sha256(bytes) !== sha256(pieza.png)) { problemas.push('pieza.png del PR no es la exportación original de Canva (bytes distintos)'); cotejo = 'distinta'; }
        else cotejo = `idéntica (sha256 ${sha256(bytes).slice(0, 12)})`;
      } catch (e) { problemas.push(`no se pudo bajar la exportación de Canva para cotejarla (${e.message})`); cotejo = 'sin bajar'; }
    }
  }
  if (cj.export?.sha256 && pieza.png && cj.export.sha256 !== sha256(pieza.png)) problemas.push('canva.json registra otra exportación');
  // Enlace de edición y carpeta aprobada (para que quien aprueba lo abra).
  const editUrl = String(cj.edit_url || '');
  if (!esperado || !/^https:\/\/www\.canva\.com\/design\//.test(editUrl) || !editUrl.includes(`/design/${esperado}/`)) problemas.push('canva.json no trae el enlace de edición del diseño');
  const movido = hist.orden.some(u => u.name === 'move-item-to-folder' && u.resultado && !u.error && idDeDiseno(u.input.item_id) === esperado && u.input.to_folder_id === meta.f);
  if (!meta.d && !movido) problemas.push('el diseño no se movió a la carpeta aprobada (quien aprueba no lo vería)');
  const negadas = hist.orden.filter(u => hist.confirmados.get(u.id) === 'deny').map(u => u.name);
  const resumen = ` Canva: diseño ${esperado || '?'}${meta.d ? ' (ronda: el mismo diseño)' : ''}, ${commits.length} commit(s), relectura ${lectura ? 'después del último commit, cotejada por elemento' : 'faltante'}, exportación PNG ${cotejo}` +
    `${negadas.length ? `, ${negadas.length} llamada(s) negada(s) por el harness (${[...new Set(negadas)].join(', ')})` : ''}. Editable: ${editUrl || 'sin enlace'}.`;
  return { problemas, resumen, editUrl };
}
