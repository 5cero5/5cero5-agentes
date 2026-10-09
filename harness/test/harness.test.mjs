import test from 'node:test';
import assert from 'node:assert/strict';
import { cfg, eventoDeCierre } from '../lib/config.mjs';
import { leeCampana, esCampanaDespachable, briefDeCampana, despachaCampanas, compruebaFilasCMO } from '../lib/campanas.mjs';
import { esDespachable, despacha } from '../lib/despacho.mjs';
import { parametrosSesion } from '../lib/sessions.mjs';
import { cierraSesion } from '../lib/cierre.mjs';
import { barre } from '../lib/barrido.mjs';
import { AGENTES, revisaRespuesta } from '../lib/agentes.mjs';

const AL = 'user-al', BONZO = 'user-bonzo', INTRUSO = 'user-x';
const c = cfg({ NOTION_APROBADORES: `${AL},${BONZO}`, MA_ENVIRONMENT_ID: 'env_1', MA_AGENT_CREATIVO: 'agent_c', MA_VAULT_IDS: 'v1', GH_REPO_URL: 'https://github.com/o/r' });
const fila = (o = {}) => ({ id: 'p1', editadoPor: { id: AL }, trabajo: 'Pieza 1', agente: 'Creativo', estado: 'Aprobado', brief: 'haz algo', campana: 'C1', sesion: '', intentos: 0, tope: null, aprobo: [AL], aprobadoEl: '2026-10-02', inicio: null, ...o });

function pageDe(f) {
  return { id: f.id, last_edited_by: f.editadoPor, properties: {
    Trabajo: { title: [{ plain_text: f.trabajo }] }, Agente: { select: { name: f.agente } }, Estado: { select: { name: f.estado } },
    Brief: { rich_text: f.brief ? [{ plain_text: f.brief }] : [] }, Campaña: { rich_text: [{ plain_text: f.campana }] },
    Sesión: { rich_text: f.sesion ? [{ plain_text: f.sesion }] : [] }, Intentos: { number: f.intentos },
    'Tope de la sesión (USD)': { number: f.tope }, Aprobó: { people: f.aprobo.map(id => ({ id })) },
    Inició: { date: f.inicio ? { start: f.inicio } : null } } };
}
function mockNotion(filas) {
  const log = [];
  return { log,
    query: async (_ds, filter) => {
      if (filter.property === 'Inició') return { results: [] };
      if (filter.property === 'Estado') return { results: filas.filter(f => f.estado === filter.select.equals).map(pageDe) };
      if (filter.property === 'Sesión') return { results: filas.filter(f => f.sesion === filter.rich_text.equals).map(pageDe) };
    },
    get: async id => pageDe(filas.find(f => f.id === id)),
    update: async (id, props) => { log.push([id, props]); const f = filas.find(x => x.id === id); if (props.Estado) f.estado = props.Estado.select.name; if (props.Intentos) f.intentos = props.Intentos.number; if (props.Sesión) f.sesion = props.Sesión.rich_text[0].text.content; } };
}
function mockClient({ status = 'idle', msg = '{"deploy_id":"d1"}', createFails = false } = {}) {
  const calls = { create: [], send: [] };
  return { calls, beta: { sessions: {
    create: async p => { if (createFails) throw new Error('boom'); calls.create.push(p); return { id: 'sesn_1' }; },
    retrieve: async () => ({ status, metadata: { notion_page_id: 'p1' }, usage: { input_tokens: 1 } }),
    events: { list: async function* () { yield { type: 'agent.message', content: [{ text: msg }] }; }, send: async e => calls.send.push(e) } } } };
}

