// Ruteo por cliente (RUTEO_CLIENTES=1) con dos clientes falsos, A y B. Todo con mocks: Notion, Anthropic, GitHub,
// Meta y HighLevel. Ninguna llamada real. Los 11 casos del encargo van numerados en el nombre de cada prueba.
import test from 'node:test';
import assert from 'node:assert/strict';
import { generateKeyPairSync } from 'node:crypto';
import { cfg } from '../lib/config.mjs';
import { despacha } from '../lib/despacho.mjs';
import { cierraSesion } from '../lib/cierre.mjs';
import { barre } from '../lib/barrido.mjs';
import { compruebaPR, tokenLectura } from '../lib/github.mjs';
import { cfgCliente, leeCliente } from '../lib/clientes.mjs';

const AL = 'user-al';
const DS_CLIENTES = '33723502-0b79-45e1-ac42-b123a22fff80';
const { privateKey: PEM } = generateKeyPairSync('rsa', { modulusLength: 2048,
  privateKeyEncoding: { type: 'pkcs8', format: 'pem' }, publicKeyEncoding: { type: 'spki', format: 'pem' } });

// Globales con valores reconocibles: con el ruteo encendido ninguno debe llegar a una sesión de cliente.
const GLOBALES = ['v_comun', 'v_global_', '9999999', 'locGLOBAL', '5cero5-marca', '5cero5-landings', '5cero5-piezas', 'marketing.5cero5.com', 'vcrd_global'];
const c = cfg({
  RUTEO_CLIENTES: '1', NOTION_APROBADORES: AL, MA_ENVIRONMENT_ID: 'env_1',
  MA_AGENT_PAUTA: 'agent_pauta', MA_AGENT_CREATIVO: 'agent_creativo', MA_AGENT_LANDING: 'agent_landing', MA_AGENT_CRM: 'agent_crm', MA_AGENT_CMO: 'agent_cmo',
  GH_AGENTES_URL: 'https://github.com/5cero5/5cero5-agentes', GH_AGENTES_READ_TOKEN: 'tok_agentes',
  GH_APP_ID: '123', GH_APP_INSTALLATION_ID: '456', GH_APP_PRIVATE_KEY: PEM,
  META_TOKEN: 'EAA_global', HL_TOKEN_CLIENTE_A: 'pit-a', HL_TOKEN_CLIENTE_B: 'pit-b',
  // globales del ruteo apagado
  GH_REPO_URL: 'https://github.com/5cero5/5cero5-marca', GH_REPO_READ_TOKEN: 'tok_pat', MA_VAULT_IDS: 'v_comun',
  MA_VAULT_PAUTA: 'v_global_pauta', MA_VAULT_CRM: 'v_global_crm', MA_VAULT_LANDING: 'v_global_landing', MA_VAULT_CREATIVO: 'v_global_creativo',
  MA_CRED_GITHUB_LANDING: 'vcrd_global_l', MA_CRED_GITHUB_CREATIVO: 'vcrd_global_c',
  META_AD_ACCOUNT_ID: '9999999', META_PAGE_ID: '9999998', HL_LOCATION_ID: 'locGLOBAL',
});

const CLIENTES = {
  a: { id: 'cli-a', nombre: 'Cliente A', slug: 'cliente-a', estado: 'Activo', ruta: 'Cita', loc: 'locA000001',
    marca: 'cliente-a/marca-a', landings: 'cliente-a/landings-a', piezas: 'cliente-a/piezas-a', sitio: 'https://landings.cliente-a.mx',
    cuenta: '1111111', pagina: '2111111', tope: 3, topePauta: 800, max: null,
    vaults: { Pauta: 'vlt_a_pauta', Creativo: 'vlt_a_creativo', Landing: 'vlt_a_landing', CRM: 'vlt_a_crm', CMO: 'vlt_a_cmo' },
    creds: { Landing: 'vcrd_a_landing', Creativo: 'vcrd_a_creativo' } },
  b: { id: 'cli-b', nombre: 'Cliente B', slug: 'cliente-b', estado: 'Activo', ruta: 'Pedido', loc: 'locB000002',
    marca: 'cliente-b/marca-b', landings: 'cliente-b/landings-b', piezas: 'cliente-b/piezas-b', sitio: 'https://landings.cliente-b.mx',
    cuenta: '2222222', pagina: '3222222', tope: null, topePauta: null, max: null,
    vaults: { Pauta: 'vlt_b_pauta', Creativo: 'vlt_b_creativo', Landing: 'vlt_b_landing', CRM: 'vlt_b_crm', CMO: 'vlt_b_cmo' },
    creds: { Landing: 'vcrd_b_landing', Creativo: 'vcrd_b_creativo' } },
};
// Lo que identifica a cada cliente: si aparece en una sesión del otro, hay cruce.
const HUELLA = { a: ['cliente-a', 'marca-a', 'landings-a', 'piezas-a', '1111111', '2111111', 'locA000001', 'vlt_a_', 'vcrd_a_'],
  b: ['cliente-b', 'marca-b', 'landings-b', 'piezas-b', '2222222', '3222222', 'locB000002', 'vlt_b_', 'vcrd_b_'] };
