// HighLevel: comprobación de la plantilla que dice el agente CRM que subió (regla 8), en la subcuenta del cliente.
// Solo lectura. El token es HL_TOKEN_<SLUG> (variable secreta de Netlify, integración privada de esa subcuenta con permiso
// de leer Email Builder) y viaja solo en el encabezado Authorization. Sin token no se da por buena.
// El contenido se comprueba aquí, fuera de la sesión: se baja el previewUrl que da HighLevel (https, host de una lista
// cerrada, con tope de tamaño y de tiempo) y se compara contra el brief aprobado: el botón, el destino del CTA y las frases
// que el brief marca como exactas. Así el sandbox no necesita salir a firebasestorage.googleapis.com.
import { gh, marcaParaLeer } from './github.mjs';

// Hosts desde donde HighLevel sirve el HTML guardado de una plantilla (previewUrl). HL_PREVIEW_HOSTS (coma) puede cambiarla.
export const HOSTS_PREVIEW = ['firebasestorage.googleapis.com'];
export const PREVIEW_MAX_BYTES = 2 * 1024 * 1024;
export const PREVIEW_MAX_MS = 10000;

const ENTIDADES = { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", nbsp: ' ' };
const desescapa = s => String(s || '').replace(/&(#x[0-9a-f]+|#\d+|\w+);/gi, (m, e) =>
  e[0] === '#' ? String.fromCodePoint(e[1].toLowerCase() === 'x' ? parseInt(e.slice(2), 16) : parseInt(e.slice(1), 10)) : (ENTIDADES[e.toLowerCase()] ?? m));
const normal = s => desescapa(s).replace(/\s+/g, ' ').trim();
const visible = html => normal(String(html).replace(/<!--[\s\S]*?-->|<style[\s\S]*?<\/style>|<head[\s\S]*?<\/head>/gi, ' ').replace(/<[^>]+>/g, ' '));

// Lo que el brief aprobado pide que lleve el correo. Dos formas:
//   - El brief nombra un archivo de copia del repo de marca (correos/<x>.json): botón = cta_texto, destino = cta_url,
//     exactas = los párrafos de cuerpo.
//   - El brief marca las líneas "Botón: <texto>", "Destino: <url>" y "Exacto: "<frase>"" (una por frase).
// Sin botón o sin destino no se puede comprobar el contenido: se rechaza.
export async function esperadoDelBrief({ brief, c, fetchImpl = fetch }) {
  const b = String(brief || '');
  const archivo = b.match(/correos\/[\w.-]+\.json/)?.[0];
  if (archivo) {
    const { repo, token } = await marcaParaLeer({ c, fetchImpl });
    const x = await gh(fetchImpl, 'GET', `/repos/${repo}/contents/${archivo}`, token);
    const d = JSON.parse(Buffer.from(String(x.content || ''), 'base64').toString('utf8'));
    return { fuente: `${repo}/${archivo}`, boton: normal(d.cta_texto), destino: String(d.cta_url || '').trim(),
      exactas: (Array.isArray(d.cuerpo) ? d.cuerpo : []).map(normal).filter(Boolean) };
  }
  const linea = k => b.match(new RegExp(`^\\s*[-*]?\\s*${k}\\s*:\\s*(.+)$`, 'mi'))?.[1].trim();
  const sinComillas = s => String(s || '').trim().replace(/^["“'«]+|["”'»]+$/g, '').trim();
  const exactas = [...b.matchAll(/^\s*[-*]?\s*Exacto\s*:\s*(.+)$/gmi)].map(m => normal(sinComillas(m[1]))).filter(Boolean);
  return { fuente: 'el brief', boton: normal(sinComillas(linea('Bot[oó]n'))), destino: sinComillas(linea('Destino')), exactas };
}

// El href del botón cumple el destino del brief: mismo origen y ruta, y todos los parámetros del destino con el mismo valor
// (el correo puede llevar además sus UTM).
function cumpleDestino(href, destino) {
  let h, d;
  try { h = new URL(desescapa(href)); d = new URL(destino); } catch { return false; }
  if (h.origin !== d.origin || h.pathname.replace(/\/$/, '') !== d.pathname.replace(/\/$/, '')) return false;
  return [...d.searchParams].every(([k, v]) => h.searchParams.get(k) === v);
}

// Baja el previewUrl con las validaciones previas. { html } o { error } (sin bajar si la URL no pasa).
export async function bajaPreview(url, { hosts = HOSTS_PREVIEW, maxBytes = PREVIEW_MAX_BYTES, maxMs = PREVIEW_MAX_MS, fetchImpl = fetch } = {}) {
  let u;
  try { u = new URL(String(url)); } catch { return { error: 'el previewUrl no es una URL válida' }; }
  if (u.protocol !== 'https:') return { error: `el previewUrl no es https (${u.protocol.replace(':', '')}); no se bajó` };
  if (!hosts.includes(u.hostname)) return { error: `el previewUrl es de ${u.hostname}, fuera de la lista (${hosts.join(', ')}); no se bajó` };
  const ctl = new AbortController();
  const reloj = setTimeout(() => ctl.abort(), maxMs);
  try {
    const res = await fetchImpl(u.toString(), { redirect: 'error', signal: ctl.signal, headers: { 'User-Agent': '5cero5-harness' } });
    if (!res.ok) return { error: `el previewUrl respondió ${res.status}` };
    if (Number(res.headers?.get?.('content-length')) > maxBytes) return { error: `el previewUrl pesa más de ${maxBytes} bytes; no se bajó` };
    const partes = []; let total = 0;
    if (res.body?.getReader) {
      const lector = res.body.getReader();
      for (;;) {
        const { done, value } = await lector.read();
        if (done) break;
        total += value.length;
        if (total > maxBytes) { ctl.abort(); return { error: `el previewUrl pasó de ${maxBytes} bytes; se cortó la descarga` }; }
        partes.push(Buffer.from(value));
      }
      return { html: Buffer.concat(partes).toString('utf8') };
    }
    const t = await res.text();
    if (Buffer.byteLength(t) > maxBytes) return { error: `el previewUrl pasó de ${maxBytes} bytes` };
    return { html: t };
  } catch (e) {
    return { error: e.name === 'AbortError' ? `el previewUrl no respondió en ${maxMs} ms` : `no se pudo bajar el previewUrl (${e.message})` };
  } finally { clearTimeout(reloj); }
}

export async function compruebaPlantilla({ c, respuesta, brief = '', fetchImpl = fetch }) {
  const loc = c.hl?.location, token = c.hl?.token, slug = c.cliente?.slug || '?';
  if (!loc) return { ok: false, informe: `Comprobación en HighLevel: falta el Location ID de ${slug}.` };
  if (!token) return { ok: false, informe: `Comprobación en HighLevel: falta HL_TOKEN_${slug.toUpperCase().replace(/-/g, '_')} en Netlify (sin comprobación). Revisar a mano en Marketing > Emails > Templates.` };
  const r = respuesta || {};
  const id = String(r.plantilla_id || ''), nombre = String(r.nombre || '');
  if (!id) return { ok: false, informe: 'Comprobación en HighLevel: sin plantilla_id.' };
  const q = new URLSearchParams({ locationId: loc, search: nombre, limit: '100' });
  let d;
  try {
    const res = await fetchImpl(`${c.hl.api.replace(/\/$/, '')}/emails/builder?${q}`, {
      headers: { Authorization: `Bearer ${token}`, Version: '2021-07-28', Accept: 'application/json', 'User-Agent': '5cero5-harness' } });
    const t = await res.text();
    if (!res.ok) return { ok: false, informe: `Comprobación en HighLevel: la subcuenta ${loc} respondió ${res.status} al leer plantillas.` };
    d = t ? JSON.parse(t) : {};
  } catch (e) { return { ok: false, informe: `Comprobación en HighLevel: no se pudo leer la subcuenta ${loc} (${e.message}).` }; }
  const lista = d.builders || d.templates || [];
  const t = lista.find(x => String(x.id) === id);
  const problemas = [];
  if (!t) problemas.push(`la plantilla ${id} no está en la subcuenta ${loc} de ${slug}`);
  else if ((t.name || t.title) !== nombre) problemas.push(`en HighLevel se llama ${t.name || t.title}, el agente dijo ${nombre}`);
  if (!nombre.startsWith('[agente] ')) problemas.push('el nombre no empieza con "[agente] "');
  let contenido = '';
  if (t) {
    let esp;
    try { esp = await esperadoDelBrief({ brief, c, fetchImpl }); }
    catch (e) { problemas.push(`no se pudo leer lo que pide el brief (${e.status || e.message})`); }
    if (esp && (!esp.boton || !esp.destino)) problemas.push(`${esp.fuente} no marca ${[!esp.boton && 'Botón', !esp.destino && 'Destino'].filter(Boolean).join(' ni ')}: no se puede comprobar el contenido`);
    else if (esp) {
      const url = t.previewUrl || t.preview_url;
      const bajado = url ? await bajaPreview(url, { hosts: c.hl.hostsPreview?.length ? c.hl.hostsPreview : HOSTS_PREVIEW, fetchImpl })
        : { error: 'HighLevel no regresó el previewUrl de la plantilla' };
      if (bajado.error) problemas.push(bajado.error);
      else {
        const texto = visible(bajado.html);
        const anclas = [...bajado.html.matchAll(/<a\b[^>]*href="([^"]+)"[^>]*>([\s\S]*?)<\/a>/gi)].map(m => ({ href: m[1], texto: visible(m[2]) }));
        const boton = anclas.find(a => a.texto === esp.boton);
        if (!boton) problemas.push(`falta el botón "${esp.boton}"`);
        else if (!cumpleDestino(boton.href, esp.destino)) problemas.push(`el botón lleva a ${desescapa(boton.href).slice(0, 120)}, no a ${esp.destino}`);
        const faltan = esp.exactas.filter(f => !texto.includes(f));
        if (faltan.length) problemas.push(`faltan frases exactas: ${faltan.slice(0, 4).map(f => `"${f.slice(0, 80)}"`).join(', ')}`);
        contenido = ` Contenido contra ${esp.fuente}: botón, destino y ${esp.exactas.length} frase(s) exacta(s).`;
      }
    }
  }
  return { ok: problemas.length === 0,
    informe: `Comprobación en HighLevel (subcuenta ${loc}): plantilla ${id}.` + (problemas.length ? ` Problemas: ${problemas.join('; ')}.` : `${contenido} Falta mirarla y activarla a mano.`) };
}
