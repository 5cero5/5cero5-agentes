// Campañas aprobadas → sesión del agente CMO, que propone una fila por pieza en Aprobaciones.
// El harness crea la fila del propio CMO ("Desglose · <campaña>") ya En curso, así el cierre por webhook
// y el barrido funcionan igual que con cualquier otra fila.
import { P } from './notion.mjs';
import { parametrosSesion } from './sessions.mjs';
import { clienteDeCampana, validaCliente, compruebaVault, cfgCliente } from './clientes.mjs';
import { conGithub } from './github.mjs';

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
  const disponibles = Object.entries(c.agentes).filter(([n, id]) => id && AGENTES_DE_PIEZA.includes(n)).map(([n]) => n);
  const vig = k.vigencia ? `${k.vigencia.start}${k.vigencia.end ? ` a ${k.vigencia.end}` : ''}` : 'sin fecha';
  return [
    `Desglosa la campaña "${k.nombre}" (página de Notion ${k.id}). Lee también el cuerpo de la página.`,
    `Cliente: ${c.cliente ? `${c.cliente.nombre} (${c.cliente.slug})` : k.cliente || '?'} · Ruta: ${k.ruta} · Objetivo: ${k.objetivo || '?'}`,
    `KPI: ${k.kpi || '?'} · Meta: ${k.meta ?? '?'} · Costo máximo por resultado: ${k.costoMax ?? '?'} MXN`,
    `Canales: ${k.canales.join(', ') || '?'} · Formatos: ${k.formatos.join(', ') || '?'} · Piezas: ${k.piezas} · Lleva landing: ${k.landing ? 'sí' : 'no'}`,
    `Pauta: ${k.presupuesto ?? '?'} MXN · Vigencia: ${vig}`,
    `Brief de la campaña: ${k.brief || '(ver cuerpo de la página)'}`,
    `Agentes disponibles hoy: ${disponibles.join(', ') || 'ninguno'}.`,
    c.agentes.Pauta && c.meta?.cuenta
      ? `Agente de Pauta (Meta): disponible. Tope diario por campaña: ${c.meta.topeDiarioMxn} MXN. Destinos permitidos: ${(c.meta.dominios || []).join(', ')}. Objetivo: ${c.meta.pixel ? 'Tráfico o Clientes potenciales (hay Pixel)' : 'solo Tráfico (sin Pixel)'}.`
      : 'Agente de Pauta (Meta): no disponible.',
    `Escribe las filas en Aprobaciones (data source ${c.notionDataSource}) con Campaña = "${k.nombre}" y Campaña ligada = ${k.id}.`,
  ].join('\n');
}

