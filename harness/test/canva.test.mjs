// Canva en el Creativo (lib/canva.mjs): despacho, confirmaciones de always_ask y cierre contra el log de la sesión.
// Todo con mocks de Notion, Anthropic y GitHub; la forma de los resultados de Canva imita read-design/copy-design/export-design
// y se confirma con la primera sesión en vivo.
import test from 'node:test';
import assert from 'node:assert/strict';
import { generateKeyPairSync, createHash } from 'node:crypto';
import { cfg } from '../lib/config.mjs';
import { despacha } from '../lib/despacho.mjs';
import { cierraSesion } from '../lib/cierre.mjs';
import { barre } from '../lib/barrido.mjs';
import { parametrosSesion } from '../lib/sessions.mjs';
import { canvaDelBrief, validaRecursos, preparaCanva, decideConfirmacion, historiaCanva, resuelveConfirmaciones,
  compruebaCanvaSesion, leeMetaCanva, metadataCanva, normalizaUrl, CANVA } from '../lib/canva.mjs';

const { privateKey: PEM } = generateKeyPairSync('rsa', { modulusLength: 2048, privateKeyEncoding: { type: 'pkcs8', format: 'pem' }, publicKeyEncoding: { type: 'spki', format: 'pem' } });
const AL = 'user-al';
const BASE = 'DAGbase0001', DIS = 'DAGpieza001', CARPETA = 'FAFcarpeta1', LOGO = 'MAGlogo5c05', CRED = 'vcrd_canva';
const ENV = { MA_ENVIRONMENT_ID: 'env_1', MA_AGENT_CREATIVO: 'agent_creativo', MA_VAULT_CREATIVO: 'v_creativo',
  GH_REPO_URL: 'https://github.com/5cero5/5cero5-marca', GH_AGENTES_URL: 'https://github.com/5cero5/5cero5-agentes', GH_REPO_READ_TOKEN: 'tok',
  GH_APP_ID: '123', GH_APP_INSTALLATION_ID: '456', GH_APP_PRIVATE_KEY: PEM, MA_CRED_GITHUB_CREATIVO: 'vcrd_cr',
  MA_AGENT_CREATIVO_CANVA: 'agent_canva', MA_ENVIRONMENT_CANVA: 'env_canva' };
const cOn = cfg({ ...ENV, CANVA_ACTIVO: '1' });
const cOff = cfg(ENV);
const FIJO = 'Desde $20,000 al mes + IVA.';
const RECURSOS = { version: 1, habilitado: true, brand_kit_id: 'kAGkit5c05', carpeta_id: CARPETA, logo_asset_id: LOGO, textos_fijos: [],
  formatos: { 'post-4x5': { base: { tipo: 'design', id: BASE }, fijos: [FIJO], textos: { kicker: 'KICKER DE MUESTRA', titular: 'TITULAR DE MUESTRA', subtitulo: 'Subtítulo de muestra', nota: 'Nota de muestra' } } } };
const COPIA = { kicker: 'Una sola mensualidad', titular: ['Seis', 'licencias,', 'no.'], subtitulo: 'Un solo equipo arma tus citas, pedidos y visitas.', nota: 'Pieza de prueba.' };
const PNG = Buffer.concat([Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0, 0, 0, 13]), Buffer.from('IHDR'),
  Buffer.from([0, 0, 4, 56, 0, 0, 5, 70]), Buffer.alloc(40000, 7)]);  // 1080x1350
const sha = b => createHash('sha256').update(b).digest('hex');
const blob = b => createHash('sha1').update(`blob ${b.length}\0`).update(b).digest('hex');

// ---------------------------------------------------------------- mocks
const fila = (o = {}) => ({ id: 'p1', editadoPor: { id: AL }, trabajo: 'Post 4:5 · Canva', agente: 'Creativo', estado: 'Aprobado',
  brief: 'Post del diagnóstico.\nCanva: sí\nFoto: no', campana: 'C1', sesion: '', intentos: 0, tope: null, aprobo: [AL], campanaLigada: ['kc'],
  sensible: false, rondaDe: [], ...o });
function pageDe(f) {
  const rt = v => ({ rich_text: v ? [{ plain_text: v }] : [] });
  return { id: f.id, last_edited_by: f.editadoPor, properties: { Trabajo: { title: [{ plain_text: f.trabajo }] }, Agente: { select: { name: f.agente } },
    Estado: { select: { name: f.estado } }, Brief: rt(f.brief), Campaña: rt(f.campana), Sesión: rt(f.sesion), Intentos: { number: f.intentos },
    'Tope de la sesión (USD)': { number: f.tope }, Aprobó: { people: f.aprobo.map(id => ({ id })) }, Inició: { date: f.inicio ? { start: f.inicio } : null },
    'Campaña ligada': { relation: f.campanaLigada.map(id => ({ id })) }, Sensible: { checkbox: false }, 'Ronda de': { relation: (f.rondaDe || []).map(id => ({ id })) },
    'Resultado del agente': rt(f.resultado) } };
}
const FICHA = { id: 'fc', parent: { type: 'data_source_id', data_source_id: cfg({}).notionClientes }, properties: { Cliente: { title: [{ plain_text: '5cero5' }] },
  Slug: { rich_text: [{ plain_text: '5cero5' }] }, Estado: { select: { name: 'Activo' } }, Aprobadores: { people: [{ id: AL }] }, 'Rondas incluidas': { number: 2 } } };
