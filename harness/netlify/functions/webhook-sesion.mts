import type { Config } from '@netlify/functions';
import { cfg, eventoDeCierre } from '../../lib/config.mjs';
import { notionClient } from '../../lib/notion.mjs';
import { anthropic } from '../../lib/sessions.mjs';
import { cierraSesion } from '../../lib/cierre.mjs';

export default async (req: Request) => {
  if (req.method !== 'POST') return new Response('método', { status: 405 });
  const body = await req.text();
  const client = anthropic();
  let ev: any;
  try {
    ev = client.beta.webhooks.unwrap(body, { headers: Object.fromEntries(req.headers), key: process.env.ANTHROPIC_WEBHOOK_SIGNING_KEY });
  } catch { return new Response('firma inválida', { status: 400 }); }
  const t = ev?.data?.type;
  const sessionId = ev?.data?.id;
  const cierre = eventoDeCierre(t);
  if (!sessionId || !cierre) {
    return new Response('ok', { status: 200 }); // otros eventos (incluidos los de hilos): se reconocen y se ignoran
  }
  const c = cfg();
  try {
    const r = await cierraSesion({ client, notion: notionClient(c.notionToken), c, sessionId, motivo: cierre.motivo });
    console.log(t, sessionId, r);
  } catch (e) {
    console.error('cierre falló', sessionId, (e as Error).message);
    return new Response('reintentar', { status: 500 }); // Anthropic reintenta hasta 3 veces; el barrido cubre el resto
  }
  return new Response('ok', { status: 200 });
};
export const config: Config = { path: '/api/webhook-sesion' };
