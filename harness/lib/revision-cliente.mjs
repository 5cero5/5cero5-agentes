// Revisión y aprobación del cliente (épica E2). Paso propio dentro de la función barrido; apagado por defecto
// (REVISION_CLIENTE=1 y sólo las fichas de REVISION_CLIENTE_CLIENTES). Dos bases de Notion:
//   - "Revisiones de cliente" (interna, nunca compartida con invitados): una fila = una revisión congelada de un
//     entregable completo (todos sus artes y documentos). Ale la deja en "Lista para exponer"; este módulo es el ÚNICO
//     escritor de Estado, Secuencia, Huella, Reemplaza a y Recibo.
//   - "Decisiones del cliente": entrada por formulario no anónimo. Cada fila es un intento, no una decisión aceptada.
//     El actor es created_by de la página (metadata del sistema que el invitado no edita) y tiene que estar en
//     "Revisores del cliente" de la ficha de ESE cliente (distinto de Aprobadores, que despacha agentes). Una fila que
//     editó otra persona después de enviarse (last_edited_by distinto) no se acepta: va a reconciliar.
// Reglas: aprobar exige la casilla de confirmación; pedir cambios, una descripción útil. Revisión reemplazada, retirada,
// no expuesta o expuesta después del envío → Rechazada. Repetición → Duplicada. Decisiones opuestas → En conflicto (nadie
// gana por escribir después; lo resuelve Ale). Manifiesto distinto al expuesto, cliente ambiguo o escritura
// fallida/divergente → Pendiente de reconciliar, sin reintento a ciegas. Un error de LECTURA antes de escribir deja la
// decisión intacta y corta la corrida (la siguiente la retoma). Se procesan una por una en orden de llegada (Notion da
// created_time al minuto; dentro del mismo minuto, por id: con decisiones opuestas el estado final es En conflicto igual).
// Nunca escribe en Assets, Campañas ni Clientes ni abre sesiones: Ale consolida y la ronda sigue por la ruta existente.
import { createHash } from 'node:crypto';
import { P } from './notion.mjs';

export const EXPUESTA = ['En revisión', 'Aprobada por cliente', 'Cambios solicitados', 'En conflicto'];
const TIPOS = ['Aprobar', 'Pedir cambios'];
const ENTREGABLE = /^[a-z0-9][a-z0-9-]{0,60}$/;
const CODIGO = /^\s*REVCLI[\s-]?(\d{1,6})\s*$/i;
const PAGINA = /^https:\/\/(app\.notion\.com|www\.notion\.so|notion\.so)\//i;
const INVISIBLES = /[­͏ᅟᅠ឴឵᠎​-‏‪-‮⁠-⁤⠀ㅤ﻿ﾠ]/g;
const MAX_PAGINAS = 5;                           // 250 filas por consulta paginada y corrida
const POR_LLEGADA = [{ timestamp: 'created_time', direction: 'ascending' }];

const sinGuiones = id => String(id || '').replace(/-/g, '').toLowerCase();
const sha = s => createHash('sha256').update(s).digest('hex');
const txt = p => (p?.rich_text || p?.title || []).map(x => x.plain_text).join('');
const ids = p => (p?.relation || p?.people || []).map(x => x.id);
const cod = n => `REVCLI-${n}`;
const corto = e => String(e?.message || e).slice(0, 200);

// "REVCLI-12", "revcli 12" o "REVCLI12" → 12. Cualquier otra cosa → null.
export function codigoDe(s) {
  const m = String(s || '').match(CODIGO);
  return m ? Number(m[1]) : null;
}

// Texto sin caracteres invisibles ni espacios (incluye NBSP y saltos) en los extremos. '' si no queda nada útil.
export function textoUtil(s) {
  return String(s || '').replace(INVISIBLES, '').trim();
}

function canonico(v) {
  if (Array.isArray(v)) return `[${v.map(canonico).join(',')}]`;
  if (v && typeof v === 'object') return `{${Object.keys(v).sort().map(k => `${JSON.stringify(k)}:${canonico(v[k])}`).join(',')}}`;
  return JSON.stringify(v);
}