function mockNotion(filas) {
  const log = [];
  const paginas = { kc: { id: 'kc', properties: { 'Ficha de cliente': { relation: [{ id: 'fc' }] } } }, fc: FICHA };
  return { log,
    query: async (_ds, filter) => {
      if (filter.property === 'Inició') return { results: [] };
      if (filter.property === 'Estado') return { results: filas.filter(f => f.estado === filter.select.equals).map(pageDe) };
      return { results: [] };
    },
    get: async id => paginas[id] ?? pageDe(filas.find(f => f.id === id)),
    update: async (id, props) => { log.push([id, props]); const f = filas.find(x => x.id === id); if (props.Estado) f.estado = props.Estado.select.name;
      if (props.Sesión) f.sesion = props.Sesión.rich_text[0].text.content; } };
}
const b64 = x => ({ content: Buffer.from(typeof x === 'string' ? x : JSON.stringify(x)).toString('base64'), encoding: 'base64' });
// GitHub (marca y piezas) y la descarga de la exportación de Canva.
function red(o = {}) {
  const pref = 'piezas/poc/post-canva';
  const st = { recursos: RECURSOS, exportBytes: PNG, png: PNG, descargas: [],
    meta: { campana: 'poc', pieza: 'post-canva', formato: 'post-4x5', foto: false, fuente: 'canva', canva: { design_id: DIS, base: { tipo: 'design', id: BASE } } },
    canvaJson: { design_id: DIS, base: { tipo: 'design', id: BASE }, edit_url: `https://www.canva.com/design/${DIS}/edit`, elementos: { kicker: 'PB-LB1', titular: 'PB-LB2', subtitulo: 'PB-LB3', nota: 'PB-LB4' },
      export: { tipo: 'png', sha256: sha(PNG) } },
    informe: { aprobada: true, fuente: 'canva', verificador: 'verificar_canva', formato: 'post-4x5', repo_version: '0.13.0', avisos: [] },
    pr: { state: 'open', merged: false, base: { ref: 'main' }, head: { ref: 'agente/poc-post-canva-1', sha: 'abc1234' }, html_url: 'https://github.com/5cero5/5cero5-piezas/pull/8' },
    ...o };
  st.carpeta = st.carpeta || ['pieza.png', 'canva.json', 'copia.json', 'pieza.json', 'informe.json'].map(name => ({ name, type: 'file', sha: name === 'pieza.png' ? blob(st.png) : `s-${name}` }));
  st.informe = { png_blob_sha: blob(st.png), ...st.informe };
  st.fetch = async (url, init = {}) => {
    const u = new URL(url);
    const ok = x => ({ ok: true, status: 200, text: async () => JSON.stringify(x), arrayBuffer: async () => x });
    const R = '/repos/5cero5/5cero5-piezas';
    if (u.hostname === 'export-download.canva.com') { st.descargas.push({ url, redirect: init.redirect }); return { ok: true, status: 200, arrayBuffer: async () => st.exportBytes }; }
    if (u.pathname === '/app/installations/456/access_tokens') return ok({ token: 'ghs_x' });
    if (u.pathname === '/repos/5cero5/5cero5-marca/contents/canva/recursos.json') return st.recursos ? ok(b64(st.recursos)) : { ok: false, status: 404, text: async () => '{}' };
    if (u.pathname === `${R}/git/ref/heads/main`) return ok({ object: { sha: 'm1' } });
    if (u.pathname === `${R}/pulls/8`) return ok(st.pr);
    if (u.pathname === `${R}/pulls/8/files`) return ok(st.carpeta.map(e => ({ filename: `${pref}/${e.name}` })));
    if (u.pathname === `${R}/contents/${pref}`) return ok(st.carpeta);
    if (u.pathname === `${R}/contents/${pref}/pieza.json`) return ok(b64(st.meta));
    if (u.pathname === `${R}/contents/${pref}/informe.json`) return ok(b64(st.informe));
    if (u.pathname === `${R}/contents/${pref}/canva.json`) return ok(b64(st.canvaJson));
    if (u.pathname === `${R}/contents/${pref}/copia.json`) return ok(b64(COPIA));
    if (u.pathname === `${R}/git/blobs/${blob(st.png)}`) return ok({ content: st.png.toString('base64'), encoding: 'base64' });
    return { ok: false, status: 404, text: async () => '{"message":"Not Found"}' };
  };
  return st;
}
const AGENTE_CANVA = { id: 'agent_canva', mcp_servers: [CANVA.servidor], tools: [{ type: 'agent_toolset_20260401' }, { type: 'mcp_toolset', mcp_server_name: 'canva',
  default_config: { enabled: false, permission_policy: { type: 'always_ask' } },
  configs: [...CANVA.herramientas.lectura.map(name => ({ name, enabled: true, permission_policy: { type: 'always_allow' } })),
    ...CANVA.herramientas.con_permiso.map(name => ({ name, enabled: true, permission_policy: { type: 'always_ask' } }))] }] };
const RESP = { pr_url: 'https://github.com/5cero5/5cero5-piezas/pull/8', pr_numero: 8, rama: 'agente/poc-post-canva-1', commit: 'abc1234',
  campana: 'poc', pieza: 'post-canva', formato: 'post-4x5', foto: false };
// Log de una sesión de Canva que hizo todo bien: copia de la base, transacción, edición, commit, relectura, export y carpeta.
const txt = x => [{ type: 'text', text: typeof x === 'string' ? x : JSON.stringify(x) }];
const uso = (id, name, input, permiso = 'ask') => ({ type: 'agent.mcp_tool_use', id, name, mcp_server_name: 'canva', input, evaluated_permission: permiso });
const res = (id, x, error = false) => ({ type: 'agent.mcp_tool_result', id: `r${id}`, mcp_tool_use_id: id, content: txt(x), is_error: error });
const conf = (id, r = 'allow') => ({ type: 'user.tool_confirmation', id: `c${id}`, tool_use_id: id, result: r });
// Relectura con la forma que imita read-design: elementos con locator_id, tipo y texto; el logo como imagen con asset_id.
const lecturaCon = (t = {}, { logo = LOGO, fijo = FIJO, extra = [], titulo = 'Post Canva' } = {}) => ({ design_metadata: { title: titulo },
  design_content: { pages: [{ page_id: 'PB', elements: [
    { locator_id: 'PB-LB1', type: 'text', text: t.kicker ?? COPIA.kicker }, { locator_id: 'PB-LB2', type: 'text', text: t.titular ?? COPIA.titular.join('\n') },
    { locator_id: 'PB-LB3', type: 'text', text: t.subtitulo ?? COPIA.subtitulo }, { locator_id: 'PB-LB4', type: 'text', text: t.nota ?? COPIA.nota },
    { locator_id: 'PB-LB6', type: 'text', text: fijo },
    ...extra.map((x, i) => ({ locator_id: `PB-LB9${i}`, type: 'text', text: x })),
    ...(logo ? [{ locator_id: 'PB-LB5', type: 'image', asset_id: logo }] : [])] }] } });
