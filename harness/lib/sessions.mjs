import Anthropic from '@anthropic-ai/sdk';
import { BETA } from './config.mjs';
import { agenteDe, mensajeInicial } from './agentes.mjs';

export function anthropic(key = process.env.ANTHROPIC_API_KEY) {
  return new Anthropic({ apiKey: key, defaultHeaders: { 'anthropic-beta': BETA } });
}

// Puro y testeable: arma los parámetros de sesión a partir de una fila aprobada.
// Falla cerrado: si falta el agente, su id, un repo que declara o el tope es inválido, no hay sesión.
export function parametrosSesion(fila, c) {
  const def = agenteDe(fila.agente);
  const agent = def ? c.agentes[fila.agente] : null;
  if (!def || !agent) throw new Error(`Agente sin configurar: ${fila.agente}`);
  if (!c.environmentId) throw new Error('Falta MA_ENVIRONMENT_ID');
  const tope = Math.min(fila.tope ?? c.topeDefaultUsd, c.topeMaxUsd);
  // Managed Agents recibe el tope en centavos y como cadena ("200" = 2 USD; "2.00" se rechaza).
  const centavos = Math.round(tope * 100);
  if (!(centavos >= 1)) throw new Error('Tope inválido');
  const resources = def.repos.map(nombre => {
    const r = c.repos[nombre];
    if (!r?.url) throw new Error(`Falta ${r?.variable || nombre} para el agente ${fila.agente}`);
    return { type: 'github_repository', url: r.url, mount_path: r.mount, ...(r.token ? { authorization_token: r.token } : {}) };
  });
  const p = {
    agent,
    environment_id: c.environmentId,
    title: `${fila.agente} · ${fila.trabajo}`.slice(0, 120),
    budget: { type: 'limit', max_list_cost: { amount: String(centavos), currency: 'USD' } },
    metadata: { notion_page_id: fila.id, agente: fila.agente, intento: String(fila.intentos + 1) },
    vault_ids: c.vaultsPorAgente?.[fila.agente]?.length ? c.vaultsPorAgente[fila.agente] : c.vaultIds,
    initial_events: [{ type: 'user.message', content: [{ type: 'text', text: mensajeInicial(fila, def) }] }],
  };
  if (resources.length) p.resources = resources;
  return p;
}

export async function ultimoMensajeAgente(client, sessionId) {
  let ultimo = '';
  for await (const ev of client.beta.sessions.events.list(sessionId, { limit: 100 })) {
    if (ev.type === 'agent.message') {
      ultimo = ev.content.map(b => b.text || '').join('');
    }
  }
  return ultimo;
}