const otro = k => (k === 'a' ? 'b' : 'a');

const txt = s => ({ rich_text: s ? [{ plain_text: s }] : [] });
function pageCliente(k, o = {}) {
  const x = { ...CLIENTES[k], ...o };
  return { id: x.id, parent: { type: 'data_source_id', data_source_id: o.dataSource || DS_CLIENTES }, properties: {
    Cliente: { title: [{ plain_text: x.nombre }] }, Slug: txt(x.slug), Estado: { select: x.estado ? { name: x.estado } : null },
    Ruta: { select: x.ruta ? { name: x.ruta } : null }, 'HighLevel Location ID': txt(x.loc),
    'Repo de marca': txt(x.marca), 'Repo de landings': txt(x.landings), 'Repo de piezas': txt(x.piezas), 'Sitio de landings': { url: x.sitio || null },
    'Meta cuenta': txt(x.cuenta), 'Meta página': txt(x.pagina), 'Meta Instagram': txt(''), 'Meta Pixel': txt(''),
    ...Object.fromEntries(Object.entries(x.vaults).map(([a, v]) => [`Vault ${a}`, txt(v)])),
    'Credencial GitHub Landing': txt(x.creds.Landing), 'Credencial GitHub Creativo': txt(x.creds.Creativo),
    'Tope de sesión (USD)': { number: x.tope }, 'Tope diario de pauta (MXN)': { number: x.topePauta }, 'Máx. sesiones por día': { number: x.max } } };
}
const pageCampana = (id, fichas) => ({ id, properties: { 'Ficha de cliente': { relation: fichas.map(f => ({ id: f })) } } });

let nFila = 0;
const fila = (agente, campanas, o = {}) => ({ id: `fila-${++nFila}`, editadoPor: { id: AL }, trabajo: `${agente} ${nFila}`, agente, estado: 'Aprobado',
  brief: 'haz la pieza', campana: 'Promo', sesion: '', intentos: 0, tope: null, aprobo: [AL], inicio: null, campanaLigada: campanas, ...o });
function pageFila(f) {
  return { id: f.id, last_edited_by: f.editadoPor, properties: {
    Trabajo: { title: [{ plain_text: f.trabajo }] }, Agente: { select: { name: f.agente } }, Estado: { select: { name: f.estado } },
    Brief: txt(f.brief), Campaña: txt(f.campana), Sesión: txt(f.sesion), Intentos: { number: f.intentos },
    'Tope de la sesión (USD)': { number: f.tope }, Aprobó: { people: f.aprobo.map(id => ({ id })) },
    Inició: { date: f.inicio ? { start: f.inicio } : null }, 'Campaña ligada': { relation: f.campanaLigada.map(id => ({ id })) } } };
}

