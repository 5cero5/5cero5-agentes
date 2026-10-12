// Meta Ads: comprobación de lo que dice el agente Pauta que creó (regla 8) y freno.
// Solo Node (fetch), sin dependencias. El token es el del usuario del sistema (META_TOKEN, variable secreta de Netlify)
// y viaja solo en el encabezado Authorization.
//   - Lee la campaña, su conjunto y sus anuncios en la cuenta configurada.
//   - Todo tiene que estar en pausa. Lo que no lo esté, el harness lo PAUSA de inmediato (única escritura del harness
//     en Meta) y la fila sale Rechazada: encender es de Al o Bonzo, nunca de un agente.

async function graph(c, fetchImpl, method, path, params = {}) {
  const q = new URLSearchParams(Object.entries(params).map(([k, v]) => [k, typeof v === 'object' ? JSON.stringify(v) : String(v)]));
  const url = `${c.meta.api.replace(/\/$/, '')}${path}${method === 'GET' && q.size ? `?${q}` : ''}`;
  const r = await fetchImpl(url, {
    method,
    headers: { Authorization: `Bearer ${c.meta.token}`, 'User-Agent': '5cero5-harness',
      ...(method === 'POST' ? { 'Content-Type': 'application/x-www-form-urlencoded' } : {}) },
    body: method === 'POST' ? q.toString() : undefined,
  });
  const t = await r.text();
  let data = {};
  try { data = t ? JSON.parse(t) : {}; } catch { data = { raw: t.slice(0, 200) }; }
  if (!r.ok) { const e = new Error(`Meta ${method} ${path} -> ${r.status}: ${data.error?.message || ''}`); e.status = r.status; throw e; }
  return data;
}

const hostDe = u => { try { return new URL(u).hostname.toLowerCase(); } catch { return ''; } };

// Pausa una entidad (campaña, conjunto o anuncio). Devuelve null si pudo, o el error.
export async function pausa(c, id, fetchImpl = fetch) {
  try { await graph(c, fetchImpl, 'POST', `/${id}`, { status: 'PAUSED' }); return null; }
  catch (e) { return e.message; }
}

