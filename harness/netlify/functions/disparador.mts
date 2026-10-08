import type { Config } from '@netlify/functions';
import { cfg } from '../../lib/config.mjs';
import { notionClient } from '../../lib/notion.mjs';
import { anthropic } from '../../lib/sessions.mjs';
import { despacha } from '../../lib/despacho.mjs';

export default async () => {
  const c = cfg();
  const r = await despacha({ client: anthropic(), notion: notionClient(c.notionToken), c });
  console.log(JSON.stringify(r));
};
export const config: Config = { schedule: '*/15 * * * *' };