const LECTURA = lecturaCon();
const MUESTRA = RECURSOS.formatos['post-4x5'].textos;
const BASE_LEIDA = lecturaCon({ kicker: MUESTRA.kicker, titular: MUESTRA.titular, subtitulo: MUESTRA.subtitulo, nota: MUESTRA.nota });
const conLectura = l => logBueno().map(e => (e.id === 'rs6' ? res('s6', l) : e));
function logBueno() {
  return [
    uso('s1', 'list-brand-kits', {}, 'allow'), res('s1', { items: [{ brand_kit_id: 'kAGkit5c05', name: '5cero5' }] }),
    uso('s2', 'copy-design', { design_id: BASE }), conf('s2'), res('s2', { design: { id: DIS, urls: { edit_url: `https://www.canva.com/design/${DIS}/edit` } } }),
    uso('s3', 'read-design', { design_id: DIS, open_transaction: true }, 'allow'), res('s3', { transaction_id: 'tx1', ...BASE_LEIDA }),
    uso('s4', 'edit-design', { transaction_id: 'tx1', page_index: 1, finalize: 'keep_open', operations: [{ type: 'replace_text', locator_id: 'PB-LB1', text: COPIA.kicker }] }), conf('s4'), res('s4', { ok: true }),
    uso('s5', 'edit-design', { transaction_id: 'tx1', finalize: 'commit' }), conf('s5'), res('s5', { saved: true }),
    uso('s6', 'read-design', { design_id: DIS }, 'allow'), res('s6', LECTURA),
    uso('s7', 'export-design', { design_id: DIS, format: { type: 'png', width: 1080, height: 1350 } }), conf('s7'),
    res('s7', { urls: ['https://export-download.canva.com/abc/pieza.png?firma=1'] }),
    uso('s8', 'move-item-to-folder', { item_id: DIS, to_folder_id: CARPETA }), conf('s8'), res('s8', { ok: true }),
    { type: 'agent.message', id: 'm1', content: [{ type: 'text', text: '```json\n' + JSON.stringify(RESP) + '\n```' }] },
    { type: 'session.status_idle', id: 'i1', stop_reason: { type: 'end_turn' } },
  ];
}
const META = { v: 1, b: { 'post-4x5': ['design', BASE] }, f: CARPETA, l: LOGO, cr: CRED };
function cliente({ eventos = logBueno(), metadata = { notion_page_id: 'p1', main_sha: 'm1', cliente_slug: '5cero5', canva: JSON.stringify(META) },
  vaultMeta = { cliente: '5cero5', rol: 'creativo' }, creds = [{ id: CRED, auth: { type: 'mcp_oauth', mcp_server_url: 'https://mcp.canva.com/mcp/' }, metadata: { cliente: '5cero5', rol: 'canva' } }],
  agente = AGENTE_CANVA, entorno = { networking: { type: 'limited', allowed_hosts: [...CANVA.hosts_red].reverse(), allow_mcp_servers: true, allow_package_managers: true } } } = {}) {
  const calls = { create: [], send: [], upd: [] };
  return { calls, beta: {
    agents: { retrieve: async id => ({ ...agente, id }) },
    environments: { retrieve: async id => ({ id, archived_at: null, config: { type: 'cloud', ...entorno } }) },
    vaults: { retrieve: async id => ({ id, metadata: vaultMeta, archived_at: null }),
      credentials: { list: async function* () { yield* creds; }, update: async (id, p) => calls.upd.push([id, p]) } },
    sessions: { create: async p => { calls.create.push(p); return { id: 'sesn_1' }; },
      retrieve: async () => ({ status: 'idle', metadata, usage: {} }),
      events: { list: async function* () { yield* eventos; }, send: async (id, e) => calls.send.push([id, e]) } } } };
}

// ---------------------------------------------------------------- pruebas
test('canva: "Canva: sí" en su línea del brief; otras menciones no cuentan', () => {
  assert.ok(canvaDelBrief('Post.\nCanva: sí\n'));
  assert.ok(canvaDelBrief('- canva: si.'));
  assert.ok(!canvaDelBrief('Post para Canva y redes'));
  assert.ok(!canvaDelBrief('Canva: no'));
});

test('canva: recursos.json solo vale habilitado, con base válida, carpeta y logo', () => {
  assert.deepEqual(validaRecursos(RECURSOS).bases, { 'post-4x5': ['design', BASE] });
  assert.throws(() => validaRecursos({ ...RECURSOS, habilitado: false }), /no está habilitado/);
  assert.throws(() => validaRecursos({ ...RECURSOS, carpeta_id: '' }), /carpeta_id/);
  assert.equal(validaRecursos({ ...RECURSOS, logo_asset_id: '' }).logo, '');  // opcional: queda el cotejo de píxeles del pie
  assert.throws(() => validaRecursos({ ...RECURSOS, logo_asset_id: 'no válido!' }), /logo_asset_id inválido/);
  assert.throws(() => validaRecursos({ ...RECURSOS, formatos: { 'post-4x5': { base: { tipo: 'design', id: 'no-es-id' } } } }), /base inválida/);
  assert.throws(() => validaRecursos({ ...RECURSOS, formatos: {} }), /ninguna base/);
});

test('canva: la URL de la credencial se compara normalizada, como el vault', () => {
  assert.equal(normalizaUrl('HTTPS://MCP.Canva.com:443/mcp/'), normalizaUrl(CANVA.servidor.url));
  assert.notEqual(normalizaUrl('https://mcp.canva.com/otro'), normalizaUrl(CANVA.servidor.url));
});

test('despacho: una fila sin Canva sigue igual y no toca recursos ni credenciales', async () => {
  const r = await preparaCanva({ client: cliente(), c: cOn, fila: fila({ brief: 'post. Foto: no' }), cli: { slug: '5cero5' }, fetchImpl: red().fetch });
  assert.equal(r, null);
});

test('despacho: "Canva: sí" con CANVA_ACTIVO apagado → Error con el motivo y sin sesión', async () => {
  const f = [fila()]; const n = mockNotion(f); const cl = cliente();
  await despacha({ client: cl, notion: n, c: cOff, fetchImpl: red().fetch });
  assert.equal(cl.calls.create.length, 0); assert.equal(f[0].estado, 'Error');
  assert.match(n.log.at(-1)[1].Error.rich_text[0].text.content, /CANVA_ACTIVO está apagado/);
});

test('despacho: Canva con foto falla cerrado (no se cobra nada) hasta integrar el núcleo de Higgsfield', async () => {
  await assert.rejects(preparaCanva({ client: cliente(), c: cOn, fila: fila({ brief: 'Canva: sí\nFoto: sí' }), cli: { slug: '5cero5' }, fetchImpl: red().fetch }),
    e => e.motivo === 'canva_foto');
});

