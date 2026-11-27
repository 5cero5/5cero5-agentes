// Qué hace el harness cuando una sesión termina. Un solo camino para webhook y barrido.
import { P, leePagina } from './notion.mjs';
import { ultimoMensajeAgente } from './sessions.mjs';
import { agenteDe, revisaRespuesta, ultimoJson } from './agentes.mjs';
import { compruebaFilasCMO, compruebaHuellaCMO } from './campanas.mjs';
import { compruebaPR } from './github.mjs';
import { compruebaCampana } from './meta.mjs';
import { compruebaPlantilla } from './highlevel.mjs';
import { resuelveCliente, cfgCliente, sesionFueraDelCliente } from './clientes.mjs';
import { compruebaCanvaSesion, leeMetaCanva, resuelveConfirmaciones } from './canva.mjs';

const ahora = () => new Date().toISOString();

export async function paginaDeSesion(notion, c, sessionId, session) {
  const id = session?.metadata?.notion_page_id;
  if (id) return leePagina(await notion.get(id));
  const r = await notion.query(c.notionDataSource, { property: 'Sesión', rich_text: { equals: sessionId } }, 1);
  return r.results[0] ? leePagina(r.results[0]) : null;
}

// Devuelve una cadena corta con lo que hizo (para logs/tests).
export async function cierraSesion({ client, notion, c, sessionId, motivo, confirmar = true, fetchImpl = fetch }) {
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
  // Idle no siempre es "terminó": con requires_action la sesión espera que alguien apruebe herramientas (Canva va con
  // always_ask). El harness decide con reglas fijas y la fila sigue En curso (el barrido aplica el mismo tope de minutos).
  // Pasada del tope de minutos, nadie le aprueba herramientas (ni el webhook ni el barrido); el barrido la interrumpe.
  const vencida = fila.inicio && (Date.now() - Date.parse(fila.inicio)) / 60000 > c.maxMinutosSesion;
  // Con el ruteo, los recursos aprobados (textos fijos) son los del repo de marca del cliente de la fila; si no se resuelve, se niega editar.
  let ccConf = c;
  if (c.ruteoClientes && leeMetaCanva(session.metadata)) { try { ccConf = cfgCliente(c, await resuelveCliente(notion, c, fila)); } catch { ccConf = null; } }
  const confirmadas = await resuelveConfirmaciones({ client, sessionId, session, confirmar: confirmar && !vencida, c: ccConf, fetchImpl });
  if (confirmadas) return `aun_requiere_accion:${confirmadas}`;

  const resultado = await ultimoMensajeAgente(client, sessionId);

  // Ruteo por cliente: el cliente sale de la fila, igual que en el disparador, y todo se comprueba contra lo suyo (cc).
  // La sesión tiene que ser de ese cliente y haber usado solo su vault; si no, Rechazada. Sin cliente no se comprueba
  // contra globales: Rechazada y revisión a mano.
  let cc = c, fuera = null;
  if (c.ruteoClientes) {
    let cli = null;
    try { cli = await resuelveCliente(notion, c, fila); }
    catch (e) {
      await notion.update(fila.id, { 'Resultado del agente': P.texto(resultado), Terminó: P.fecha(ahora()), Estado: P.estado('Para revisar'),
        Verificador: P.verificador('Rechazada'),
        'Informe del Verificador': P.texto(`Fuera del cliente: ${e.message}. Sin comprobación contra las variables globales: revisar a mano (GitHub, Meta y HighLevel).`) });
      return 'para_revisar';
    }
    cc = cfgCliente(c, cli);
    fuera = sesionFueraDelCliente(session, cc, fila.agente);
  }

  // El agente no marca nada como bueno. Sin Verificador activo, pasa a revisión humana marcado Pendiente.
  const props = {
    'Resultado del agente': P.texto(resultado),
    Terminó: P.fecha(ahora()),
    Verificador: P.verificador('Pendiente'),
    Estado: P.estado(c.verificadorActivo ? 'Verificando' : 'Para revisar'),
  };
  // El formato de la respuesta se revisa aquí; si el trabajo está bien lo decide el Verificador o una persona.
  const formato = revisaRespuesta(agenteDe(fila.agente), resultado);
  if (fila.agente === 'CMO') {
    // El trabajo del CMO son filas en Notion: el harness mismo las comprueba (regla 8).
    let rev = formato ? { ok: false, informe: 'Sin comprobación: la respuesta no trae el formato pedido.' }
      : await compruebaFilasCMO(notion, fila, ultimoJson(resultado));
    // Aunque la respuesta venga mal, se revisa todo lo que el bot tocó en Notion durante la sesión (aislamiento entre clientes).
    const huella = await compruebaHuellaCMO(notion, cc, fila, formato ? {} : ultimoJson(resultado));
    rev = { ok: rev.ok && huella.ok, informe: `${rev.informe} ${huella.informe}` };
    props.Verificador = P.verificador(rev.ok ? 'Aprobada' : 'Rechazada');
    props.Estado = P.estado('Para revisar');
    props['Informe del Verificador'] = P.texto(`Formato de la respuesta: ${formato ?? 'OK'}. ${rev.informe}`);
  } else if (agenteDe(fila.agente)?.meta) {
    // El trabajo de Pauta es una campaña en Meta: el harness la lee en Meta y pausa lo que no esté en pausa (regla 8).
    // Aunque la respuesta venga incompleta (creación a medias), si trae el id de una campaña se lee en Meta y se frena.
    const r = ultimoJson(resultado);
    const conId = /^\d+$/.test(String(r?.campana_meta_id || ''));
    // El número de WhatsApp contra el que se compara sale de la ficha también sin el ruteo (con el ruteo ya viene en cc).
    let ccMeta = cc;
    if (!c.ruteoClientes) {
      try { ccMeta = { ...cc, meta: { ...cc.meta, whatsappFicha: (await resuelveCliente(notion, c, fila)).meta.whatsapp || undefined } }; }
      catch { /* sin ficha no hay número: una campaña de WhatsApp sale Rechazada */ }
    }
    let rev = conId ? await compruebaCampana({ c: ccMeta, respuesta: r, inicio: fila.inicio, fetchImpl })
      : { ok: false, informe: 'Sin comprobación: la respuesta no trae el id de la campaña. Revisar a mano en el Administrador de anuncios que no haya nada encendido.' };
    if (formato && rev.ok) rev = { ...rev, ok: false };
    props.Verificador = P.verificador(rev.ok ? 'Aprobada' : 'Rechazada');
    props.Estado = P.estado('Para revisar');
    props['Informe del Verificador'] = P.texto(`Formato de la respuesta: ${formato ?? 'OK'}. ${rev.informe}`);
  } else if (agenteDe(fila.agente)?.github) {
    // El trabajo de Landing y Creativo es un PR: el harness lo comprueba en GitHub (regla 8). Publicar sigue siendo de Al o Bonzo.
    let rev = formato ? { ok: false, informe: 'Sin comprobación: la respuesta no trae el formato pedido.' }
      : await compruebaPR({ c: cc, agente: fila.agente, respuesta: ultimoJson(resultado), mainAntes: session.metadata?.main_sha,
        ronda: session.metadata?.ronda_pr ? session.metadata : null, fetchImpl });
    // Canva: lo que pasó en Canva se comprueba en el log de la sesión y la exportación se coteja byte a byte (lib/canva.mjs).
    if (rev.canva) {
      const k = await compruebaCanvaSesion({ client, sessionId, session, pieza: rev.canva, c: cc, fetchImpl });
      rev = { ok: rev.ok && !k.problemas.length, informe: `${rev.informe}${k.resumen}${k.problemas.length ? ` Problemas en Canva: ${k.problemas.join('; ')}.` : ''}` };
    } else if (!formato && leeMetaCanva(session.metadata)) {
      rev = { ok: false, informe: `${rev.informe} La fila pedía Canva y la pieza del PR no es de Canva.` };
    }
    props.Verificador = P.verificador(rev.ok ? 'Aprobada' : 'Rechazada');
    props.Estado = P.estado('Para revisar');
    props['Informe del Verificador'] = P.texto(`Formato de la respuesta: ${formato ?? 'OK'}. ${rev.informe}`);
  } else if (fila.agente === 'CRM' && c.ruteoClientes) {
    // Con el ruteo, el trabajo del CRM se comprueba en la subcuenta del cliente: la plantilla tiene que estar ahí.
    const rev = formato ? { ok: false, informe: 'Sin comprobación: la respuesta no trae el formato pedido.' }
      : await compruebaPlantilla({ c: cc, respuesta: ultimoJson(resultado), brief: fila.brief, fetchImpl });
    props.Verificador = P.verificador(rev.ok ? 'Aprobada' : 'Rechazada');
    props.Estado = P.estado('Para revisar');
    props['Informe del Verificador'] = P.texto(`Formato de la respuesta: ${formato ?? 'OK'}. ${rev.informe}`);
  } else if (!c.verificadorActivo) {
    props['Informe del Verificador'] = P.texto(`Verificador no activo: revisar a mano contra reglas.md. Formato de la respuesta: ${formato ?? 'OK'}.`);
  }
  if (fuera) {
    props.Verificador = P.verificador('Rechazada');
    props.Estado = P.estado('Para revisar');
    const antes = props['Informe del Verificador']?.rich_text?.[0]?.text?.content || '';
    props['Informe del Verificador'] = P.texto(`Fuera del cliente: ${fuera}. ${antes}`);
  }
  await notion.update(fila.id, props);
  return props.Estado.select.name === 'Verificando' ? 'verificando' : 'para_revisar';
}
