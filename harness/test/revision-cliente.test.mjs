// Revisión y aprobación del cliente (épica E2) con dos clientes falsos, A y B. Todo con un Notion simulado en memoria
// que aplica filtros y escrituras (para comprobar readback y fallos parciales). Ninguna llamada real.
import test from 'node:test';
import assert from 'node:assert/strict';
import { cfg } from '../lib/config.mjs';
import { codigoDe, textoUtil, huellaDe, revisionCliente } from '../lib/revision-cliente.mjs';

const DS_REV = 'ds-revisiones';
const DS_DEC_A = 'ds-decisiones-a', DS_DEC_B = 'ds-decisiones-b';  // una base de entrada por cliente
const DS_CLI = '33723502-0b79-45e1-ac42-b123a22fff80';
const CLI_A = 'cli-a', CLI_B = 'cli-b', CLI_X = 'cli-x';
const REVISOR_A = 'user-rev-a', REVISOR_A2 = 'user-rev-a2', REVISOR_B = 'user-rev-b', ALE = 'user-ale', BOT = 'bot-form';
const AHORA = Date.parse('2026-11-27T12:00:00Z');

const c = cfg({ REVISION_CLIENTE: '1', REVISION_CLIENTE_CLIENTES: `${CLI_A}=${DS_DEC_A}, ${CLI_B}=${DS_DEC_B}`,
  NOTION_REVISIONES_ID: DS_REV });

const MANIF_A1 = JSON.stringify({ version: 1, entregable: 'correo-bienvenida', componentes: [
  { rol: 'hero', nombre: 'hero.png', tipo: 'image/png', sha256: 'a'.repeat(64), origen: 'notion:1' },
  { rol: 'pie', nombre: 'pie.png', tipo: 'image/png', sha256: 'b'.repeat(64), origen: 'notion:2' }] });
const MANIF_A2 = JSON.stringify({ version: 1, entregable: 'correo-bienvenida', componentes: [
  { rol: 'hero', nombre: 'hero.png', tipo: 'image/png', sha256: 'a'.repeat(64), origen: 'notion:1' },
  { rol: 'pie', nombre: 'pie-v2.png', tipo: 'image/png', sha256: 'c'.repeat(64), origen: 'notion:3' }] });
const MANIF_B1 = JSON.stringify({ version: 1, entregable: 'journey', componentes: [
  { rol: 'documento', nombre: 'journey.pdf', tipo: 'application/pdf', sha256: 'd'.repeat(64), origen: 'notion:4' }] });

const rt = s => ({ rich_text: s ? [{ plain_text: s }] : [] });
function revPage(o) {
  return { id: o.id, created_time: o.creada || '2026-11-27T10:00:00.000Z', parent: { type: 'data_source_id', data_source_id: DS_REV },
    properties: {
      'Revisión': { title: [{ plain_text: o.titulo || o.id }] },
      'Código': { unique_id: { prefix: 'REVCLI', number: o.codigo } },
      'Cliente': { relation: (o.cliente === undefined ? [CLI_A] : o.cliente).map(id => ({ id })) },
      'Entregable': rt(o.entregable ?? 'correo-bienvenida'),
      'Secuencia': { number: o.secuencia ?? null },
      'Estado': { select: o.estado ? { name: o.estado } : null },
      'Manifiesto': rt(o.manifiesto ?? MANIF_A1),
      'Huella': rt(o.huella || ''),
      'Página del cliente': { url: o.pagina === undefined ? `https://app.notion.com/p/${o.id}pres` : o.pagina },
      'Reemplaza a': { relation: (o.reemplazaA || []).map(id => ({ id })) },
      'Reemplazada por': { relation: (o.reemplazadaPor || []).map(id => ({ id })) },
      'Recibo': rt(o.recibo || ''),
      'Expuesta el': { date: null },
    } };
}
function decPage(o) {
  const actor = o.actor === null ? undefined : { object: 'user', id: o.actor ?? REVISOR_A };
  return { id: o.id, created_time: o.creada, created_by: actor, last_edited_by: o.editor ? { object: 'user', id: o.editor } : actor,
    parent: { type: 'data_source_id', data_source_id: o.ds ?? (o.actor === REVISOR_B ? DS_DEC_B : DS_DEC_A) },
    properties: {
      'Resumen': { title: [{ plain_text: o.resumen || 'decisión' }] },
      'Tipo': { select: o.tipo ? { name: o.tipo } : null },
      'Código de revisión': rt(o.codigo ?? 'REVCLI-1'),
      'Confirmo la revisión completa': { checkbox: o.confirmo === true },
      'Descripción de los cambios': rt(o.descripcion || ''),
      'Resultado': { select: o.resultado ? { name: o.resultado } : null },
      'Motivo': rt(''), 'Clave': rt(o.clave || ''),
      'Revisión': { relation: (o.revision || []).map(id => ({ id })) },
      'Actor verificado': { people: [] },
      'Procesada el': { date: null },
    } };
}
function cliPage(id, revisores, ds = DS_CLI) {
  return { id, parent: { type: 'data_source_id', data_source_id: ds }, properties: {
    'Cliente': { title: [{ plain_text: id }] }, 'Revisores del cliente': { people: revisores.map(x => ({ id: x })) },
    'Aprobadores': { people: [{ id: 'user-al' }] } } };
}

