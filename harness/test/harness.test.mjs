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
// Las pruebas generales usan CRM (sin GitHub App). Las de Landing y Creativo, más abajo, configuran la app.
const c = cfg({ NOTION_APROBADORES: `${AL},${BONZO}`, MA_ENVIRONMENT_ID: 'env_1', MA_AGENT_CRM: 'agent_c', MA_VAULT_IDS: 'v1',
  GH_REPO_URL: 'https://github.com/o/r', GH_AGENTES_URL: 'https://github.com/o/a' });
const fila = (o = {}) => ({ id: 'p1', editadoPor: { id: AL }, trabajo: 'Pieza 1', agente: 'CRM', estado: 'Aprobado', brief: 'haz algo', campana: 'C1', sesion: '', intentos: 0, tope: null, aprobo: [AL], aprobadoEl: '2026-10-02', inicio: null, ...o });

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
  const cv = cfg({ MA_ENVIRONMENT_ID: 'env_1', MA_AGENT_CMO: 'agent_cmo', MA_AGENT_CRM: 'agent_crm', MA_VAULT_IDS: 'v_comun', MA_VAULT_CRM: 'v_hl',
    GH_REPO_URL: 'https://github.com/o/m', GH_AGENTES_URL: 'https://github.com/o/a' });
  assert.deepEqual(parametrosSesion(filaCRM(), cv).vault_ids, ['v_hl']);
  assert.deepEqual(parametrosSesion(fila({ agente: 'CMO' }), cv).vault_ids, ['v_comun']);
});
test('router: CRM no recibe las reglas de Creativo', () => {
  const m = parametrosSesion(fila(), c).initial_events[0].content[0].text;
  assert.doesNotMatch(m, /pr_pieza\.py/); assert.match(m, /correo\.py/); assert.match(m, /C30/);
});
test('router: agente fuera del catálogo o sin id no se despacha', () => {
  assert.throws(() => parametrosSesion(fila({ agente: 'Pauta' }), c), /Agente sin configurar: Pauta/);
  assert.throws(() => parametrosSesion(fila({ agente: 'Creativo' }), c), /Agente sin configurar: Creativo/);
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
  assert.equal(revisaRespuesta(AGENTES.Creativo, '{"deploy_id":"d1","archivos":["a"],"sha1":{"a":"x"}}'), 'faltan_claves:pr_url,pr_numero,rama,commit,campana,pieza,formato');
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

// ---- Agente Landing (PR en 5cero5-landings con la GitHub App) ----
import { generateKeyPairSync, createVerify } from 'node:crypto';
import { jwtApp, compruebaPR, preparaGithub } from '../lib/github.mjs';
const { privateKey: PEM, publicKey: PUB } = generateKeyPairSync('rsa', { modulusLength: 2048,
  privateKeyEncoding: { type: 'pkcs8', format: 'pem' }, publicKeyEncoding: { type: 'spki', format: 'pem' } });
const cL = cfg({ NOTION_APROBADORES: `${AL},${BONZO}`, MA_ENVIRONMENT_ID: 'env_1', MA_AGENT_LANDING: 'agent_landing', MA_VAULT_LANDING: 'v_landing',
  GH_REPO_URL: 'https://github.com/5cero5/5cero5-marca', GH_AGENTES_URL: 'https://github.com/5cero5/5cero5-agentes', GH_REPO_READ_TOKEN: 'tok',
  GH_APP_ID: '123', GH_APP_INSTALLATION_ID: '456', GH_APP_PRIVATE_KEY: PEM.replace(/\n/g, '\\n'), MA_CRED_GITHUB_LANDING: 'vcrd_gh' });
const filaL = (o = {}) => fila({ agente: 'Landing', trabajo: 'Landing Buen Fin', brief: 'landing de la promo', ...o });

// GitHub falso: tokens de instalación, main, PR y sus archivos.
function ghFalso(o = {}) {
  const st = { tokens: [], pr: { state: 'open', merged: false, base: { ref: 'main' }, head: { ref: 'agente/buen-fin-1', sha: 'abc1234' }, html_url: 'https://github.com/5cero5/5cero5-landings/pull/7' },
    archivos: [{ filename: 'landings/buen-fin/index.html' }, { filename: 'landings/buen-fin/landing.json' }], main: ['m1'], ...o };
  st.fetch = async (url, init = {}) => {
    const u = new URL(url); const body = init.body ? JSON.parse(init.body) : null;
    const ok = x => ({ ok: true, status: 200, text: async () => JSON.stringify(x) });
    if (u.pathname === '/app/installations/456/access_tokens') {
      st.tokens.push({ auth: init.headers.Authorization, body });
      return ok({ token: `ghs_${st.tokens.length}`, expires_at: '2026-10-12T05:00:00Z' });
    }
    if (u.pathname === '/repos/5cero5/5cero5-landings/git/ref/heads/main') return ok({ object: { sha: st.main.length > 1 ? st.main.shift() : st.main[0] } });
    if (u.pathname === '/repos/5cero5/5cero5-landings/pulls/7') return ok(st.pr);
    if (u.pathname === '/repos/5cero5/5cero5-landings/pulls/7/files') return ok(st.archivos);
    return { ok: false, status: 404, text: async () => '{"message":"Not Found"}' };
  };
  return st;
}
const respL = { pr_url: 'https://github.com/5cero5/5cero5-landings/pull/7', pr_numero: 7, rama: 'agente/buen-fin-1', commit: 'abc1234', slug: 'buen-fin', cambios: ['titular'] };

test('github: el JWT de la app va firmado con su llave y vence en menos de 10 minutos', () => {
  const t = jwtApp('123', PEM.replace(/\n/g, '\\n'), 1000);
  const [h, p, f] = t.split('.');
  assert.ok(createVerify('RSA-SHA256').update(`${h}.${p}`).verify(PUB, Buffer.from(f, 'base64url')));
  const c = JSON.parse(Buffer.from(p, 'base64url'));
  assert.equal(c.iss, '123'); assert.ok(c.exp - c.iat <= 600);
});
test('github: la llave sirve aunque Netlify la guarde con espacios, \\n, CRLF o en base64; si no es PEM, error claro', () => {
  const verifica = pem => { const [h, p, f] = jwtApp('123', pem, 1000).split('.');
    return createVerify('RSA-SHA256').update(`${h}.${p}`).verify(PUB, Buffer.from(f, 'base64url')); };
  for (const v of [PEM, PEM.replace(/\n/g, ' '), PEM.replace(/\n/g, '\\n'), PEM.replace(/\n/g, '\r\n'), Buffer.from(PEM).toString('base64'), `  ${PEM}  `])
    assert.ok(verifica(v));
  assert.throws(() => jwtApp('123', 'no-es-una-llave', 1000), /GH_APP_PRIVATE_KEY/);
});
test('router: Landing monta marca, agentes y landings, usa su vault y abre PRs con pr_landing.py', () => {
  const p = parametrosSesion(filaL(), cL);
  assert.equal(p.agent, 'agent_landing'); assert.deepEqual(p.vault_ids, ['v_landing']);
  assert.deepEqual(p.resources.map(r => r.mount_path), ['/workspace/marca', '/workspace/agentes', '/workspace/landings']);
  assert.ok(!p.resources[2].authorization_token, 'el token del repo de landings lo pone preparaGithub');
  const m = p.initial_events[0].content[0].text;
  assert.match(m, /pr_landing\.py/); assert.match(m, /Nunca fusionas/); assert.match(m, /landings\/<slug>\//); assert.match(m, /pr_numero/);
  assert.doesNotMatch(m, /landing\.py construir/); assert.doesNotMatch(m, /correo\.py/);
});
test('github: antes de la sesión, token de escritura limitado al repo en el vault y token de lectura para montar', async () => {
  const g = ghFalso(); const upd = [];
  const client = { beta: { vaults: { credentials: { update: async (id, prm) => upd.push([id, prm]) } } } };
  const r = await preparaGithub({ client, c: cL, fetchImpl: g.fetch });
  assert.deepEqual(g.tokens.map(t => t.body), [
    { repositories: ['5cero5-landings'], permissions: { contents: 'write', pull_requests: 'write' } },
    { repositories: ['5cero5-landings'], permissions: { contents: 'read' } }]);
  assert.ok(g.tokens.every(t => t.auth.startsWith('Bearer ey')), 'se pide con el JWT de la app');
  assert.deepEqual(upd, [['vcrd_gh', { vault_id: 'v_landing', auth: { type: 'environment_variable', secret_value: 'ghs_1' } }]]);
  assert.equal(r.lectura, 'ghs_2'); assert.equal(r.mainSha, 'm1');
});
test('github: sin la configuración de la app no se abre la sesión de Landing', async () => {
  await assert.rejects(preparaGithub({ client: {}, c: cfg({ MA_VAULT_LANDING: 'v' }) }), /Falta configuración de GitHub para Landing: appId, installationId, privateKey, MA_CRED_GITHUB_LANDING/);
});
test('despacha Landing: renueva el token, monta landings con el de lectura y guarda el sha de main', async () => {
  const g = ghFalso(); const f = [filaL()]; const cl = mockClient(); const upd = [];
  cl.beta.vaults = { credentials: { update: async (id, prm) => upd.push(id) } };
  await despacha({ client: cl, notion: mockNotion(f), c: cL, fetchImpl: g.fetch });
  assert.equal(f[0].estado, 'En curso'); assert.deepEqual(upd, ['vcrd_gh']);
  const p = cl.calls.create[0];
  assert.equal(p.resources.find(r => r.mount_path === '/workspace/landings').authorization_token, 'ghs_2');
  assert.equal(p.metadata.main_sha, 'm1');
});
test('despacha: al reclamar un reintento limpia el Error del intento anterior', async () => {
  const f = [filaCRM({ intentos: 1 })]; const n = mockNotion(f);
  await despacha({ client: mockClient(), notion: n, c: cCRM });
  const reclamo = n.log.find(([, p]) => p.Estado?.select?.name === 'En curso')[1];
  assert.deepEqual(reclamo.Error, { rich_text: [] });
});
test('despacha Landing: si GitHub falla, la fila pasa a Error y no hay sesión', async () => {
  const f = [filaL()]; const cl = mockClient();
  cl.beta.vaults = { credentials: { update: async () => {} } };
  const caido = async () => ({ ok: false, status: 500, text: async () => '{"message":"boom"}' });
  await despacha({ client: cl, notion: mockNotion(f), c: cL, fetchImpl: caido });
  assert.equal(f[0].estado, 'Error'); assert.equal(cl.calls.create.length, 0);
});
test('formato: Landing exige pr_url, pr_numero, rama de agente, commit y slug', () => {
  const d = AGENTES.Landing;
  assert.equal(revisaRespuesta(d, 'Listo\n```json\n' + JSON.stringify(respL) + '\n```'), null);
  assert.equal(revisaRespuesta(d, JSON.stringify({ ...respL, rama: 'main' })), 'rama_no_es_de_agente');
  assert.equal(revisaRespuesta(d, JSON.stringify({ ...respL, slug: '../otra' })), 'slug_invalido');
  assert.equal(revisaRespuesta(d, '{"pr_url":"","pr_numero":"","rama":"","commit":"","slug":"","motivo":"el brief pide fotos"}'), 'faltan_claves:pr_url,pr_numero,rama,commit,slug');
});
test('comprobación del PR: pasa si está abierto, sin fusionar, con su commit y solo con su carpeta', async () => {
  const r = await compruebaPR({ c: cL, respuesta: respL, mainAntes: 'm1', fetchImpl: ghFalso().fetch });
  assert.equal(r.ok, true, r.informe); assert.match(r.informe, /PR #7/);
});
test('comprobación del PR: falla si está fusionado, toca otra carpeta, cambió el commit o main se movió', async () => {
  const casos = [
    [{ pr: { ...ghFalso().pr, state: 'closed', merged: true, merged_at: 'x' } }, /fusionado/],
    [{ archivos: [{ filename: 'landings/buen-fin/index.html' }, { filename: 'netlify/functions/prospecto/prospecto.js' }] }, /fuera de landings\/buen-fin\//],
    [{ pr: { ...ghFalso().pr, head: { ref: 'agente/buen-fin-1', sha: 'otro999' } } }, /no es el reportado/],
    [{ pr: { ...ghFalso().pr, head: { ref: 'main', sha: 'abc1234' } } }, /no empieza con agente\//],
    [{ main: ['m2'] }, /main cambió durante la sesión/],
    [{ archivos: [] }, /no cambia ningún archivo/],
  ];
  for (const [o, re] of casos) {
    const r = await compruebaPR({ c: cL, respuesta: respL, mainAntes: 'm1', fetchImpl: ghFalso(o).fetch });
    assert.equal(r.ok, false); assert.match(r.informe, re);
  }
  const r = await compruebaPR({ c: cL, respuesta: { ...respL, pr_numero: 99 }, mainAntes: 'm1', fetchImpl: ghFalso().fetch });
  assert.equal(r.ok, false); assert.match(r.informe, /#99 no existe/);
});
test('cierre de Landing: comprueba el PR en GitHub y marca el Verificador; nunca Listo', async () => {
  const f = [filaL({ estado: 'En curso', sesion: 'sesn_1' })]; const n = mockNotion(f);
  const cl = mockClient({ msg: JSON.stringify(respL) });
  cl.beta.sessions.retrieve = async () => ({ status: 'idle', metadata: { notion_page_id: 'p1', main_sha: 'm1' }, usage: {} });
  await cierraSesion({ client: cl, notion: n, c: cL, sessionId: 'sesn_1', fetchImpl: ghFalso().fetch });
  const props = n.log.at(-1)[1];
  assert.equal(f[0].estado, 'Para revisar'); assert.equal(props.Verificador.select.name, 'Aprobada');
  assert.match(props['Informe del Verificador'].rich_text[0].text.content, /PR #7/);
  const f2 = [filaL({ estado: 'En curso', sesion: 'sesn_1' })]; const n2 = mockNotion(f2);
  await cierraSesion({ client: cl, notion: n2, c: cL, sessionId: 'sesn_1', fetchImpl: ghFalso({ main: ['m9'] }).fetch });
  assert.equal(n2.log.at(-1)[1].Verificador.select.name, 'Rechazada'); assert.equal(f2[0].estado, 'Para revisar');
});

// ---- Agente Creativo (PR en 5cero5-piezas con la misma GitHub App) ----
import { medidasPng } from '../lib/github.mjs';
const cC = cfg({ NOTION_APROBADORES: `${AL},${BONZO}`, MA_ENVIRONMENT_ID: 'env_1', MA_AGENT_CREATIVO: 'agent_creativo', MA_VAULT_CREATIVO: 'v_creativo',
  GH_REPO_URL: 'https://github.com/5cero5/5cero5-marca', GH_AGENTES_URL: 'https://github.com/5cero5/5cero5-agentes', GH_REPO_READ_TOKEN: 'tok',
  GH_APP_ID: '123', GH_APP_INSTALLATION_ID: '456', GH_APP_PRIVATE_KEY: PEM, MA_CRED_GITHUB_CREATIVO: 'vcrd_cr' });
const filaC = (o = {}) => fila({ agente: 'Creativo', trabajo: 'Post 4:5 · agencia vs 5cero5', brief: 'post del diagnóstico. Foto: no', ...o });
const respC = { pr_url: 'https://github.com/5cero5/5cero5-piezas/pull/8', pr_numero: 8, rama: 'agente/poc-post-a-1', commit: 'abc1234',
  campana: 'poc', pieza: 'post-a', formato: 'post-4x5', foto: false };
function png(w, h) {
  const b = Buffer.alloc(40); Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]).copy(b, 0);
  b.writeUInt32BE(13, 8); b.write('IHDR', 12, 'ascii'); b.writeUInt32BE(w, 16); b.writeUInt32BE(h, 20); return b;
}
// GitHub falso de piezas: PR #8, sus archivos y la carpeta en la punta del PR.
function ghPiezas(o = {}) {
  const pref = 'piezas/poc/post-a';
  const st = { tokens: [], main: ['m1'],
    pr: { state: 'open', merged: false, base: { ref: 'main' }, head: { ref: 'agente/poc-post-a-1', sha: 'abc1234' }, html_url: respC.pr_url },
    carpeta: ['pieza.png', 'pieza.html', 'copia.json', 'pieza.json', 'informe.json'].map(name => ({ name, type: 'file', sha: name === 'pieza.png' ? 'pngsha' : `s-${name}` })),
    fotos: null, png: png(1080, 1350),
    informe: { aprobada: true, png_blob_sha: 'pngsha', formato: 'post-4x5', formato_pedido: 'post-4x5', repo_version: '0.12.0', avisos: [{ id: 'paleta' }] },
    meta: { campana: 'poc', pieza: 'post-a', formato: 'post-4x5', foto: false }, ...o };
  st.archivos = o.archivos || st.carpeta.map(e => ({ filename: `${pref}/${e.name}`, sha: e.sha }));
  st.fetch = async (url, init = {}) => {
    const u = new URL(url); const body = init.body ? JSON.parse(init.body) : null;
    const ok = x => ({ ok: true, status: 200, text: async () => JSON.stringify(x) });
    const b64 = x => ({ content: Buffer.from(typeof x === 'string' ? x : JSON.stringify(x)).toString('base64'), encoding: 'base64' });
    const R = '/repos/5cero5/5cero5-piezas';
    if (u.pathname === '/app/installations/456/access_tokens') { st.tokens.push({ body }); return ok({ token: `ghs_${st.tokens.length}` }); }
    if (u.pathname === `${R}/git/ref/heads/main`) return ok({ object: { sha: st.main.length > 1 ? st.main.shift() : st.main[0] } });
    if (u.pathname === `${R}/pulls/8`) return ok(st.pr);
    if (u.pathname === `${R}/pulls/8/files`) return ok(st.archivos);
    if (u.pathname === `${R}/contents/${pref}`) return ok([...st.carpeta, ...(st.fotos ? [{ name: 'fotos', type: 'dir' }] : [])]);
    if (u.pathname === `${R}/contents/${pref}/fotos` && st.fotos) return ok(st.fotos);
    if (u.pathname === `${R}/contents/${pref}/informe.json`) return ok(b64(st.informe));
    if (u.pathname === `${R}/contents/${pref}/pieza.json`) return ok(b64(st.meta));
    if (u.pathname === `${R}/git/blobs/pngsha`) return ok({ content: st.png.toString('base64'), encoding: 'base64' });
    return { ok: false, status: 404, text: async () => '{"message":"Not Found"}' };
  };
  return st;
}

test('router: Creativo monta marca y agentes, usa su vault y trabaja con pr_pieza.py', () => {
  const p = parametrosSesion(filaC(), cC);
  assert.equal(p.agent, 'agent_creativo'); assert.deepEqual(p.vault_ids, ['v_creativo']);
  assert.deepEqual(p.resources.map(r => r.mount_path), ['/workspace/marca', '/workspace/agentes']);
  const m = p.initial_events[0].content[0].text;
  assert.match(m, /pr_pieza\.py/); assert.match(m, /Nunca fusionas/); assert.match(m, /Foto: sí/); assert.match(m, /pr_numero/);
  assert.doesNotMatch(m, /deploy_id/); assert.doesNotMatch(m, /Netlify/);
});
test('github: el Creativo recibe un token de escritura solo de 5cero5-piezas, en su credencial', async () => {
  const g = ghPiezas(); const upd = [];
  const client = { beta: { vaults: { credentials: { update: async (id, prm) => upd.push([id, prm]) } } } };
  const r = await preparaGithub({ client, c: cC, agente: 'Creativo', fetchImpl: g.fetch });
  assert.deepEqual(g.tokens.map(t => t.body.repositories), [['5cero5-piezas'], ['5cero5-piezas']]);
  assert.deepEqual(upd, [['vcrd_cr', { vault_id: 'v_creativo', auth: { type: 'environment_variable', secret_value: 'ghs_1' } }]]);
  assert.equal(r.mainSha, 'm1');
  await assert.rejects(preparaGithub({ client, c: cfg({ ...{ GH_APP_ID: '1' } }), agente: 'Creativo' }), /Creativo: installationId, privateKey, MA_CRED_GITHUB_CREATIVO, MA_VAULT_CREATIVO/);
});
test('despacha Creativo: renueva su token y guarda el sha de main; no monta piezas', async () => {
  const g = ghPiezas(); const f = [filaC()]; const cl = mockClient(); const upd = [];
  cl.beta.vaults = { credentials: { update: async id => upd.push(id) } };
  await despacha({ client: cl, notion: mockNotion(f), c: cC, fetchImpl: g.fetch });
  assert.deepEqual(upd, ['vcrd_cr']); const p = cl.calls.create[0];
  assert.equal(p.metadata.main_sha, 'm1'); assert.ok(p.resources.every(r => r.authorization_token === 'tok'));
});
test('formato: Creativo exige PR, campaña, pieza y formato conocido', () => {
  const d = AGENTES.Creativo;
  assert.equal(revisaRespuesta(d, JSON.stringify(respC)), null);
  assert.equal(revisaRespuesta(d, JSON.stringify({ ...respC, formato: 'reel' })), 'formato_desconocido');
  assert.equal(revisaRespuesta(d, JSON.stringify({ ...respC, pieza: '../x' })), 'carpeta_invalida');
  assert.equal(revisaRespuesta(d, JSON.stringify({ ...respC, rama: 'main' })), 'rama_no_es_de_agente');
});
test('medidas del PNG desde su cabecera', () => {
  assert.deepEqual(medidasPng(png(1080, 1920)), [1080, 1920]); assert.equal(medidasPng(Buffer.from('no es png')), null);
});
test('comprobación de la pieza: pasa con su carpeta completa, informe aprobado del mismo PNG y medidas del formato', async () => {
  const r = await compruebaPR({ c: cC, agente: 'Creativo', respuesta: respC, mainAntes: 'm1', fetchImpl: ghPiezas().fetch });
  assert.equal(r.ok, true, r.informe); assert.match(r.informe, /PR #8/); assert.match(r.informe, /v0\.12\.0: aprobada, 1 aviso/);
  const conFoto = ghPiezas({ meta: { ...ghPiezas().meta, foto: true }, fotos: [{ name: 'fondo.jpg', type: 'file' }] });
  conFoto.carpeta.push({ name: 'prompt.txt', type: 'file', sha: 'p' });
  const r2 = await compruebaPR({ c: cC, agente: 'Creativo', respuesta: { ...respC, foto: true }, mainAntes: 'm1', fetchImpl: conFoto.fetch });
  assert.equal(r2.ok, true, r2.informe); assert.match(r2.informe, /con foto de Higgsfield/);
});
test('comprobación de la pieza: falla por informe, PNG, formato, foto, archivos de más o fuera de su carpeta', async () => {
  const base = ghPiezas();
  const casos = [
    [{ informe: { ...base.informe, aprobada: false } }, respC, /no está aprobado/],
    [{ informe: { ...base.informe, png_blob_sha: 'otro' } }, respC, /de otro PNG/],
    [{ png: png(1080, 1080) }, respC, /mide 1080x1080, no 1080x1350/],
    [{}, { ...respC, formato: 'post-1x1' }, /formato: el agente dice post-1x1/],
    [{}, { ...respC, foto: true }, /foto: el agente dice true/],
    [{ meta: { ...base.meta, foto: true } }, { ...respC, foto: true }, /faltan la foto o prompt\.txt/],
    [{ carpeta: [...base.carpeta, { name: 'script.js', type: 'file', sha: 'x' }] }, respC, /no van en una pieza: script\.js/],
    [{ carpeta: base.carpeta.filter(e => e.name !== 'informe.json') }, respC, /faltan en la carpeta: informe\.json/],
    [{ archivos: [{ filename: 'piezas/poc/post-a/pieza.png' }, { filename: 'piezas/otra/x/pieza.png' }] }, respC, /fuera de piezas\/poc\/post-a\//],
    [{ pr: { ...base.pr, merged: true, merged_at: 'x', state: 'closed' } }, respC, /fusionado/],
  ];
  for (const [o, resp, re] of casos) {
    const r = await compruebaPR({ c: cC, agente: 'Creativo', respuesta: resp, mainAntes: 'm1', fetchImpl: ghPiezas(o).fetch });
    assert.equal(r.ok, false, `${re}`); assert.match(r.informe, re);
  }
});
test('cierre de Creativo: comprueba PR y pieza y deja la fila Para revisar; nunca Listo', async () => {
  const f = [filaC({ estado: 'En curso', sesion: 'sesn_1' })]; const n = mockNotion(f);
  const cl = mockClient({ msg: 'Listo.\n```json\n' + JSON.stringify(respC) + '\n```' });
  cl.beta.sessions.retrieve = async () => ({ status: 'idle', metadata: { notion_page_id: 'p1', main_sha: 'm1' }, usage: {} });
  await cierraSesion({ client: cl, notion: n, c: cC, sessionId: 'sesn_1', fetchImpl: ghPiezas().fetch });
  const props = n.log.at(-1)[1];
  assert.equal(f[0].estado, 'Para revisar'); assert.equal(props.Verificador.select.name, 'Aprobada');
  assert.match(props['Informe del Verificador'].rich_text[0].text.content, /Pieza post-4x5/);
});

// ---- Agente Pauta (campaña en Meta, siempre en pausa; piezas de 5cero5-piezas montadas solo lectura) ----
import { compruebaCampana } from '../lib/meta.mjs';
const cP = cfg({ NOTION_APROBADORES: `${AL},${BONZO}`, MA_ENVIRONMENT_ID: 'env_1', MA_AGENT_PAUTA: 'agent_pauta', MA_VAULT_PAUTA: 'v_pauta',
  GH_REPO_URL: 'https://github.com/5cero5/5cero5-marca', GH_AGENTES_URL: 'https://github.com/5cero5/5cero5-agentes', GH_REPO_READ_TOKEN: 'tok',
  GH_APP_ID: '123', GH_APP_INSTALLATION_ID: '456', GH_APP_PRIVATE_KEY: PEM,
  META_AD_ACCOUNT_ID: '1234567', META_PAGE_ID: '1127307763190247', META_TOKEN: 'EAAh', META_TOPE_DIARIO_MXN: '1500' });
const filaP = (o = {}) => fila({ agente: 'Pauta', trabajo: 'Pauta · agencia vs 5cero5', inicio: '2026-10-14T16:00:00.000Z',
  brief: 'Nombre en Meta: 2026-10_mty_agencia-vs-505. Presupuesto diario: 500 MXN.', ...o });
const respP = { campana_meta_id: '900', nombre: '2026-10_mty_agencia-vs-505', cuenta: 'act_1234567', conjunto_id: '901',
  anuncios: [{ id: '902', nombre: 'a01_post4x5_agencia', pieza: 'post-a' }, { id: '903', nombre: 'a02_historia_agencia', pieza: 'historia-a' }],
  presupuesto_diario_mxn: 500, objetivo: 'trafico' };
// Graph API falsa: campaña 900, conjunto 901, anuncios 902 y 903. Registra los POST (el freno).
function metaFalsa(o = {}) {
  const ad = (id, x = {}) => ({ id, name: `a-${id}`, status: 'PAUSED', creative: { id: `c${id}`, url_tags: 'utm_source=meta&utm_medium=paid_social',
    object_story_spec: { page_id: '1127307763190247', link_data: { link: 'https://marketing.5cero5.com/diagnostico/' } } }, ...x });
  const st = { posts: [], auth: new Set(),
    camp: { id: '900', name: respP.nombre, status: 'PAUSED', objective: 'OUTCOME_TRAFFIC', account_id: '1234567', created_time: '2026-10-14T16:05:00+0000' },
    conjuntos: [{ id: '901', name: 'mty_duenos-pyme', status: 'PAUSED', daily_budget: '50000', lifetime_budget: '0' }],
    ads: [ad('902'), ad('903')], cuenta: { spend_cap: '4500000', amount_spent: '0' }, ...o };
  st.ad = ad;
  st.fetch = async (url, init = {}) => {
    const u = new URL(url); st.auth.add(init.headers?.Authorization);
    const ok = x => ({ ok: true, status: 200, text: async () => JSON.stringify(x) });
    if (init.method === 'POST') { st.posts.push([u.pathname, String(init.body)]); return ok({ success: true }); }
    const p = u.pathname.replace('/v25.0', '');
    if (p === '/900') return ok(st.camp);
    if (p === '/900/adsets') return ok({ data: st.conjuntos });
    if (p === '/900/ads') return ok({ data: st.ads });
    if (p === '/act_1234567') return ok(st.cuenta);
    return { ok: false, status: 400, text: async () => '{"error":{"message":"Unsupported get request"}}' };
  };
  return st;
}

test('router: Pauta monta agentes y piezas, usa su vault y recibe cuenta, página, tope y el comando', () => {
  const p = parametrosSesion(filaP(), cP);
  assert.equal(p.agent, 'agent_pauta'); assert.deepEqual(p.vault_ids, ['v_pauta']);
  assert.deepEqual(p.resources.map(r => r.mount_path), ['/workspace/agentes', '/workspace/piezas']);
  assert.ok(!p.resources[1].authorization_token, 'el token de lectura de piezas lo pone preparaGithub');
  const m = p.initial_events[0].content[0].text;
  assert.match(m, /cuenta act_1234567, página 1127307763190247, sin Instagram, sin Pixel/);
  assert.match(m, /--tope-mxn 1500 --dominios marketing\.5cero5\.com/); assert.match(m, /nunca activas/);
  assert.doesNotMatch(m, /EAAh/, 'el token nunca va en el mensaje');
});
test('router: Pauta sin cuenta o página de Meta no abre sesión', () => {
  assert.throws(() => parametrosSesion(filaP(), cfg({ ...cP, MA_ENVIRONMENT_ID: 'env_1', MA_AGENT_PAUTA: 'a', GH_AGENTES_URL: 'https://github.com/o/a' })),
    /Falta configuración de Meta para Pauta: META_AD_ACCOUNT_ID, META_PAGE_ID/);
});
test('github: Pauta solo recibe token de LECTURA de piezas y no toca ningún vault', async () => {
  const g = ghPiezas(); const upd = [];
  const client = { beta: { vaults: { credentials: { update: async (id, prm) => upd.push([id, prm]) } } } };
  await preparaGithub({ client, c: cP, agente: 'Pauta', fetchImpl: g.fetch });
  assert.deepEqual(g.tokens.map(t => t.body), [{ repositories: ['5cero5-piezas'], permissions: { contents: 'read' } }]);
  assert.deepEqual(upd, []);
});
test('despacha Pauta: monta piezas con el token de lectura', async () => {
  const g = ghPiezas(); const f = [filaP()]; const cl = mockClient();
  cl.beta.vaults = { credentials: { update: async () => { throw new Error('no debe tocar vaults'); } } };
  await despacha({ client: cl, notion: mockNotion(f), c: cP, fetchImpl: g.fetch });
  const p = cl.calls.create[0];
  assert.equal(p.resources.find(r => r.mount_path === '/workspace/piezas').authorization_token, 'ghs_1');
});
test('formato: Pauta exige nombre de la convención, ids numéricos y anuncios', () => {
  const d = AGENTES.Pauta;
  assert.equal(revisaRespuesta(d, JSON.stringify(respP)), null);
  assert.equal(revisaRespuesta(d, JSON.stringify({ ...respP, nombre: 'Campaña octubre' })), 'nombre_fuera_de_convencion');
  assert.equal(revisaRespuesta(d, JSON.stringify({ ...respP, campana_meta_id: 'act_1' })), 'ids_invalidos');
  assert.equal(revisaRespuesta(d, JSON.stringify({ ...respP, anuncios: [] })), 'anuncios_invalidos');
});
test('meta: pasa con todo en pausa, en la cuenta y página, dentro del tope; el token va en el encabezado', async () => {
  const m = metaFalsa();
  const r = await compruebaCampana({ c: cP, respuesta: respP, inicio: '2026-10-14T16:00:00.000Z', fetchImpl: m.fetch });
  assert.equal(r.ok, true, r.informe); assert.match(r.informe, /2 anuncio\(s\), 500 MXN al día/); assert.match(r.informe, /encenderla \(Al o Bonzo\)/);
  assert.deepEqual(m.posts, []); assert.deepEqual([...m.auth], ['Bearer EAAh']);
});
test('meta: lo que no esté en pausa lo pausa el harness y la fila sale Rechazada', async () => {
  const m = metaFalsa(); m.ads[1] = m.ad('903', { status: 'ACTIVE' }); m.camp.status = 'ACTIVE';
  const r = await compruebaCampana({ c: cP, respuesta: respP, inicio: '2026-10-14T16:00:00.000Z', fetchImpl: m.fetch });
  assert.equal(r.ok, false); assert.deepEqual(m.posts.map(p => p[0]).sort(), ['/v25.0/900', '/v25.0/903']);
  assert.ok(m.posts.every(p => p[1] === 'status=PAUSED')); assert.match(r.informe, /el harness la pausó/);
});
test('meta: falla por cuenta, página, destino, tope, presupuesto total, anuncios de más o campaña vieja', async () => {
  const casos = [
    [m => { m.camp.account_id = '999'; }, /act_999, no de act_1234567/],
    [m => { m.ads[0].creative.object_story_spec.page_id = '555'; }, /no usa la página/],
    [m => { m.ads[0].creative.object_story_spec.link_data.link = 'https://otro.com/'; }, /fuera de marketing\.5cero5\.com/],
    [m => { m.conjuntos[0].daily_budget = '200000'; }, /2000 MXN al día, arriba del tope de 1500/],
    [m => { m.conjuntos[0].lifetime_budget = '900000'; }, /presupuesto total/],
    [m => { m.ads.push(m.ad('904')); }, /Meta tiene 3/],
    [m => { m.conjuntos.push({ ...m.conjuntos[0], id: '905' }); }, /2 conjuntos/],
    [m => { m.camp.created_time = '2026-10-01T00:00:00+0000'; }, /anterior a esta sesión/],
    [m => { m.camp.name = 'otra'; }, /se llama otra/],
  ];
  for (const [cambia, re] of casos) {
    const m = metaFalsa(); cambia(m);
    const r = await compruebaCampana({ c: cP, respuesta: respP, inicio: '2026-10-14T16:00:00.000Z', fetchImpl: m.fetch });
    assert.equal(r.ok, false, `${re}`); assert.match(r.informe, re);
  }
});
test('meta: sin límite de gasto en la cuenta pasa con aviso; sin token no se da por buena', async () => {
  const m = metaFalsa({ cuenta: { spend_cap: '0' } });
  const r = await compruebaCampana({ c: cP, respuesta: respP, inicio: null, fetchImpl: m.fetch });
  assert.equal(r.ok, true); assert.match(r.informe, /no tiene límite de gasto/);
  const sin = await compruebaCampana({ c: cfg({ META_AD_ACCOUNT_ID: '1', META_PAGE_ID: '2' }), respuesta: respP, fetchImpl: m.fetch });
  assert.equal(sin.ok, false); assert.match(sin.informe, /falta META_TOKEN/);
});
test('cierre de Pauta: comprueba en Meta y deja la fila Para revisar; nunca Listo', async () => {
  const f = [filaP({ estado: 'En curso', sesion: 'sesn_1' })]; const n = mockNotion(f);
  const cl = mockClient({ msg: 'Creada en pausa.\n' + JSON.stringify(respP) });
  await cierraSesion({ client: cl, notion: n, c: cP, sessionId: 'sesn_1', fetchImpl: metaFalsa().fetch });
  const props = n.log.at(-1)[1];
  assert.equal(f[0].estado, 'Para revisar'); assert.equal(props.Verificador.select.name, 'Aprobada');
  assert.match(props['Informe del Verificador'].rich_text[0].text.content, /Comprobación en Meta: campaña 900/);
  const f2 = [filaP({ estado: 'En curso', sesion: 'sesn_1' })]; const n2 = mockNotion(f2);
  await cierraSesion({ client: mockClient({ msg: 'no pude' }), notion: n2, c: cP, sessionId: 'sesn_1', fetchImpl: metaFalsa().fetch });
  assert.equal(n2.log.at(-1)[1].Verificador.select.name, 'Rechazada'); assert.match(n2.log.at(-1)[1]['Informe del Verificador'].rich_text[0].text.content, /Revisar a mano/);
});
test('CMO: Pauta no aparece entre los agentes de pieza disponibles', () => {
  const cc = cfg({ ...{}, MA_AGENT_CMO: 'a', MA_AGENT_PAUTA: 'p', MA_AGENT_CREATIVO: 'cr' });
  const b = briefDeCampana({ nombre: 'K', id: 'k1', ruta: 'Cita', canales: [], formatos: [], piezas: 1 }, cc);
  assert.match(b, /Agentes disponibles hoy: Creativo\./);
});

test('cierre de Pauta a medias: con el id de la campaña igual la lee en Meta y frena; sin id, revisión a mano', async () => {
  const f = [filaP({ estado: 'En curso', sesion: 'sesn_1' })]; const n = mockNotion(f);
  const m = metaFalsa({ conjuntos: [], ads: [] }); m.camp.status = 'ACTIVE';
  const resp = { ...respP, conjunto_id: '', anuncios: [], motivo: 'Meta rechazó el conjunto' };
  await cierraSesion({ client: mockClient({ msg: JSON.stringify(resp) }), notion: n, c: cP, sessionId: 'sesn_1', fetchImpl: m.fetch });
  const props = n.log.at(-1)[1]; const inf = props['Informe del Verificador'].rich_text[0].text.content;
  assert.equal(props.Verificador.select.name, 'Rechazada'); assert.match(inf, /faltan_claves:conjunto_id/);
  assert.match(inf, /campaña 900/); assert.match(inf, /el harness la pausó/); assert.deepEqual(m.posts.map(p => p[0]), ['/v25.0/900']);
  const f2 = [filaP({ estado: 'En curso', sesion: 'sesn_1' })]; const n2 = mockNotion(f2);
  await cierraSesion({ client: mockClient({ msg: '{"campana_meta_id":"","motivo":"no"}' }), notion: n2, c: cP, sessionId: 'sesn_1', fetchImpl: metaFalsa().fetch });
  assert.match(n2.log.at(-1)[1]['Informe del Verificador'].rich_text[0].text.content, /no trae el id de la campaña/);
});
