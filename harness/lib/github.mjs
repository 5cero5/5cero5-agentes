// GitHub App "5cero5-agentes": tokens de corta vida (1 hora) para el agente Landing y comprobación de sus PRs.
// Solo Node (crypto + fetch), sin dependencias.
//   - Antes de cada sesión de Landing, el harness saca un token de ESCRITURA limitado al repo de landings
//     (contents + pull_requests) y lo pone en la credencial GITHUB_TOKEN del vault de Landing (solo en
//     encabezados hacia api.github.com). Y uno de LECTURA para montar el repo en la sesión.
//   - Al cerrar la sesión, comprueba en GitHub el PR que el agente dice que abrió (regla 8).
import { createSign } from 'node:crypto';

const API = () => process.env.GITHUB_API_BASE || 'https://api.github.com';
const b64url = b => Buffer.from(b).toString('base64').replace(/=+$/, '').replace(/\+/g, '-').replace(/\//g, '_');

// JWT RS256 de la app (vale 9 minutos; GitHub acepta hasta 10). iat 60 s antes por diferencias de reloj.
export function jwtApp(appId, pem, ahora = Math.floor(Date.now() / 1000)) {
  const h = b64url(JSON.stringify({ alg: 'RS256', typ: 'JWT' }));
  const p = b64url(JSON.stringify({ iat: ahora - 60, exp: ahora + 540, iss: String(appId) }));
  let firma;
  try { firma = createSign('RSA-SHA256').update(`${h}.${p}`).sign(normalizaPem(pem)); }
  catch (e) { throw new Error(`No se pudo firmar con GH_APP_PRIVATE_KEY (${e.message}). Revisa que sea la llave .pem completa de la GitHub App.`); }
  return `${h}.${p}.${b64url(firma)}`;
}

// Al pegar la llave en Netlify los saltos de línea pueden llegar como "\n" literales, espacios o CRLF, o la llave
// puede venir entera en base64. Se rearma el PEM: encabezado, cuerpo en base64 sin espacios en líneas de 64 y pie.
export function normalizaPem(pem) {
  const s = String(pem || '').replace(/\\n/g, '\n').replace(/\r/g, '').trim();
  const m = s.match(/-----BEGIN ([A-Z ]+)-----([\s\S]*?)-----END \1-----/);
  if (!m) {
    if (/^[A-Za-z0-9+/=\s]+$/.test(s)) {
      const dec = Buffer.from(s.replace(/\s/g, ''), 'base64').toString('utf8');
      if (dec.includes('-----BEGIN ')) return normalizaPem(dec);
    }
    throw new Error('GH_APP_PRIVATE_KEY no parece una llave PEM (falta -----BEGIN ... PRIVATE KEY-----)');
  }
  const cuerpo = m[2].replace(/[^A-Za-z0-9+/=]/g, '');
  return `-----BEGIN ${m[1]}-----\n${cuerpo.match(/.{1,64}/g).join('\n')}\n-----END ${m[1]}-----\n`;
}

async function gh(fetchImpl, method, path, token, body, tipo = 'Bearer') {
  const r = await fetchImpl(API() + path, {
    method,
    headers: { Authorization: `${tipo} ${token}`, Accept: 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28',
      'User-Agent': '5cero5-harness', ...(body ? { 'Content-Type': 'application/json' } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  const t = await r.text();
  let data = {};
  try { data = t ? JSON.parse(t) : {}; } catch { data = { raw: t.slice(0, 200) }; }
  if (!r.ok) { const e = new Error(`GitHub ${method} ${path.split('?')[0]} -> ${r.status}: ${data.message || ''}`); e.status = r.status; throw e; }
  return data;
}

// Token de instalación limitado a un repo y a los permisos pedidos (nunca más de lo que la app tiene).
export async function tokenInstalacion({ appId, pem, installationId, repo, permisos, fetchImpl = fetch }) {
  if (!appId || !pem || !installationId) throw new Error('Falta GH_APP_ID, GH_APP_PRIVATE_KEY o GH_APP_INSTALLATION_ID');
  const nombre = String(repo).split('/').pop();
  const r = await gh(fetchImpl, 'POST', `/app/installations/${installationId}/access_tokens`, jwtApp(appId, pem),
    { repositories: [nombre], permissions: permisos });
  if (!r.token) throw new Error('GitHub no regresó el token de instalación');
  return { token: r.token, vence: r.expires_at };
}

export async function shaDeMain(token, repo, fetchImpl = fetch) {
  return (await gh(fetchImpl, 'GET', `/repos/${repo}/git/ref/heads/main`, token)).object?.sha || null;
}

import { agenteDe } from './agentes.mjs';

const SLUG = /^[a-z0-9][a-z0-9-]{0,40}$/;

// Destino de GitHub del agente (repo, credencial y vault) o error claro de qué falta.
function destinoDe(c, agente) {
  const gd = agenteDe(agente)?.github;
  if (!gd) throw new Error(`${agente} no abre PRs en GitHub`);
  const g = c.github || {};
  const d = g.destinos?.[gd.destino] || {};
  const faltan = [['appId', g.appId], ['installationId', g.installationId], ['privateKey', g.privateKey], [d.credVar || 'cred', d.cred], [d.vaultVar || 'vault', d.vault]]
    .filter(([, v]) => !v).map(([k]) => k);
  if (faltan.length) throw new Error(`Falta configuración de GitHub para ${agente}: ${faltan.join(', ')}`);
  return { g, d, gd };
}

// Antes de abrir la sesión: credencial de escritura en el vault del agente, token de lectura (montaje y sha de main).
export async function preparaGithub({ client, c, agente = 'Landing', fetchImpl = fetch }) {
  const { g, d } = destinoDe(c, agente);
  const base = { appId: g.appId, pem: g.privateKey, installationId: g.installationId, repo: d.repo, fetchImpl };
  const escritura = await tokenInstalacion({ ...base, permisos: { contents: 'write', pull_requests: 'write' } });
  const lectura = await tokenInstalacion({ ...base, permisos: { contents: 'read' } });
  await client.beta.vaults.credentials.update(d.cred, {
    vault_id: d.vault, auth: { type: 'environment_variable', secret_value: escritura.token } });
  return { lectura: lectura.token, mainSha: await shaDeMain(lectura.token, d.repo, fetchImpl) };
}

// Carpeta que el PR puede tocar según la respuesta del agente.
const PREFIJOS = {
  landings: r => (SLUG.test(String(r.slug || '')) ? `landings/${r.slug}/` : null),
  piezas: r => (SLUG.test(String(r.campana || '')) && SLUG.test(String(r.pieza || '')) ? `piezas/${r.campana}/${r.pieza}/` : null),
};

// Regla 8: el PR existe, está abierto y sin fusionar, va de agente/* a main, su commit es el que reportó el agente,
// solo cambia su carpeta y main no cambió durante la sesión. Para piezas, además, lo que hay en la carpeta (compruebaPieza).
export async function compruebaPR({ c, agente = 'Landing', respuesta, mainAntes, fetchImpl = fetch }) {
  let g, d, gd;
  try { ({ g, d, gd } = destinoDe(c, agente)); } catch (e) { return { ok: false, informe: `Comprobación en GitHub: ${e.message}.` }; }
  const problemas = [];
  const r = respuesta || {};
  const pref = PREFIJOS[gd.destino](r);
  if (!pref) problemas.push(`carpeta inválida en la respuesta (${gd.destino === 'piezas' ? `campana=${r.campana || 'vacío'}, pieza=${r.pieza || 'vacío'}` : `slug ${r.slug || 'vacío'}`})`);
  const numero = Number(r.pr_numero);
  if (!Number.isInteger(numero) || numero < 1) return { ok: false, informe: `Comprobación en GitHub: sin pr_numero válido.` };
  let token;
  try { token = (await tokenInstalacion({ appId: g.appId, pem: g.privateKey, installationId: g.installationId, repo: d.repo,
    permisos: { contents: 'read', pull_requests: 'read' }, fetchImpl })).token; }
  catch (e) { return { ok: false, informe: `Comprobación en GitHub: no se pudo sacar token (${e.message}).` }; }
  let pr;
  try { pr = await gh(fetchImpl, 'GET', `/repos/${d.repo}/pulls/${numero}`, token); }
  catch (e) { return { ok: false, informe: `Comprobación en GitHub: el PR #${numero} no existe o no se puede leer (${e.status || e.message}).` }; }
  if (pr.state !== 'open') problemas.push(`el PR está ${pr.state}`);
  if (pr.merged || pr.merged_at) problemas.push('el PR ya está fusionado (nadie más que Al o Bonzo publica)');
  if (pr.base?.ref !== 'main') problemas.push(`va a ${pr.base?.ref}, no a main`);
  if (!String(pr.head?.ref || '').startsWith('agente/')) problemas.push(`la rama ${pr.head?.ref} no empieza con agente/`);
  if (r.commit && pr.head?.sha !== r.commit) problemas.push(`el commit del PR (${pr.head?.sha?.slice(0, 7)}) no es el reportado (${String(r.commit).slice(0, 7)})`);
  let archivos = [];
  try { archivos = await gh(fetchImpl, 'GET', `/repos/${d.repo}/pulls/${numero}/files?per_page=100`, token); }
  catch (e) { problemas.push(`no se pudieron leer los archivos del PR (${e.status || e.message})`); }
  const fuera = archivos.map(f => f.filename).filter(n => !pref || !n.startsWith(pref));
  if (fuera.length) problemas.push(`cambia archivos fuera de ${pref || 'su carpeta'}: ${fuera.slice(0, 5).join(', ')}`);
  if (!archivos.length) problemas.push('el PR no cambia ningún archivo');
  let extra = '';
  if (gd.destino === 'piezas' && pref && pr.head?.sha) {
    const p = await compruebaPieza({ repo: d.repo, pref, ref: pr.head.sha, respuesta: r, token, fetchImpl });
    problemas.push(...p.problemas); extra = p.resumen;
  }
  if (mainAntes) {
    try {
      const ahora = await shaDeMain(token, d.repo, fetchImpl);
      if (ahora !== mainAntes) problemas.push(`main cambió durante la sesión (${mainAntes.slice(0, 7)} → ${String(ahora).slice(0, 7)}): revisar quién publicó`);
    } catch (e) { problemas.push(`no se pudo leer main (${e.status || e.message})`); }
  }
  const informe = `Comprobación en GitHub: PR #${numero} (${pr.html_url || ''}), ${archivos.length} archivo(s) en ${pref || '?'}.${extra}` +
    (problemas.length ? ` Problemas: ${problemas.join('; ')}.` : ` Abierto, sin fusionar y solo con su carpeta. Falta ${gd.destino === 'piezas' ? 'mirar la pieza' : 'revisar el deploy preview'} y aprobarlo en GitHub.`);
  return { ok: problemas.length === 0, informe };
}

// Tamaño de cada formato (tokens.json del repo de marca). El PNG del PR debe medir esto.
export const MEDIDAS = { 'post-4x5': [1080, 1350], 'post-1x1': [1080, 1080], 'historia-9x16': [1080, 1920] };
const PERMITIDOS = /^(pieza\.png|pieza\.html|copia\.json|pieza\.json|informe\.json|prompt\.txt|fotos\/fondo\.(jpg|jpeg|png|webp))$/;

export function medidasPng(buf) {
  const b = Buffer.from(buf);
  if (b.length < 24 || b.readUInt32BE(0) !== 0x89504e47 || b.toString('ascii', 12, 16) !== 'IHDR') return null;
  return [b.readUInt32BE(16), b.readUInt32BE(20)];
}

// La carpeta de la pieza en la punta del PR: lista fija de archivos, informe del Verificador aprobado y del mismo PNG
// (sha del blob), formato y foto como dijo el agente, y el PNG mide lo que su formato.
export async function compruebaPieza({ repo, pref, ref, respuesta, token, fetchImpl = fetch }) {
  const problemas = [];
  const r = respuesta || {};
  const lee = async (ruta) => {
    const x = await gh(fetchImpl, 'GET', `/repos/${repo}/contents/${ruta}?ref=${ref}`, token);
    return Buffer.from(String(x.content || ''), 'base64');
  };
  let lista = [], fotos = [];
  try {
    lista = await gh(fetchImpl, 'GET', `/repos/${repo}/contents/${pref.replace(/\/$/, '')}?ref=${ref}`, token);
    if (lista.some(e => e.type === 'dir' && e.name === 'fotos'))
      fotos = await gh(fetchImpl, 'GET', `/repos/${repo}/contents/${pref}fotos?ref=${ref}`, token);
  } catch (e) { return { problemas: [`no se pudo leer la carpeta ${pref} (${e.status || e.message})`], resumen: '' }; }
  const nombres = [...lista.filter(e => e.type !== 'dir').map(e => e.name), ...fotos.map(e => `fotos/${e.name}`)];
  const raros = [...nombres.filter(n => !PERMITIDOS.test(n)), ...lista.filter(e => e.type === 'dir' && e.name !== 'fotos').map(e => `${e.name}/`)];
  if (raros.length) problemas.push(`archivos que no van en una pieza: ${raros.slice(0, 5).join(', ')}`);
  const faltan = ['pieza.png', 'pieza.html', 'copia.json', 'pieza.json', 'informe.json'].filter(n => !nombres.includes(n));
  if (faltan.length) return { problemas: [...problemas, `faltan en la carpeta: ${faltan.join(', ')}`], resumen: '' };
  let inf, meta;
  try { inf = JSON.parse((await lee(`${pref}informe.json`)).toString('utf8')); meta = JSON.parse((await lee(`${pref}pieza.json`)).toString('utf8')); }
  catch (e) { return { problemas: [...problemas, `informe.json o pieza.json no se pueden leer (${e.status || e.message})`], resumen: '' }; }
  const shaPng = lista.find(e => e.name === 'pieza.png')?.sha;
  if (inf.aprobada !== true) problemas.push('el informe del Verificador no está aprobado');
  if (inf.png_blob_sha !== shaPng) problemas.push('el informe del Verificador es de otro PNG');
  const formato = String(r.formato || '');
  if (!MEDIDAS[formato]) problemas.push(`formato desconocido: ${formato || 'vacío'}`);
  if (meta.formato !== formato || inf.formato !== formato) problemas.push(`formato: el agente dice ${formato}, pieza.json ${meta.formato}, el Verificador midió ${inf.formato}`);
  if (meta.campana !== r.campana || meta.pieza !== r.pieza) problemas.push('pieza.json es de otra campaña o pieza');
  if (r.foto !== undefined && Boolean(r.foto) !== Boolean(meta.foto)) problemas.push(`foto: el agente dice ${Boolean(r.foto)}, pieza.json ${Boolean(meta.foto)}`);
  if (meta.foto && !(nombres.includes('prompt.txt') && nombres.some(n => n.startsWith('fotos/')))) problemas.push('lleva foto y faltan la foto o prompt.txt');
  if (!meta.foto && (nombres.includes('prompt.txt') || nombres.some(n => n.startsWith('fotos/')))) problemas.push('no lleva foto pero trae foto o prompt.txt');
  if (MEDIDAS[formato] && shaPng) {
    try {
      const blob = await gh(fetchImpl, 'GET', `/repos/${repo}/git/blobs/${shaPng}`, token);
      const m = medidasPng(Buffer.from(String(blob.content || ''), 'base64'));
      if (!m) problemas.push('pieza.png no es un PNG');
      else if (m[0] !== MEDIDAS[formato][0] || m[1] !== MEDIDAS[formato][1]) problemas.push(`pieza.png mide ${m[0]}x${m[1]}, no ${MEDIDAS[formato].join('x')}`);
    } catch (e) { problemas.push(`no se pudo leer pieza.png (${e.status || e.message})`); }
  }
  const avisos = Array.isArray(inf.avisos) ? inf.avisos.length : 0;
  const resumen = ` Pieza ${formato}${meta.foto ? ' con foto de Higgsfield' : ''}; Verificador de marca v${inf.repo_version || '?'}: ${inf.aprobada ? 'aprobada' : 'rechazada'}, ${avisos} aviso(s).`;
  return { problemas, resumen };
}