// Notion falso: filas de Aprobaciones, campañas y fichas. Registra cada update.
function mockNotion({ filas, paginas }) {
  const log = [];
  return { log, filas,
    query: async (ds, filter) => {
      if (ds === c.notionCampanas) return { results: [] };
      if (filter.property === 'Inició') return { results: [] };
      if (filter.and) return { results: [{ properties: { Estado: { select: { name: 'Listo' } } } }] }; // piezas del Creativo en Listo
      if (filter.property === 'Estado') return { results: filas.filter(f => f.estado === filter.select.equals).map(pageFila) };
      if (filter.property === 'Sesión') return { results: filas.filter(f => f.sesion === filter.rich_text.equals).map(pageFila) };
      return { results: [] };
    },
    get: async id => { const f = filas.find(x => x.id === id); if (f) return pageFila(f); if (paginas[id]) return paginas[id]; throw new Error(`Notion 404 ${id}`); },
    update: async (id, props) => {
      log.push([id, props]); const f = filas.find(x => x.id === id);
      if (props.Estado) f.estado = props.Estado.select.name;
      if (props.Intentos) f.intentos = props.Intentos.number;
      if (props.Sesión) f.sesion = props.Sesión.rich_text[0].text.content;
      if (props.Error) f.error = props.Error.rich_text[0]?.text.content || '';
      if (props.Inició) f.inicio = props.Inició.date.start;
      if (props.Verificador) f.verificador = props.Verificador.select.name;
      if (props['Informe del Verificador']) f.informe = props['Informe del Verificador'].rich_text[0].text.content;
    } };
}
const paginasBase = (o = {}) => ({
  'camp-a': pageCampana('camp-a', ['cli-a']), 'camp-b': pageCampana('camp-b', ['cli-b']),
  'cli-a': pageCliente('a'), 'cli-b': pageCliente('b'), ...o });

// Anthropic falso: sesiones, vaults con su metadata y credenciales.
function mockClient({ msgs = {} } = {}) {
  const st = { creadas: [], credenciales: [], vaultsLeidos: [], sesiones: {} };
  const vaults = {};
  for (const k of ['a', 'b']) for (const [ag, v] of Object.entries(CLIENTES[k].vaults)) vaults[v] = { id: v, metadata: { cliente: CLIENTES[k].slug, rol: ag.toLowerCase() } };
  st.beta = {
    sessions: {
      create: async p => { const id = `sesn_${st.creadas.length + 1}`; st.creadas.push(p); st.sesiones[id] = { status: 'idle', metadata: p.metadata, vault_ids: p.vault_ids }; return { id }; },
      retrieve: async id => ({ ...st.sesiones[id], usage: { input_tokens: 1 } }),
      events: { list: async function* (id) { yield { type: 'agent.message', content: [{ text: msgs[id] || '{}' }] }; }, send: async () => {} },
    },
    vaults: {
      retrieve: async id => { st.vaultsLeidos.push(id); if (!vaults[id]) { const e = new Error('not found'); e.status = 404; throw e; } return vaults[id]; },
      credentials: { update: async (id, prm) => st.credenciales.push([id, prm]) },
    },
  };
  return st;
}

// GitHub + Meta + HighLevel falsos, enrutados por host. Un token de instalación solo ve el repo para el que se pidió.
function mockApis() {
  const st = { tokens: [], porToken: {}, llamadas: [], prs: {} };
  const ok = x => ({ ok: true, status: 200, text: async () => JSON.stringify(x) });
  const no = (s, m = 'Not Found') => ({ ok: false, status: s, text: async () => JSON.stringify({ message: m }) });
  st.fetch = async (url, init = {}) => {
    const u = new URL(url); const auth = init.headers?.Authorization || '';
    st.llamadas.push(`${init.method || 'GET'} ${u.host}${u.pathname}${u.search}`);
    if (u.host === 'api.github.com') {
      if (u.pathname === '/app/installations/456/access_tokens') {
        const body = JSON.parse(init.body); const t = `ghs_${body.repositories.join('+')}_${st.tokens.length + 1}`;
        st.tokens.push(body); st.porToken[`Bearer ${t}`] = body.repositories; return ok({ token: t, expires_at: '2026-10-28T05:00:00Z' });
      }
      const m = u.pathname.match(/^\/repos\/([^/]+)\/([^/]+)(\/.*)$/);
      if (!m || !(st.porToken[auth] || []).includes(m[2])) return no(404); // el token no ve ese repo
      const repo = `${m[1]}/${m[2]}`, resto = m[3];
      if (resto === '/git/ref/heads/main') return ok({ object: { sha: 'm1' } });
      const pr = resto.match(/^\/pulls\/(\d+)(\/files)?$/);
      if (pr && st.prs[`${repo}#${pr[1]}`]) return ok(pr[2] ? st.prs[`${repo}#${pr[1]}`].files : st.prs[`${repo}#${pr[1]}`].pr);
      return no(404);
    }
    if (u.host === 'services.leadconnectorhq.com') {
      const loc = u.searchParams.get('locationId');
      const propia = { 'Bearer pit-a': 'locA000001', 'Bearer pit-b': 'locB000002' }[auth];
      if (propia !== loc) return no(403, 'forbidden');
      return ok({ builders: [{ id: `t_${loc}`, name: '[agente] W1' }] });
    }
    return no(400, 'host no esperado');
  };
  st.pr = (repo, n, slug) => {
    st.prs[`${repo}#${n}`] = { pr: { state: 'open', merged: false, base: { ref: 'main' }, head: { ref: `agente/${slug}-1`, sha: 'abc1234' }, html_url: `https://github.com/${repo}/pull/${n}` },
      files: [{ filename: `landings/${slug}/index.html` }] };
  };
  return st;
}