// ---------- Notion en memoria ----------
const sel = p => p?.select?.name ?? null;
const txt = p => (p?.rich_text || p?.title || []).map(x => x.plain_text).join('');
function cumple(page, f) {
  if (!f) return true;
  if (f.and) return f.and.every(x => cumple(page, x));
  if (f.or) return f.or.some(x => cumple(page, x));
  const p = page.properties[f.property];
  if (f.select) {
    if ('equals' in f.select) return sel(p) === f.select.equals;
    if ('is_empty' in f.select) return sel(p) === null;
    if ('does_not_equal' in f.select) return sel(p) !== f.select.does_not_equal;
  }
  if (f.unique_id) return p?.unique_id?.number === f.unique_id.equals;
  if (f.relation) return (p?.relation || []).some(r => r.id === f.relation.contains);
  if (f.rich_text) return txt(p) === f.rich_text.equals;
  throw new Error(`filtro no soportado: ${JSON.stringify(f)}`);
}
function aplica(page, props) {
  for (const [k, v] of Object.entries(props)) {
    if (!(k in page.properties)) throw new Error(`Notion 400: propiedad ${k} no existe`);
    if ('select' in v) page.properties[k] = { select: v.select };
    else if ('rich_text' in v) page.properties[k] = { rich_text: v.rich_text.map(x => ({ plain_text: x.text.content })) };
    else if ('number' in v) page.properties[k] = { number: v.number };
    else if ('date' in v) page.properties[k] = { date: v.date };
    else if ('relation' in v) page.properties[k] = { relation: v.relation };
    else if ('people' in v) page.properties[k] = { people: v.people };
    else throw new Error(`tipo no soportado en ${k}`);
  }
}
function mundo({ revs = [], decs = [], clientes, fallos = {} } = {}) {
  const pages = new Map();
  for (const p of [...revs, ...decs, ...(clientes || [cliPage(CLI_A, [REVISOR_A, REVISOR_A2]), cliPage(CLI_B, [REVISOR_B]), cliPage(CLI_X, [REVISOR_A])])]) pages.set(p.id, p);
  const llamadas = { query: [], update: [], get: [] };
  const ds = id => [...pages.values()].filter(p => p.parent?.data_source_id === id);
  const notion = {
    async query(dsId, filter, pageSize = 50, extra = {}) {
      llamadas.query.push({ ds: dsId, filter, extra });
      if (![DS_REV, DS_DEC_A, DS_DEC_B].includes(dsId)) throw new Error(`consulta a una base ajena: ${dsId}`);
      if (fallos.query?.(dsId, filter)) throw new Error('Notion POST query 429: rate_limited');
      let r = ds(dsId).filter(p => cumple(p, filter));
      if (extra.sorts?.[0]?.timestamp === 'created_time') r = [...r].sort((a, b) => Date.parse(a.created_time) - Date.parse(b.created_time));
      const desde = Number(extra.start_cursor || 0);
      const mas = r.length > desde + pageSize;
      return { results: r.slice(desde, desde + pageSize).map(p => structuredClone(p)), has_more: mas, next_cursor: mas ? String(desde + pageSize) : null };
    },
    async get(id) {
      llamadas.get.push(id);
      if (fallos.get?.(id)) throw new Error('Notion GET 503: fallo simulado');
      if (!pages.has(id)) throw new Error(`Notion GET /pages/${id} 404`);
      return structuredClone(pages.get(id));
    },
    async update(id, props) {
      llamadas.update.push({ id, props });
      if (fallos.update?.(id, props)) throw new Error('Notion PATCH 502: fallo simulado');
      const page = pages.get(id);
      if (!page) throw new Error(`Notion PATCH /pages/${id} 404`);
      if (fallos.ignora?.(id, props)) return structuredClone(page);   // responde OK sin guardar (readback divergente)
      aplica(page, props);
      return structuredClone(page);
    },
  };
  const estado = id => sel(pages.get(id).properties['Estado']);
  const resultado = id => sel(pages.get(id).properties['Resultado']);
  const motivo = id => txt(pages.get(id).properties['Motivo']);
  return { notion, pages, llamadas, estado, resultado, motivo };
}
const expuesta = (o = {}) => revPage({ id: 'rev-a1', codigo: 1, estado: 'En revisión', secuencia: 1, huella: huellaDe(o.manifiesto ?? MANIF_A1).huella, ...o });
const corre = (m, extra = {}) => revisionCliente({ notion: m.notion, c: { ...c, ...extra }, ahora: AHORA });

// ---------- piezas puras ----------
test('E2-03 · código de revisión: sólo REVCLI-n exacto (tolera espacios, guion opcional y minúsculas)', () => {
  assert.equal(codigoDe('REVCLI-12'), 12);
  assert.equal(codigoDe('  revcli 7 '), 7);
  assert.equal(codigoDe('REVCLI3'), 3);
  for (const malo of ['', '12', 'REVCLI-', 'REVCLI-1 y REVCLI-2', 'REVCLI-1x', 'XREVCLI-1', 'REVCLI--1']) assert.equal(codigoDe(malo), null, malo);
});

test('E2-03 · descripción útil: vacío, espacios, saltos, NBSP y caracteres invisibles no cuentan', () => {
  for (const vacio of ['', '   ', '\n\n\t', '  ', '​‌‍﻿', ' 　 \n', 'ㅤ', '⠀⠀', '­', '‎‮']) assert.equal(textoUtil(vacio), '', JSON.stringify(vacio));
  assert.equal(textoUtil('  Cambia el pie \n'), 'Cambia el pie');
});

