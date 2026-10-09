// Campañas aprobadas → sesión del agente CMO, que propone una fila por pieza en Aprobaciones.
// El harness crea la fila del propio CMO ("Desglose · <campaña>") ya En curso, así el cierre por webhook
// y el barrido funcionan igual que con cualquier otra fila.
import { P } from './notion.mjs';
import { parametrosSesion } from './sessions.mjs';

const RUTAS = ['Cita', 'Pedido', 'Visita']; // regla 2
const ahora = () => new Date().toISOString();

export function leeCampana(page) {
  const p = page.properties || {};
  const t = k => (p[k]?.rich_text || p[k]?.title || []).map(x => x.plain_text).join('');
  const multi = k => (p[k]?.multi_select || []).map(x => x.name);
  return {
    id: page.id,
    editadoPor: page.last_edited_by,
    nombre: t('Campaña'),
    estado: p['Estado']?.select?.name || null,
    cliente: p['Cliente']?.select?.name || null,
    ruta: p['Ruta']?.select?.name || null,
    objetivo: t('Objetivo'),
    kpi: p['KPI']?.select?.name || null,
    meta: p['Meta']?.number ?? null,
    costoMax: p['Costo máximo por resultado (MXN)']?.number ?? null,
    canales: multi('Canales'),
    formatos: multi('Formatos'),
    piezas: p['Piezas']?.number ?? null,
    landing: p['Lleva landing']?.checkbox === true,
    presupuesto: p['Presupuesto de pauta (MXN)']?.number ?? null,
    vigencia: p['Vigencia']?.date || null,
    brief: t('Brief'),
    aprobo: (p['Aprobó']?.people || []).map(x => x.id),
  };
}

// Mismas reglas que una fila: aprobada por Al o Bonzo y con la última edición suya.
export function esCampanaDespachable(k, c) {
  if (k.estado !== 'Aprobada') return 'estado';
  if (!c.aprobadores.length) return 'sin_aprobadores_configurados';
  if (!k.aprobo.some(id => c.aprobadores.includes(id))) return 'aprobo_no_autorizado';
  if (!c.aprobadores.includes(k.editadoPor?.id)) return 'ultima_edicion_no_es_de_un_aprobador';
  if (!RUTAS.includes(k.ruta)) return 'sin_ruta';
  if (!(k.piezas > 0)) return 'sin_piezas';
  if (!c.agentes.CMO) return 'cmo_sin_configurar';
  return null;
}

export function briefDeCampana(k, c) {
  const disponibles = Object.entries(c.agentes).filter(([n, id]) => id && n !== 'CMO').map(([n]) => n);
  const vig = k.vigencia ? `${k.vigencia.start}${k.vigencia.end ? ` a ${k.vigencia.end}` : ''}` : 'sin fecha';
  return [
    `Desglosa la campaña "${k.nombre}" (página de Notion ${k.id}). Lee también el cuerpo de la página.`,
    `Cliente: ${k.cliente || '?'} · Ruta: ${k.ruta} · Objetivo: ${k.objetivo || '?'}`,
    `KPI: ${k.kpi || '?'} · Meta: ${k.meta ?? '?'} · Costo máximo por resultado: ${k.costoMax ?? '?'} MXN`,
    `Canales: ${k.canales.join(', ') || '?'} · Formatos: ${k.formatos.join(', ') || '?'} · Piezas: ${k.piezas} · Lleva landing: ${k.landing ? 'sí' : 'no'}`,
    `Pauta: ${k.presupuesto ?? '?'} MXN · Vigencia: ${vig}`,
    `Brief de la campaña: ${k.brief || '(ver cuerpo de la página)'}`,
    `Agentes disponibles hoy: ${disponibles.join(', ') || 'ninguno'}.`,
    `Escribe las filas en Aprobaciones (data source ${c.notionDataSource}) con Campaña = "${k.nombre}" y Campaña ligada = ${k.id}.`,
  ].join('\n');
}

