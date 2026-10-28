// Ruteo por cliente (RUTEO_CLIENTES=1). Cada fila de Aprobaciones pertenece a UN cliente:
//   fila → Campaña ligada (exactamente una) → Ficha de cliente (exactamente una) → página de la base Clientes.
// La ficha solo trae ids (nunca secretos). De ahí salen repos, vaults, credenciales, ids de Meta, Location ID y topes.
// Todo falla cerrado: si algo no cuadra, la fila pasa a Error con el motivo y no se abre sesión.
// Solo lectura en Notion. La caché vive dentro de una ejecución (un Map que se pasa por parámetro), nunca entre ejecuciones.
import { agenteDe } from './agentes.mjs';

const SLUG = /^[a-z0-9][a-z0-9-]{0,40}$/;
const REPO = /^[A-Za-z0-9][A-Za-z0-9_.-]*\/[A-Za-z0-9][A-Za-z0-9_.-]*$/;
const sinGuiones = id => String(id || '').replace(/-/g, '').toLowerCase();

// Lo que cada agente necesita de la ficha. El error nombra el campo tal como está en Notion.
// CRM y CMO montan el repo de marca, así que también lo piden (no estaba en el diseño; sin él no hay marca que montar).
export const CAMPOS = {
  Pauta: ['Meta cuenta', 'Meta página', 'Vault Pauta', 'Repo de piezas', 'Sitio de landings'],
  Creativo: ['Repo de piezas', 'Repo de marca', 'Vault Creativo', 'Credencial GitHub Creativo'],
  Landing: ['Repo de landings', 'Repo de marca', 'Vault Landing', 'Credencial GitHub Landing'],
  CRM: ['HighLevel Location ID', 'Vault CRM', 'Repo de marca'],
  CMO: ['Vault CMO', 'Ruta', 'Repo de marca'],
};

export class ErrorCliente extends Error {}
const falla = m => new ErrorCliente(m);

