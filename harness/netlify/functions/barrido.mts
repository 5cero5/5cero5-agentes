import type { Config } from '@netlify/functions';
import { cfg } from '../../lib/config.mjs';
import { notionClient } from '../../lib/notion.mjs';
import { anthropic } from '../../lib/sessions.mjs';
import { barre } from '../../lib/barrido.mjs';

export default async () => {
  const c = cfg();
  console.log(JSON.stringify(await barre({ client: anthropic(), notion: notionClient(c.notionToken), c })));
};
export const config: Config = { schedule: '7 * * * *' };