test('despachable: aprobación válida', () => assert.equal(esDespachable(fila(), c), null));
test('rechaza si aprobó alguien no autorizado', () => assert.equal(esDespachable(fila({ aprobo: [INTRUSO] }), c), 'aprobo_no_autorizado'));
test('rechaza si la última edición no es de un aprobador (un agente no se autoaprueba)', () => assert.equal(esDespachable(fila({ editadoPor: { id: 'bot' } }), c), 'ultima_edicion_no_es_de_un_aprobador'));
test('rechaza sin aprobadores configurados', () => assert.equal(esDespachable(fila(), cfg({})), 'sin_aprobadores_configurados'));
test('rechaza sin brief, con sesión, o intentos agotados', () => {
  assert.equal(esDespachable(fila({ brief: '' }), c), 'sin_brief');
  assert.equal(esDespachable(fila({ sesion: 's' }), c), 'ya_tiene_sesion');
  assert.equal(esDespachable(fila({ intentos: 2 }), c), 'intentos_agotados');
});
test('tope: usa default y nunca pasa del máximo', () => {
  assert.equal(parametrosSesion(fila(), c).budget.max_list_cost.amount, '200');
  assert.equal(parametrosSesion(fila({ tope: 99 }), c).budget.max_list_cost.amount, '500');
});
test('sesión lleva repo, vault, metadata y mensaje', () => {
  const p = parametrosSesion(fila(), c);
  assert.equal(p.metadata.notion_page_id, 'p1'); assert.deepEqual(p.vault_ids, ['v1']);
  assert.equal(p.resources[0].mount_path, '/workspace/marca'); assert.match(p.initial_events[0].content[0].text, /haz algo/);
});
test('despacha: reclama, crea y guarda la sesión', async () => {
  const f = [fila()]; const n = mockNotion(f); const cl = mockClient();
  const r = await despacha({ client: cl, notion: n, c });
  assert.equal(r.creadas.length, 1); assert.equal(f[0].estado, 'En curso'); assert.equal(f[0].intentos, 1); assert.equal(f[0].sesion, 'sesn_1');
});
test('despacha: segunda corrida no duplica', async () => {
  const f = [fila()]; const n = mockNotion(f); const cl = mockClient();
  await despacha({ client: cl, notion: n, c }); await despacha({ client: cl, notion: n, c });
  assert.equal(cl.calls.create.length, 1);
});
test('despacha: fallo al crear pasa a Error y no reintenta', async () => {
  const f = [fila()]; const n = mockNotion(f); const cl = mockClient({ createFails: true });
  await despacha({ client: cl, notion: n, c }); assert.equal(f[0].estado, 'Error');
  await despacha({ client: cl, notion: n, c }); assert.equal(cl.calls.create.length, 0);
});
test('pausa general no despacha nada', async () => {
  const f = [fila()]; const cl = mockClient();
  await despacha({ client: cl, notion: mockNotion(f), c: { ...c, pausa: true } }); assert.equal(cl.calls.create.length, 0); assert.equal(f[0].estado, 'Aprobado');
});
test('tope diario', async () => {
  const f = [fila(), fila({ id: 'p2' })]; const cl = mockClient();
  const n = mockNotion(f); n.query = (orig => async (ds, fl, sz) => fl.property === 'Inició' ? { results: Array(5).fill({}) } : orig(ds, fl, sz))(n.query);
  await despacha({ client: cl, notion: n, c: { ...c, maxSesionesPorDia: 6 } }); assert.equal(cl.calls.create.length, 1);
});
test('cierre: idle → Para revisar, Verificador Pendiente, nunca Listo', async () => {
  const f = [fila({ estado: 'En curso', sesion: 'sesn_1' })]; const n = mockNotion(f);
  assert.equal(await cierraSesion({ client: mockClient(), notion: n, c, sessionId: 'sesn_1' }), 'para_revisar');
  assert.equal(f[0].estado, 'Para revisar');
  assert.equal(n.log.at(-1)[1].Verificador.select.name, 'Pendiente');
});
test('cierre: con Verificador activo → Verificando', async () => {
  const f = [fila({ estado: 'En curso', sesion: 'sesn_1' })];
  assert.equal(await cierraSesion({ client: mockClient(), notion: mockNotion(f), c: { ...c, verificadorActivo: true }, sessionId: 'sesn_1' }), 'verificando');
});
test('cierre: idempotente (webhook repetido)', async () => {
  const f = [fila({ estado: 'En curso', sesion: 'sesn_1' })]; const n = mockNotion(f); const cl = mockClient();
  await cierraSesion({ client: cl, notion: n, c, sessionId: 'sesn_1' });
  assert.match(await cierraSesion({ client: cl, notion: n, c, sessionId: 'sesn_1' }), /^ignorada/);
});
test('cierre: tope alcanzado → Error', async () => {
  const f = [fila({ estado: 'En curso', sesion: 'sesn_1' })];
  await cierraSesion({ client: mockClient({ status: 'idle' }), notion: mockNotion(f), c, sessionId: 'sesn_1', motivo: 'budget' });
  assert.equal(f[0].estado, 'Error');
});
test('barrido: recoge sesión idle perdida', async () => {
  const f = [fila({ estado: 'En curso', sesion: 'sesn_1', inicio: new Date(Date.now() - 600000).toISOString() })];
  await barre({ client: mockClient(), notion: mockNotion(f), c }); assert.equal(f[0].estado, 'Para revisar');
});
test('barrido: timeout interrumpe y marca Error', async () => {
  const f = [fila({ estado: 'En curso', sesion: 'sesn_1', inicio: new Date(Date.now() - 3600000).toISOString() })]; const cl = mockClient({ status: 'running' });
  await barre({ client: cl, notion: mockNotion(f), c }); assert.equal(f[0].estado, 'Error'); assert.equal(cl.calls.send.length, 1);
});
test('barrido: reclamada sin sesión → Error', async () => {
  const f = [fila({ estado: 'En curso', inicio: new Date(Date.now() - 900000).toISOString() })];
  await barre({ client: mockClient(), notion: mockNotion(f), c }); assert.equal(f[0].estado, 'Error');
});

