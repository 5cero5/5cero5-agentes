// Configuración y guardrails. Todo sale de variables de entorno de Netlify.
export const BETA = 'managed-agents-2026-04-01';

export function cfg(env = process.env) {
  const num = (k, d) => (env[k] !== undefined && env[k] !== '' ? Number(env[k]) : d);
  return {
    notionToken: env.NOTION_TOKEN,
    notionDataSource: env.NOTION_DATA_SOURCE_ID || '67d74148-a4a3-407a-80b5-596630168d4c',
    // IDs de Notion de quienes pueden aprobar (Al y Bonzo). Sin esto, el disparador no hace nada.
    aprobadores: (env.NOTION_APROBADORES || '').split(',').map(s => s.trim()).filter(Boolean),
    environmentId: env.MA_ENVIRONMENT_ID,
    vaultIds: (env.MA_VAULT_IDS || '').split(',').map(s => s.trim()).filter(Boolean),
    agentes: {
      Creativo: env.MA_AGENT_CREATIVO,
      Landing: env.MA_AGENT_LANDING,
    },
    repoUrl: env.GH_REPO_URL,
    repoToken: env.GH_REPO_READ_TOKEN, // solo lectura, del repo de marca
    repoMount: '/workspace/marca',
    topeDefaultUsd: num('TOPE_DEFAULT_USD', 2),
    topeMaxUsd: num('TOPE_MAX_USD', 5),        // ningún Notion puede subir el tope más allá de esto
    maxSesionesPorDia: num('MAX_SESIONES_DIA', 6),
    maxIntentos: num('MAX_INTENTOS', 2),
    maxMinutosSesion: num('MAX_MINUTOS_SESION', 30),
    pausa: env.HARNESS_PAUSA === '1',          // interruptor general
    verificadorActivo: env.VERIFICADOR_ACTIVO === '1',
  };
}