export async function despachaCampanas({ client, notion, c, cupo }) {
  const out = { creadas: [], omitidas: [] };
  const r = await notion.query(c.notionCampanas, { property: 'Estado', select: { equals: 'Aprobada' } }, 10);
  for (const page of r.results) {
    const k = leeCampana(page);
    const motivo = esCampanaDespachable(k, c);
    if (motivo) { out.omitidas.push([k.id, motivo]); continue; }
    if (cupo <= 0) { out.omitidas.push([k.id, 'tope_diario']); continue; }
    // Se reclama ANTES de crear nada: la campaña sale de Aprobada y no se vuelve a despachar.
    await notion.update(k.id, { Estado: P.select('En producción') });
    const brief = briefDeCampana(k, c);
    const trabajo = `Desglose · ${k.nombre}`;
    const nueva = await notion.create(c.notionDataSource, {
      Trabajo: P.titulo(trabajo),
      Agente: P.select('CMO'),
      Estado: P.estado('En curso'),
      Campaña: P.texto(k.nombre),
      'Campaña ligada': P.relacion([k.id]),
      Brief: P.texto(brief),
      Aprobó: P.personas(k.aprobo.filter(id => c.aprobadores.includes(id))),
      Intentos: P.numero(1),
      Inició: P.fecha(ahora()),
      'Tope de la sesión (USD)': P.numero(c.topeDefaultUsd),
    });
    const fila = { id: nueva.id, agente: 'CMO', trabajo, campana: k.nombre, brief, intentos: 0, tope: null };
    try {
      const s = await client.beta.sessions.create(parametrosSesion(fila, c));
      await notion.update(fila.id, { Sesión: P.texto(s.id) });
      out.creadas.push([k.id, fila.id, s.id]); cupo--;
    } catch (e) {
      await notion.update(fila.id, { Estado: P.estado('Error'), Error: P.texto(`No se pudo crear la sesión del CMO: ${e.message}`) });
      out.omitidas.push([k.id, 'create_fallo']);
    }
  }
  return out;
}

// Regla 8: lo que el CMO dice que escribió se comprueba en Notion, fila por fila.
// Devuelve { ok, informe }. No cambia ninguna fila; solo lee.
const sinGuiones = id => String(id || '').replace(/-/g, '').toLowerCase();
const AGENTES_DE_PIEZA = ['CRM', 'Landing', 'Creativo'];

export async function compruebaFilasCMO(notion, filaCMO, respuesta) {
  const campana = filaCMO.campanaLigada?.[0];
  const problemas = [];
  if (!campana) problemas.push('la fila del CMO no está ligada a una campaña');
  if (respuesta?.campana_id && campana && sinGuiones(respuesta.campana_id) !== sinGuiones(campana)) {
    problemas.push(`campana_id ${respuesta.campana_id} no es la campaña de la fila`);
  }
  const filas = Array.isArray(respuesta?.filas) ? respuesta.filas : [];
  let buenas = 0;
  for (const f of filas) {
    let page;
    try { page = await notion.get(f.id); } catch { problemas.push(`${f.id}: no existe o no se puede leer`); continue; }
    const p = page.properties || {};
    const mal = [];
    if (page.archived || page.in_trash) mal.push('está en la papelera');
    if (p['Estado']?.select?.name !== 'Propuesta') mal.push(`Estado = ${p['Estado']?.select?.name || 'vacío'}`);
    if ((p['Aprobó']?.people || []).length) mal.push('tiene Aprobó');
    if (!AGENTES_DE_PIEZA.includes(p['Agente']?.select?.name)) mal.push(`Agente = ${p['Agente']?.select?.name || 'vacío'}`);
    const ligadas = (p['Campaña ligada']?.relation || []).map(r => sinGuiones(r.id));
    if (!campana || !ligadas.includes(sinGuiones(campana))) mal.push('no está ligada a la campaña');
    if (mal.length) problemas.push(`${f.id}: ${mal.join(', ')}`); else buenas++;
  }
  const informe = `Comprobación en Notion: ${buenas}/${filas.length} filas en Propuesta, ligadas y sin aprobar.` +
    (problemas.length ? ` Problemas: ${problemas.join('; ')}.` : '');
  return { ok: filas.length > 0 && problemas.length === 0, informe };
}