test('despacho: recursos deshabilitados, credencial ausente, de otro cliente o vault ajeno → Error sin sesión', async () => {
  const casos = [
    [{ red: { recursos: { ...RECURSOS, habilitado: false } } }, /no está habilitado/],
    [{ red: { recursos: null } }, /no tiene canva\/recursos\.json/],
    [{ cli: { creds: [] } }, /no tiene la credencial mcp_oauth de Canva/],
    [{ cli: { creds: [{ id: 'x', auth: { type: 'mcp_oauth', mcp_server_url: 'https://mcp.canva.com/mcp' }, metadata: { cliente: 'opticas', rol: 'canva' } }] } }, /no es de 5cero5\/canva/],
    [{ cli: { creds: [{ id: 'x', auth: { type: 'static_bearer', mcp_server_url: 'https://mcp.canva.com/mcp' }, metadata: { cliente: '5cero5', rol: 'canva' } }] } }, /no tiene la credencial mcp_oauth/],
    [{ cli: { vaultMeta: { cliente: 'opticas', rol: 'creativo' } } }, /no es el Vault Creativo de 5cero5/],
    [{ cli: { creds: [1, 2].map(i => ({ id: `c${i}`, auth: { type: 'mcp_oauth', mcp_server_url: 'https://mcp.canva.com/mcp' }, metadata: { cliente: '5cero5', rol: 'canva' } })) } }, /tiene 2 credenciales de Canva/],
    [{ cli: { agente: { ...AGENTE_CANVA, tools: [{ type: 'mcp_toolset', mcp_server_name: 'canva' }] } } }, /no tiene la lista cerrada/],
    [{ cli: { agente: { ...AGENTE_CANVA, mcp_servers: [CANVA.servidor, { type: 'url', name: 'otro', url: 'https://mcp.otro.com/mcp' }] } } }, /no declara solo el servidor de Canva/],
    [{ c: cfg({ ...ENV, CANVA_ACTIVO: '1', MA_VAULT_CREATIVO: 'v_creativo,v_otro' }) }, /llevaría 2 vaults/],
    [{ c: cfg({ ...ENV, CANVA_ACTIVO: '1', MA_AGENT_CREATIVO_CANVA: '' }) }, /faltan MA_AGENT_CREATIVO_CANVA/],
    [{ fila: { brief: 'Post.\nCanva: sí, base 4:5' } }, /línea "Canva:" del brief no se entiende/],
    [{ cli: { entorno: { networking: { type: 'limited', allowed_hosts: [...CANVA.hosts_red, 'mcp.canva.com'], allow_mcp_servers: true } } } }, /no tiene la red de agentes\/canva\.json/],
    [{ cli: { entorno: { networking: { type: 'limited', allowed_hosts: CANVA.hosts_red, allow_mcp_servers: false } } } }, /no tiene la red de agentes\/canva\.json/],
    [{ cli: { entorno: { networking: { type: 'unrestricted' } } } }, /no tiene la red de agentes\/canva\.json/],
  ];
  for (const [o, re] of casos) {
    const f = [fila(o.fila)]; const n = mockNotion(f); const cl = cliente(o.cli);
    await despacha({ client: cl, notion: n, c: o.c || cOn, fetchImpl: red(o.red).fetch });
    assert.equal(cl.calls.create.length, 0, `${re}`); assert.equal(f[0].estado, 'Error');
    assert.match(n.log.at(-1)[1].Error.rich_text[0].text.content, re);
  }
});

test('despacho: Canva válido → sesión con el vault del cliente, metadata canva y recursos aprobados en el mensaje', async () => {
  const f = [fila()]; const cl = cliente();
  await despacha({ client: cl, notion: mockNotion(f), c: cOn, fetchImpl: red().fetch });
  assert.equal(cl.calls.create.length, 1);
  const p = cl.calls.create[0];
  assert.deepEqual(p.vault_ids, ['v_creativo']);
  assert.equal(p.agent, 'agent_canva'); assert.equal(p.environment_id, 'env_canva');
  assert.deepEqual(leeMetaCanva(p.metadata), { v: 1, b: { 'post-4x5': ['design', BASE] }, f: CARPETA, l: LOGO, k: 'kAGkit5c05', cr: CRED });
  assert.ok(p.metadata.canva.length <= 512);
  const m = p.initial_events[0].content[0].text;
  assert.match(m, /CANVA: esta pieza se hace en Canva/); assert.match(m, new RegExp(`post-4x5 → design:${BASE}`));
  assert.match(m, new RegExp(CARPETA)); assert.match(m, new RegExp(LOGO)); assert.match(m, /KICKER DE MUESTRA/);
  assert.doesNotMatch(m, /vcrd_|secret|token/i);
});

test('despacho: la credencial conectada desde la Console (sin metadata) sirve; la de otro cliente por metadata, no', async () => {
  const consola = [{ id: CRED, display_name: 'Canva MCP · 5cero5 · Creativo', auth: { type: 'mcp_oauth', mcp_server_url: 'https://mcp.canva.com/mcp' }, metadata: {} }];
  const f = [fila()]; const cl = cliente({ creds: consola });
  await despacha({ client: cl, notion: mockNotion(f), c: cOn, fetchImpl: red().fetch });
  assert.equal(cl.calls.create.length, 1);
  assert.equal(leeMetaCanva(cl.calls.create[0].metadata).cr, CRED);
});

test('cuenta de Canva: copiar la base exige que list-brand-kits haya mostrado el Brand Kit del cliente; al cerrar también', async () => {
  const metaK = { ...META, k: 'kAGkit5c05' };
  const kits = id => [uso('k1', 'list-brand-kits', {}, 'allow'), res('k1', { items: [{ brand_kit_id: id, name: 'x' }] })];
  const copia = h => decideConfirmacion({ id: 'c1', name: 'copy-design', mcp_server_name: 'canva', input: { design_id: BASE } }, { meta: metaK, hist: historiaCanva(h) });
  assert.equal(copia([]).result, 'deny'); assert.match(copia([]).deny_message, /Brand Kit del cliente \(kAGkit5c05\)/);
  assert.equal(copia(kits('kAGotro0001')).result, 'deny');
  assert.equal(copia(kits('kAGkit5c05')).result, 'allow');
  const pieza = { meta: red().meta, canva: red().canvaJson, copia: COPIA, png: PNG };
  const cierra = ev => compruebaCanvaSesion({ client: cliente({ eventos: ev }), sessionId: 's', session: { metadata: { canva: JSON.stringify(metaK) } }, pieza, c: cOn, fetchImpl: red().fetch });
  assert.deepEqual((await cierra(logBueno())).problemas, []);
  const sinKit = logBueno().filter(e => e.id !== 's1' && e.mcp_tool_use_id !== 's1');
  assert.ok((await cierra(sinKit)).problemas.some(p => /no comprobó la cuenta de Canva/.test(p)));
});

