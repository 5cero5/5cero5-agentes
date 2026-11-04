// Creativo: fotos del cliente en el brief y rondas de cambios sobre la misma pieza. Antes de abrir la sesión; todo falla
// cerrado (la fila pasa a Error con el motivo y no hay sesión).
//   - "Foto: repo:<id>" (la foto tal cual) o "Foto: referencia:<id>" (referencia para el modelo de edición): el id tiene que
//     estar en fotos/fotos.json del repo de marca DE ESE CLIENTE, autorizado y con ese uso; como referencia, sin personas.
//   - Ronda: una fila con "Ronda de" (la pieza original). Del Resultado del agente de la original salen el PR, la rama y la
//     carpeta; el PR tiene que estar abierto y sin fusionar, y la original ser del mismo cliente. Arriba de "Rondas incluidas"
//     de la ficha, solo despacha con Aprobó en APROBADORES_SENSIBLES.
//   - Editar en una ronda manda la foto actual a la IA: si es una foto del cliente, tiene que permitir referencia_ia y no
//     tener personas (igual que "referencia:"). Sobre una foto generada por Higgsfield, se permite.
import { leePagina } from './notion.mjs';
import { ultimoJson } from './agentes.mjs';
import { resuelveCliente } from './clientes.mjs';
import { fotosDeLaMarca, gh, tokenInstalacion } from './github.mjs';

const SLUG = /^[a-z0-9][a-z0-9-]{0,40}$/;
const FOTO = /Foto:\s*(repo|referencia):\s*([A-Za-z0-9][A-Za-z0-9_-]{0,60})/i;
export const FOTOS_RONDA = ['Igual', 'Editar', 'Nueva'];

export class ErrorRonda extends Error {
  constructor(m, motivo = 'ronda') { super(m); this.motivo = motivo; }
}

export function fotoDelBrief(brief) {
  const m = String(brief || '').match(FOTO);
  return m ? { tipo: m[1].toLowerCase(), id: m[2] } : null;
}

// La foto <id> de fotos.json del repo de marca de ESTE cliente, con el uso pedido. Para referencia_ia, además sin personas.
async function fotoPermitida({ id, uso, c, fetchImpl, etiqueta }) {
  let r;
  try { r = await fotosDeLaMarca({ c, fetchImpl }); } catch (e) { throw new ErrorRonda(`${etiqueta}: ${e.message}`, 'foto'); }
  const f = r.fotos.find(x => x && x.id === id);
  if (!f) throw new ErrorRonda(`${etiqueta}: no está en fotos/fotos.json de ${r.repo} (repo de marca de este cliente)`, 'foto');
  if (!f.autorizo) throw new ErrorRonda(`${etiqueta}: fotos.json no dice quién autorizó su uso`, 'foto');
  if (!(f.uso || []).includes(uso)) throw new ErrorRonda(`${etiqueta}: su uso no permite ${uso} (uso: ${(f.uso || []).join(', ') || 'ninguno'})`, 'foto');
  if (uso === 'referencia_ia' && f.personas !== false) throw new ErrorRonda(`${etiqueta}: tiene personas (o no lo dice); no se manda a la IA`, 'foto');
  return f;
}

// null si el brief no pide una foto del cliente; si la pide y no se puede, lanza ErrorRonda con el motivo.
export async function compruebaFotoDelBrief({ brief, c, fetchImpl = fetch }) {
  const pedida = fotoDelBrief(brief);
  if (!pedida) return null;
  const uso = pedida.tipo === 'repo' ? 'directo' : 'referencia_ia';
  const f = await fotoPermitida({ id: pedida.id, uso, c, fetchImpl, etiqueta: `Foto ${pedida.tipo}:${pedida.id}` });
  return { ...pedida, uso, archivo: f.archivo };
}

