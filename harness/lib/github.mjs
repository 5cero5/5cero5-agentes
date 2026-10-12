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

// Antes de abrir la sesión: credencial de escritura en el vault de Landing y token de lectura para el montaje.
export async function preparaGithub({ client, c, fetchImpl = fetch }) {
  const g = c.github;
  const faltan = ['appId', 'installationId', 'privateKey', 'repoLandings', 'credLanding', 'vaultLanding'].filter(k => !g?.[k]);
  if (faltan.length) throw new Error(`Falta configuración de GitHub para Landing: ${faltan.join(', ')}`);
  const base = { appId: g.appId, pem: g.privateKey, installationId: g.installationId, repo: g.repoLandings, fetchImpl };
  const escritura = await tokenInstalacion({ ...base, permisos: { contents: 'write', pull_requests: 'write' } });
  const lectura = await tokenInstalacion({ ...base, permisos: { contents: 'read' } });
  await client.beta.vaults.credentials.update(g.credLanding, {
    vault_id: g.vaultLanding, auth: { type: 'environment_variable', secret_value: escritura.token } });
  return { lectura: lectura.token, mainSha: await shaDeMain(lectura.token, g.repoLandings, fetchImpl) };
}

// Regla 8: el PR existe, está abierto y sin fusionar, va de agente/* a main, su commit es el que reportó el agente,
// solo cambia landings/<slug>/ y main no cambió durante la sesión.
export async function compruebaPR({ c, respuesta, mainAntes, fetchImpl = fetch }) {
  const g = c.github;
  const problemas = [];
  const r = respuesta || {};
  const slug = String(r.slug || '');
  if (!/^[a-z0-9][a-z0-9-]{0,40}$/.test(slug)) problemas.push(`slug inválido: ${slug || 'vacío'}`);
  const numero = Number(r.pr_numero);
  if (!Number.isInteger(numero) || numero < 1) return { ok: false, informe: `Comprobación en GitHub: sin pr_numero válido.` };
  let token;
  try { token = (await tokenInstalacion({ appId: g.appId, pem: g.privateKey, installationId: g.installationId, repo: g.repoLandings,
    permisos: { contents: 'read', pull_requests: 'read' }, fetchImpl })).token; }
  catch (e) { return { ok: false, informe: `Comprobación en GitHub: no se pudo sacar token (${e.message}).` }; }
  let pr;
  try { pr = await gh(fetchImpl, 'GET', `/repos/${g.repoLandings}/pulls/${numero}`, token); }
  catch (e) { return { ok: false, informe: `Comprobación en GitHub: el PR #${numero} no existe o no se puede leer (${e.status || e.message}).` }; }
  if (pr.state !== 'open') problemas.push(`el PR está ${pr.state}`);
  if (pr.merged || pr.merged_at) problemas.push('el PR ya está fusionado (nadie más que Al o Bonzo publica)');
  if (pr.base?.ref !== 'main') problemas.push(`va a ${pr.base?.ref}, no a main`);
  if (!String(pr.head?.ref || '').startsWith('agente/')) problemas.push(`la rama ${pr.head?.ref} no empieza con agente/`);
  if (r.commit && pr.head?.sha !== r.commit) problemas.push(`el commit del PR (${pr.head?.sha?.slice(0, 7)}) no es el reportado (${String(r.commit).slice(0, 7)})`);
  let archivos = [];
  try { archivos = await gh(fetchImpl, 'GET', `/repos/${g.repoLandings}/pulls/${numero}/files?per_page=100`, token); }
  catch (e) { problemas.push(`no se pudieron leer los archivos del PR (${e.status || e.message})`); }
  const fuera = archivos.map(f => f.filename).filter(n => !n.startsWith(`landings/${slug}/`));
  if (fuera.length) problemas.push(`cambia archivos fuera de landings/${slug}/: ${fuera.slice(0, 5).join(', ')}`);
  if (!archivos.length) problemas.push('el PR no cambia ningún archivo');
  if (mainAntes) {
    try {
      const ahora = await shaDeMain(token, g.repoLandings, fetchImpl);
      if (ahora !== mainAntes) problemas.push(`main cambió durante la sesión (${mainAntes.slice(0, 7)} → ${String(ahora).slice(0, 7)}): revisar quién publicó`);
    } catch (e) { problemas.push(`no se pudo leer main (${e.status || e.message})`); }
  }
  const informe = `Comprobación en GitHub: PR #${numero} (${pr.html_url || ''}), ${archivos.length} archivo(s) en landings/${slug}/.` +
    (problemas.length ? ` Problemas: ${problemas.join('; ')}.` : ' Abierto, sin fusionar y solo con su carpeta. Falta revisar el deploy preview y aprobarlo en GitHub.');
  return { ok: problemas.length === 0, informe };
}
