import { P, leePagina } from './notion.mjs';
import { parametrosSesion } from './sessions.mjs';

const ahora = () => new Date().toISOString();

// Una fila vale para despachar solo si TODO esto se cumple.
export function esDespachable(fila, c) {
  if (fila.estado !== 'Aprobado') return 'estado';
  if (!c.aprobadores.length) return 'sin_aprobadores_configurados';
  if (!fila.aprobo.some(id => c.aprobadores.includes(id))) return 'aprobo_no_autorizado';
  if (!c.aprobadores.includes(fila.editadoPor?.id)) return 'ultima_edicion_no_es_de_un_aprobador';
  if (!fila.brief) return 'sin_brief';
  if (fila.sesion) return 'ya_tiene_sesion';
  if (fila.intentos >= c.maxIntentos) return 'intentos_agotados';
  return null;
}

export async function despacha({ client, notion, c }) {
  const out = { creadas: [], omitidas: [], error: null };
  if (c.pausa) { out.error = 'HARNESS_PAUSA'; return out; }

  const hoy = new Date().toISOString().slice(0, 10);
  const del_dia = await notion.query(c.notionDataSource, { property: 'Inició', date: { on_or_after: hoy } }, 100);
  let cupo = c.maxSesionesPorDia - del_dia.results.length;

  const r = await notion.query(c.notionDataSource, { property: 'Estado', select: { equals: 'Aprobado' } }, 20);
  for (const page of r.results) {
    const fila = leePagina(page);
    const motivo = esDespachable(fila, c);
    if (motivo) { out.omitidas.push([fila.id, motivo]); continue; }
    if (cupo <= 0) { out.omitidas.push([fila.id, 'tope_diario']); continue; }
    let params;
    try { params = parametrosSesion(fila, c); }
    catch (e) {
      await notion.update(fila.id, { Estado: P.estado('Error'), Error: P.texto(e.message) });
      out.omitidas.push([fila.id, 'params']); continue;
    }
    // Se reclama ANTES de crear: si algo se cae a medias, no hay doble gasto.
    await notion.update(fila.id, { Estado: P.estado('En curso'), Intentos: P.numero(fila.intentos + 1), Inició: P.fecha(ahora()) });
    try {
      const s = await client.beta.sessions.create(params);
      await notion.update(fila.id, { Sesión: P.texto(s.id) });
      out.creadas.push([fila.id, s.id]); cupo--;
    } catch (e) {
      // No se reintenta solo: un humano decide.
      await notion.update(fila.id, { Estado: P.estado('Error'), Error: P.texto(`No se pudo crear la sesión: ${e.message}`) });
      out.omitidas.push([fila.id, 'create_fallo']);
    }
  }
  return out;
}