const texto = x => JSON.stringify(x);
// Todo lo que el harness mandó para una sesión: parámetros de la sesión.
function sinCruce(params, k) {
  const s = texto(params);
  for (const h of HUELLA[otro(k)]) assert.ok(!s.includes(h), `la sesión de ${k} trae ${h} (del otro cliente)`);
  for (const g of GLOBALES) assert.ok(!s.includes(g), `la sesión de ${k} trae el global ${g}`);
}

// ---- Casos 1 y 2: cada fila recibe solo lo de su cliente ----
for (const k of ['a', 'b']) {
  const n = k === 'a' ? 1 : 2;
  test(`caso ${n}: fila de ${k.toUpperCase()} → la sesión trae solo vault, repos, Location ID e ids de Meta de ${k.toUpperCase()}`, async () => {
    const x = CLIENTES[k], camp = `camp-${k}`;
    const filas = ['Pauta', 'Creativo', 'Landing', 'CRM'].map(a => fila(a, [camp]));
    const notion = mockNotion({ filas, paginas: paginasBase() }); const cl = mockClient(); const api = mockApis();
    const r = await despacha({ client: cl, notion, c, fetchImpl: api.fetch });
    assert.equal(r.creadas.length, 4, texto(r.omitidas));
    for (const p of cl.creadas) {
      sinCruce(p, k);
      assert.equal(p.metadata.cliente_slug, x.slug);
      assert.deepEqual(p.vault_ids, [x.vaults[p.metadata.agente]]);
      const m = p.initial_events[0].content[0].text;
      for (const res of p.resources) if (res.mount_path !== '/workspace/agentes') assert.match(res.url, new RegExp(`github\\.com/${x.slug}/`));
      if (p.metadata.agente === 'Pauta') { assert.match(m, new RegExp(`--cuenta act_${x.cuenta} --pagina ${x.pagina}`)); assert.match(m, new RegExp(`--dominios landings\\.${x.slug}\\.mx`)); }
      if (p.metadata.agente === 'CRM') assert.match(m, new RegExp(`--location ${x.loc}`));
      if (p.metadata.agente === 'Landing') assert.match(m, new RegExp(`--repo ${x.landings}`));
      if (p.metadata.agente === 'Creativo') assert.match(m, new RegExp(`--repo ${x.piezas}`));
    }
    // Tokens de GitHub: todos limitados a un repo del cliente; credenciales: solo las de su vault.
    assert.ok(api.tokens.length > 0 && api.tokens.every(t => t.repositories.length === 1 && t.repositories[0].endsWith(`-${k}`)), texto(api.tokens));
    assert.deepEqual(cl.credenciales.map(([id, prm]) => [id, prm.vault_id]).sort(), [[x.creds.Creativo, x.vaults.Creativo], [x.creds.Landing, x.vaults.Landing]].sort());
    assert.ok(cl.vaultsLeidos.every(v => v.startsWith(`vlt_${k}_`)));
    // Topes de la ficha: A trae tope de sesión 3 USD y pauta 800 MXN; B usa los globales (2 USD, 1500 MXN).
    const pauta = cl.creadas.find(p => p.metadata.agente === 'Pauta');
    assert.equal(pauta.budget.max_list_cost.amount, k === 'a' ? '300' : '200');
    assert.match(pauta.initial_events[0].content[0].text, new RegExp(`--tope-mxn ${k === 'a' ? 800 : 1500}`));
  });
}

