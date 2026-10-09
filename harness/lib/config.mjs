// Configuración y guardrails. Todo sale de variables de entorno de Netlify.
import { AGENTES } from './agentes.mjs';

export const BETA = 'managed-agents-2026-04-01';

// Eventos del webhook que cierran una fila. Nombres confirmados en la consola de Claude el 8 oct de 2026.
// Los de hilos (session.thread_*) y cualquier otro se reconocen con 200 y se ignoran: el estado de la
// sesión completa es el que cuenta.
export const EVENTOS_CIERRE = {
  'session.status_idled': null,
  'session.status_terminated': null,
  'session.budget_reached': 'budget',
};
export function eventoDeCierre(tipo) {
  return Object.hasOwn(EVENTOS_CIERRE, tipo || '') ? { motivo: EVENTOS_CIERRE[tipo] ?? undefined } : null;
}

export function cfg(env = process.env) {
  const num = (k, d) => (env[k] !== undefined && env[k] !== '' ? Number(env[k]) : d);
  return {
    notionToken: env.NOTION_TOKEN,
    notionDataSource: env.NOTION_DATA_SOURCE_ID || '67d74148-a4a3-407a-80b5-596630168d4c',
    // IDs de Notion de quienes pueden aprobar (Al y Bonzo). Sin esto, el disparador no hace nada.
    aprobadores: (env.NOTION_APROBADORES || '').split(',').map(s => s.trim()).filter(Boolean),
    environmentId: env.MA_ENVIRONMENT_ID,
    vaultIds: (env.MA_VAULT_IDS || '').split(',').map(s => s.trim()).filter(Boolean),
    // Vault propio por agente (ids separados por coma). Si no hay, se usa MA_VAULT_IDS.
    vaultsPorAgente: Object.fromEntries(Object.entries(AGENTES).map(([nombre, d]) =>
      [nombre, (env[d.vaultEnv] || '').split(',').map(s => s.trim()).filter(Boolean)])),
    // id de Managed Agents por agente del catálogo (lib/agentes.mjs)
    agentes: Object.fromEntries(Object.entries(AGENTES).map(([nombre, d]) => [nombre, env[d.env]])),
    // Repos que se montan en la sesión, solo lectura. Cada agente declara cuáles necesita.
    repos: {
      marca: { url: env.GH_REPO_URL, token: env.GH_REPO_READ_TOKEN, mount: '/workspace/marca', variable: 'GH_REPO_URL' },
      agentes: { url: env.GH_AGENTES_URL, token: env.GH_AGENTES_READ_TOKEN || env.GH_REPO_READ_TOKEN, mount: '/workspace/agentes', variable: 'GH_AGENTES_URL' },
    },
    topeDefaultUsd: num('TOPE_DEFAULT_USD', 2),
    topeMaxUsd: num('TOPE_MAX_USD', 5),        // ningún Notion puede subir el tope más allá de esto
    maxSesionesPorDia: num('MAX_SESIONES_DIA', 6),
    maxIntentos: num('MAX_INTENTOS', 2),
    maxMinutosSesion: num('MAX_MINUTOS_SESION', 30),
    pausa: env.HARNESS_PAUSA === '1',          // interruptor general
    verificadorActivo: env.VERIFICADOR_ACTIVO === '1',
  };
}