// ---- Hito 1: router por agente, tope en centavos, formato de respuesta ----
const cCRM = cfg({ NOTION_APROBADORES: `${AL},${BONZO}`, MA_ENVIRONMENT_ID: 'env_1', MA_AGENT_CRM: 'agent_crm', MA_VAULT_IDS: 'v_crm',
  GH_REPO_URL: 'https://github.com/5cero5/5cero5-marca', GH_AGENTES_URL: 'https://github.com/5cero5/5cero5-agentes', GH_REPO_READ_TOKEN: 'tok' });
const filaCRM = (o = {}) => fila({ agente: 'CRM', trabajo: 'Plantilla W1', brief: 'arma W1', ...o });

test('router: CRM usa su agente, monta marca y agentes, y lleva sus reglas', () => {
  const p = parametrosSesion(filaCRM(), cCRM);
  assert.equal(p.agent, 'agent_crm');
  assert.deepEqual(p.resources.map(r => r.mount_path), ['/workspace/marca', '/workspace/agentes']);
  assert.ok(p.resources.every(r => r.authorization_token === 'tok'));
  const m = p.initial_events[0].content[0].text;
  assert.match(m, /correo\.py/); assert.match(m, /\[agente\] /); assert.match(m, /No envías correos/); assert.match(m, /plantilla_id/);
  assert.doesNotMatch(m, /deploy_id/);
});
test('vault: cada agente usa el suyo; sin vault propio, el común', () => {
  const cv = cfg({ MA_ENVIRONMENT_ID: 'env_1', MA_AGENT_CREATIVO: 'agent_c', MA_AGENT_CRM: 'agent_crm', MA_VAULT_IDS: 'v_comun', MA_VAULT_CRM: 'v_hl',
    GH_REPO_URL: 'https://github.com/o/m', GH_AGENTES_URL: 'https://github.com/o/a' });
  assert.deepEqual(parametrosSesion(filaCRM(), cv).vault_ids, ['v_hl']);
  assert.deepEqual(parametrosSesion(fila(), cv).vault_ids, ['v_comun']);
});
test('router: Creativo no recibe las reglas de CRM', () => {
  const m = parametrosSesion(fila(), c).initial_events[0].content[0].text;
  assert.match(m, /deploy_id/); assert.doesNotMatch(m, /correo\.py/); assert.match(m, /C30/);
});
test('router: agente fuera del catálogo o sin id no se despacha', () => {
  assert.throws(() => parametrosSesion(fila({ agente: 'Pauta' }), c), /Agente sin configurar: Pauta/);
  assert.throws(() => parametrosSesion(filaCRM(), c), /Agente sin configurar: CRM/);
  assert.throws(() => parametrosSesion(fila({ agente: 'constructor' }), c), /Agente sin configurar: constructor/);
});
test('router: falta un repo que el agente declara → no hay sesión', () => {
  const sinAgentes = cfg({ ...{ NOTION_APROBADORES: AL, MA_ENVIRONMENT_ID: 'env_1', MA_AGENT_CRM: 'agent_crm', GH_REPO_URL: 'https://github.com/o/m' } });
  assert.throws(() => parametrosSesion(filaCRM(), sinAgentes), /Falta GH_AGENTES_URL/);
});
test('despacha: agente sin configurar pasa a Error y no crea sesión', async () => {
  const f = [fila({ agente: 'Pauta' })]; const cl = mockClient();
  await despacha({ client: cl, notion: mockNotion(f), c }); assert.equal(f[0].estado, 'Error'); assert.equal(cl.calls.create.length, 0);
});
test('tope en centavos como cadena; menos de un centavo se rechaza', () => {
  const a = parametrosSesion(fila({ tope: 1.5 }), c).budget.max_list_cost.amount;
  assert.equal(a, '150'); assert.equal(typeof a, 'string');
  assert.equal(parametrosSesion(fila({ tope: 0.999 }), c).budget.max_list_cost.amount, '100');
  assert.throws(() => parametrosSesion(fila({ tope: 0.004 }), c), /Tope inválido/);
  assert.throws(() => parametrosSesion(fila({ tope: 0 }), c), /Tope inválido/);
});
test('última edición: vale de Bonzo aunque aprobó Al; no de alguien más', () => {
  assert.equal(esDespachable(fila({ editadoPor: { id: BONZO } }), c), null);
  assert.equal(esDespachable(fila({ editadoPor: { id: INTRUSO }, aprobo: [AL, BONZO] }), c), 'ultima_edicion_no_es_de_un_aprobador');
});
test('formato: CRM válido, en bloque ```json, sin prefijo, sin claves y sin JSON', () => {
  const d = AGENTES.CRM;
  assert.equal(revisaRespuesta(d, 'Listo.\n```json\n{"plantilla_id":"t1","nombre":"[agente] W1","html_sha1":"ab"}\n```'), null);
  assert.equal(revisaRespuesta(d, '{"plantilla_id":"t1","nombre":"W1","html_sha1":"ab"}'), 'nombre_sin_prefijo_agente');
  assert.equal(revisaRespuesta(d, '{"plantilla_id":"t1","nombre":"[agente] W1"}'), 'faltan_claves:html_sha1');
  assert.equal(revisaRespuesta(d, 'Ya quedó la plantilla.'), 'sin_json');
  assert.equal(revisaRespuesta(AGENTES.Creativo, '{"deploy_id":"d1","archivos":["a"],"sha1":{"a":"x"}}'), null);
});
test('cierre: anota el formato de la respuesta en el informe', async () => {
  const f = [filaCRM({ estado: 'En curso', sesion: 'sesn_1' })]; const n = mockNotion(f);
  await cierraSesion({ client: mockClient({ msg: '{"plantilla_id":"t1","nombre":"W1","html_sha1":"ab"}' }), notion: n, c: cCRM, sessionId: 'sesn_1' });
  assert.equal(f[0].estado, 'Para revisar');
  assert.match(n.log.at(-1)[1]['Informe del Verificador'].rich_text[0].text.content, /nombre_sin_prefijo_agente/);
});