test('E2-03 · huella: estable ante el orden de llaves; manifiesto inválido explica el motivo', () => {
  const a = huellaDe('{"version":1,"componentes":[{"rol":"hero","nombre":"h.png","sha256":"' + 'a'.repeat(64) + '"}]}');
  const b = huellaDe('{"componentes":[{"sha256":"' + 'a'.repeat(64) + '","nombre":"h.png","rol":"hero"}],"version":1}');
  assert.equal(a.ok, true); assert.equal(a.huella, b.huella); assert.match(a.huella, /^[0-9a-f]{64}$/);
  assert.equal(huellaDe('no es json').ok, false);
  assert.equal(huellaDe('{"componentes":[]}').ok, false);
  assert.match(huellaDe('{"componentes":[{"rol":"hero","nombre":"h.png","sha256":"corto"}]}').motivo, /sha256/);
});

// ---------- apagado por defecto ----------
test('E2-03 · apagado por defecto: sin REVISION_CLIENTE=1 no consulta ni escribe nada', async () => {
  const m = mundo({ revs: [expuesta()], decs: [decPage({ id: 'd1', creada: '2026-11-27T11:00:00Z', tipo: 'Aprobar', confirmo: true })] });
  const r = await revisionCliente({ notion: m.notion, c: cfg({}), ahora: AHORA });
  assert.deepEqual(r, []);
  assert.equal(m.llamadas.query.length + m.llamadas.update.length + m.llamadas.get.length, 0);
});

test('E2-03 · encendido sin clientes canary: falla cerrado, no procesa ninguna decisión', async () => {
  const m = mundo({ revs: [expuesta()], decs: [decPage({ id: 'd1', creada: '2026-11-27T11:00:00Z', tipo: 'Aprobar', confirmo: true })] });
  await revisionCliente({ notion: m.notion, c: cfg({ REVISION_CLIENTE: '1', NOTION_REVISIONES_ID: DS_REV }), ahora: AHORA });
  assert.equal(m.llamadas.update.length, 0);
});

// ---------- aprobar y pedir cambios ----------
test('E2-03 · aprobar con confirmación: Aplicada, revisión Aprobada por cliente, recibo con actor y decisión', async () => {
  const m = mundo({ revs: [expuesta()], decs: [decPage({ id: 'd1', creada: '2026-11-27T11:00:00Z', tipo: 'Aprobar', confirmo: true })] });
  await corre(m);
  assert.equal(m.resultado('d1'), 'Aplicada');
  assert.equal(m.estado('rev-a1'), 'Aprobada por cliente');
  const recibo = txt(m.pages.get('rev-a1').properties['Recibo']);
  assert.match(recibo, /Aprobar/); assert.match(recibo, new RegExp(REVISOR_A)); assert.match(recibo, /d1/);
  const d = m.pages.get('d1').properties;
  assert.deepEqual(d['Revisión'].relation, [{ id: 'rev-a1' }]);
  assert.deepEqual(d['Actor verificado'].people, [{ id: REVISOR_A }]);
  assert.match(txt(d['Clave']), /^[0-9a-f]{24}$/);
});

test('E2-03 · aprobar sin la casilla de confirmación: Rechazada y la revisión no cambia', async () => {
  const m = mundo({ revs: [expuesta()], decs: [decPage({ id: 'd1', creada: '2026-11-27T11:00:00Z', tipo: 'Aprobar', confirmo: false })] });
  await corre(m);
  assert.equal(m.resultado('d1'), 'Rechazada'); assert.match(m.motivo('d1'), /confirm/i);
  assert.equal(m.estado('rev-a1'), 'En revisión');
});

test('E2-03 · pedir cambios sin descripción útil (vacío, espacios, saltos, invisibles): Rechazada', async () => {
  const vacios = ['', '   ', '\n\n', '​ '];
  const m = mundo({ revs: [expuesta()], decs: vacios.map((d, i) => decPage({ id: `d${i}`, creada: `2026-11-27T11:0${i}:00Z`, tipo: 'Pedir cambios', descripcion: d })) });
  await corre(m);
  for (let i = 0; i < vacios.length; i++) { assert.equal(m.resultado(`d${i}`), 'Rechazada'); assert.match(m.motivo(`d${i}`), /descripci/i); }
  assert.equal(m.estado('rev-a1'), 'En revisión');
});

test('E2-03 · pedir cambios con texto (sólo al pie): Aplicada, Cambios solicitados, ligada al entregable completo', async () => {
  const m = mundo({ revs: [expuesta()], decs: [decPage({ id: 'd1', creada: '2026-11-27T11:00:00Z', tipo: 'Pedir cambios', descripcion: 'Pie: cambiar el teléfono' })] });
  await corre(m);
  assert.equal(m.resultado('d1'), 'Aplicada');
  assert.equal(m.estado('rev-a1'), 'Cambios solicitados');
  assert.deepEqual(m.pages.get('d1').properties['Revisión'].relation, [{ id: 'rev-a1' }]);
});

test('E2-03 · tipo vacío o código ilegible/inexistente: Rechazada con motivo', async () => {
  const m = mundo({ revs: [expuesta()], decs: [
    decPage({ id: 'd1', creada: '2026-11-27T11:00:00Z', tipo: null, confirmo: true }),
    decPage({ id: 'd2', creada: '2026-11-27T11:01:00Z', tipo: 'Aprobar', confirmo: true, codigo: 'el del correo' }),
    decPage({ id: 'd3', creada: '2026-11-27T11:02:00Z', tipo: 'Aprobar', confirmo: true, codigo: 'REVCLI-99' })] });
  await corre(m);
  assert.match(m.motivo('d1'), /tipo/i); assert.match(m.motivo('d2'), /código/i); assert.match(m.motivo('d3'), /REVCLI-99/);
  for (const d of ['d1', 'd2', 'd3']) assert.equal(m.resultado(d), 'Rechazada');
  assert.equal(m.estado('rev-a1'), 'En revisión');
});