// ---- Casos 3 a 6: fallar cerrado ----
async function despachaUna(f, paginas = paginasBase()) {
  const notion = mockNotion({ filas: [f], paginas }); const cl = mockClient(); const api = mockApis();
  await despacha({ client: cl, notion, c, fetchImpl: api.fetch });
  return { f, cl, api, notion };
}
test('caso 3: fila sin Campaña ligada → no se despacha, Error "sin cliente"', async () => {
  const { f, cl } = await despachaUna(fila('Landing', []));
  assert.equal(cl.creadas.length, 0); assert.equal(f.estado, 'Error'); assert.match(f.error, /^sin cliente/);
  // y con dos campañas ligadas tampoco
  const dos = await despachaUna(fila('Landing', ['camp-a', 'camp-b']));
  assert.equal(dos.cl.creadas.length, 0); assert.match(dos.f.error, /^sin cliente/);
});
test('caso 4: campaña sin cliente (o con dos) → no se despacha', async () => {
  const sin = await despachaUna(fila('CRM', ['camp-x']), paginasBase({ 'camp-x': pageCampana('camp-x', []) }));
  assert.equal(sin.cl.creadas.length, 0); assert.equal(sin.f.estado, 'Error'); assert.match(sin.f.error, /^sin cliente: la campaña no tiene Ficha/);
  const dos = await despachaUna(fila('CRM', ['camp-x']), paginasBase({ 'camp-x': pageCampana('camp-x', ['cli-a', 'cli-b']) }));
  assert.equal(dos.cl.creadas.length, 0); assert.match(dos.f.error, /^sin cliente/);
  const ajena = await despachaUna(fila('CRM', ['camp-a']), paginasBase({ 'cli-a': pageCliente('a', { dataSource: 'otra-base' }) }));
  assert.equal(ajena.cl.creadas.length, 0); assert.match(ajena.f.error, /no es de la base Clientes/);
});
test('caso 5: cliente en Pausa o Baja → no se despacha', async () => {
  for (const estado of ['Pausa', 'Baja']) {
    const { f, cl, api } = await despachaUna(fila('Landing', ['camp-a']), paginasBase({ 'cli-a': pageCliente('a', { estado }) }));
    assert.equal(cl.creadas.length, 0); assert.equal(f.estado, 'Error'); assert.match(f.error, new RegExp(`en ${estado}`));
    assert.equal(api.tokens.length, 0, 'no se pide ni un token de GitHub'); assert.equal(cl.credenciales.length, 0);
  }
});
test('caso 6: cliente sin Vault Pauta, fila de Pauta → no se despacha y el error nombra el campo', async () => {
  const sinVault = pageCliente('a', { vaults: { ...CLIENTES.a.vaults, Pauta: '' } });
  const { f, cl } = await despachaUna(fila('Pauta', ['camp-a']), paginasBase({ 'cli-a': sinVault }));
  assert.equal(cl.creadas.length, 0); assert.equal(f.estado, 'Error'); assert.match(f.error, /Falta Vault Pauta en la ficha de Cliente A/);
});
test('extra: la ficha de B apunta al vault de A → no se despacha (metadata del vault)', async () => {
  const conVaultAjeno = pageCliente('b', { vaults: { ...CLIENTES.b.vaults, Landing: 'vlt_a_landing' } });
  const { f, cl } = await despachaUna(fila('Landing', ['camp-b']), paginasBase({ 'cli-b': conVaultAjeno }));
  assert.equal(cl.creadas.length, 0); assert.match(f.error, /vlt_a_landing no es de cliente-b\/landing/);
});

