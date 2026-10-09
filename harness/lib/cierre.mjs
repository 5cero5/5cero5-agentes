// Qué hace el harness cuando una sesión termina. Un solo camino para webhook y barrido.
import { P, leePagina } from './notion.mjs';
import { ultimoMensajeAgente } from './sessions.mjs';
import { agenteDe, revisaRespuesta } from './agentes.mjs';

const ahora = () => new Date().toISOString();

export async function paginaDeSesion(notion, c, sessionId, session) {
  const id = session?.metadata?.notion_page_id;
  if (id) return leePagina(await notion.get(id));
  const r = await notion.query(c.notionDataSource, { property: 'Sesión', rich_text: { equals: sessionId } }, 1);
  return r.results[0] ? leePagina(r.results[0]) : null;
}

// Devuelve una cadena corta con lo que hizo (para logs/tests).
export async function cierraSesion({ client, notion, c, sessionId, motivo }) {
  const session = await client.beta.sessions.retrieve(sessionId);
  const fila = await paginaDeSesion(notion, c, sessionId, session);
  if (!fila) return 'sin_fila';
  // Idempotencia: solo se cierra lo que está en curso.
  if (fila.estado !== 'En curso') return `ignorada_estado_${fila.estado}`;

  const usd = session.usage ? JSON.stringify(session.usage).slice(0, 300) : '';
  if (session.status === 'terminated' || motivo === 'budget') {
    await notion.update(fila.id, {
      Estado: P.estado('Error'),
      Terminó: P.fecha(ahora()),
      Error: P.texto(motivo === 'budget' ? 'Se alcanzó el tope de la sesión.' : 'La sesión terminó con error.'),
      'Fricción': P.texto(`Uso: ${usd}`),
    });
    return 'error';
  }
  if (session.status !== 'idle') return `aun_${session.status}`;

  const resultado = await ultimoMensajeAgente(client, sessionId);
  // El agente no marca nada como bueno. Sin Verificador activo, pasa a revisión humana marcado Pendiente.
  const props = {
    'Resultado del agente': P.texto(resultado),
    Terminó: P.fecha(ahora()),
    Verificador: P.verificador('Pendiente'),
    Estado: P.estado(c.verificadorActivo ? 'Verificando' : 'Para revisar'),
  };
  // El formato de la respuesta se revisa aquí; si el trabajo está bien lo decide el Verificador o una persona.
  const formato = revisaRespuesta(agenteDe(fila.agente), resultado);
  if (!c.verificadorActivo) props['Informe del Verificador'] = P.texto(`Verificador no activo: revisar a mano contra reglas.md. Formato de la respuesta: ${formato ?? 'OK'}.`);
  await notion.update(fila.id, props);
  return c.verificadorActivo ? 'verificando' : 'para_revisar';
}
