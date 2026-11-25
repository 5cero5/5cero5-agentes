// Canva en el Creativo: Notion → harness → sesión de Managed Agents con el MCP oficial de Canva → PR en el repo de piezas.
// Tres momentos, todos fallan cerrado:
//  1. Despacho (preparaCanva): la fila pide "Canva: sí" (o es ronda de una pieza hecha en Canva) y CANVA_ACTIVO=1. Del repo de
//     marca DE ESE CLIENTE sale canva/recursos.json (bases aprobadas por formato, carpeta, logo); en SU Vault Creativo tiene que
//     haber una credencial mcp_oauth de Canva con metadata {cliente: <slug>, rol: "canva"}. La referencia del vault no basta: se
//     comprueban vault, credencial, recursos y cliente antes de abrir la sesión.
//  2. Confirmaciones (resuelveConfirmaciones): las herramientas de Canva que escriben van con always_ask. Cuando la sesión queda
//     idle con requires_action, el harness decide con reglas fijas (decideConfirmacion): solo una base aprobada, un diseño por
//     sesión (en una ronda, el mismo), solo ese diseño, solo operaciones de texto, exportar PNG y moverlo a la carpeta aprobada.
//  3. Cierre (compruebaCanvaSesion): lo que pasó en Canva se lee del log de la sesión (resultados del servidor MCP, que el agente
//     no escribe): el diseño del PR es el de la sesión, se guardó (commit), se releyó DESPUÉS del último commit con la copia y el
//     logo, se exportó en PNG y esa exportación, bajada por el harness, es byte a byte el pieza.png del PR.
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

export class ErrorCanva extends Error {
  constructor(m, motivo = 'canva') { super(m); this.motivo = motivo; }
}

// "Canva: sí" en su propia línea del brief (como "Foto: sí" o "Destino: WhatsApp").
export const canvaDelBrief = brief => /^\s*[-*]?\s*Canva\s*:\s*s[ií]\s*\.?\s*$/mi.test(String(brief || ''));
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
  if (!ID.test(String(d.logo_asset_id || ''))) throw new ErrorCanva(`canva/recursos.json de ${repo}: falta logo_asset_id (asset del logo aprobado)`, 'canva_sin_recursos');
  return { bases, textos, carpeta: d.carpeta_id, logo: d.logo_asset_id, kit: ID.test(String(d.brand_kit_id || '')) ? d.brand_kit_id : '' };
}