test('sesión: sin Canva, ni metadata canva ni bloque CANVA (todo como antes)', () => {
  const p = parametrosSesion(fila({ brief: 'post. Foto: no' }), cOn);
  assert.equal(p.metadata.canva, undefined); assert.doesNotMatch(p.initial_events[0].content[0].text, /CANVA:/);
});

test('confirmaciones: reglas fijas por herramienta', () => {
  const hist = historiaCanva(logBueno());
  const d = (name, input, meta = META, h = hist, id = 'nuevo') => decideConfirmacion({ id, name, mcp_server_name: 'canva', input }, { meta, hist: h });
  const vacio = historiaCanva([]);
  assert.equal(d('copy-design', { design_id: BASE }, META, vacio).result, 'allow');
  assert.equal(d('copy-design', { design_id: 'DAGotro0001' }, META, vacio).result, 'deny');
  assert.match(d('copy-design', { design_id: BASE }).deny_message, /ya se creó uno/);
  assert.match(d('copy-design', { design_id: BASE }, { ...META, d: DIS }, vacio).deny_message, /ronda/);
  assert.equal(d('copy-design', { design_id: BASE, page_numbers: [2] }, META, vacio).result, 'deny');
  assert.equal(d('edit-design', { transaction_id: 'tx1', operations: [{ type: 'replace_text', locator_id: 'PB-LB1' }, { type: 'find_and_replace_text', locator_id: 'PB-LB3' }] }).result, 'allow');
  assert.match(d('edit-design', { transaction_id: 'tx1', operations: [{ type: 'replace_text', locator_id: 'LB3' }] }).deny_message, /locator completo/);
  assert.match(d('edit-design', { transaction_id: 'tx1', page_index: 2, operations: [{ type: 'replace_text', locator_id: 'PB-LB1' }] }).deny_message, /página 1/);
  const conFijos = (input) => decideConfirmacion({ id: 'n', name: 'edit-design', mcp_server_name: 'canva', input }, { meta: META, hist, fijos: [FIJO] });
  assert.match(conFijos({ transaction_id: 'tx1', operations: [{ type: 'delete_element', locator_id: 'PB-LB6' }] }).deny_message, /texto fijo aprobado/);
  assert.match(conFijos({ transaction_id: 'tx1', operations: [{ type: 'replace_text', locator_id: 'PB-LB6', text: COPIA.subtitulo }] }).deny_message, /texto fijo aprobado/);
  assert.equal(conFijos({ transaction_id: 'tx1', operations: [{ type: 'replace_text', locator_id: 'PB-LB3' }] }).result, 'allow');
  assert.equal(d('edit-design', { transaction_id: 'tx1', finalize: 'commit' }).result, 'allow');
  assert.equal(d('edit-design', { transaction_id: 'tx1', operations: [{ type: 'delete_element', locator_id: 'PB-LB1' }] }).result, 'allow');
  assert.match(d('edit-design', { transaction_id: 'tx1', operations: [{ type: 'delete_element', locator_id: 'PB-LB5' }] }).deny_message, /solo se editan elementos de texto/);  // el logo
  assert.match(d('edit-design', { transaction_id: 'tx1', operations: [{ type: 'replace_text', locator_id: 'PB-LB77' }] }).deny_message, /PB-LB77/);   // no leído
  assert.match(d('edit-design', { transaction_id: 'tx1', operations: [{ type: 'update_title', title: 'x' }] }).deny_message, /update_title/);
  assert.match(d('edit-design', { transaction_id: 'tx1', operations: [{ type: 'insert_fill' }] }).deny_message, /insert_fill/);
  assert.match(d('edit-design', { transaction_id: 'tx-ajena', operations: [{ type: 'replace_text', locator_id: 'PB-LB1' }] }).deny_message, /no es del diseño de esta sesión/);
  assert.match(d('copy-design', { design_id: BASE, folder_id: 'FAFotra' }, META, vacio).deny_message, /parámetros no permitidos/);
  assert.match(d('export-design', { design_id: DIS, format: { type: 'png', otra: 1 } }).deny_message, /opciones de exportación/);
  assert.equal(d('export-design', { design_id: DIS, format: { type: 'png' } }).result, 'allow');
  assert.equal(d('export-design', { design_id: DIS, format: { type: 'pdf' } }).result, 'deny');
  assert.equal(d('export-design', { design_id: DIS, format: { type: 'png', transparent_background: true } }).result, 'deny');
  assert.equal(d('export-design', { design_id: BASE, format: { type: 'png' } }).result, 'deny');
  assert.equal(d('move-item-to-folder', { item_id: DIS, to_folder_id: CARPETA }).result, 'allow');
  assert.equal(d('move-item-to-folder', { item_id: DIS, to_folder_id: 'root' }).result, 'deny');
  assert.equal(d('create-design', { brief: 'algo' }).result, 'deny');
  assert.equal(d('copy-design', { design_id: BASE }, null, vacio).result, 'deny');
  assert.equal(decideConfirmacion({ name: 'x', mcp_server_name: 'otro', input: {} }, { meta: META, hist }).result, 'deny');
});