test('webhook: solo los eventos confirmados en la consola cierran la fila', () => {
  assert.deepEqual(eventoDeCierre('session.status_idled'), { motivo: undefined });
  assert.deepEqual(eventoDeCierre('session.status_terminated'), { motivo: undefined });
  assert.deepEqual(eventoDeCierre('session.budget_reached'), { motivo: 'budget' });
  for (const t of ['session.thread_idled', 'session.thread_terminated', 'session.idled', 'constructor', '', undefined]) assert.equal(eventoDeCierre(t), null);
});

// ---- Campañas → agente CMO ----
const cK = cfg({ NOTION_APROBADORES: `${AL},${BONZO}`, MA_ENVIRONMENT_ID: 'env_1', MA_AGENT_CMO: 'agent_cmo', MA_AGENT_CRM: 'agent_crm',
  MA_VAULT_CMO: 'v_notion', GH_REPO_URL: 'https://github.com/5cero5/5cero5-marca', GH_AGENTES_URL: 'https://github.com/5cero5/5cero5-agentes' });
const campana = (o = {}) => ({ id: 'k1', editadoPor: { id: AL }, nombre: 'Promo', estado: 'Aprobada', ruta: 'Cita', piezas: 3, aprobo: [AL],
  formatos: ['Correo', 'Post 4:5'], canales: ['Correo'], landing: true, objetivo: 'Llamadas', kpi: 'Llamadas agendadas', meta: 35, costoMax: 1400,
  presupuesto: 50000, vigencia: { start: '2026-10-19', end: '2026-11-18' }, brief: 'agencia vs 5cero5', cliente: '5cero5', ...o });
