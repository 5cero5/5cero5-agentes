// HighLevel: comprobación de la plantilla que dice el agente CRM que subió (regla 8), en la subcuenta del cliente.
// Solo lectura. El token es HL_TOKEN_<SLUG> (variable secreta de Netlify, integración privada de esa subcuenta con permiso
// de leer Email Builder) y viaja solo en el encabezado Authorization. Sin token no se da por buena.

export async function compruebaPlantilla({ c, respuesta, fetchImpl = fetch }) {
  const loc = c.hl?.location, token = c.hl?.token, slug = c.cliente?.slug || '?';
  if (!loc) return { ok: false, informe: `Comprobación en HighLevel: falta el Location ID de ${slug}.` };
  if (!token) return { ok: false, informe: `Comprobación en HighLevel: falta HL_TOKEN_${slug.toUpperCase().replace(/-/g, '_')} en Netlify (sin comprobación). Revisar a mano en Marketing > Emails > Templates.` };
  const r = respuesta || {};
  const id = String(r.plantilla_id || ''), nombre = String(r.nombre || '');
  if (!id) return { ok: false, informe: 'Comprobación en HighLevel: sin plantilla_id.' };
  const q = new URLSearchParams({ locationId: loc, search: nombre, limit: '100' });
  let d;
  try {
    const res = await fetchImpl(`${c.hl.api.replace(/\/$/, '')}/emails/builder?${q}`, {
      headers: { Authorization: `Bearer ${token}`, Version: '2021-07-28', Accept: 'application/json', 'User-Agent': '5cero5-harness' } });
    const t = await res.text();
    if (!res.ok) return { ok: false, informe: `Comprobación en HighLevel: la subcuenta ${loc} respondió ${res.status} al leer plantillas.` };
    d = t ? JSON.parse(t) : {};
  } catch (e) { return { ok: false, informe: `Comprobación en HighLevel: no se pudo leer la subcuenta ${loc} (${e.message}).` }; }
  const lista = d.builders || d.templates || [];
  const t = lista.find(x => String(x.id) === id);
  const problemas = [];
  if (!t) problemas.push(`la plantilla ${id} no está en la subcuenta ${loc} de ${slug}`);
  else if ((t.name || t.title) !== nombre) problemas.push(`en HighLevel se llama ${t.name || t.title}, el agente dijo ${nombre}`);
  if (!nombre.startsWith('[agente] ')) problemas.push('el nombre no empieza con "[agente] "');
  return { ok: problemas.length === 0,
    informe: `Comprobación en HighLevel (subcuenta ${loc}): plantilla ${id}.` + (problemas.length ? ` Problemas: ${problemas.join('; ')}.` : ' Existe con su nombre. Falta mirarla y activarla a mano.') };
}