export async function despachaCampanas({ client, notion, c, cupo, cache = new Map(), hoyCliente = new Map(), fetchImpl = fetch }) {
  const out = { creadas: [], omitidas: [] };
  const r = await notion.query(c.notionCampanas, { property: 'Estado', select: { equals: 'Aprobada' } }, 10);
  for (const page of r.results) {
    const k = leeCampana(page);
    const motivo = esCampanaDespachable(k, c);
    if (motivo) { out.omitidas.push([k.id, motivo]); continue; }
    if (cupo <= 0) { out.omitidas.push([k.id, 'tope_diario']); continue; }
    // Ruteo por cliente: la campaña tiene que tener un solo cliente Activo con Vault CMO suyo y Ruta. Si no, la fila del CMO
    // se crea ya en Error con el motivo (queda a la vista y la campaña no se vuelve a despachar).
    let cc = c, cli = null, errCliente = null;
    if (c.ruteoClientes) {
      try { cli = await clienteDeCampana(notion, c, k.id, cache); validaCliente(cli, 'CMO'); await compruebaVault(client, cli, 'CMO'); cc = cfgCliente(c, cli); }
      catch (e) { errCliente = e.message; }
      if (cli && !errCliente && (hoyCliente.get(cli.id) || 0) >= cc.maxSesionesPorDia) { out.omitidas.push([k.id, 'tope_diario_cliente']); continue; }
    }
    // Se reclama ANTES de crear nada: la campaña sale de Aprobada y no se vuelve a despachar.
    await notion.update(k.id, { Estado: P.select('En producción') });
    const brief = briefDeCampana(k, cc);
    const trabajo = `Desglose · ${k.nombre}`;
    const nueva = await notion.create(c.notionDataSource, {
      Trabajo: P.titulo(trabajo),
      Agente: P.select('CMO'),
      Estado: P.estado(errCliente ? 'Error' : 'En curso'),
      ...(errCliente ? { Error: P.texto(errCliente) } : {}),
      Campaña: P.texto(k.nombre),
      'Campaña ligada': P.relacion([k.id]),
      Brief: P.texto(brief),
      Aprobó: P.personas(k.aprobo.filter(id => c.aprobadores.includes(id))),
      Intentos: P.numero(1),
      Inició: P.fecha(ahora()),
      'Tope de la sesión (USD)': P.numero(cc.topeDefaultUsd),
    });
    if (errCliente) { out.omitidas.push([k.id, 'cliente']); continue; }
    const fila = { id: nueva.id, agente: 'CMO', trabajo, campana: k.nombre, brief, intentos: 0, tope: null };
    try {
      const s = await client.beta.sessions.create(await conGithub({ params: parametrosSesion(fila, cc), fila, c: cc, client, fetchImpl }));
      await notion.update(fila.id, { Sesión: P.texto(s.id) });
      out.creadas.push([k.id, fila.id, s.id]); cupo--;
      if (cli) hoyCliente.set(cli.id, (hoyCliente.get(cli.id) || 0) + 1);
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
  let buenas = 0, pautas = 0;
  for (const f of filas) {
    let page;
    try { page = await notion.get(f.id); } catch { problemas.push(`${f.id}: no existe o no se puede leer`); continue; }
    const p = page.properties || {};
    const mal = [];
    if (page.archived || page.in_trash) mal.push('está en la papelera');
    if (p['Estado']?.select?.name !== 'Propuesta') mal.push(`Estado = ${p['Estado']?.select?.name || 'vacío'}`);
    if ((p['Aprobó']?.people || []).length) mal.push('tiene Aprobó');
    const agente = p['Agente']?.select?.name;
    if (agente === 'Pauta') pautas++;
    else if (!AGENTES_DE_PIEZA.includes(agente)) mal.push(`Agente = ${agente || 'vacío'}`);
    const ligadas = (p['Campaña ligada']?.relation || []).map(r => sinGuiones(r.id));
    if (!campana || !ligadas.includes(sinGuiones(campana))) mal.push('no está ligada a la campaña');
    if (mal.length) problemas.push(`${f.id}: ${mal.join(', ')}`); else buenas++;
  }
  if (pautas > 1) problemas.push(`${pautas} filas de Pauta (se permite una por campaña)`);
  const informe = `Comprobación en Notion: ${buenas}/${filas.length} filas en Propuesta, ligadas y sin aprobar${pautas ? ` (una de Pauta)` : ''}.` +
    (problemas.length ? ` Problemas: ${problemas.join('; ')}.` : '');
  return { ok: filas.length > 0 && problemas.length === 0, informe };
}

// Una fila de Pauta ligada a una campaña espera a sus piezas: no se despacha mientras alguna fila del Creativo de esa
// campaña no esté en Listo (Rechazado no cuenta). Sin campaña ligada (fila hecha a mano), no hay nada que esperar.
export async function piezasPendientes(notion, c, fila) {
  const campana = fila.campanaLigada?.[0];
  if (!campana) return null;
  const r = await notion.query(c.notionDataSource, { and: [
    { property: 'Campaña ligada', relation: { contains: campana } },
    { property: 'Agente', select: { equals: 'Creativo' } },
  ] }, 50);
  const piezas = r.results.map(pg => pg.properties?.Estado?.select?.name).filter(e => e !== 'Rechazado');
  if (!piezas.length) return 'sin_piezas_del_creativo';
  return piezas.every(e => e === 'Listo') ? null : 'piezas_pendientes';
}