// sha256 del manifiesto en forma canónica (el orden de las llaves no cambia la huella). Valida lo mínimo.
export function huellaDe(texto) {
  let m;
  try { m = JSON.parse(texto); } catch { return { ok: false, motivo: 'el manifiesto no es JSON' }; }
  const comps = m?.componentes;
  if (!Array.isArray(comps) || !comps.length) return { ok: false, motivo: 'el manifiesto no trae componentes' };
  for (const [i, x] of comps.entries()) {
    if (!x || !String(x.rol || '').trim() || !String(x.nombre || '').trim()) return { ok: false, motivo: `el componente ${i + 1} del manifiesto no trae rol y nombre` };
    if (!/^[0-9a-f]{64}$/.test(String(x.sha256))) return { ok: false, motivo: `el componente ${i + 1} del manifiesto no trae un sha256 válido` };
  }
  return { ok: true, huella: sha(canonico(m)) };
}

export function leeRevision(page) {
  const p = page.properties || {};
  return {
    id: page.id, creada: page.created_time,
    codigo: p['Código']?.unique_id?.number ?? null,
    cliente: ids(p['Cliente']),
    entregable: txt(p['Entregable']).trim(),
    secuencia: p['Secuencia']?.number ?? null,
    estado: p['Estado']?.select?.name || null,
    manifiesto: txt(p['Manifiesto']),
    huella: txt(p['Huella']).trim(),
    expuestaEl: p['Expuesta el']?.date?.start || null,
    pagina: p['Página del cliente']?.url || '',
    reemplazadaPor: ids(p['Reemplazada por']),
  };
}

export function leeDecision(page) {
  const p = page.properties || {};
  return {
    id: page.id, creada: page.created_time,
    actor: page.created_by?.id || null,               // quien envió el formulario; el invitado no puede cambiarlo
    editor: page.last_edited_by?.id || null,
    tipo: p['Tipo']?.select?.name || null,
    codigoTexto: txt(p['Código de revisión']),
    confirmo: p['Confirmo la revisión completa']?.checkbox === true,
    descripcion: textoUtil(txt(p['Descripción de los cambios'])),
    resultado: p['Resultado']?.select?.name || null,
    clave: txt(p['Clave']).trim(),
  };
}

export async function revisionCliente({ notion, c, ahora = Date.now(), reloj = Date.now }) {
  const rc = c.revisionCliente;
  if (!rc?.activa) return [];
  const canary = new Set((rc.clientes || []).map(sinGuiones));
  if (!canary.size) return [['revision_cliente', 'sin_clientes_canary']];
  const ctx = { notion, c, rc, canary, iso: new Date(ahora).toISOString(), out: [], revisores: new Map(), porCodigo: new Map(),
    previas: new Map(), expuestasAhora: new Map(), hasta: reloj() + (rc.msMax ?? 15000), reloj, escrituras: 0 };
  ctx.notion = { ...notion, update: (...a) => { ctx.escrituras++; return notion.update(...a); } };
  await compruebaHuellas(ctx);
  await procesaDecisiones(ctx);
  await exponeRevisiones(ctx);
  return ctx.out;
}
const sinTiempo = ctx => ctx.reloj() > ctx.hasta;

// Todas las filas de una consulta (hasta MAX_PAGINAS páginas). Se juntan antes de escribir: paginar mientras se cambian
// las filas del filtro saltaría algunas.
async function todas(ctx, ds, filter, sorts) {
  const filas = [];
  let cursor;
  for (let i = 0; i < MAX_PAGINAS; i++) {
    const r = await ctx.notion.query(ds, filter, 50, { ...(sorts ? { sorts } : {}), ...(cursor ? { start_cursor: cursor } : {}) });
    filas.push(...r.results);
    if (!r.has_more || !r.next_cursor) return filas;
    cursor = r.next_cursor;
  }
  ctx.out.push(['consulta', 'mas_filas_que_las_que_se_leen_en_una_corrida']);
  return filas;
}

// null: la revisión es de un cliente fuera del canary (no se toca). 'ambiguo': sin ficha o con varias.
function clienteCanary(ctx, rev) {
  if (rev.cliente.length !== 1) return rev.cliente.length && !rev.cliente.some(id => ctx.canary.has(sinGuiones(id))) ? null : 'ambiguo';
  return ctx.canary.has(sinGuiones(rev.cliente[0])) ? rev.cliente[0] : null;
}