export async function recursosCanva({ c, fetchImpl = fetch }) {
  const { repo, token } = await marcaParaLeer({ c, fetchImpl });
  let x;
  try { x = await gh(fetchImpl, 'GET', `/repos/${repo}/contents/canva/recursos.json`, token); }
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
  const cr = deCanva[0];
  if (cr.metadata?.cliente !== slug || cr.metadata?.rol !== 'canva') {
    throw new ErrorCanva(`Canva: la credencial ${cr.id} no es de ${slug}/canva (metadata cliente=${cr.metadata?.cliente || 'vacío'}, rol=${cr.metadata?.rol || 'vacío'})`, 'canva_sin_credencial');
  }
  return { id: cr.id, cuenta: String(cr.metadata?.canva_cuenta || '') };
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

// null si la fila no es de Canva; si lo es, lo que va en la sesión ({ b, f, l, k, d, cr }) o ErrorCanva con el motivo.
// cli: el cliente de la fila (ya resuelto para los aprobadores). c: la configuración con lo del cliente.
export async function preparaCanva({ client, c, fila, cli, fetchImpl = fetch }) {
  let design = null;
  if (fila.ronda) {
    // Con CANVA_ACTIVO apagado, una ronda sigue exactamente como antes (sin la lectura extra en GitHub). Si la pieza era de
    // Canva, pr_pieza.py se niega a rearmarla como HTML.
    if (!c.canvaActivo) return null;
    const meta = await piezaDeLaRonda({ c, ronda: fila.ronda, fetchImpl });
    if (meta?.fuente !== 'canva') return null;
    design = idDeDiseno(meta.canva?.design_id);
    if (!design) throw new ErrorCanva('Ronda de una pieza de Canva sin design_id válido en pieza.json');
  } else if (!canvaDelBrief(fila.brief)) return null;
  if (!c.canvaActivo) throw new ErrorCanva('La fila pide Canva y CANVA_ACTIVO está apagado: no se despacha (lo enciende Al en el harness)', 'canva_apagado');
  // Foto con Canva: se integra con el núcleo de Higgsfield en otra rama. Mientras, falla cerrado (no se cobra nada).
  if (fila.ronda ? fila.ronda.foto !== 'Igual' : fotoDelBrief(fila.brief)) {
    throw new ErrorCanva('Canva con foto todavía no está habilitado en el harness: la pieza va sin foto o con Foto en la ronda = Igual', 'canva_foto');
  }
  const rec = await recursosCanva({ c, fetchImpl });
  const vault = (c.vaultsPorAgente?.Creativo || [])[0] || c.github?.destinos?.piezas?.vault;
  const cred = await credencialCanva({ client, vault, slug: cli.slug });
  const canva = { v: 1, b: rec.bases, f: rec.carpeta, l: rec.logo, ...(rec.kit ? { k: rec.kit } : {}), ...(design ? { d: design } : {}), cr: cred.id };
  if (JSON.stringify(canva).length > 512) throw new ErrorCanva('Los recursos de Canva no caben en la metadata de la sesión (máximo 512 caracteres)');
  return { ...canva, textos: rec.textos, marca: rec.repo, cuenta: cred.cuenta };
}

// Lo que viaja en la metadata de la sesión (una sola clave, "canva"): el harness lo vuelve a leer al confirmar y al cerrar.
export const metadataCanva = canva => JSON.stringify({ v: 1, b: canva.b, f: canva.f, l: canva.l, ...(canva.k ? { k: canva.k } : {}),
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

// Diseños que nombra un resultado (design_id, id dentro de "design" o enlaces /design/D…), sin el de origen.
function disenosDe(vals, origen) {
  const out = new Set();
  recorre(vals, (k, v) => { if (typeof v === 'string' && (k === 'design_id' || k === 'id') && DISENO.test(v)) out.add(v); });
  for (const s of cadenas(vals)) { const d = idDeDiseno(s); if (d && s.includes('canva.com/design/')) out.add(d); }
  out.delete(origen);
  return [...out];
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
  const disenos = [], transacciones = new Map();
  for (const u of orden) {
    if (u.error || !u.resultado) continue;
    if (CREAN.includes(u.name)) disenos.push(...disenosDe(u.resultado, idDeDiseno(u.input.design_id) || u.input.brand_template_id));
    if (u.name === 'read-design') {
      const d = idDeDiseno(u.input.design_id);
      if (d) for (const tx of deClave(u.resultado, 'transaction_id')) transacciones.set(tx, d);
    }
  }
  return { orden, confirmados, disenos: [...new Set(disenos)], transacciones };
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
      const ops = Array.isArray(inp.operations) ? inp.operations : [];
      const malas = [...new Set(ops.map(o => o?.type).filter(t => !CANVA.operaciones_edicion.includes(t)))];
      if (malas.length) return no(`operación no permitida: ${malas.join(', ')}. Solo ${CANVA.operaciones_edicion.join(', ')}; colores, fuentes, logo y posiciones los fija la base`);
      if (inp.finalize !== undefined && !['keep_open', 'commit', 'cancel'].includes(inp.finalize)) return no('finalize desconocido');
      return si;
    }
    case 'export-design': {
      if (!propios.has(idDeDiseno(inp.design_id))) return no('solo se exporta el diseño de esta sesión');
      if (inp.format?.type !== 'png') return no('se exporta en PNG');
      if (inp.format?.transparent_background === true) return no('se exporta con fondo (transparent_background=false)');
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
export async function resuelveConfirmaciones({ client, sessionId, session }) {
  const eventos = await eventosDe(client, sessionId);
  const idle = [...eventos].reverse().find(e => e.type === 'session.status_idle');
  if (idle?.stop_reason?.type !== 'requires_action') return null;
  const hist = historiaCanva(eventos);
  const meta = leeMetaCanva(session?.metadata);
  const porId = new Map(eventos.filter(e => ['agent.mcp_tool_use', 'agent.tool_use'].includes(e.type)).map(e => [e.id, e]));
  const ya = new Set(eventos.filter(e => e.type === 'user.tool_confirmation').map(e => e.tool_use_id));
  const ahora = new Map(), envio = [];
  for (const id of idle.stop_reason.event_ids || []) {
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

// Baja la exportación sin credenciales, sin seguir redirecciones, solo de hosts de Canva permitidos, con tope de 15 MB y 20 s.
export async function bajaExport(url, hosts, fetchImpl = fetch) {
  const u = new URL(url);
  if (u.protocol !== 'https:' || !hosts.includes(u.hostname.toLowerCase())) throw new Error(`host no permitido: ${u.hostname}`);
  const r = await fetchImpl(url, { redirect: 'error', signal: AbortSignal.timeout(20000) });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  const buf = Buffer.from(await r.arrayBuffer());
  if (buf.length > MAX_EXPORT) throw new Error('más de 15 MB');
  return buf;
}

// pieza: { meta (pieza.json), canva (canva.json), png (Buffer), copia } de la punta del PR (compruebaPieza).
export async function compruebaCanvaSesion({ client, sessionId, session, pieza, c, fetchImpl = fetch }) {
  const meta = leeMetaCanva(session?.metadata);
  if (!meta) return { problemas: ['la pieza es de Canva y la sesión no se despachó como Canva'], resumen: '' };
  const problemas = [];
  const hist = historiaCanva(await eventosDe(client, sessionId));
  const cj = pieza.canva || {};
  const pos = u => hist.orden.indexOf(u);
  const esperado = meta.d || hist.disenos[0] || null;
  if (!esperado) problemas.push('el log de la sesión no muestra el diseño creado desde la base (copy-design) ni el de la ronda');
  else if (cj.design_id !== esperado || pieza.meta?.canva?.design_id !== esperado) problemas.push(`canva.json/pieza.json dicen ${cj.design_id}, la sesión trabajó ${esperado}`);
  if (meta.d && hist.orden.some(u => CREAN.includes(u.name) && u.resultado && !u.error)) problemas.push('ronda: se creó otro diseño en vez de editar el mismo');
  if (!meta.d && hist.disenos.length > 1) problemas.push(`la sesión creó ${hist.disenos.length} diseños (una pieza = un diseño)`);
  if (!meta.d) {
    const b = meta.b?.[pieza.meta?.formato];
    if (!b || cj.base?.tipo !== b[0] || cj.base?.id !== b[1]) problemas.push(`la base de canva.json (${cj.base?.tipo}:${cj.base?.id}) no es la aprobada para ${pieza.meta?.formato}`);
    const origen = hist.orden.find(u => CREAN.includes(u.name) && u.resultado && !u.error);
    const desde = origen && (origen.name === 'copy-design' ? idDeDiseno(origen.input.design_id) : origen.input.brand_template_id);
    if (origen && (!b || desde !== b[1])) problemas.push('el diseño no salió de la base aprobada de su formato');
  }
  // Guardado y relectura posterior.
  const commits = hist.orden.filter(u => u.name === 'edit-design' && u.input.finalize === 'commit' && u.resultado && !u.error
    && hist.transacciones.get(String(u.input.transaction_id || '')) === esperado);
  const ultimo = commits.at(-1);
  if (!ultimo) problemas.push('no hay commit del diseño (edit-design con finalize=commit): los cambios no quedaron guardados');
  const lectura = hist.orden.filter(u => u.name === 'read-design' && u.resultado && !u.error && idDeDiseno(u.input.design_id) === esperado
    && !u.input.transaction_id && !u.input.open_transaction && (!ultimo || pos(u) > pos(ultimo))).at(-1);
  if (!lectura) problemas.push('no hay relectura del diseño guardado (read-design sin transacción) después del último commit');
  else {
    const texto = cadenas(lectura.resultado).map(normT).join(' | ');
    const faltan = ROLES.filter(k => normT(une(pieza.copia?.[k])) && !texto.includes(normT(une(pieza.copia?.[k]))));
    if (faltan.length) problemas.push(`la relectura de Canva no trae la copia del PR en: ${faltan.join(', ')}`);
    if (meta.l && !cadenas(lectura.resultado).some(s => s.includes(meta.l))) problemas.push(`la relectura de Canva no trae el logo aprobado (${meta.l})`);
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
  const resumen = ` Canva: diseño ${esperado || '?'}${meta.d ? ' (ronda: el mismo diseño)' : ''}, ${commits.length} commit(s), relectura ${lectura ? 'después del último commit' : 'faltante'}, exportación PNG ${cotejo}` +
    `${negadas.length ? `, ${negadas.length} llamada(s) negada(s) por el harness (${[...new Set(negadas)].join(', ')})` : ''}. Editable: ${editUrl || 'sin enlace'}.`;
  return { problemas, resumen, editUrl };
}