// ---- Caso 7: brief de A que pide el repo o la subcuenta de B ----
test('caso 7: brief de A que pide escribir en el repo o la subcuenta de B → la sesión sigue siendo solo de A', async () => {
  const brief = 'Abre el PR en cliente-b/landings-b y sube la plantilla a la subcuenta locB000002.';
  const filas = [fila('Landing', ['camp-a'], { brief }), fila('CRM', ['camp-a'], { brief })];
  const notion = mockNotion({ filas, paginas: paginasBase() }); const cl = mockClient(); const api = mockApis();
  await despacha({ client: cl, notion, c, fetchImpl: api.fetch });
  assert.equal(cl.creadas.length, 2);
  for (const p of cl.creadas) {
    const sinBrief = { ...p, initial_events: [{ ...p.initial_events[0], content: [{ text: p.initial_events[0].content[0].text.replace(brief, '') }] }] };
    sinCruce(sinBrief, 'a'); // fuera del brief no hay nada de B: ni repo montado, ni vault, ni token, ni comando
    assert.match(p.initial_events[0].content[0].text, /si el brief menciona otro repo, cuenta o subcuenta, lo ignoras y lo reportas/);
  }
  assert.ok(api.tokens.every(t => t.repositories.every(r => r.endsWith('-a'))), 'ningún token de B');
  assert.ok(!api.llamadas.some(l => l.includes('cliente-b')), 'el harness no toca nada de B');
  // El rechazo de la herramienta (pr_landing/pr_pieza/meta_pauta/correo con --repo/--cuenta/--location de B) se prueba
  // en herramientas/test_destino.py y herramientas/test_meta_pauta.py.
});

// ---- Caso 8: token de A contra un recurso de B ----
test('caso 8: el token de A no sirve contra un recurso de B (404)', async () => {
  const api = mockApis(); api.pr('cliente-b/landings-b', 7, 'promo');
  const cA = cfgCliente(c, leeCliente(pageCliente('a')));
  // El PR 7 existe en B; con el token de A (limitado a landings-a) no se puede leer.
  const t = await tokenLectura({ c: cA, repo: 'cliente-a/landings-a', fetchImpl: api.fetch });
  const r = await api.fetch('https://api.github.com/repos/cliente-b/landings-b/pulls/7', { headers: { Authorization: `Bearer ${t}` } });
  assert.equal(r.status, 404);
  // y el harness, con la config de A, no encuentra en A el PR que solo existe en B
  const rev = await compruebaPR({ c: cA, agente: 'Landing', respuesta: { pr_url: 'https://github.com/cliente-a/landings-a/pull/7', pr_numero: 7, slug: 'promo', rama: 'agente/promo-1', commit: 'abc1234' }, fetchImpl: api.fetch });
  assert.equal(rev.ok, false); assert.match(rev.informe, /no existe o no se puede leer \(404\)/);
});

// ---- Caso 9: resultado fuera de lo del cliente ----
test('caso 9: PR en el repo de B para una fila de A → Verificador = Rechazada', async () => {
  const f = fila('Landing', ['camp-a']);
  const notion = mockNotion({ filas: [f], paginas: paginasBase() }); const api = mockApis();
  const cl = mockClient();
  await despacha({ client: cl, notion, c, fetchImpl: api.fetch });
  api.pr('cliente-b/landings-b', 7, 'promo');
  cl.beta.sessions.events.list = async function* () {
    yield { type: 'agent.message', content: [{ text: '{"pr_url":"https://github.com/cliente-b/landings-b/pull/7","pr_numero":7,"rama":"agente/promo-1","commit":"abc1234","slug":"promo"}' }] };
  };
  assert.equal(await cierraSesion({ client: cl, notion, c, sessionId: f.sesion, fetchImpl: api.fetch }), 'para_revisar');
  assert.equal(f.verificador, 'Rechazada'); assert.equal(f.estado, 'Para revisar');
  assert.match(f.informe, /no es de cliente-a\/landings-a/);
});
test('caso 9 (Meta): campaña en la cuenta de B para una fila de Pauta de A → Rechazada', async () => {
  const { compruebaCampana } = await import('../lib/meta.mjs');
  const cA = cfgCliente(c, leeCliente(pageCliente('a')));
  const fetchMeta = async (url) => {
    const p = new URL(url).pathname.replace('/v25.0', '');
    const ok = x => ({ ok: true, status: 200, text: async () => JSON.stringify(x) });
    if (p === '/900') return ok({ id: '900', name: '2026-10_mty_promo', status: 'PAUSED', objective: 'OUTCOME_TRAFFIC', account_id: '2222222' });
    if (p === '/900/adsets') return ok({ data: [{ id: '901', status: 'PAUSED', daily_budget: '50000' }] });
    if (p === '/900/ads') return ok({ data: [{ id: '902', status: 'PAUSED', creative: { url_tags: 'utm_source=meta', object_story_spec: { page_id: '3222222', link_data: { link: 'https://landings.cliente-b.mx/x/' } } } }] });
    return ok({ spend_cap: '1' });
  };
  const rev = await compruebaCampana({ c: cA, respuesta: { campana_meta_id: '900', nombre: '2026-10_mty_promo', conjunto_id: '901', anuncios: [{ id: '902' }] }, fetchImpl: fetchMeta });
  assert.equal(rev.ok, false);
  assert.match(rev.informe, /cuenta act_2222222, no de act_1111111/);
  assert.match(rev.informe, /no usa la página 2111111/); assert.match(rev.informe, /fuera de landings\.cliente-a\.mx/);
});