// Una revisión expuesta cuyo manifiesto ya no da la huella con la que se expuso: alguien cambió el contenido.
async function compruebaHuellas(ctx) {
  const filas = await todas(ctx, ctx.rc.revisiones, { or: EXPUESTA.map(e => ({ property: 'Estado', select: { equals: e } })) });
  for (const rev of filas.map(leeRevision)) {
    const cliente = clienteCanary(ctx, rev);
    if (!cliente) continue;
    const h = huellaDe(rev.manifiesto);
    if (cliente !== 'ambiguo' && h.ok && h.huella === rev.huella) continue;
    const m = cliente === 'ambiguo' ? 'la revisión no tiene exactamente una ficha de cliente'
      : `huella distinta: el manifiesto cambió después de exponer (estaba ${rev.estado})`;
    try {
      await ctx.notion.update(rev.id, { Estado: P.estado('Pendiente de reconciliar'), Recibo: P.texto(`${m}, ${ctx.iso}. Reconciliar antes de aceptar decisiones.`) });
      ctx.out.push([rev.id, 'pendiente_de_reconciliar', m]);
    } catch (e) { ctx.out.push([rev.id, 'error', corto(e)]); }
  }
}

async function revisionPorCodigo(ctx, n) {
  if (!ctx.porCodigo.has(n)) {
    const r = await ctx.notion.query(ctx.rc.revisiones, { property: 'Código', unique_id: { equals: n } }, 2);
    ctx.porCodigo.set(n, r.results.length === 1 ? leeRevision(r.results[0]) : (r.results.length ? 'varias' : null));
  }
  return ctx.porCodigo.get(n);
}

async function revisoresDe(ctx, clienteId) {
  if (!ctx.revisores.has(clienteId)) {
    const page = await ctx.notion.get(clienteId);
    let falla = null;
    if (sinGuiones(page.parent?.data_source_id) !== sinGuiones(ctx.c.notionClientes)) falla = 'la ficha del cliente no es de la base Clientes';
    else if (page.in_trash || page.archived) falla = 'la ficha del cliente está en la papelera';
    ctx.revisores.set(clienteId, falla ? { falla } : new Set(ids(page.properties?.['Revisores del cliente']).map(sinGuiones)));
  }
  return ctx.revisores.get(clienteId);
}

// Decisiones ya aceptadas (Aplicada o En conflicto) de una revisión, para detectar repeticiones.
async function previasDe(ctx, revId) {
  if (!ctx.previas.has(revId)) {
    const filas = await todas(ctx, ctx.rc.decisiones, { property: 'Revisión', relation: { contains: revId } });
    ctx.previas.set(revId, filas.map(leeDecision).filter(d => ['Aplicada', 'En conflicto'].includes(d.resultado)));
  }
  return ctx.previas.get(revId);
}

async function vigenteDe(ctx, rev) {
  const r = await ctx.notion.query(ctx.rc.revisiones, { and: [{ property: 'Entregable', rich_text: { equals: rev.entregable } },
    { property: 'Cliente', relation: { contains: rev.cliente[0] } }] }, 50);
  const v = r.results.map(leeRevision).find(x => x.id !== rev.id && EXPUESTA.includes(x.estado));
  return v ? cod(v.codigo) : null;
}

async function procesaDecisiones(ctx) {
  const filas = await todas(ctx, ctx.rc.decisiones,
    { or: [{ property: 'Resultado', select: { is_empty: true } }, { property: 'Resultado', select: { equals: 'Pendiente' } }] }, POR_LLEGADA);
  const pendientes = filas.map(leeDecision)
    .sort((a, b) => (Date.parse(a.creada) - Date.parse(b.creada)) || String(a.id).localeCompare(String(b.id)));
  let hechas = 0;
  for (const d of pendientes) {
    if (hechas >= (ctx.rc.maxDecisiones ?? 10) || sinTiempo(ctx)) { ctx.out.push(['decisiones', 'presupuesto_agotado']); break; }
    const antes = ctx.escrituras;
    try {
      const res = await decide(ctx, d);
      ctx.out.push([d.id, res]);
      if (ctx.escrituras > antes) hechas++;
    } catch (e) {
      if (ctx.escrituras === antes) {                // falló una lectura: nada escrito, la decisión queda intacta
        ctx.out.push([d.id, 'lectura_fallida', corto(e)]);
        break;                                       // Notion no responde bien: la siguiente corrida retoma
      }
      ctx.out.push([d.id, 'error', corto(e)]);
      try {
        await ctx.notion.update(d.id, { Resultado: P.select('Pendiente de reconciliar'),
          Motivo: P.texto(`Error al procesar (${corto(e)}). Reconciliar a mano.`), 'Procesada el': P.fecha(ctx.iso) });
      } catch {}
    }
  }
}

