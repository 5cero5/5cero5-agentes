import test from 'node:test';
import assert from 'node:assert/strict';
import { cfg, eventoDeCierre } from '../lib/config.mjs';
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