// ---------- identidad y aislamiento ----------
test('E2-03 · aislamiento: un revisor de B no decide sobre una revisión de A (aunque sepa el código)', async () => {
  const m = mundo({ revs: [expuesta()], decs: [
    decPage({ id: 'd1', creada: '2026-11-27T11:00:00Z', tipo: 'Aprobar', confirmo: true, actor: REVISOR_B }),               // desde la base de B
    decPage({ id: 'd2', creada: '2026-11-27T11:01:00Z', tipo: 'Aprobar', confirmo: true, actor: REVISOR_B, ds: DS_DEC_A })] }); // y si llegara a la de A
  await corre(m);
  assert.equal(m.resultado('d1'), 'Rechazada'); assert.match(m.motivo('d1'), /no es una revisión de este cliente/);
  assert.equal(m.resultado('d2'), 'Rechazada'); assert.match(m.motivo('d2'), /revisor/i);
  assert.equal(m.estado('rev-a1'), 'En revisión');
  assert.deepEqual(m.pages.get('d1').properties['Actor verificado'].people, []);
});

test('E2-03 · identidad: sin created_by, bot del formulario o personal interno fuera de la lista → Rechazada', async () => {
  const m = mundo({ revs: [expuesta()], decs: [
    decPage({ id: 'd1', creada: '2026-11-27T11:00:00Z', tipo: 'Aprobar', confirmo: true, actor: null }),
    decPage({ id: 'd2', creada: '2026-11-27T11:01:00Z', tipo: 'Aprobar', confirmo: true, actor: BOT }),
    decPage({ id: 'd3', creada: '2026-11-27T11:02:00Z', tipo: 'Aprobar', confirmo: true, actor: ALE })] });
  await corre(m);
  for (const d of ['d1', 'd2', 'd3']) assert.equal(m.resultado(d), 'Rechazada', d);
  assert.equal(m.estado('rev-a1'), 'En revisión');
});

test('E2-03 · revocación: quitar a un revisor bloquea sus decisiones nuevas y conserva la historia previa', async () => {
  const m = mundo({ revs: [expuesta()], decs: [decPage({ id: 'd1', creada: '2026-11-27T11:00:00Z', tipo: 'Pedir cambios', descripcion: 'Hero más claro' })] });
  await corre(m);
  assert.equal(m.resultado('d1'), 'Aplicada');
  m.pages.get(CLI_A).properties['Revisores del cliente'] = { people: [{ id: REVISOR_A2 }] };   // Al/Bonzo retiran a REVISOR_A
  m.pages.set('d2', decPage({ id: 'd2', creada: '2026-11-27T11:30:00Z', tipo: 'Aprobar', confirmo: true }));
  await corre(m);
  assert.equal(m.resultado('d2'), 'Rechazada'); assert.match(m.motivo('d2'), /revisor/i);
  assert.equal(m.resultado('d1'), 'Aplicada');                       // la decisión anterior no se borra ni cambia
  assert.equal(m.estado('rev-a1'), 'Cambios solicitados');
});

test('E2-03 · binding: la base de un cliente sólo decide revisiones de ese cliente (aunque la persona revise a ambos)', async () => {
  const m = mundo({ revs: [expuesta(), expuesta({ id: 'rev-b1', codigo: 2, cliente: [CLI_B], entregable: 'journey', manifiesto: MANIF_B1 }),
    expuesta({ id: 'rev-x', codigo: 5, cliente: [CLI_X] })],
  clientes: [cliPage(CLI_A, [REVISOR_A]), cliPage(CLI_B, [REVISOR_A, REVISOR_B]), cliPage(CLI_X, [REVISOR_A])],
  decs: [
    decPage({ id: 'd1', creada: '2026-11-27T11:00:00Z', tipo: 'Aprobar', confirmo: true, codigo: 'REVCLI-2' }),   // base de A, revisión de B
    decPage({ id: 'd2', creada: '2026-11-27T11:01:00Z', tipo: 'Aprobar', confirmo: true, codigo: 'REVCLI-5' })] }); // revisión fuera del canary
  await corre(m);
  for (const d of ['d1', 'd2']) { assert.equal(m.resultado(d), 'Rechazada'); assert.match(m.motivo(d), /no es una revisión de este cliente/); }
  assert.equal(m.estado('rev-b1'), 'En revisión'); assert.equal(m.estado('rev-x'), 'En revisión');
  assert.ok(m.llamadas.update.every(u => !['rev-b1', 'rev-x'].includes(u.id)));
});

test('E2-03 · una ficha del canary sin base de entrada sólo expone revisiones; no lee decisiones', async () => {
  const m = mundo({ revs: [revPage({ id: 'rev-a1', codigo: 1, estado: 'Lista para exponer' })],
    decs: [decPage({ id: 'd1', creada: '2026-11-27T11:00:00Z', tipo: 'Aprobar', confirmo: true })] });
  await corre(m, { revisionCliente: { ...c.revisionCliente, clientes: [{ ficha: CLI_A, decisiones: null }] } });
  assert.equal(m.estado('rev-a1'), 'En revisión');
  assert.equal(m.resultado('d1'), null);
  assert.ok(m.llamadas.query.every(q => q.ds === DS_REV));
});