function pageCampana(k) {
  return { id: k.id, last_edited_by: k.editadoPor, properties: {
    Campaña: { title: [{ plain_text: k.nombre }] }, Estado: { select: k.estado ? { name: k.estado } : null }, Ruta: { select: k.ruta ? { name: k.ruta } : null },
    Cliente: { select: { name: k.cliente } }, Objetivo: { rich_text: [{ plain_text: k.objetivo }] }, KPI: { select: { name: k.kpi } }, Meta: { number: k.meta },
    'Costo máximo por resultado (MXN)': { number: k.costoMax }, Canales: { multi_select: k.canales.map(name => ({ name })) },
    Formatos: { multi_select: k.formatos.map(name => ({ name })) }, Piezas: { number: k.piezas }, 'Lleva landing': { checkbox: k.landing },
    'Presupuesto de pauta (MXN)': { number: k.presupuesto }, Vigencia: { date: k.vigencia }, Brief: { rich_text: [{ plain_text: k.brief }] },
    Aprobó: { people: k.aprobo.map(id => ({ id })) } } };
}
function mockNotionK(campanas) {
  const log = [], creadas = [];
  return { log, creadas,
    query: async (ds, filter) => ds === cK.notionCampanas
      ? { results: campanas.filter(k => k.estado === filter.select.equals).map(pageCampana) }
      : { results: [] },
    create: async (ds, props) => { const id = `fila${creadas.length + 1}`; creadas.push({ ds, id, props }); return { id }; },
    update: async (id, props) => { log.push([id, props]); const k = campanas.find(x => x.id === id); if (k && props.Estado) k.estado = props.Estado.select.name; } };
}