async function decide(ctx, d) {
  const n = codigoDe(d.codigoTexto);
  const rev = n === null ? null : await revisionPorCodigo(ctx, n);
  if (rev && rev !== 'varias') {
    const cliente = clienteCanary(ctx, rev);
    if (!cliente) return 'fuera_del_canary';                     // intacta: se procesa cuando ese cliente se habilite
    if (cliente === 'ambiguo') return cierra(ctx, d, { rev, resultado: 'Pendiente de reconciliar', motivo: `${cod(n)} no tiene exactamente una ficha de cliente` });
  }
  if (d.editor && d.actor && sinGuiones(d.editor) !== sinGuiones(d.actor)) {
    return cierra(ctx, d, { rev: rev && rev !== 'varias' ? rev : null, resultado: 'Pendiente de reconciliar',
      motivo: 'La decisión la editó otra persona después de enviarse; no se acepta como del cliente' });
  }
  if (n === null) return cierra(ctx, d, { resultado: 'Rechazada', motivo: 'Código de revisión ilegible: escríbelo como aparece en la página (por ejemplo REVCLI-3)' });
  if (!rev) return cierra(ctx, d, { resultado: 'Rechazada', motivo: `No existe la revisión ${cod(n)}` });
  if (rev === 'varias') return cierra(ctx, d, { resultado: 'Pendiente de reconciliar', motivo: `Hay más de una revisión con el código ${cod(n)}` });
  const revisores = await revisoresDe(ctx, rev.cliente[0]);
  if (revisores.falla) return cierra(ctx, d, { rev, resultado: 'Pendiente de reconciliar', motivo: `${cod(n)}: ${revisores.falla}` });
  if (!d.actor) return cierra(ctx, d, { rev, resultado: 'Rechazada', motivo: 'Sin autor verificable (created_by vacío)' });
  if (!revisores.has(sinGuiones(d.actor))) return cierra(ctx, d, { rev, resultado: 'Rechazada', motivo: 'La persona que envió no es revisora de este cliente (Revisores del cliente)' });
  if (!TIPOS.includes(d.tipo)) return cierra(ctx, d, { rev, resultado: 'Rechazada', motivo: 'Falta el tipo de decisión (Aprobar o Pedir cambios)' });
  if (rev.estado === 'Pendiente de reconciliar') return 'espera_reconciliacion';   // intacta hasta que Ale reconcilie
  if (rev.estado === 'Reemplazada' || rev.reemplazadaPor.length) {
    const v = await vigenteDe(ctx, rev);
    return cierra(ctx, d, { rev, resultado: 'Rechazada', motivo: `La revisión ${cod(n)} fue reemplazada${v ? `; la vigente es ${v}` : ''}` });
  }
  if (rev.estado === 'Retirada') return cierra(ctx, d, { rev, resultado: 'Rechazada', motivo: `La revisión ${cod(n)} fue retirada` });
  if (!EXPUESTA.includes(rev.estado)) return cierra(ctx, d, { rev, resultado: 'Rechazada', motivo: `La revisión ${cod(n)} no está expuesta al cliente` });
  // created_time viene al minuto: sólo es "antes" si todo ese minuto es anterior a la exposición.
  if (rev.expuestaEl && Date.parse(d.creada) + 60000 <= Date.parse(rev.expuestaEl)) {
    return cierra(ctx, d, { rev, resultado: 'Rechazada', motivo: `Se envió antes de que ${cod(n)} se expusiera` });
  }
  if (d.tipo === 'Aprobar' && !d.confirmo) return cierra(ctx, d, { rev, resultado: 'Rechazada', motivo: 'Aprobar necesita marcar «Confirmo la revisión completa»' });
  if (d.tipo === 'Pedir cambios' && !d.descripcion) return cierra(ctx, d, { rev, resultado: 'Rechazada', motivo: 'Pedir cambios necesita una descripción de qué cambiar' });

  const clave = sha(`${sinGuiones(rev.id)}|${sinGuiones(d.actor)}|${d.tipo}|${d.tipo === 'Pedir cambios' ? d.descripcion : ''}`).slice(0, 24);
  const previas = await previasDe(ctx, rev.id);
  const igual = previas.find(p => p.clave === clave && p.id !== d.id);
  if (igual) return cierra(ctx, d, { rev, clave, actorOk: true, resultado: 'Duplicada', motivo: `Repite la decisión ${igual.id}` });

  let resultado = 'Aplicada', nuevo = null, motivo;
  if (rev.estado === 'En revisión') {
    nuevo = d.tipo === 'Aprobar' ? 'Aprobada por cliente' : 'Cambios solicitados';
    motivo = `${nuevo} (${cod(n)})`;
  } else if (rev.estado === 'En conflicto') {
    resultado = 'En conflicto'; motivo = `${cod(n)} ya está en conflicto; lo resuelve Ale`;
  } else if ((rev.estado === 'Aprobada por cliente') === (d.tipo === 'Aprobar')) {
    motivo = d.tipo === 'Aprobar' ? `Aprobación adicional; ${cod(n)} ya estaba aprobada` : `Cambios adicionales sobre ${cod(n)}`;
  } else {
    resultado = 'En conflicto'; nuevo = 'En conflicto';
    motivo = `${d.tipo} contradice el estado ${rev.estado} de ${cod(n)}; se conservan ambas y lo resuelve Ale`;
  }
  const r = await cierra(ctx, d, { rev, clave, actorOk: true, resultado, nuevo, motivo });
  if (r === resultado) previas.push({ id: d.id, clave, resultado });
  return r;
}