for (const [nombre, cliente] of [['dos fichas', [CLI_A, CLI_B]], ['ninguna ficha', []]]) {
  test(`E2-03 · revisión con cliente ambiguo (${nombre}): no se decide; revisión y decisión quedan para reconciliar`, async () => {
    const m = mundo({ revs: [expuesta({ cliente })], decs: [decPage({ id: 'd1', creada: '2026-11-27T11:00:00Z', tipo: 'Aprobar', confirmo: true })] });
    await corre(m);
    assert.equal(m.resultado('d1'), 'Pendiente de reconciliar');
    assert.equal(m.estado('rev-a1'), 'Pendiente de reconciliar');
  });
}

test('E2-03 · la ficha ligada no es de la base Clientes (o está en la papelera): Pendiente de reconciliar', async () => {
  const m = mundo({ revs: [expuesta()], decs: [decPage({ id: 'd1', creada: '2026-11-27T11:00:00Z', tipo: 'Aprobar', confirmo: true })],
    clientes: [cliPage(CLI_A, [REVISOR_A], 'otra-base')] });
  await corre(m);
  assert.equal(m.resultado('d1'), 'Pendiente de reconciliar'); assert.match(m.motivo('d1'), /Clientes/);
  assert.equal(m.estado('rev-a1'), 'En revisión');
});

test('E2-03 · decisión editada por otra persona después de enviarse (p. ej. Pedir cambios → Aprobar): no se acepta', async () => {
  const m = mundo({ revs: [expuesta()], decs: [decPage({ id: 'd1', creada: '2026-11-27T11:00:00Z', tipo: 'Aprobar', confirmo: true, editor: ALE })] });
  await corre(m);
  assert.equal(m.resultado('d1'), 'Pendiente de reconciliar'); assert.match(m.motivo('d1'), /edit/i);
  assert.equal(m.estado('rev-a1'), 'En revisión');
  assert.deepEqual(m.pages.get('d1').properties['Actor verificado'].people, []);
});

test('E2-03 · decisión enviada antes de que la revisión se expusiera: Rechazada (el minuto de created_time se respeta)', async () => {
  const rev = expuesta();
  rev.properties['Expuesta el'] = { date: { start: '2026-11-27T11:05:30.000Z' } };
  const m = mundo({ revs: [rev], decs: [
    decPage({ id: 'd1', creada: '2026-11-27T11:04:00.000Z', tipo: 'Aprobar', confirmo: true }),
    decPage({ id: 'd2', creada: '2026-11-27T11:05:00.000Z', tipo: 'Pedir cambios', descripcion: 'x', actor: REVISOR_A2 })] });
  await corre(m);
  assert.equal(m.resultado('d1'), 'Rechazada'); assert.match(m.motivo('d1'), /antes/);
  assert.equal(m.resultado('d2'), 'Aplicada');                       // mismo minuto que la exposición: se acepta
});

// ---------- versiones ----------
test('E2-03 · revisión reemplazada o retirada: rechazo explícito; Borrador: rechazo; lista sin página: espera', async () => {
  const m = mundo({ revs: [
    expuesta({ estado: 'Reemplazada', reemplazadaPor: ['rev-a2'] }),
    expuesta({ id: 'rev-r', codigo: 2, estado: 'Retirada' }),
    revPage({ id: 'rev-b', codigo: 3, estado: 'Borrador' }),
    revPage({ id: 'rev-l', codigo: 4, estado: 'Lista para exponer', pagina: null })],   // sin página: no se expone en esta corrida
  decs: [
    decPage({ id: 'd1', creada: '2026-11-27T11:00:00Z', tipo: 'Aprobar', confirmo: true, codigo: 'REVCLI-1' }),
    decPage({ id: 'd2', creada: '2026-11-27T11:01:00Z', tipo: 'Aprobar', confirmo: true, codigo: 'REVCLI-2' }),
    decPage({ id: 'd3', creada: '2026-11-27T11:02:00Z', tipo: 'Aprobar', confirmo: true, codigo: 'REVCLI-3' }),
    decPage({ id: 'd4', creada: '2026-11-27T11:03:00Z', tipo: 'Aprobar', confirmo: true, codigo: 'REVCLI-4' })] });
  await corre(m);
  assert.match(m.motivo('d1'), /reemplazada/i); assert.match(m.motivo('d2'), /retirada/i); assert.match(m.motivo('d3'), /expuesta/i);
  for (const d of ['d1', 'd2', 'd3']) assert.equal(m.resultado(d), 'Rechazada');
  // Lista para exponer sin página: la exposición la deja para reconciliar y su decisión espera (no se decide nada a medias).
  assert.equal(m.estado('rev-l'), 'Pendiente de reconciliar'); assert.equal(m.resultado('d4'), null);
});

test('E2-03 · exponer: Lista para exponer → En revisión con huella, secuencia 1 y fecha', async () => {
  const m = mundo({ revs: [revPage({ id: 'rev-a1', codigo: 1, estado: 'Lista para exponer' })] });
  await corre(m);
  const p = m.pages.get('rev-a1').properties;
  assert.equal(m.estado('rev-a1'), 'En revisión');
  assert.equal(p['Secuencia'].number, 1);
  assert.equal(txt(p['Huella']), huellaDe(MANIF_A1).huella);
  assert.equal(p['Expuesta el'].date.start, new Date(AHORA).toISOString());
});

