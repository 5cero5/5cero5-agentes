import { leePagina, P } from './notion.mjs';
import { cierraSesion } from './cierre.mjs';

// Red de seguridad: el webhook no reenvía lo perdido. Revisa lo que lleva "En curso" demasiado.
export async function barre({ client, notion, c, ahora = Date.now() }) {
  const out = [];
  const r = await notion.query(c.notionDataSource, { property: 'Estado', select: { equals: 'En curso' } }, 50);
  for (const page of r.results) {
    const fila = leePagina(page);
    if (!fila.sesion) {
      const min = fila.inicio ? (ahora - Date.parse(fila.inicio)) / 60000 : 999;
      if (min > 5) {
        await notion.update(fila.id, { Estado: P.estado('Error'), Error: P.texto('Reclamada pero sin sesión (se cayó entre pasos).') });
        out.push([fila.id, 'sin_sesion']);
      }
      continue;
    }
    const res = await cierraSesion({ client, notion, c, sessionId: fila.sesion });
    if (res.startsWith('aun_')) {
      const min = fila.inicio ? (ahora - Date.parse(fila.inicio)) / 60000 : 0;
      if (min > c.maxMinutosSesion) {
        try { await client.beta.sessions.events.send(fila.sesion, { events: [{ type: 'user.interrupt' }] }); } catch {}
        await notion.update(fila.id, { Estado: P.estado('Error'), Error: P.texto(`Pasó de ${c.maxMinutosSesion} min; se interrumpió.`) });
        out.push([fila.id, 'timeout']); continue;
      }
    }
    out.push([fila.id, res]);
  }
  return out;
}
