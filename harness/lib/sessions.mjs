import Anthropic from '@anthropic-ai/sdk';
import { BETA } from './config.mjs';

export function anthropic(key = process.env.ANTHROPIC_API_KEY) {
  return new Anthropic({ apiKey: key, defaultHeaders: { 'anthropic-beta': BETA } });
}

// Puro y testeable: arma los parámetros de sesión a partir de una fila aprobada.
export function parametrosSesion(fila, c) {
  const agent = c.agentes[fila.agente];
  if (!agent) throw new Error(`Agente sin configurar: ${fila.agente}`);
  if (!c.environmentId) throw new Error('Falta MA_ENVIRONMENT_ID');
  const tope = Math.min(fila.tope ?? c.topeDefaultUsd, c.topeMaxUsd);
  if (!(tope > 0)) throw new Error('Tope inválido');
  const mensaje = [
    `Trabajo: ${fila.trabajo}`,
    fila.campana ? `Campaña: ${fila.campana}` : '',
    '',
    'Brief aprobado:',
    fila.brief,
    '',
    'Reglas fijas: entrega solo a un borrador (draft deploy); no publiques; no gastes; no prometas nada que C30 prohíba. Al terminar, responde con un JSON: {"deploy_id":"...","archivos":[...],"sha1":{...}}.',
  ].filter(x => x !== undefined).join('\n');
  const p = {
    agent,
    environment_id: c.environmentId,
    title: `${fila.agente} · ${fila.trabajo}`.slice(0, 120),
    budget: { type: 'limit', max_list_cost: { amount: String(Math.round(tope * 100)), currency: 'USD' } },
    metadata: { notion_page_id: fila.id, agente: fila.agente, intento: String(fila.intentos + 1) },
    vault_ids: c.vaultIds,
    initial_events: [{ type: 'user.message', content: [{ type: 'text', text: mensaje }] }],
  };
  if (c.repoUrl) {
    p.resources = [{
      type: 'github_repository', url: c.repoUrl, mount_path: c.repoMount,
      ...(c.repoToken ? { authorization_token: c.repoToken } : {}),
    }];
  }
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