// Escribe el resultado. Con cambio de estado de la revisión: (1) reclama la decisión con todos sus campos como Pendiente
// de reconciliar, (2) escribe la revisión y la relee, (3) cierra la decisión y la relee. Si algo falla después de (1), la
// decisión queda Pendiente de reconciliar (fuera de la cola: no se reintenta a ciegas); si falla después de cambiar la
// revisión, la revisión también queda Pendiente de reconciliar y no acepta más decisiones hasta que Ale la revise.
async function cierra(ctx, d, { resultado, motivo, rev = null, nuevo = null, clave = '', actorOk = false }) {
  const { notion } = ctx;
  const campos = { 'Procesada el': P.fecha(ctx.iso) };
  if (rev) campos['Revisión'] = P.relacion([rev.id]);
  if (clave) campos.Clave = P.texto(clave);
  if (actorOk) campos['Actor verificado'] = P.personas([d.actor]);
  let revisionTocada = false;
  const reconciliar = async m => {
    try { await notion.update(d.id, { Resultado: P.select('Pendiente de reconciliar'), Motivo: P.texto(m) }); } catch {}
    if (rev && revisionTocada) {
      try { await notion.update(rev.id, { Estado: P.estado('Pendiente de reconciliar'), Recibo: P.texto(`Escritura incompleta con la decisión ${d.id}: ${m}`) }); } catch {}
    }
    if (rev) rev.estado = 'Pendiente de reconciliar';             // en esta corrida, nada más sobre esa revisión
    return 'Pendiente de reconciliar';
  };
  if (!nuevo) {
    await notion.update(d.id, { ...campos, Resultado: P.select(resultado), Motivo: P.texto(motivo) });
  } else {
    await notion.update(d.id, { ...campos, Resultado: P.select('Pendiente de reconciliar'), Motivo: P.texto(`En proceso: ${motivo}. Si queda así, reconciliar a mano.`) });
    try {
      revisionTocada = true;
      await notion.update(rev.id, { Estado: P.estado(nuevo),
        Recibo: P.texto(`${resultado === 'En conflicto' ? 'En conflicto' : d.tipo} · ${d.actor} · decisión ${d.id} · ${ctx.iso}`) });
      const leida = leeRevision(await notion.get(rev.id));
      if (leida.estado !== nuevo) return reconciliar(`Readback: la revisión quedó en ${leida.estado || 'vacío'} y se esperaba ${nuevo}. Reconciliar a mano.`);
      rev.estado = nuevo;
      await notion.update(d.id, { Resultado: P.select(resultado), Motivo: P.texto(motivo) });
    } catch (e) {
      return reconciliar(`No se completó la escritura (${corto(e)}). Reconciliar a mano; no se reintenta sola.`);
    }
  }
  let ld;
  try { ld = leeDecision(await notion.get(d.id)); } catch (e) { return reconciliar(`No se pudo releer la decisión (${corto(e)}). Reconciliar a mano.`); }
  if (ld.resultado !== resultado) return reconciliar(`Readback: la decisión quedó en ${ld.resultado || 'vacío'} y se esperaba ${resultado}. Reconciliar a mano.`);
  return resultado;
}

