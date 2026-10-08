import test from 'node:test';
import assert from 'node:assert/strict';
import { cfg } from '../lib/config.mjs';
import { esDespachable, despacha } from '../lib/despacho.mjs';
import { parametrosSesion } from '../lib/sessions.mjs';
import { cierraSesion } from '../lib/cierre.mjs';
import { barre } from '../lib/barrido.mjs';

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