test('campaña: leeCampana lee lo que el CMO necesita', () => {
  const k = leeCampana(pageCampana(campana()));
  assert.equal(k.ruta, 'Cita'); assert.equal(k.piezas, 3); assert.equal(k.landing, true); assert.deepEqual(k.formatos, ['Correo', 'Post 4:5']);
  assert.equal(k.costoMax, 1400); assert.equal(k.vigencia.end, '2026-11-18');
});
test('campaña: solo se despacha aprobada por Al o Bonzo, con su última edición, ruta y piezas', () => {
  assert.equal(esCampanaDespachable(campana(), cK), null);
  assert.equal(esCampanaDespachable(campana({ estado: 'Borrador' }), cK), 'estado');
  assert.equal(esCampanaDespachable(campana({ aprobo: [INTRUSO] }), cK), 'aprobo_no_autorizado');
  assert.equal(esCampanaDespachable(campana({ editadoPor: { id: 'bot' } }), cK), 'ultima_edicion_no_es_de_un_aprobador');
  assert.equal(esCampanaDespachable(campana({ ruta: null }), cK), 'sin_ruta');
  assert.equal(esCampanaDespachable(campana({ piezas: 0 }), cK), 'sin_piezas');
  assert.equal(esCampanaDespachable(campana(), cfg({ NOTION_APROBADORES: AL })), 'cmo_sin_configurar');
});
test('campaña: el brief del CMO lleva los datos y solo los agentes con id', () => {
  const b = briefDeCampana(campana(), cK);
  assert.match(b, /Ruta: Cita/); assert.match(b, /Piezas: 3/); assert.match(b, /Lleva landing: sí/); assert.match(b, /1400 MXN/);
  assert.match(b, /Agentes disponibles hoy: CRM\./); assert.match(b, /Campaña ligada = k1/);
});
test('campaña: se reclama, se crea la fila del CMO En curso y se abre su sesión', async () => {
  const ks = [campana()]; const n = mockNotionK(ks); const cl = mockClient();
  const r = await despachaCampanas({ client: cl, notion: n, c: cK, cupo: 6 });
  assert.equal(r.creadas.length, 1); assert.equal(ks[0].estado, 'En producción');
  const f = n.creadas[0];
  assert.equal(f.ds, cK.notionDataSource); assert.equal(f.props.Agente.select.name, 'CMO'); assert.equal(f.props.Estado.select.name, 'En curso');
  assert.deepEqual(f.props['Campaña ligada'].relation, [{ id: 'k1' }]); assert.deepEqual(f.props.Aprobó.people, [{ id: AL }]);
  const p = cl.calls.create[0];
  assert.equal(p.agent, 'agent_cmo'); assert.deepEqual(p.vault_ids, ['v_notion']); assert.equal(p.metadata.notion_page_id, 'fila1');
  assert.deepEqual(p.resources.map(x => x.mount_path), ['/workspace/marca']);
  assert.match(p.initial_events[0].content[0].text, /Estado "Propuesta"/);
  assert.deepEqual(n.log.at(-1), ['fila1', { Sesión: { rich_text: [{ type: 'text', text: { content: 'sesn_1' } }] } }]);
});
test('campaña: no se despacha dos veces ni pasa del cupo', async () => {
  const ks = [campana(), campana({ id: 'k2' })]; const n = mockNotionK(ks); const cl = mockClient();
  await despachaCampanas({ client: cl, notion: n, c: cK, cupo: 1 });
  await despachaCampanas({ client: cl, notion: n, c: cK, cupo: 1 });
  assert.equal(cl.calls.create.length, 2); // k1 en la primera, k2 en la segunda; ninguna repetida
  assert.deepEqual(ks.map(k => k.estado), ['En producción', 'En producción']);
});
test('campaña: si falla crear la sesión, la fila del CMO queda en Error', async () => {
  const ks = [campana()]; const n = mockNotionK(ks);
  const r = await despachaCampanas({ client: mockClient({ createFails: true }), notion: n, c: cK, cupo: 6 });
  assert.deepEqual(r.omitidas, [['k1', 'create_fallo']]);
  assert.equal(n.log.at(-1)[1].Estado.select.name, 'Error');
});
test('formato: CMO necesita al menos una fila', () => {
  assert.equal(revisaRespuesta(AGENTES.CMO, '{"campana_id":"k1","filas":[{"id":"f","agente":"CRM","trabajo":"W1"}],"sin_agente":0}'), null);
  assert.equal(revisaRespuesta(AGENTES.CMO, '{"campana_id":"k1","filas":[]}'), 'sin_filas');
});

// ---- Regla 8 para el CMO: el cierre comprueba en Notion las filas que reporta ----
const filaPieza = (id, o = {}) => ({ id, properties: {
  Estado: { select: { name: o.estado ?? 'Propuesta' } }, Agente: { select: { name: o.agente ?? 'CRM' } },
  Aprobó: { people: (o.aprobo ?? []).map(id => ({ id })) },
  'Campaña ligada': { relation: (o.campanas ?? ['k1-uuid']).map(id => ({ id })) } } });
function notionPiezas(paginas) {
  const log = [];
  return { log, get: async id => { if (!paginas[id]) throw new Error('404'); return paginas[id]; },
    update: async (id, props) => { log.push([id, props]); if (paginas[id] && props.Estado) paginas[id].properties.Estado = { select: { name: props.Estado.select.name } }; } };
}
const filaCMO = { id: 'cmo1', campanaLigada: ['k1uuid'] };