// La ronda de una fila del Creativo: { n, incluidas, pr, prUrl, rama, head, campana, pieza, foto, cambios, briefOriginal }.
// cli: el cliente de la fila (ya resuelto para los aprobadores). c: la configuración con lo del cliente (repo de piezas).
export async function preparaRonda({ notion, c, fila, cli, cache = new Map(), fetchImpl = fetch }) {
  if (fila.agente !== 'Creativo') throw new ErrorRonda(`Solo el Creativo tiene rondas (la fila es de ${fila.agente})`);
  if (fila.rondaDe.length !== 1) throw new ErrorRonda(`Ronda de liga ${fila.rondaDe.length} filas: tiene que ser una, la pieza original`);
  if (!FOTOS_RONDA.includes(fila.fotoRonda)) throw new ErrorRonda('Falta Foto en la ronda (Igual, Editar o Nueva)');
  if (!fila.cambiosPedidos) throw new ErrorRonda('Falta Cambios pedidos');
  let original;
  try { original = leePagina(await notion.get(fila.rondaDe[0])); } catch (e) { throw new ErrorRonda(`No se pudo leer la pieza original (${e.message})`); }
  if (original.agente !== 'Creativo') throw new ErrorRonda('La pieza original no es del Creativo');
  if (original.rondaDe.length) throw new ErrorRonda('Ronda de tiene que apuntar a la pieza original, no a otra ronda');
  let delOriginal;
  try { delOriginal = await resuelveCliente(notion, c, original, cache); } catch (e) { throw new ErrorRonda(`La pieza original no tiene cliente (${e.message})`); }
  if (delOriginal.id !== cli.id) throw new ErrorRonda(`Ronda de otro cliente: la pieza original es de ${delOriginal.slug || delOriginal.id}`, 'ronda_otro_cliente');
  const r = ultimoJson(original.resultado) || {};
  const numero = Number(r.pr_numero);
  if (!Number.isInteger(numero) || numero < 1 || !SLUG.test(String(r.campana)) || !SLUG.test(String(r.pieza)) || !String(r.rama).startsWith('agente/')) {
    throw new ErrorRonda('La pieza original no tiene un PR en su Resultado del agente (pr_numero, rama, campana, pieza)');
  }
  const repo = c.github?.destinos?.piezas?.repo;
  if (!repo || !String(r.pr_url).toLowerCase().startsWith(`https://github.com/${String(repo).toLowerCase()}/pull/`)) {
    throw new ErrorRonda(`El PR de la pieza original (${r.pr_url}) no es del repo de piezas ${repo || '(sin configurar)'}`);
  }
  const g = c.github;
  let pr, token;
  try {
    ({ token } = await tokenInstalacion({ appId: g.appId, pem: g.privateKey, installationId: g.installationId, repo,
      permisos: { contents: 'read', pull_requests: 'read' }, fetchImpl }));
    pr = await gh(fetchImpl, 'GET', `/repos/${repo}/pulls/${numero}`, token);
  } catch (e) { throw new ErrorRonda(`No se pudo leer el PR #${numero} de ${repo} (${e.status || e.message})`); }
  if (pr.merged || pr.merged_at) throw new ErrorRonda(`El PR #${numero} ya está fusionado: una ronda necesita el PR abierto y sin fusionar`, 'ronda_pr_cerrado');
  if (pr.state !== 'open') throw new ErrorRonda(`El PR #${numero} está ${pr.state}: una ronda necesita el PR abierto`, 'ronda_pr_cerrado');
  if (pr.head?.ref !== r.rama || !pr.head?.sha) throw new ErrorRonda(`La rama del PR #${numero} (${pr.head?.ref}) no es la de la pieza (${r.rama})`);
  // Editar manda la foto actual de la pieza (la de la punta del PR) al modelo de edición.
  if (fila.fotoRonda === 'Editar') {
    let meta;
    try {
      const x = await gh(fetchImpl, 'GET', `/repos/${repo}/contents/piezas/${r.campana}/${r.pieza}/pieza.json?ref=${pr.head.sha}`, token);
      meta = JSON.parse(Buffer.from(String(x.content || ''), 'base64').toString('utf8'));
    } catch (e) { throw new ErrorRonda(`No se pudo leer pieza.json del PR #${numero} (${e.status || e.message})`); }
    if (!meta.foto) throw new ErrorRonda('Foto en la ronda = Editar y la pieza no lleva foto');
    if (meta.foto_cliente) {
      await fotoPermitida({ id: meta.foto_cliente.id, uso: 'referencia_ia', c, fetchImpl,
        etiqueta: `Editar la foto del cliente ${meta.foto_cliente.id}` });
    } else if (!meta.higgsfield?.request_id) throw new ErrorRonda('Foto en la ronda = Editar y pieza.json no dice de dónde salió la foto');
  }
  // Cuántas rondas lleva la pieza (todas las filas con Ronda de = original, esta incluida).
  let n;
  try { n = Math.max((await notion.query(c.notionDataSource, { property: 'Ronda de', relation: { contains: original.id } }, 100)).results.length, 1); }
  catch (e) { throw new ErrorRonda(`No se pudieron contar las rondas de la pieza (${e.message})`); }
  const incluidas = cli.rondasIncluidas ?? 0;
  if (n > incluidas && !fila.aprobo.some(id => (c.aprobadoresSensibles || []).includes(id))) {
    throw new ErrorRonda(`Ronda ${n} y la ficha de ${cli.nombre || cli.slug} incluye ${incluidas}: la tiene que aprobar alguien de APROBADORES_SENSIBLES`, 'ronda_fuera_de_limite');
  }
  return { n, incluidas, pr: numero, prUrl: pr.html_url || r.pr_url, rama: r.rama, head: pr.head.sha, campana: r.campana, pieza: r.pieza,
    foto: fila.fotoRonda, cambios: fila.cambiosPedidos, briefOriginal: original.brief };
}