// Lista para exponer → En revisión. Primero reemplaza las vigentes del mismo cliente y entregable (si eso falla, no se
// expone: nunca hay dos vigentes), luego expone con secuencia, huella y fecha, y relee.
async function exponeRevisiones(ctx) {
  const { notion, rc } = ctx;
  const filas = await todas(ctx, rc.revisiones, { property: 'Estado', select: { equals: 'Lista para exponer' } }, POR_LLEGADA);
  const listas = filas.map(leeRevision).sort((a, b) => (Date.parse(a.creada) - Date.parse(b.creada)) || (a.codigo - b.codigo));
  for (const rev of listas) {
    if (sinTiempo(ctx)) { ctx.out.push(['exponer', 'presupuesto_agotado']); break; }
    const cliente = clienteCanary(ctx, rev);
    if (!cliente) continue;
    const pendiente = async m => {
      await notion.update(rev.id, { Estado: P.estado('Pendiente de reconciliar'), Recibo: P.texto(`No se expuso: ${m} (${ctx.iso})`) });
      ctx.out.push([rev.id, 'no_expuesta', m]);
    };
    try {
      if (cliente === 'ambiguo') { await pendiente('no tiene exactamente una ficha de cliente'); continue; }
      if (!ENTREGABLE.test(rev.entregable)) { await pendiente('Entregable vacío o inválido (minúsculas, números y guiones)'); continue; }
      if (!PAGINA.test(rev.pagina)) { await pendiente('falta la Página del cliente (URL de Notion)'); continue; }
      const h = huellaDe(rev.manifiesto);
      if (!h.ok) { await pendiente(h.motivo); continue; }
      const q = await notion.query(rc.revisiones, { and: [{ property: 'Entregable', rich_text: { equals: rev.entregable } },
        { property: 'Cliente', relation: { contains: cliente } }] }, 100);
      if (q.has_more) { await pendiente('demasiadas revisiones de este entregable; reconciliar a mano'); continue; }
      const llave = `${sinGuiones(cliente)}|${rev.entregable}`;
      const mismas = q.results.map(leeRevision).filter(x => x.id !== rev.id && x.cliente.length === 1 && sinGuiones(x.cliente[0]) === sinGuiones(cliente));
      const recien = ctx.expuestasAhora.get(llave);                // el índice de Notion puede no reflejarla todavía
      if (recien) {
        const i = mismas.findIndex(x => x.id === recien.id);
        if (i >= 0) mismas.splice(i, 1);
        mismas.push(recien);
      }
      const enReconciliacion = mismas.find(x => x.estado === 'Pendiente de reconciliar');
      if (enReconciliacion) { await pendiente(`${cod(enReconciliacion.codigo)} del mismo entregable está pendiente de reconciliar`); continue; }
      const vigentes = mismas.filter(x => EXPUESTA.includes(x.estado));
      for (const v of vigentes) {
        await notion.update(v.id, { Estado: P.estado('Reemplazada'), Recibo: P.texto(`Reemplazada por ${cod(rev.codigo)} el ${ctx.iso}`) });
        v.estado = 'Reemplazada';
      }
      const secuencia = Math.max(0, ...mismas.map(x => x.secuencia || 0)) + 1;
      await notion.update(rev.id, { Estado: P.estado('En revisión'), Secuencia: P.numero(secuencia), Huella: P.texto(h.huella),
        'Expuesta el': P.fecha(ctx.iso), 'Reemplaza a': P.relacion(vigentes.map(v => v.id)) });
      const leida = leeRevision(await notion.get(rev.id));
      if (leida.estado !== 'En revisión' || leida.huella !== h.huella) { await pendiente('readback distinto después de exponer'); continue; }
      ctx.expuestasAhora.set(llave, { ...leida, secuencia });
      ctx.out.push([rev.id, 'expuesta', secuencia]);
    } catch (e) {
      ctx.out.push([rev.id, 'error', corto(e)]);
      try { await pendiente(`error al exponer (${corto(e)})`); } catch {}
    }
  }
}