test('E2-03 · nueva revisión reemplaza a la anterior; la aprobación vieja no aplica y una decisión tardía sobre R1 se rechaza', async () => {
  const m = mundo({ revs: [
    expuesta({ estado: 'Aprobada por cliente' }),
    revPage({ id: 'rev-a2', codigo: 2, estado: 'Lista para exponer', manifiesto: MANIF_A2, creada: '2026-11-27T11:00:00Z' })] });
  await corre(m);
  assert.equal(m.estado('rev-a1'), 'Reemplazada');
  assert.equal(m.estado('rev-a2'), 'En revisión');                   // no hereda la aprobación de R1
  assert.equal(m.pages.get('rev-a2').properties['Secuencia'].number, 2);
  assert.deepEqual(m.pages.get('rev-a2').properties['Reemplaza a'].relation, [{ id: 'rev-a1' }]);
  m.pages.set('d1', decPage({ id: 'd1', creada: '2026-11-27T11:40:00Z', tipo: 'Aprobar', confirmo: true, codigo: 'REVCLI-1' }));
  await corre(m);
  assert.equal(m.resultado('d1'), 'Rechazada'); assert.match(m.motivo('d1'), /REVCLI-2/);   // ofrece la vigente
  assert.equal(m.estado('rev-a2'), 'En revisión');
});

test('E2-03 · exponer sólo dentro del mismo cliente: la revisión de B con el mismo entregable no reemplaza a la de A', async () => {
  const m = mundo({ revs: [
    expuesta(),
    revPage({ id: 'rev-b1', codigo: 2, estado: 'Lista para exponer', cliente: [CLI_B], manifiesto: MANIF_B1 })] });
  await corre(m);
  assert.equal(m.estado('rev-a1'), 'En revisión');
  assert.equal(m.estado('rev-b1'), 'En revisión');
  assert.equal(m.pages.get('rev-b1').properties['Secuencia'].number, 1);
});

test('E2-03 · exponer con manifiesto inválido o sin página del cliente: no se expone y queda para reconciliar', async () => {
  const m = mundo({ revs: [revPage({ id: 'rev-a1', codigo: 1, estado: 'Lista para exponer', manifiesto: '{"componentes":[]}' })] });
  await corre(m);
  assert.equal(m.estado('rev-a1'), 'Pendiente de reconciliar');
  assert.match(txt(m.pages.get('rev-a1').properties['Recibo']), /manifiesto/i);
});

test('E2-03 · manifiesto editado después de exponer (huella distinta): Pendiente de reconciliar y las decisiones esperan', async () => {
  const m = mundo({ revs: [expuesta({ manifiesto: MANIF_A2, huella: huellaDe(MANIF_A1).huella })],
    decs: [decPage({ id: 'd1', creada: '2026-11-27T11:00:00Z', tipo: 'Aprobar', confirmo: true })] });
  await corre(m);
  assert.equal(m.estado('rev-a1'), 'Pendiente de reconciliar');
  assert.equal(m.resultado('d1'), null);                              // no se aprueba un contenido distinto al expuesto
});

// ---------- repetición y concurrencia ----------
test('E2-03 · doble clic / dos pestañas: la segunda aprobación igual es Duplicada, sin otra decisión', async () => {
  const m = mundo({ revs: [expuesta()], decs: [
    decPage({ id: 'd1', creada: '2026-11-27T11:00:00Z', tipo: 'Aprobar', confirmo: true }),
    decPage({ id: 'd2', creada: '2026-11-27T11:00:01Z', tipo: 'Aprobar', confirmo: true })] });
  await corre(m);
  assert.equal(m.resultado('d1'), 'Aplicada');
  assert.equal(m.resultado('d2'), 'Duplicada'); assert.match(m.motivo('d2'), /d1/);
  assert.equal(m.estado('rev-a1'), 'Aprobada por cliente');
  await corre(m);                                                     // otra corrida no reprocesa nada
  assert.equal(m.resultado('d2'), 'Duplicada');
});

test('E2-03 · decisiones opuestas en la misma revisión: En conflicto, ambas conservadas, sin última-escritura-gana', async () => {
  const m = mundo({ revs: [expuesta()], decs: [
    decPage({ id: 'd2', creada: '2026-11-27T11:00:05Z', tipo: 'Pedir cambios', descripcion: 'Otro tono', actor: REVISOR_A2 }),
    decPage({ id: 'd1', creada: '2026-11-27T11:00:00Z', tipo: 'Aprobar', confirmo: true })] });
  await corre(m);
  assert.equal(m.resultado('d1'), 'Aplicada');                       // se procesan en orden de llegada
  assert.equal(m.resultado('d2'), 'En conflicto');
  assert.equal(m.estado('rev-a1'), 'En conflicto');
  m.pages.set('d3', decPage({ id: 'd3', creada: '2026-11-27T11:20:00Z', tipo: 'Aprobar', confirmo: true, actor: REVISOR_A2 }));
  await corre(m);
  assert.equal(m.resultado('d3'), 'En conflicto');                   // nadie lo resuelve escribiendo después
  assert.equal(m.estado('rev-a1'), 'En conflicto');
});

test('E2-03 · segunda persona que también aprueba: Aplicada sin cambiar el estado; más cambios con otro texto: Aplicada', async () => {
  const m = mundo({ revs: [expuesta(), expuesta({ id: 'rev-b1', codigo: 2, cliente: [CLI_B], entregable: 'journey', manifiesto: MANIF_B1 })], decs: [
    decPage({ id: 'd1', creada: '2026-11-27T11:00:00Z', tipo: 'Aprobar', confirmo: true }),
    decPage({ id: 'd2', creada: '2026-11-27T11:01:00Z', tipo: 'Aprobar', confirmo: true, actor: REVISOR_A2 }),
    decPage({ id: 'd3', creada: '2026-11-27T11:02:00Z', tipo: 'Pedir cambios', descripcion: 'Paso 2 más corto', actor: REVISOR_B, codigo: 'REVCLI-2' }),
    decPage({ id: 'd4', creada: '2026-11-27T11:03:00Z', tipo: 'Pedir cambios', descripcion: 'Y el paso 3 también', actor: REVISOR_B, codigo: 'REVCLI-2' })] });
  await corre(m);
  assert.equal(m.resultado('d2'), 'Aplicada'); assert.equal(m.estado('rev-a1'), 'Aprobada por cliente');
  assert.equal(m.resultado('d4'), 'Aplicada'); assert.equal(m.estado('rev-b1'), 'Cambios solicitados');
});