// "org/repo", "https://github.com/org/repo" o con .git → "org/repo". Cualquier otra cosa → null.
export function repoDe(v) {
  const s = String(v || '').trim().replace(/^https:\/\/github\.com\//i, '').replace(/\.git$/, '').replace(/\/$/, '');
  return REPO.test(s) ? s : null;
}
const hostDe = u => { try { return new URL(u).hostname.toLowerCase(); } catch { return ''; } };
const act = v => (v ? (String(v).startsWith('act_') ? String(v) : `act_${v}`) : '');

export function leeCliente(page) {
  const p = page.properties || {};
  const t = k => (p[k]?.rich_text || p[k]?.title || []).map(x => x.plain_text).join('').trim();
  const n = k => (typeof p[k]?.number === 'number' ? p[k].number : null);
  const crudo = {
    'Slug': t('Slug'), 'Ruta': p['Ruta']?.select?.name || '', 'HighLevel Location ID': t('HighLevel Location ID'),
    'Repo de marca': t('Repo de marca'), 'Repo de landings': t('Repo de landings'), 'Repo de piezas': t('Repo de piezas'),
    'Sitio de landings': p['Sitio de landings']?.url || '',
    'Meta cuenta': t('Meta cuenta'), 'Meta página': t('Meta página'), 'Meta Instagram': t('Meta Instagram'), 'Meta Pixel': t('Meta Pixel'),
    'Vault CMO': t('Vault CMO'), 'Vault CRM': t('Vault CRM'), 'Vault Landing': t('Vault Landing'), 'Vault Creativo': t('Vault Creativo'),
    'Vault Pauta': t('Vault Pauta'), 'Credencial GitHub Landing': t('Credencial GitHub Landing'), 'Credencial GitHub Creativo': t('Credencial GitHub Creativo'),
  };
  return {
    id: page.id,
    dataSource: page.parent?.data_source_id || null,
    nombre: t('Cliente'),
    slug: crudo.Slug,
    estado: p['Estado']?.select?.name || null,
    dePrueba: p['De prueba']?.checkbox === true,
    crudo,
    ruta: crudo.Ruta,
    location: crudo['HighLevel Location ID'],
    repos: { marca: repoDe(crudo['Repo de marca']), landings: repoDe(crudo['Repo de landings']), piezas: repoDe(crudo['Repo de piezas']) },
    sitio: crudo['Sitio de landings'],
    dominio: hostDe(crudo['Sitio de landings']),
    meta: { cuenta: act(crudo['Meta cuenta']), pagina: crudo['Meta página'], ig: crudo['Meta Instagram'], pixel: crudo['Meta Pixel'] },
    vaults: { CMO: crudo['Vault CMO'], CRM: crudo['Vault CRM'], Landing: crudo['Vault Landing'], Creativo: crudo['Vault Creativo'], Pauta: crudo['Vault Pauta'] },
    creds: { Landing: crudo['Credencial GitHub Landing'], Creativo: crudo['Credencial GitHub Creativo'] },
    tope: n('Tope de sesión (USD)'),
    topePauta: n('Tope diario de pauta (MXN)'),
    maxSesiones: n('Máx. sesiones por día'),
  };
}

function leePaginaCache(notion, cache, id) {
  if (!cache.has(id)) cache.set(id, notion.get(id));
  return cache.get(id);
}
const relacion = (page, k) => (page?.properties?.[k]?.relation || []).map(r => r.id);

// Cliente de una campaña (página de Campañas). Lo usan las filas y el CMO.
export async function clienteDeCampana(notion, c, campanaId, cache = new Map()) {
  const camp = await leePaginaCache(notion, cache, campanaId);
  const fichas = relacion(camp, 'Ficha de cliente');
  if (!fichas.length) throw falla('sin cliente: la campaña no tiene Ficha de cliente');
  if (fichas.length > 1) throw falla(`sin cliente: la campaña tiene ${fichas.length} Fichas de cliente`);
  const cli = leeCliente(await leePaginaCache(notion, cache, fichas[0]));
  if (sinGuiones(cli.dataSource) !== sinGuiones(c.notionClientes)) throw falla('sin cliente: la Ficha de cliente no es de la base Clientes');
  return cli;
}

// Cliente de una fila de Aprobaciones: una Campaña ligada y un solo cliente.
export async function resuelveCliente(notion, c, fila, cache = new Map()) {
  const ligadas = fila.campanaLigada || [];
  if (!ligadas.length) throw falla('sin cliente: la fila no tiene Campaña ligada');
  if (ligadas.length > 1) throw falla(`sin cliente: la fila tiene ${ligadas.length} Campañas ligadas`);
  return clienteDeCampana(notion, c, ligadas[0], cache);
}

// Estado y campos que necesita ese agente. Lanza ErrorCliente con el motivo.
export function validaCliente(cli, agente) {
  if (!agenteDe(agente) || !CAMPOS[agente]) throw falla(`Agente sin configurar: ${agente}`);
  const quien = cli.nombre || cli.slug || cli.id;
  if (!SLUG.test(cli.slug)) throw falla(`Falta Slug válido en la ficha de ${quien}`);
  if (cli.estado !== 'Activo') throw falla(`Cliente ${quien} en ${cli.estado || 'sin Estado'}: solo Activo despacha`);
  const faltan = CAMPOS[agente].filter(k => !cli.crudo[k]);
  if (faltan.length) throw falla(`Falta ${faltan.join(', ')} en la ficha de ${quien} (agente ${agente})`);
  const malos = ['Repo de marca', 'Repo de landings', 'Repo de piezas'].filter(k => CAMPOS[agente].includes(k) && !repoDe(cli.crudo[k]));
  if (malos.length) throw falla(`${malos.join(', ')} inválido en la ficha de ${quien}: debe ser org/repo`);
  if (CAMPOS[agente].includes('Sitio de landings') && !cli.dominio) throw falla(`Sitio de landings inválido en la ficha de ${quien}`);
  if (CAMPOS[agente].includes('Meta cuenta') && !/^act_\d{5,20}$/.test(cli.meta.cuenta)) throw falla(`Meta cuenta inválida en la ficha de ${quien}`);
}

// El vault de la ficha tiene que ser de ese cliente y de ese agente: metadata {cliente: <slug>, rol: <agente>} y sin archivar.
// Así una ficha con el vault de otro cliente (copiado por error) no abre sesión.
export async function compruebaVault(client, cli, agente) {
  const id = cli.vaults[agente];
  let v;
  try { v = await client.beta.vaults.retrieve(id); }
  catch (e) { throw falla(`No se pudo leer el Vault ${agente} ${id} (${e.status || e.message})`); }
  const rol = agente.toLowerCase();
  if (v.archived_at) throw falla(`El Vault ${agente} ${id} está archivado`);
  if (v.metadata?.cliente !== cli.slug || v.metadata?.rol !== rol) {
    throw falla(`El Vault ${agente} ${id} no es de ${cli.slug}/${rol} (su metadata dice cliente=${v.metadata?.cliente || 'vacío'}, rol=${v.metadata?.rol || 'vacío'})`);
  }
  return v;
}

// Configuración del harness para UNA fila: la global con lo del cliente encima. Objeto nuevo; nunca se toca `c`.
// Sin vault común de respaldo: cada agente usa solo el vault de su ficha.
export function cfgCliente(c, cli) {
  const montado = (base, repo, variable) => ({ ...base, url: repo ? `https://github.com/${repo}` : undefined, repo, token: undefined, dinamico: true, variable });
  const d = c.github?.destinos || {};
  return {
    ...c,
    cliente: { id: cli.id, slug: cli.slug, nombre: cli.nombre, location: cli.location, sitio: cli.sitio, dominio: cli.dominio, ruta: cli.ruta },
    vaultIds: [],
    vaultsPorAgente: Object.fromEntries(Object.keys(c.agentes).map(a => [a, cli.vaults[a] ? [cli.vaults[a]] : []])),
    repos: {
      ...c.repos,
      marca: montado(c.repos.marca, cli.repos.marca, 'Repo de marca'),
      landings: montado(c.repos.landings, cli.repos.landings, 'Repo de landings'),
      piezas: montado(c.repos.piezas, cli.repos.piezas, 'Repo de piezas'),
    },
    meta: {
      ...c.meta, cuenta: cli.meta.cuenta || undefined, pagina: cli.meta.pagina || undefined, ig: cli.meta.ig, pixel: cli.meta.pixel,
      topeDiarioMxn: cli.topePauta ?? c.meta.topeDiarioMxn,
      dominios: cli.dominio ? [cli.dominio] : [],
      token: c.secretoCliente('META_TOKEN', cli.slug) || c.meta.token,
    },
    github: {
      ...c.github,
      destinos: {
        landings: { ...d.landings, repo: cli.repos.landings, cred: cli.creds.Landing, credVar: 'Credencial GitHub Landing', vault: cli.vaults.Landing, vaultVar: 'Vault Landing' },
        piezas: { ...d.piezas, repo: cli.repos.piezas, cred: cli.creds.Creativo, credVar: 'Credencial GitHub Creativo', vault: cli.vaults.Creativo, vaultVar: 'Vault Creativo' },
      },
    },
    hl: { ...c.hl, location: cli.location, token: c.secretoCliente('HL_TOKEN', cli.slug) },
    // El tope de la ficha manda, pero nunca pasa del máximo global. La fila puede bajarlo, no subirlo.
    topeDefaultUsd: Math.min(cli.tope ?? c.topeDefaultUsd, c.topeMaxUsd),
    topeMaxUsd: Math.min(cli.tope ?? c.topeMaxUsd, c.topeMaxUsd),
    maxSesionesPorDia: cli.maxSesiones ?? c.maxSesionesPorDia,
  };
}

// Todo lo anterior junto, para el disparador: cliente válido, vault suyo y configuración de la fila.
export async function preparaCliente({ client, notion, c, fila, cache }) {
  const cli = await resuelveCliente(notion, c, fila, cache);
  validaCliente(cli, fila.agente);
  await compruebaVault(client, cli, fila.agente);
  return { cli, cc: cfgCliente(c, cli) };
}

// Al cerrar: la sesión tiene que ser del cliente de la fila y haber usado solo su vault. null si cuadra; si no, el motivo.
export function sesionFueraDelCliente(session, cc, agente) {
  const slug = cc.cliente?.slug;
  const meta = session?.metadata || {};
  if (meta.cliente_slug !== slug) return `la sesión es del cliente ${meta.cliente_slug || 'sin cliente'}, la fila es de ${slug}`;
  const esperado = cc.vaultsPorAgente?.[agente] || [];
  const usados = session?.vault_ids || [];
  if (!esperado.length || usados.length !== esperado.length || usados.some(v => !esperado.includes(v))) {
    return `la sesión usó el vault ${usados.join(', ') || 'ninguno'}, no el Vault ${agente} de ${slug} (${esperado.join(', ') || 'vacío'})`;
  }
  return null;
}