test('confirmaciones: idle con requires_action → el harness decide, la fila sigue En curso y no se repite lo ya confirmado', async () => {
  const eventos = [uso('s2', 'copy-design', { design_id: BASE }), uso('s9', 'copy-design', { design_id: BASE }),
    { type: 'session.status_idle', id: 'i1', stop_reason: { type: 'requires_action', event_ids: ['s2', 's9'] } }];
  const f = [fila({ estado: 'En curso', sesion: 'sesn_1' })]; const n = mockNotion(f); const cl = cliente({ eventos });
  const r = await cierraSesion({ client: cl, notion: n, c: cOn, sessionId: 'sesn_1', fetchImpl: red().fetch });
  assert.match(r, /^aun_requiere_accion:copy-design:allow,copy-design:deny$/);
  assert.equal(f[0].estado, 'En curso'); assert.equal(n.log.length, 0);
  const enviados = cl.calls.send[0][1].events;
  assert.deepEqual(enviados.map(e => [e.tool_use_id, e.result]), [['s2', 'allow'], ['s9', 'deny']]);
  assert.match(enviados[1].deny_message, /ya se creó uno/);
  // Webhook duplicado: lo ya confirmado no se vuelve a mandar y la fila tampoco se cierra.
  const cl2 = cliente({ eventos: [...eventos, conf('s2'), conf('s9', 'deny')] });
  assert.equal(await resuelveConfirmaciones({ client: cl2, sessionId: 'sesn_1', session: { metadata: { canva: JSON.stringify(META) } } }), 'sin_pendientes');
  assert.equal(cl2.calls.send.length, 0);
});

test('barrido: una sesión esperando confirmación pasa por el harness y respeta el tope de minutos', async () => {
  const eventos = [uso('s2', 'copy-design', { design_id: BASE }), { type: 'session.status_idle', id: 'i1', stop_reason: { type: 'requires_action', event_ids: ['s2'] } }];
  const f = [fila({ estado: 'En curso', sesion: 'sesn_1', inicio: new Date(Date.now() - 5 * 60000).toISOString() })];
  const cl = cliente({ eventos });
  const out = await barre({ client: cl, notion: mockNotion(f), c: cOn, fetchImpl: red().fetch });
  assert.match(out[0][1], /^aun_requiere_accion/); assert.equal(cl.calls.send.length, 1); assert.equal(f[0].estado, 'En curso');
});

test('cierre: pieza de Canva completa → Para revisar, Aprobada, con enlace editable y exportación cotejada byte a byte', async () => {
  const f = [fila({ estado: 'En curso', sesion: 'sesn_1' })]; const n = mockNotion(f); const g = red();
  await cierraSesion({ client: cliente(), notion: n, c: cOn, sessionId: 'sesn_1', fetchImpl: g.fetch });
  const props = n.log.at(-1)[1]; const inf = props['Informe del Verificador'].rich_text[0].text.content;
  assert.equal(f[0].estado, 'Para revisar'); assert.equal(props.Verificador.select.name, 'Aprobada', inf);
  assert.match(inf, /hecha en Canva/); assert.match(inf, new RegExp(`Canva: diseño ${DIS}`)); assert.match(inf, /exportación PNG idéntica/);
  assert.match(inf, new RegExp(`Editable: https://www.canva.com/design/${DIS}/edit`));
  assert.deepEqual(g.descargas.map(x => x.redirect), ['error']);
});