// ---- Caso 10: dos clientes en el mismo ciclo ----
test('caso 10: filas de A y de B en el mismo ciclo → sesiones independientes, sin estado compartido', async () => {
  const antes = texto(c);
  const filas = [fila('Landing', ['camp-a']), fila('Landing', ['camp-b']), fila('CRM', ['camp-b']), fila('CRM', ['camp-a'])];
  const notion = mockNotion({ filas, paginas: paginasBase() }); const cl = mockClient(); const api = mockApis();
  const r = await despacha({ client: cl, notion, c, fetchImpl: api.fetch });
  assert.equal(r.creadas.length, 4);
  for (const p of cl.creadas) sinCruce(p, p.metadata.cliente_slug === 'cliente-a' ? 'a' : 'b');
  assert.deepEqual(cl.creadas.map(p => p.metadata.cliente_slug), ['cliente-a', 'cliente-b', 'cliente-b', 'cliente-a']);
  assert.deepEqual(cl.creadas.map(p => p.vault_ids[0]), ['vlt_a_landing', 'vlt_b_landing', 'vlt_b_crm', 'vlt_a_crm']);
  assert.equal(texto(c), antes, 'la configuración global no cambió');
  // credencial de GitHub de cada uno en su propio vault
  assert.deepEqual(cl.credenciales.map(([id, p]) => `${id}@${p.vault_id}`), ['vcrd_a_landing@vlt_a_landing', 'vcrd_b_landing@vlt_b_landing']);
});
test('caso 10 (cupo): el máximo de sesiones por día de un cliente no frena al otro', async () => {
  const filas = [fila('CRM', ['camp-a']), fila('CRM', ['camp-a']), fila('CRM', ['camp-b'])];
  const notion = mockNotion({ filas, paginas: paginasBase({ 'cli-a': pageCliente('a', { max: 1 }) }) }); const cl = mockClient();
  const r = await despacha({ client: cl, notion, c, fetchImpl: mockApis().fetch });
  assert.deepEqual(cl.creadas.map(p => p.metadata.cliente_slug), ['cliente-a', 'cliente-b']);
  assert.deepEqual(r.omitidas.map(([, m]) => m), ['tope_diario_cliente']);
});

