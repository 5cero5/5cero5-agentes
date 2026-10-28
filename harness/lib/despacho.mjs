import { P, leePagina } from './notion.mjs';
import { parametrosSesion } from './sessions.mjs';
import { despachaCampanas, piezasPendientes } from './campanas.mjs';
import { agenteDe } from './agentes.mjs';
import { conGithub } from './github.mjs';
import { preparaCliente, resuelveCliente } from './clientes.mjs';

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

// Sesiones de hoy por cliente (id de su ficha). Las filas sin cliente resoluble no cuentan para ningún cliente.
async function sesionesHoyPorCliente(notion, c, paginas, cache) {
  const cuenta = new Map();
  for (const pg of paginas) {
    try { const cli = await resuelveCliente(notion, c, leePagina(pg), cache); cuenta.set(cli.id, (cuenta.get(cli.id) || 0) + 1); } catch {}
  }
  return cuenta;
}

export async function despacha({ client, notion, c, fetchImpl = fetch }) {
  const out = { creadas: [], omitidas: [], error: null };
  if (c.pausa) { out.error = 'HARNESS_PAUSA'; return out; }

  const hoy = new Date().toISOString().slice(0, 10);
  const del_dia = await notion.query(c.notionDataSource, { property: 'Inició', date: { on_or_after: hoy } }, 100);
  let cupo = c.maxSesionesPorDia - del_dia.results.length;
  // Ruteo por cliente: caché de páginas de Notion solo para esta corrida, y el cupo del día también por cliente.
  const cache = new Map();
  const hoyCliente = c.ruteoClientes ? await sesionesHoyPorCliente(notion, c, del_dia.results, cache) : null;

  const r = await notion.query(c.notionDataSource, { property: 'Estado', select: { equals: 'Aprobado' } }, 20);
  for (const page of r.results) {
    const fila = leePagina(page);
    const motivo = esDespachable(fila, c);
    if (motivo) { out.omitidas.push([fila.id, motivo]); continue; }
    if (agenteDe(fila.agente)?.meta) {
      // Pauta espera a que las piezas de su campaña estén en Listo (fusionadas y revisadas).
      const espera = await piezasPendientes(notion, c, fila);
      if (espera) { out.omitidas.push([fila.id, espera]); continue; }
    }
    // Con el ruteo, la fila toma todo de su cliente (cc). Cualquier falla del cliente: Error con el motivo y sin sesión.
    let cc = c, cli = null;
    if (c.ruteoClientes) {
      try { ({ cli, cc } = await preparaCliente({ client, notion, c, fila, cache })); }
      catch (e) {
        await notion.update(fila.id, { Estado: P.estado('Error'), Error: P.texto(e.message) });
        out.omitidas.push([fila.id, 'cliente']); continue;
      }
    }
    if (cupo <= 0) { out.omitidas.push([fila.id, 'tope_diario']); continue; }
    if (cli && (hoyCliente.get(cli.id) || 0) >= cc.maxSesionesPorDia) { out.omitidas.push([fila.id, 'tope_diario_cliente']); continue; }
    let params;
    try { params = parametrosSesion(fila, cc); }
    catch (e) {
      await notion.update(fila.id, { Estado: P.estado('Error'), Error: P.texto(e.message) });
      out.omitidas.push([fila.id, 'params']); continue;
    }
    // Se reclama ANTES de crear: si algo se cae a medias, no hay doble gasto.
    // Se limpia el Error de un intento anterior para que la fila no muestre un error que ya no aplica.
    await notion.update(fila.id, { Estado: P.estado('En curso'), Intentos: P.numero(fila.intentos + 1), Inició: P.fecha(ahora()), Error: P.texto('') });
    try {
      const s = await client.beta.sessions.create(await conGithub({ params, fila, c: cc, client, fetchImpl }));
      await notion.update(fila.id, { Sesión: P.texto(s.id) });
      out.creadas.push([fila.id, s.id]); cupo--;
      if (cli) hoyCliente.set(cli.id, (hoyCliente.get(cli.id) || 0) + 1);
    } catch (e) {
      // No se reintenta solo: un humano decide.
      await notion.update(fila.id, { Estado: P.estado('Error'), Error: P.texto(`No se pudo crear la sesión: ${e.message}`) });
      out.omitidas.push([fila.id, 'create_fallo']);
    }
  }
  // Después de las filas, las campañas aprobadas (comparten el cupo del día).
  out.campanas = await despachaCampanas({ client, notion, c, cupo, cache, hoyCliente, fetchImpl });
  return out;
}