test('cierre: cada falta en Canva rechaza la pieza con su motivo', async () => {
  const sin = ids => logBueno().filter(e => !ids.includes(e.id) && !ids.includes(e.mcp_tool_use_id) && !ids.includes(e.tool_use_id));
  const lecturaAntes = () => { const l = sin(['s6']); l.splice(l.findIndex(e => e.id === 's4'), 0, uso('s6', 'read-design', { design_id: DIS }, 'allow'), res('s6', LECTURA)); return l; };
  const casos = [
    [{ red: { exportBytes: Buffer.from('otro png') } }, /no es la exportación original de Canva/],
    [{ eventos: sin(['s5']) }, /no hay commit del diseño/],
    [{ eventos: lecturaAntes() }, /no hay relectura del diseño guardado/],
    [{ eventos: sin(['s7']) }, /no hay exportación PNG/],
    [{ eventos: sin(['s8']) }, /no se movió a la carpeta aprobada/],
    [{ eventos: conLectura(lecturaCon({}, { extra: ['Nota de muestra'] })) }, /siguen textos de muestra de la base: "Nota de muestra"/],
    [{ eventos: conLectura(lecturaCon({}, { fijo: 'Desde $10,000 al mes, garantizado 100%' })) }, /fuera de los roles y de los fijos aprobados: "Desde \$10,000/],
    // Elementos con textos de muestra y sin logo, pero el título del diseño con la copia y el id del logo: el título no cuenta.
    [{ eventos: conLectura(lecturaCon({ kicker: MUESTRA.kicker, titular: MUESTRA.titular, subtitulo: MUESTRA.subtitulo, nota: MUESTRA.nota },
      { logo: null, titulo: `${COPIA.kicker} ${COPIA.titular.join(' ')} ${COPIA.subtitulo} ${COPIA.nota} ${LOGO}` })) }, /kicker guardado en Canva no es la copia del PR.*no trae el logo aprobado/],
    [{ eventos: conLectura(lecturaCon({ subtitulo: 'Otra frase distinta de cinco palabras.' })) }, /subtitulo guardado en Canva no es la copia del PR/],
    [{ eventos: conLectura('sin elementos legibles') }, /no trae elementos de texto legibles/],
    // Texto fijo borrado (precio o aviso legal): falta el fijo y su elemento cambió.
    [{ eventos: conLectura((() => { const l = lecturaCon(); l.design_content.pages[0].elements = l.design_content.pages[0].elements.filter(e => e.locator_id !== 'PB-LB6'); return l; })()) },
      /falta el texto fijo aprobado.*se cambió o borró un texto fijo de la base \(PB-LB6\)/],
    // Texto fijo sobrescrito con un rol (el subtítulo escrito sobre el elemento del fijo y mapeado ahí).
    [{ eventos: conLectura((() => { const l = lecturaCon(); const els = l.design_content.pages[0].elements;
      els.find(e => e.locator_id === 'PB-LB6').text = COPIA.subtitulo; els.find(e => e.locator_id === 'PB-LB3').text = ''; return l; })()),
      red: { canvaJson: { ...red().canvaJson, elementos: { kicker: 'PB-LB1', titular: 'PB-LB2', subtitulo: 'PB-LB6', nota: 'PB-LB4' } } } }, /se cambió o borró un texto fijo de la base/],
    // Llamada directa al MCP de Canva desde bash (fuera de las herramientas con aprobación).
    [{ eventos: [...logBueno().slice(0, -2), { type: 'agent.tool_use', id: 'b1', name: 'bash', input: { command: 'curl -X POST https://mcp.canva.com/mcp -d x' } }, ...logBueno().slice(-2)] },
      /llamó al servidor MCP de Canva por fuera de las herramientas/],
    [{ red: { canvaJson: { ...red().canvaJson, design_id: 'DAGotro0001' } } }, /canva\.json y pieza\.json no son del mismo diseño/],
    [{ red: { canvaJson: { ...red().canvaJson, edit_url: 'https://evil.example/x' } } }, /enlace de edición/],
    [{ red: { informe: { aprobada: true, formato: 'post-4x5', repo_version: '0.13.0' } } }, /no es del Verificador de Canva/],
    [{ red: { carpeta: [...red().carpeta, { name: 'pieza.html', type: 'file', sha: 'h' }] } }, /no lleva pieza\.html/],
    [{ cliente: { metadata: { notion_page_id: 'p1', main_sha: 'm1' } } }, /no se despachó como Canva/],
  ];
  for (const [o, re] of casos) {
    const f = [fila({ estado: 'En curso', sesion: 'sesn_1' })]; const n = mockNotion(f);
    await cierraSesion({ client: cliente({ eventos: o.eventos, ...(o.cliente || {}) }), notion: n, c: cOn, sessionId: 'sesn_1', fetchImpl: red(o.red).fetch });
    const props = n.log.at(-1)[1];
    assert.equal(f[0].estado, 'Para revisar'); assert.equal(props.Verificador.select.name, 'Rechazada', `${re}`);
    assert.match(props['Informe del Verificador'].rich_text[0].text.content, re);
  }
});

test('cierre: una fila de Canva que entrega una pieza HTML sale Rechazada', async () => {
  const g = red({ meta: { campana: 'poc', pieza: 'post-canva', formato: 'post-4x5', foto: false },
    carpeta: ['pieza.png', 'pieza.html', 'copia.json', 'pieza.json', 'informe.json'].map(name => ({ name, type: 'file', sha: name === 'pieza.png' ? blob(PNG) : `s-${name}` })),
    informe: { aprobada: true, formato: 'post-4x5', repo_version: '0.12.1', avisos: [] } });
  const f = [fila({ estado: 'En curso', sesion: 'sesn_1' })]; const n = mockNotion(f);
  await cierraSesion({ client: cliente(), notion: n, c: cOn, sessionId: 'sesn_1', fetchImpl: g.fetch });
  assert.equal(n.log.at(-1)[1].Verificador.select.name, 'Rechazada');
  assert.match(n.log.at(-1)[1]['Informe del Verificador'].rich_text[0].text.content, /pedía Canva y la pieza del PR no es de Canva/);
});

test('ronda Igual en Canva: mismo diseño; crear otro rechaza y la exportación nueva se coteja', async () => {
  const meta = { ...META, d: DIS };
  const ronda = [uso('s3', 'read-design', { design_id: DIS, open_transaction: true }, 'allow'), res('s3', { transaction_id: 'tx2', ...LECTURA }),
    uso('s4', 'edit-design', { transaction_id: 'tx2', operations: [{ type: 'replace_text', locator_id: 'PB-LB3' }] }), conf('s4'), res('s4', {}),
    uso('s5', 'edit-design', { transaction_id: 'tx2', finalize: 'commit' }), conf('s5'), res('s5', {}),
    uso('s6', 'read-design', { design_id: DIS }, 'allow'), res('s6', LECTURA),
    uso('s7', 'export-design', { design_id: DIS, format: { type: 'png' } }), conf('s7'), res('s7', { urls: ['https://export-download.canva.com/r2.png'] })];
  const pieza = { meta: red().meta, canva: red().canvaJson, copia: COPIA, png: PNG };
  const cl = cliente({ eventos: ronda });
  const bien = await compruebaCanvaSesion({ client: cl, sessionId: 's', session: { metadata: { canva: JSON.stringify(meta) } }, pieza, c: cOn, fetchImpl: red().fetch });
  assert.deepEqual(bien.problemas, []); assert.match(bien.resumen, /ronda: el mismo diseño/);
  assert.equal(decideConfirmacion({ id: 'z', name: 'copy-design', mcp_server_name: 'canva', input: { design_id: BASE } }, { meta, hist: historiaCanva(ronda) }).result, 'deny');
  const conCopia = [...ronda, uso('s9', 'copy-design', { design_id: BASE }), conf('s9'), res('s9', { design: { id: 'DAGotra0001' } })];
  const mal = await compruebaCanvaSesion({ client: cliente({ eventos: conCopia }), sessionId: 's', session: { metadata: { canva: JSON.stringify(meta) } }, pieza, c: cOn, fetchImpl: red().fetch });
  assert.ok(mal.problemas.some(p => /ronda: se creó otro diseño/.test(p)));
});

test('exportación: solo hosts de Canva permitidos y sin seguir redirecciones', async () => {
  const pieza = { meta: red().meta, canva: red().canvaJson, copia: COPIA, png: PNG };
  const ev = logBueno().map(e => (e.id === 'rs7' ? res('s7', { urls: ['https://evil.example/pieza.png'] }) : e));
  const r = await compruebaCanvaSesion({ client: cliente({ eventos: ev }), sessionId: 's', session: { metadata: { canva: JSON.stringify(META) } }, pieza, c: cOn, fetchImpl: red().fetch });
  assert.ok(r.problemas.some(p => /no trae una URL de export-download\.canva\.com/.test(p)));
});

test('metadata canva: ida y vuelta, y basura se lee como "no es de Canva"', () => {
  assert.deepEqual(leeMetaCanva({ canva: metadataCanva({ ...META, textos: { x: 1 } }) }), META);
  assert.equal(leeMetaCanva({ canva: 'no json' }), null);
  assert.equal(leeMetaCanva({}), null);
});

test('sesión: solo una fila de Canva usa el agente y el entorno de Canva; las demás del Creativo, los de siempre', () => {
  const sin = parametrosSesion(fila({ brief: 'post. Foto: no' }), cOn);
  assert.equal(sin.agent, 'agent_creativo'); assert.equal(sin.environment_id, 'env_1');
  const con = parametrosSesion({ ...fila(), canva: { ...META, agente: 'agent_canva', entorno: 'env_canva' } }, cOn);
  assert.equal(con.agent, 'agent_canva'); assert.equal(con.environment_id, 'env_canva');
});

test('comando del Creativo: lleva --fila con el id de la página de Notion (y nada si no es un id)', () => {
  const uuid = '41e6eacb-3ef9-80d1-90e3-d783ea414de0';
  assert.match(parametrosSesion(fila({ id: uuid }), cOn).initial_events[0].content[0].text, new RegExp(`pr_pieza\\.py --fila ${uuid} --trabajo`));
  assert.doesNotMatch(parametrosSesion(fila({ id: 'p1; rm -rf /' }), cOn).initial_events[0].content[0].text, /--fila/);
});

test('piloto: GH_REPO_REF / GH_AGENTES_REF montan esa rama y recursos.json se lee de la misma; vacías, como siempre', async () => {
  const cR = cfg({ ...ENV, CANVA_ACTIVO: '1', GH_REPO_REF: 'creativo', GH_AGENTES_REF: 'creativo' });
  const p = parametrosSesion(fila(), cR);
  assert.deepEqual(p.resources.map(r => r.checkout), [{ type: 'branch', name: 'creativo' }, { type: 'branch', name: 'creativo' }]);
  assert.ok(parametrosSesion(fila(), cOn).resources.every(r => r.checkout === undefined));
  const vistos = []; const g = red();
  const f = async (url, init) => { vistos.push(url); return g.fetch(url, init); };
  await preparaCanva({ client: cliente(), c: cR, fila: fila(), cli: { slug: '5cero5' }, fetchImpl: f });
  assert.ok(vistos.some(u => u.includes('/contents/canva/recursos.json?ref=creativo')));
});

test('confirmaciones: desfase del log y sesiones vencidas no cierran ni aprueban', async () => {
  // La sesión dice idle pero el log aún no trae ese idle (último estado: running): una sesión de Canva no se cierra.
  const desfase = [uso('s2', 'copy-design', { design_id: BASE }), { type: 'session.status_running', id: 'r1' }];
  const f = [fila({ estado: 'En curso', sesion: 'sesn_1' })]; const n = mockNotion(f);
  assert.match(await cierraSesion({ client: cliente({ eventos: desfase }), notion: n, c: cOn, sessionId: 'sesn_1', fetchImpl: red().fetch }), /^aun_requiere_accion:sin_evento_idle/);
  assert.equal(f[0].estado, 'En curso');
  // Pasada del tope de minutos: el barrido no aprueba la copia y la interrumpe.
  const pide = [uso('s2', 'copy-design', { design_id: BASE }), { type: 'session.status_idle', id: 'i1', stop_reason: { type: 'requires_action', event_ids: ['s2'] } }];
  const g = [fila({ estado: 'En curso', sesion: 'sesn_1', inicio: new Date(Date.now() - 90 * 60000).toISOString() })]; const cl = cliente({ eventos: pide });
  await barre({ client: cl, notion: mockNotion(g), c: cOn, fetchImpl: red().fetch });
  assert.ok(cl.calls.send.every(([, e]) => e.events.every(x => x.type !== 'user.tool_confirmation')));
  assert.equal(g[0].estado, 'Error');
});

test('Canva apagado: una línea "Canva:" ilegible no cambia nada (como antes); encendido, Error', async () => {
  assert.equal(await preparaCanva({ client: cliente(), c: cOff, fila: fila({ brief: 'Post.\nCanva: no aplica' }), cli: { slug: '5cero5' }, fetchImpl: red().fetch }), null);
  await assert.rejects(preparaCanva({ client: cliente(), c: cOn, fila: fila({ brief: 'Post.\nCanva: no aplica' }), cli: { slug: '5cero5' }, fetchImpl: red().fetch }), e => e.motivo === 'canva_brief');
});

test('webhook: una sesión pasada del tope de minutos no recibe aprobaciones', async () => {
  const pide = [uso('s2', 'copy-design', { design_id: BASE }), { type: 'session.status_idle', id: 'i1', stop_reason: { type: 'requires_action', event_ids: ['s2'] } }];
  const f = [fila({ estado: 'En curso', sesion: 'sesn_1', inicio: new Date(Date.now() - 90 * 60000).toISOString() })]; const cl = cliente({ eventos: pide });
  assert.match(await cierraSesion({ client: cl, notion: mockNotion(f), c: cOn, sessionId: 'sesn_1', fetchImpl: red().fetch }), /aun_requiere_accion:vencida/);
  assert.equal(cl.calls.send.length, 0);
});

test('confirmaciones de edición: los textos fijos se leen de los recursos del cliente; sin poder leerlos, se niega editar', async () => {
  const ev = [...logBueno().slice(0, 7), uso('s4', 'edit-design', { transaction_id: 'tx1', operations: [{ type: 'delete_element', locator_id: 'PB-LB6' }] }),
    { type: 'session.status_idle', id: 'i9', stop_reason: { type: 'requires_action', event_ids: ['s4'] } }];
  const md = { metadata: { canva: JSON.stringify(META) } };
  const cl = cliente({ eventos: ev });
  await resuelveConfirmaciones({ client: cl, sessionId: 's', session: md, c: cOn, fetchImpl: red().fetch });
  assert.match(cl.calls.send[0][1].events[0].deny_message, /texto fijo aprobado/);
  const cl2 = cliente({ eventos: ev });
  await resuelveConfirmaciones({ client: cl2, sessionId: 's', session: md, c: cOn, fetchImpl: red({ recursos: null }).fetch });
  assert.match(cl2.calls.send[0][1].events[0].deny_message, /no se pudieron leer los recursos aprobados/);
});

test('piloto: con RUTEO_CLIENTES=1 se ignoran GH_REPO_REF / GH_AGENTES_REF', () => {
  const r = cfg({ ...ENV, GH_REPO_REF: 'creativo', GH_AGENTES_REF: 'creativo', RUTEO_CLIENTES: '1' });
  assert.equal(r.repos.marca.ref, ''); assert.equal(r.repos.agentes.ref, '');
});

test('copy-design con un resultado ambiguo (dos diseños) no hace propio a ninguno', () => {
  const ev = [uso('s2', 'copy-design', { design_id: BASE }), conf('s2'), res('s2', { design: { id: DIS }, otro: { design_id: 'DAGajeno001' } })];
  const h = historiaCanva(ev);
  assert.deepEqual(h.disenos, []);
  assert.equal(decideConfirmacion({ id: 'x', name: 'export-design', mcp_server_name: 'canva', input: { design_id: 'DAGajeno001', format: { type: 'png' } } }, { meta: META, hist: h }).result, 'deny');
});