test('CMO: comprobación pasa si cada fila existe, está en Propuesta, sin Aprobó y ligada', async () => {
  const n = notionPiezas({ a: filaPieza('a'), b: filaPieza('b') });
  const r = await compruebaFilasCMO(n, { ...filaCMO, campanaLigada: ['k1-uuid'] }, { campana_id: 'k1uuid', filas: [{ id: 'a' }, { id: 'b' }] });
  assert.equal(r.ok, true); assert.match(r.informe, /2\/2 filas/);
});
test('CMO: comprobación falla con fila aprobada, inexistente, sin ligar o de otra campaña', async () => {
  const n = notionPiezas({ a: filaPieza('a', { estado: 'Aprobado', aprobo: [AL] }), c: filaPieza('c', { campanas: ['otra'] }), d: filaPieza('d', { agente: 'CMO' }) });
  const r = await compruebaFilasCMO(n, { ...filaCMO, campanaLigada: ['k1-uuid'] }, { campana_id: 'k2', filas: [{ id: 'a' }, { id: 'x' }, { id: 'c' }, { id: 'd' }] });
  assert.equal(r.ok, false);
  for (const t of [/no es la campaña/, /Estado = Aprobado/, /tiene Aprobó/, /x: no existe/, /c: no está ligada/, /Agente = CMO/, /0\/4 filas/]) assert.match(r.informe, t);
});
test('CMO: sin filas reportadas no pasa', async () => {
  assert.equal((await compruebaFilasCMO(notionPiezas({}), filaCMO, { campana_id: 'k1uuid', filas: [] })).ok, false);
});
function paginaCMO() {
  return { id: 'cmo1', last_edited_by: { id: 'bot' }, properties: {
    Trabajo: { title: [{ plain_text: 'Desglose · Promo' }] }, Agente: { select: { name: 'CMO' } }, Estado: { select: { name: 'En curso' } },
    Brief: { rich_text: [{ plain_text: 'b' }] }, Sesión: { rich_text: [{ plain_text: 'sesn_1' }] }, Intentos: { number: 1 },
    Aprobó: { people: [{ id: AL }] }, 'Campaña ligada': { relation: [{ id: 'k1-uuid' }] } } };
}
test('cierre del CMO: comprueba las filas y marca el Verificador Aprobada', async () => {
  const n = notionPiezas({ cmo1: paginaCMO(), a: filaPieza('a'), b: filaPieza('b') });
  const cl = mockClient({ msg: '{"campana_id":"k1-uuid","filas":[{"id":"a","agente":"CRM","trabajo":"W"},{"id":"b","agente":"CRM","trabajo":"X"}],"sin_agente":0}' });
  cl.beta.sessions.retrieve = async () => ({ status: 'idle', metadata: { notion_page_id: 'cmo1' } });
  assert.equal(await cierraSesion({ client: cl, notion: n, c: { ...cK, verificadorActivo: true }, sessionId: 'sesn_1' }), 'para_revisar');
  const props = n.log.at(-1)[1];
  assert.equal(props.Estado.select.name, 'Para revisar'); assert.equal(props.Verificador.select.name, 'Aprobada');
  assert.match(props['Informe del Verificador'].rich_text[0].text.content, /Formato de la respuesta: OK\. Comprobación en Notion: 2\/2/);
});
test('cierre del CMO: si una fila reportada no existe, Verificador Rechazada', async () => {
  const n = notionPiezas({ cmo1: paginaCMO(), a: filaPieza('a') });
  const cl = mockClient({ msg: '{"campana_id":"k1-uuid","filas":[{"id":"a"},{"id":"fantasma"}]}' });
  cl.beta.sessions.retrieve = async () => ({ status: 'idle', metadata: { notion_page_id: 'cmo1' } });
  await cierraSesion({ client: cl, notion: n, c: cK, sessionId: 'sesn_1' });
  const props = n.log.at(-1)[1];
  assert.equal(props.Verificador.select.name, 'Rechazada'); assert.match(props['Informe del Verificador'].rich_text[0].text.content, /fantasma: no existe/);
});
