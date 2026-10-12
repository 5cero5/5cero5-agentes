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
    notionCampanas: env.NOTION_CAMPANAS_ID || '3a8ee225-0743-449d-8ff8-a5f01d0bb0be',
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
      // Repo de landings: el token de lectura lo saca la GitHub App al abrir la sesión (lib/github.mjs).
      landings: { url: env.GH_LANDINGS_URL || 'https://github.com/5cero5/5cero5-landings', mount: '/workspace/landings', variable: 'GH_LANDINGS_URL', dinamico: true },
      // Repo de piezas (solo lo monta Pauta, para subir a Meta las piezas ya fusionadas). Token de lectura de la GitHub App.
      piezas: { url: env.GH_PIEZAS_URL || 'https://github.com/5cero5/5cero5-piezas', mount: '/workspace/piezas', variable: 'GH_PIEZAS_URL', dinamico: true },
    },
    // Meta Ads (agente Pauta). Ids no secretos; META_TOKEN es el del usuario del sistema y va como variable secreta:
    // el harness lo usa para comprobar lo que creó el agente y para pausar cualquier cosa que no esté en pausa.
    meta: {
      cuenta: env.META_AD_ACCOUNT_ID ? (String(env.META_AD_ACCOUNT_ID).startsWith('act_') ? env.META_AD_ACCOUNT_ID : `act_${env.META_AD_ACCOUNT_ID}`) : undefined,
      pagina: env.META_PAGE_ID,
      ig: env.META_IG_USER_ID || '',
      pixel: env.META_PIXEL_ID || '',
      token: env.META_TOKEN,
      topeDiarioMxn: num('META_TOPE_DIARIO_MXN', 1500),
      dominios: (env.META_DOMINIOS || 'marketing.5cero5.com').split(',').map(s => s.trim().toLowerCase()).filter(Boolean),
      api: env.META_API_BASE || 'https://graph.facebook.com/v25.0',
    },
    // GitHub App "5cero5-agentes", instalada en los repos donde los agentes abren PRs. La llave privada va como variable secreta.
    // Un destino por repo: a qué repo escribe el agente y en qué credencial de qué vault va su token de 1 hora.
    github: {
      appId: env.GH_APP_ID,
      installationId: env.GH_APP_INSTALLATION_ID,
      privateKey: env.GH_APP_PRIVATE_KEY,
      destinos: {
        landings: { repo: env.GH_LANDINGS_REPO || '5cero5/5cero5-landings', cred: env.MA_CRED_GITHUB_LANDING, credVar: 'MA_CRED_GITHUB_LANDING',
          vault: (env.MA_VAULT_LANDING || '').split(',')[0].trim() || undefined, vaultVar: 'MA_VAULT_LANDING' },
        piezas: { repo: env.GH_PIEZAS_REPO || '5cero5/5cero5-piezas', cred: env.MA_CRED_GITHUB_CREATIVO, credVar: 'MA_CRED_GITHUB_CREATIVO',
          vault: (env.MA_VAULT_CREATIVO || '').split(',')[0].trim() || undefined, vaultVar: 'MA_VAULT_CREATIVO' },
      },
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