// ---------- fallos parciales y readback ----------
test('E2-03 · fallo al escribir la revisión: la decisión queda Pendiente de reconciliar y no se reintenta a ciegas', async () => {
  let falla = true;
  const m = mundo({ revs: [expuesta()], decs: [decPage({ id: 'd1', creada: '2026-11-27T11:00:00Z', tipo: 'Aprobar', confirmo: true })],
    fallos: { update: id => falla && id === 'rev-a1' } });
  await corre(m);
  assert.equal(m.resultado('d1'), 'Pendiente de reconciliar');
  assert.equal(m.estado('rev-a1'), 'En revisión');
  falla = false;
  const antes = m.llamadas.update.length;
  await corre(m);
  assert.equal(m.llamadas.update.filter((u, i) => i >= antes && u.id === 'd1').length, 0);   // no se reprocesa sola
  assert.equal(m.resultado('d1'), 'Pendiente de reconciliar');
});

test('E2-03 · readback divergente (Notion responde OK pero no guarda): Pendiente de reconciliar', async () => {
  const m = mundo({ revs: [expuesta()], decs: [decPage({ id: 'd1', creada: '2026-11-27T11:00:00Z', tipo: 'Aprobar', confirmo: true })],
    fallos: { ignora: (id, props) => id === 'rev-a1' && props.Estado } });
  await corre(m);
  assert.equal(m.resultado('d1'), 'Pendiente de reconciliar');
  assert.match(m.motivo('d1'), /readback|leer/i);
});

// ---------- límites de integración ----------
test('E2-03 · nunca toca Assets, Campañas ni Clientes, y no abre sesiones: sólo escribe filas de Revisiones y Decisiones', async () => {
  const m = mundo({ revs: [expuesta(), revPage({ id: 'rev-a2', codigo: 2, estado: 'Lista para exponer', manifiesto: MANIF_A2, entregable: 'otro' })], decs: [
    decPage({ id: 'd1', creada: '2026-11-27T11:00:00Z', tipo: 'Aprobar', confirmo: true }),
    decPage({ id: 'd2', creada: '2026-11-27T11:01:00Z', tipo: 'Pedir cambios', descripcion: 'x', actor: REVISOR_B })] });
  await corre(m);
  const ajenas = m.llamadas.update.filter(u => !['rev-a1', 'rev-a2', 'd1', 'd2'].includes(u.id));
  assert.deepEqual(ajenas, []);
  for (const u of m.llamadas.update) for (const k of ['Aprobó', 'Aprobado el', 'Cambios pedidos', 'Sesión', 'Ronda de']) assert.ok(!(k in u.props), k);
  assert.ok(m.llamadas.query.every(q => [DS_REV, DS_DEC_A, DS_DEC_B].includes(q.ds)));
});

// ---------- hallazgos de la revisión independiente ----------
test('E2-03 · error de lectura (429) antes de escribir: la decisión queda intacta, la corrida se corta y la siguiente la procesa', async () => {
  let falla = true;
  const m = mundo({ revs: [expuesta()], decs: [
    decPage({ id: 'd1', creada: '2026-11-27T11:00:00Z', tipo: 'Aprobar', confirmo: true }),
    decPage({ id: 'd2', creada: '2026-11-27T11:01:00Z', tipo: 'Pedir cambios', descripcion: 'x', actor: REVISOR_A2 })],
    fallos: { query: (ds, f) => falla && ds === DS_REV && f.unique_id } });
  const r = await corre(m);
  assert.equal(m.resultado('d1'), null); assert.equal(m.resultado('d2'), null);
  assert.ok(r.some(x => x[1] === 'lectura_fallida'));
  falla = false;
  await corre(m);
  assert.equal(m.resultado('d1'), 'Aplicada'); assert.equal(m.resultado('d2'), 'En conflicto');
});

test('E2-03 · cola con más de 50 pendientes en espera: pagina, no gasta presupuesto en ellas y procesa la siguiente', async () => {
  const fuera = Array.from({ length: 60 }, (_, i) => decPage({ id: `x${i}`, creada: `2026-11-27T10:${String(i % 60).padStart(2, '0')}:00Z`,
    tipo: 'Aprobar', confirmo: true, codigo: 'REVCLI-5' }));
  const m = mundo({ revs: [expuesta(), revPage({ id: 'rev-x', codigo: 5, estado: 'Pendiente de reconciliar', entregable: 'otro' })],
    decs: [...fuera, decPage({ id: 'd1', creada: '2026-11-27T11:30:00Z', tipo: 'Aprobar', confirmo: true })] });
  await corre(m);
  assert.equal(m.resultado('d1'), 'Aplicada');
  assert.ok(fuera.every(d => m.resultado(d.id) === null));
  assert.ok(m.llamadas.query.some(q => q.extra?.start_cursor));      // usó paginación
  assert.ok(m.llamadas.query.some(q => q.extra?.sorts?.[0]?.timestamp === 'created_time'));
});