// respuesta: el JSON del agente. inicio: cuándo se despachó la fila (ISO); la campaña tiene que ser posterior.
export async function compruebaCampana({ c, respuesta, inicio, fetchImpl = fetch }) {
  const m = c.meta || {};
  const faltan = [['META_TOKEN', m.token], ['META_AD_ACCOUNT_ID', m.cuenta], ['META_PAGE_ID', m.pagina]].filter(([, v]) => !v).map(([k]) => k);
  if (faltan.length) return { ok: false, informe: `Comprobación en Meta: falta ${faltan.join(', ')} en el harness. Revisar a mano en el Administrador de anuncios.` };
  const r = respuesta || {};
  const cid = String(r.campana_meta_id || '');
  if (!/^\d+$/.test(cid)) return { ok: false, informe: 'Comprobación en Meta: sin campana_meta_id válido.' };
  const problemas = [], avisos = [], pausadas = [];
  const g = (path, params) => graph(c, fetchImpl, 'GET', path, params);
  let camp, conjuntos = [], ads = [];
  try {
    camp = await g(`/${cid}`, { fields: 'id,name,status,effective_status,objective,account_id,created_time' });
    conjuntos = (await g(`/${cid}/adsets`, { fields: 'id,name,status,daily_budget,lifetime_budget', limit: 50 })).data || [];
    ads = (await g(`/${cid}/ads`, { fields: 'id,name,status,creative{id,object_story_spec,url_tags}', limit: 50 })).data || [];
  } catch (e) {
    return { ok: false, informe: `Comprobación en Meta: no se pudo leer la campaña ${cid} (${e.message}). Revisar a mano en el Administrador de anuncios.` };
  }

  // Freno primero: cualquier cosa que no esté en pausa se pausa, sea de quien sea la culpa.
  for (const [tipo, e] of [['campaña', camp], ...conjuntos.map(x => ['conjunto', x]), ...ads.map(x => ['anuncio', x])]) {
    if (e?.status !== 'PAUSED') {
      const err = await pausa(c, e.id, fetchImpl);
      problemas.push(`${tipo} ${e.id} estaba en ${e.status}: ${err ? `NO SE PUDO PAUSAR (${err}), pausarla a mano YA` : 'el harness la pausó'}`);
      pausadas.push(e.id);
    }
  }
  if (`act_${camp.account_id}` !== m.cuenta) problemas.push(`la campaña es de la cuenta act_${camp.account_id}, no de ${m.cuenta}`);
  if (camp.name !== r.nombre) problemas.push(`la campaña se llama ${camp.name}, el agente dijo ${r.nombre}`);
  if (inicio && camp.created_time && Date.parse(camp.created_time) < Date.parse(inicio) - 5 * 60e3)
    problemas.push(`la campaña es de ${camp.created_time}, anterior a esta sesión`);
  if (conjuntos.length !== 1) problemas.push(`${conjuntos.length} conjuntos (se espera 1)`);
  else if (String(conjuntos[0].id) !== String(r.conjunto_id)) problemas.push(`el conjunto ${conjuntos[0].id} no es el reportado (${r.conjunto_id})`);
  for (const s of conjuntos) {
    const diario = Number(s.daily_budget || 0) / 100;
    if (Number(s.lifetime_budget || 0)) problemas.push(`el conjunto ${s.id} trae presupuesto total; solo se permite diario`);
    if (!(diario > 0)) problemas.push(`el conjunto ${s.id} no tiene presupuesto diario`);
    if (diario > m.topeDiarioMxn) problemas.push(`el conjunto ${s.id} tiene ${diario} MXN al día, arriba del tope de ${m.topeDiarioMxn}`);
    if (r.presupuesto_diario_mxn !== undefined && Math.abs(diario - Number(r.presupuesto_diario_mxn)) > 0.01)
      avisos.push(`presupuesto: el agente dijo ${r.presupuesto_diario_mxn} MXN, Meta tiene ${diario}`);
  }
  const reportados = (Array.isArray(r.anuncios) ? r.anuncios : []).map(a => String(a?.id)).sort();
  const enMeta = ads.map(a => String(a.id)).sort();
  if (JSON.stringify(reportados) !== JSON.stringify(enMeta)) problemas.push(`anuncios: el agente reportó ${reportados.length}, Meta tiene ${enMeta.length} distintos o con otros ids`);
  for (const a of ads) {
    const spec = a.creative?.object_story_spec || {};
    const link = spec.link_data?.link || spec.link_data?.call_to_action?.value?.link || '';
    if (String(spec.page_id || '') !== String(m.pagina)) problemas.push(`el anuncio ${a.id} no usa la página ${m.pagina}`);
    if (!m.dominios.includes(hostDe(link))) problemas.push(`el anuncio ${a.id} lleva a ${link || 'ningún lado'}, fuera de ${m.dominios.join(', ')}`);
    if (!String(a.creative?.url_tags || '').includes('utm_source=meta')) avisos.push(`el anuncio ${a.id} no trae las UTM de la convención`);
  }
  try {
    const cuenta = await g(`/${m.cuenta}`, { fields: 'spend_cap,amount_spent' });
    if (!Number(cuenta.spend_cap || 0)) avisos.push('la cuenta no tiene límite de gasto: ponerlo antes de encender');
  } catch { avisos.push('no se pudo leer el límite de gasto de la cuenta'); }

  const resumen = `Comprobación en Meta: campaña ${cid} (${camp.name}, ${camp.objective}), ${conjuntos.length} conjunto(s), ${ads.length} anuncio(s)` +
    (conjuntos[0] ? `, ${Number(conjuntos[0].daily_budget || 0) / 100} MXN al día` : '') + '.';
  const informe = resumen +
    (problemas.length ? ` Problemas: ${problemas.join('; ')}.` : ' Todo en pausa, en la cuenta y página correctas, dentro del tope.') +
    (avisos.length ? ` Avisos: ${avisos.join('; ')}.` : '') +
    (problemas.length ? '' : ' Falta revisar en el Administrador de anuncios y encenderla (Al o Bonzo).');
  return { ok: problemas.length === 0, informe, pausadas };
}
