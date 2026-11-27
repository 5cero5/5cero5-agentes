import type { Config } from '@netlify/functions';
import { cfg } from '../../lib/config.mjs';
import { notionClient } from '../../lib/notion.mjs';
import { anthropic } from '../../lib/sessions.mjs';
import { barre } from '../../lib/barrido.mjs';
import { revisionCliente } from '../../lib/revision-cliente.mjs';

export default async () => {
  const c = cfg();
  const notion = notionClient(c.notionToken);
  console.log(JSON.stringify(await barre({ client: anthropic(), notion, c })));
  // Revisión del cliente (épica E2): paso aparte, apagado por defecto y detenido con HARNESS_PAUSA. Un fallo aquí no
  // afecta al barrido de sesiones de arriba.
  if (c.revisionCliente.activa && !c.pausa) {
    try { console.log(JSON.stringify({ revisionCliente: await revisionCliente({ notion, c }) })); }
    catch (e) { console.log(JSON.stringify({ revisionCliente: 'error', mensaje: String(e?.message || e).slice(0, 300) })); }
  }
};
export const config: Config = { schedule: '7 * * * *' };
