// Cliente mínimo de Notion (fetch). Esquema: base "Aprobaciones".
const V = '2025-09-03';

export function notionClient(token, fetchImpl = fetch) {
  async function call(method, path, body) {
    const r = await fetchImpl(`https://api.notion.com/v1${path}`, {
      method,
      headers: { Authorization: `Bearer ${token}`, 'Notion-Version': V, 'Content-Type': 'application/json' },
      body: body ? JSON.stringify(body) : undefined,
    });
    const t = await r.text();
    if (!r.ok) throw new Error(`Notion ${method} ${path} ${r.status}: ${t.slice(0, 300)}`);
    return t ? JSON.parse(t) : {};
  }
  return {
    query: (ds, filter, page_size = 50) => call('POST', `/data_sources/${ds}/query`, { filter, page_size }),
    update: (pageId, properties) => call('PATCH', `/pages/${pageId}`, { properties }),
    get: pageId => call('GET', `/pages/${pageId}`),
    create: (ds, properties) => call('POST', '/pages', { parent: { type: 'data_source_id', data_source_id: ds }, properties }),
  };
}

const txt = s => ({ rich_text: s ? [{ type: 'text', text: { content: String(s).slice(0, 1900) } }] : [] });
export const P = {
  estado: v => ({ select: { name: v } }),
  texto: txt,
  numero: n => ({ number: n }),
  fecha: iso => ({ date: { start: iso } }),
  verificador: v => ({ select: { name: v } }),
  select: v => ({ select: { name: v } }),
  titulo: s => ({ title: [{ type: 'text', text: { content: String(s).slice(0, 200) } }] }),
  relacion: ids => ({ relation: ids.map(id => ({ id })) }),
  personas: ids => ({ people: ids.map(id => ({ id })) }),
};

export function leePagina(page) {
  const p = page.properties || {};
  const t = k => (p[k]?.rich_text || p[k]?.title || []).map(x => x.plain_text).join('');
  return {
    id: page.id,
    editadoPor: page.last_edited_by,            // {object:'user', id}
    trabajo: t('Trabajo'),
    agente: p['Agente']?.select?.name || null,
    estado: p['Estado']?.select?.name || null,
    brief: t('Brief'),
    campana: t('Campaña'),
    sesion: t('Sesión'),
    intentos: p['Intentos']?.number ?? 0,
    tope: p['Tope de la sesión (USD)']?.number ?? null,
    aprobo: (p['Aprobó']?.people || []).map(x => x.id),
    aprobadoEl: p['Aprobado el']?.date?.start || null,
    inicio: p['Inició']?.date?.start || null,
    campanaLigada: (p['Campaña ligada']?.relation || []).map(r => r.id),
  };
}