test('E2-03 · aprobar y pedir cambios en el mismo minuto: el estado final es En conflicto sin importar el desempate', async () => {
  for (const [p, q] of [['a', 'b'], ['b', 'a']]) {
    const m = mundo({ revs: [expuesta()], decs: [
      decPage({ id: `${p}-aprobar`, creada: '2026-11-27T11:00:00Z', tipo: 'Aprobar', confirmo: true }),
      decPage({ id: `${q}-cambios`, creada: '2026-11-27T11:00:00Z', tipo: 'Pedir cambios', descripcion: 'Hero', actor: REVISOR_A2 })] });
    await corre(m);
    assert.equal(m.estado('rev-a1'), 'En conflicto');
    assert.deepEqual([m.resultado(`${p}-aprobar`), m.resultado(`${q}-cambios`)].sort(), ['Aplicada', 'En conflicto']);
  }
});

test('E2-03 · una escritura fallida al marcar una huella distinta no detiene las demás revisiones ni las decisiones', async () => {
  const m = mundo({ revs: [expuesta({ id: 'rev-mala', codigo: 7, entregable: 'otro', manifiesto: MANIF_A2, huella: huellaDe(MANIF_A1).huella }), expuesta()],
    decs: [decPage({ id: 'd1', creada: '2026-11-27T11:00:00Z', tipo: 'Aprobar', confirmo: true })],
    fallos: { update: id => id === 'rev-mala' } });
  const r = await corre(m);
  assert.ok(r.some(x => x[0] === 'rev-mala' && x[1] === 'error'));
  assert.equal(m.resultado('d1'), 'Aplicada');
});

test('E2-03 · dos revisiones del mismo entregable listas en la misma corrida: queda una sola vigente (secuencias 1 y 2)', async () => {
  const m = mundo({ revs: [
    revPage({ id: 'rev-a1', codigo: 1, estado: 'Lista para exponer', creada: '2026-11-27T10:00:00Z' }),
    revPage({ id: 'rev-a2', codigo: 2, estado: 'Lista para exponer', manifiesto: MANIF_A2, creada: '2026-11-27T10:05:00Z' })] });
  // El índice de Notion puede tardar: la consulta por entregable no ve los cambios de esta corrida.
  const consulta = m.notion.query;
  const foto = structuredClone([...m.pages.values()]);
  m.notion.query = async (ds, f, n, e) => (f.and ? { results: foto.filter(p => cumple(p, f)), has_more: false } : consulta(ds, f, n, e));
  await corre(m);
  assert.equal(m.estado('rev-a1'), 'Reemplazada');
  assert.equal(m.estado('rev-a2'), 'En revisión');
  assert.equal(m.pages.get('rev-a2').properties['Secuencia'].number, 2);
});

test('E2-03 · falla el cierre de la decisión después de cambiar la revisión: la revisión también queda Pendiente de reconciliar', async () => {
  let n = 0;
  const m = mundo({ revs: [expuesta()], decs: [decPage({ id: 'd1', creada: '2026-11-27T11:00:00Z', tipo: 'Aprobar', confirmo: true })],
    fallos: { update: (id, props) => id === 'd1' && props.Resultado?.select?.name === 'Aplicada' && ++n === 1 } });
  await corre(m);
  assert.equal(m.resultado('d1'), 'Pendiente de reconciliar');
  assert.equal(m.estado('rev-a1'), 'Pendiente de reconciliar');
  assert.match(txt(m.pages.get('rev-a1').properties['Recibo']), /d1/);
  m.pages.set('d2', decPage({ id: 'd2', creada: '2026-11-27T11:30:00Z', tipo: 'Pedir cambios', descripcion: 'x', actor: REVISOR_A2 }));
  await corre(m);
  assert.equal(m.resultado('d2'), null);                             // espera a que Ale reconcilie
});

test('E2-03 · presupuesto por corrida: no procesa más de REVISION_CLIENTE_MAX decisiones', async () => {
  const decs = Array.from({ length: 5 }, (_, i) => decPage({ id: `d${i}`, creada: `2026-11-27T11:0${i}:00Z`, tipo: 'Pedir cambios', descripcion: `cambio ${i}` }));
  const m = mundo({ revs: [expuesta()], decs });
  const r = await corre(m, { revisionCliente: { ...c.revisionCliente, maxDecisiones: 2 } });
  assert.deepEqual(decs.map(d => m.resultado(d.id)), ['Aplicada', 'Aplicada', null, null, null]);
  assert.ok(r.some(x => x[1] === 'presupuesto_agotado'));
});

test('E2-03 · decisión enviada mientras la revisión estaba «Lista para exponer»: se expone primero y la decisión se rechaza por anticipada', async () => {
  const m = mundo({ revs: [revPage({ id: 'rev-a1', codigo: 1, estado: 'Lista para exponer' })],
    decs: [decPage({ id: 'd1', creada: '2026-11-27T11:00:00Z', tipo: 'Aprobar', confirmo: true })] });
  await corre(m);                                                     // AHORA = 12:00: expone a las 12:00
  assert.equal(m.estado('rev-a1'), 'En revisión');
  assert.equal(m.resultado('d1'), 'Rechazada'); assert.match(m.motivo('d1'), /antes de que REVCLI-1 se expusiera/);
  m.pages.set('d2', decPage({ id: 'd2', creada: '2026-11-27T12:30:00Z', tipo: 'Aprobar', confirmo: true }));
  await revisionCliente({ notion: m.notion, c, ahora: Date.parse('2026-11-27T13:00:00Z') });
  assert.equal(m.resultado('d2'), 'Aplicada'); assert.equal(m.estado('rev-a1'), 'Aprobada por cliente');
});