// ---- Caso 11: webhook y barrido de una sesión de A ----
test('caso 11: webhook y barrido de una sesión de A escriben solo en la fila de A y comprueban contra lo de A', async () => {
  const fA = fila('Landing', ['camp-a']), fB = fila('Landing', ['camp-b']), cA = fila('CRM', ['camp-a']);
  const notion = mockNotion({ filas: [fA, fB, cA], paginas: paginasBase() }); const api = mockApis(); const cl = mockClient();
  await despacha({ client: cl, notion, c, fetchImpl: api.fetch });
  api.pr('cliente-a/landings-a', 7, 'promo'); api.pr('cliente-b/landings-b', 7, 'promo');
  const msgs = { [fA.sesion]: '{"pr_url":"https://github.com/cliente-a/landings-a/pull/7","pr_numero":7,"rama":"agente/promo-1","commit":"abc1234","slug":"promo"}',
    [cA.sesion]: '{"plantilla_id":"t_locA000001","nombre":"[agente] W1","html_sha1":"ab"}' };
  cl.beta.sessions.events.list = async function* (id) { yield { type: 'agent.message', content: [{ text: msgs[id] || '{}' }] }; };

  // webhook: cierra la sesión de Landing de A
  notion.log.length = 0; api.llamadas.length = 0;
  assert.equal(await cierraSesion({ client: cl, notion, c, sessionId: fA.sesion, fetchImpl: api.fetch }), 'para_revisar');
  assert.deepEqual([...new Set(notion.log.map(([id]) => id))], [fA.id], 'solo escribe en la fila de A');
  assert.equal(fA.verificador, 'Aprobada', fA.informe);
  const gh = api.llamadas.filter(l => l.includes('/repos/'));
  assert.ok(gh.length && gh.every(l => l.includes('/repos/cliente-a/landings-a/')), gh.join('\n'));
  assert.equal(fB.estado, 'En curso');

  // barrido: solo la fila de CRM de A queda En curso además de la de B; se cierra la de A contra su subcuenta
  fB.estado = 'Para revisar';
  notion.log.length = 0; api.llamadas.length = 0;
  await barre({ client: cl, notion, c, fetchImpl: api.fetch });
  assert.deepEqual([...new Set(notion.log.map(([id]) => id))], [cA.id]);
  assert.equal(cA.verificador, 'Aprobada', cA.informe);
  assert.deepEqual(api.llamadas.filter(l => l.includes('leadconnectorhq')).map(l => new URL(`https://${l.split(' ')[1]}`).searchParams.get('locationId')), ['locA000001']);
});
test('caso 11 (cruce): una sesión que dice ser de B o usó el vault de B, cerrada sobre la fila de A → Rechazada', async () => {
  for (const cambio of [{ metadata: { cliente_slug: 'cliente-b' } }, { vault_ids: ['vlt_b_landing'] }]) {
    const f = fila('Landing', ['camp-a']);
    const notion = mockNotion({ filas: [f], paginas: paginasBase() }); const api = mockApis(); const cl = mockClient();
    await despacha({ client: cl, notion, c, fetchImpl: api.fetch });
    api.pr('cliente-a/landings-a', 7, 'promo');
    const s = cl.sesiones[f.sesion];
    Object.assign(s, cambio.vault_ids ? cambio : { metadata: { ...s.metadata, ...cambio.metadata } });
    cl.beta.sessions.events.list = async function* () { yield { type: 'agent.message', content: [{ text: '{"pr_url":"https://github.com/cliente-a/landings-a/pull/7","pr_numero":7,"rama":"agente/promo-1","commit":"abc1234","slug":"promo"}' }] }; };
    await cierraSesion({ client: cl, notion, c, sessionId: f.sesion, fetchImpl: api.fetch });
    assert.equal(f.verificador, 'Rechazada'); assert.match(f.informe, /^Fuera del cliente/);
  }
});
test('caso 11 (CRM sin token): sin HL_TOKEN_<SLUG> la plantilla no se da por buena', async () => {
  const c2 = { ...c, secretoCliente: () => '' };
  const f = fila('CRM', ['camp-a']);
  const notion = mockNotion({ filas: [f], paginas: paginasBase() }); const cl = mockClient({});
  await despacha({ client: cl, notion, c: c2, fetchImpl: mockApis().fetch });
  cl.beta.sessions.events.list = async function* () { yield { type: 'agent.message', content: [{ text: '{"plantilla_id":"t1","nombre":"[agente] W1","html_sha1":"ab"}' }] }; };
  await cierraSesion({ client: cl, notion, c: c2, sessionId: f.sesion, fetchImpl: mockApis().fetch });
  assert.equal(f.verificador, 'Rechazada'); assert.match(f.informe, /falta HL_TOKEN_CLIENTE_A/);
});

// ---- Interruptor ----
test('interruptor: sin RUTEO_CLIENTES no se lee ninguna ficha ni vault (comportamiento de hoy)', async () => {
  const apagado = { ...c, ruteoClientes: false };
  const f = fila('CRM', []);
  const notion = mockNotion({ filas: [f], paginas: {} }); const cl = mockClient();
  await despacha({ client: cl, notion, c: apagado, fetchImpl: mockApis().fetch });
  assert.equal(cl.creadas.length, 1); assert.deepEqual(cl.creadas[0].vault_ids, ['v_global_crm']); assert.equal(cl.vaultsLeidos.length, 0);
  assert.equal(cl.creadas[0].metadata.cliente_slug, undefined);
});
