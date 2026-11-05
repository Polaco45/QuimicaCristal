# -*- coding: utf-8 -*-
"""Claudio como asistente de empleados: contexto del registro, herramientas acotadas y
respuesta en el mismo chatter. Usa el motor de cristal_agent (ClaudeClient)."""
import logging
import re

from markupsafe import Markup

from odoo import SUPERUSER_ID, fields
from odoo.tools import html2plaintext

from odoo.addons.cristal_agent.services.claude_client import ClaudeClient
from odoo.addons.cristal_agent.services.tool_registry import ToolRegistry
from odoo.addons.cristal_agent.services.tools.base import AgentTool

_logger = logging.getLogger(__name__)

SILENCE = 'SIN_RESPUESTA'
HANDOFF_TEXT = "Esto lo paso a Sergio, te aviso cuando me conteste."
# Solo lectura + agendar. Nada que le escriba a un cliente o toque pedidos/fichas.
ALLOWED_TOOLS = ('read_partner', 'search_products', 'search_orders', 'get_route_info',
                 'search_knowledge', 'schedule_activity', 'ask_advanced_model')
RE_CALC = re.compile(r'(\d+\s*(x|\*|por|en vez|más|mas|menos|%|litros?|lts?|kg)\b|cu[aá]nt[oa]s?\b|'
                     r'calcul|proporci|rinde|alcanza)', re.IGNORECASE)
STOPWORDS = {'tengo', 'hacer', 'puedo', 'tiene', 'sobre', 'cuando', 'donde', 'desde', 'hasta',
             'para', 'este', 'esta', 'esto', 'como', 'porque', 'pero', 'orden', 'ahora', 'entonces'}


# ───────────────────────── Herramientas propias de este modo ─────────────────────────
class EscalateToSergio(AgentTool):
    name = 'escalate_to_sergio'
    description = ("Le pasa a Sergio una consulta del empleado que no podés contestar con los datos "
                   "o que necesita su decisión (precios, proveedores, cantidades distintas a la orden, "
                   "descartar producto, cambiar fechas a clientes). Le crea una actividad para hoy y "
                   "le avisa por WhatsApp. Después contestá exactamente 'Esto lo paso a Sergio'.")
    input_schema = {
        'type': 'object',
        'properties': {
            'question': {'type': 'string', 'description': "La consulta completa, como la haría el empleado."},
            'summary': {'type': 'string', 'description': "Resumen de 3 a 8 palabras para el título."},
        },
        'required': ['question'],
    }

    def __init__(self, session):
        self.session = session

    def _execute(self, env, run=None, question=None, summary=None, **kwargs):
        if not question:
            return {'error': "question es obligatorio"}
        escalation = self.session.escalate(question, summary, run=run)
        return {'ok': True, 'escalation_id': escalation.id, 'whatsapp': escalation.whatsapp_note,
                'summary': "Le pasé la consulta a Sergio. Contestá exactamente 'Esto lo paso a Sergio'."}


class MarkOwnActivityDone(AgentTool):
    name = 'mark_activity_done'
    description = ("Marca como hecha una actividad del empleado en ESTE registro, solo si él dijo que "
                   "la terminó. activity_id tiene que ser una de las actividades suyas que te pasé.")
    input_schema = {
        'type': 'object',
        'properties': {'activity_id': {'type': 'integer'}, 'feedback': {'type': 'string'}},
        'required': ['activity_id'],
    }

    def __init__(self, session):
        self.session = session

    def _execute(self, env, run=None, activity_id=None, feedback=None, **kwargs):
        activity = env['mail.activity'].sudo().browse(int(activity_id or 0)).exists()
        if not activity or activity not in self.session.own_activities():
            return {'error': "Esa actividad no es del empleado en este registro: no la puedo cerrar."}
        activity.action_feedback(feedback=feedback or f"Hecha según {self.session.first_name}")
        return {'ok': True, 'summary': "Actividad marcada como hecha."}


class EmployeeTools:
    """Registro acotado de herramientas: el ClaudeClient lo usa en lugar del global."""

    def __init__(self, extra):
        self.extra = {t.name: t for t in extra}

    def _tools(self):
        tools = [t for t in ToolRegistry.all() if t.name in ALLOWED_TOOLS]
        return tools + list(self.extra.values())

    def schemas_for_anthropic(self, client_type=None):
        return [{'name': t.name, 'description': t.description, 'input_schema': t.input_schema}
                for t in self._tools()]

    def get(self, name):
        if name in self.extra:
            return self.extra[name]
        return ToolRegistry.get(name) if name in ALLOWED_TOOLS else None

    def names(self):
        return [t.name for t in self._tools()]


class EmployeeClaudeClient(ClaudeClient):
    def __init__(self, env, tools, **kwargs):
        super().__init__(env, **kwargs)
        self.tool_registry = tools


# ───────────────────────── Sesión de una consulta ─────────────────────────
class EmployeeSession:
    def __init__(self, env, question):
        self.env = env
        self.question = question
        self.record = question.record()
        self.employee = question.employee_partner_id
        self.first_name = (self.employee.name or '').split(' ')[0]
        self.config = env['cristal.agent.config'].sudo().get_active()
        self.escalation = env['cristal.agent.employee.escalation']

    def own_activities(self):
        domain = [('res_model', '=', self.record._name), ('res_id', '=', self.record.id)]
        if self.employee.user_ids:
            domain.append(('user_id', 'in', self.employee.user_ids.ids))
        return self.env['mail.activity'].sudo().search(domain)

    def escalate(self, question, summary=None, run=None):
        if not self.escalation:
            self.escalation = self.env['cristal.agent.employee.escalation'].sudo().escalate(
                self.record, self.employee, question, summary, run=run)
        return self.escalation

    # ───── Contexto ─────
    def context(self):
        rec = self.record
        lines = [f"REGISTRO: {rec._description} «{rec.display_name}» (modelo {rec._name}, id {rec.id})"]
        if 'state' in rec._fields and rec.state:
            lines.append(f"Estado: {dict(rec._fields['state']._description_selection(self.env)).get(rec.state, rec.state)}")
        lines += self._model_lines(rec)
        acts = self.own_activities()
        lines.append("\nACTIVIDADES ABIERTAS DE " + self.first_name.upper() + ":")
        for a in acts:
            lines.append(f"- [id {a.id}] {a.activity_type_id.name}: {a.summary or ''} — vence {a.date_deadline}. "
                         f"{_plain(a.note)[:600]}")
        lines.append("\nÚLTIMOS MENSAJES DEL CHATTER (del más viejo al más nuevo):")
        msgs = self.env['mail.message'].sudo().search([
            ('model', '=', rec._name), ('res_id', '=', rec.id),
            ('message_type', 'in', ['comment', 'email'])], order='id desc', limit=6)
        for m in reversed(msgs):
            body = _plain(m.body)
            if body:
                lines.append(f"- {m.author_id.name or 'Sistema'} ({fields.Datetime.to_string(m.date)[:16]}): {body[:400]}")
        knowledge = self._knowledge()
        if knowledge:
            lines.append("\nCONOCIMIENTO QUE APLICA:")
            lines += [f"- {k.name}: {(k.content or '')[:500]}" for k in knowledge]
        return "\n".join(lines)

    def _model_lines(self, rec):
        out = []
        name = rec._name
        if name == 'mrp.production':
            out.append(f"Producto: {rec.product_id.display_name} × {rec.product_qty:g} {rec.product_uom_id.name}")
            if rec.bom_id:
                out.append(f"Lista de materiales: {rec.bom_id.display_name}")
            out.append(f"Origen / notas de la orden: {rec.origin or '—'}")
            if rec.date_start:
                out.append(f"Inicio previsto: {rec.date_start}")
            out.append(f"Ubicaciones: {rec.location_src_id.display_name} → {rec.location_dest_id.display_name}")
            out.append("Componentes (lo que se consume; el «a granel» es el producto del tacho o tanque):")
            out += [f"- {m.product_id.display_name}: {m.product_uom_qty:g} {m.product_uom.name}"
                    f" (sale de {m.location_id.display_name})" for m in rec.move_raw_ids]
            centers = rec.workorder_ids.mapped('workcenter_id') or rec.bom_id.operation_ids.mapped('workcenter_id')
            if centers:
                out.append("Centro de trabajo: " + ", ".join(centers.mapped('display_name')))
            for wo in rec.workorder_ids:
                out.append(f"- Operación {wo.name} en {wo.workcenter_id.display_name} ({wo.state})")
        elif name == 'stock.picking':
            out.append(f"Tipo: {rec.picking_type_id.display_name} · Origen: {rec.origin or '—'}")
            out.append(f"Contacto: {rec.partner_id.display_name or '—'} · Fecha: {rec.scheduled_date}")
            out.append(f"De {rec.location_id.display_name} a {rec.location_dest_id.display_name}")
            out += [f"- {m.product_id.display_name}: {m.product_uom_qty:g} {m.product_uom.name}" for m in rec.move_ids]
            if rec.note:
                out.append(f"Nota: {_plain(rec.note)[:500]}")
        elif name == 'sale.order':
            out.append(f"Cliente: {rec.partner_id.display_name} · Fecha: {rec.date_order} · "
                       f"Entrega: {rec.commitment_date or '—'}")
            out += [f"- {l.product_id.display_name or l.name}: {l.product_uom_qty:g} {l.product_uom.name}"
                    for l in rec.order_line if not l.display_type]
            if rec.note:
                out.append(f"Notas: {_plain(rec.note)[:500]}")
        elif name == 'res.partner':
            out.append(f"Nombre: {rec.display_name}")
            if rec.comment:
                out.append(f"Notas internas: {_plain(rec.comment)[:600]}")
        else:
            for field in ('partner_id', 'origin', 'description', 'note'):
                if field in rec._fields and rec[field]:
                    value = rec[field]
                    value = value.display_name if hasattr(value, 'display_name') and not isinstance(value, str) else value
                    out.append(f"{rec._fields[field].string}: {_plain(str(value))[:500]}")
        return out

    def _knowledge(self):
        words = {w.lower() for w in re.findall(r'[A-Za-zÁÉÍÓÚáéíóúñÑ]{5,}', f"{self.question.text} {self.record.display_name}")}
        words -= STOPWORDS
        if not words:
            return self.env['cristal.agent.knowledge']
        domain = self._or_domain([[('name', 'ilike', w)] for w in list(words)[:8]] +
                                 [[('content', 'ilike', w)] for w in list(words)[:8]])
        return self.env['cristal.agent.knowledge'].sudo().search([('active', '=', True)] + domain,
                                                                 order='priority desc', limit=5)

    @staticmethod
    def _or_domain(parts):
        from odoo.osv import expression
        return expression.OR(parts)

    # ───── Respuesta ─────
    def post(self, text):
        bot = self.config.bot_partner_id or self.env.ref('base.partner_root')
        self.record.with_context(cristal_employee_bot=True, from_cristal_agent=True).message_post(
            body=Markup("<p>%s</p>") % text, message_type='comment', subtype_xmlid='mail.mt_note',
            author_id=bot.id, partner_ids=self.employee.ids)


def _plain(html):
    return re.sub(r'\s+', ' ', html2plaintext(html or '')).strip()


def answer_question(env, question):
    """Contesta una consulta en cola (la llama el cron)."""
    if env.uid != SUPERUSER_ID:
        env = env(user=SUPERUSER_ID)
        question = question.with_env(env)
    session = EmployeeSession(env, question)
    if not session.record:
        question.write({'state': 'error', 'error': "El registro ya no existe."})
        return
    config = session.config
    max_turns = config.employee_max_turns or 5
    if question.turns_today(session.record) >= max_turns:
        session.escalate(question.text, "muchas consultas hoy en este registro")
        session.post(HANDOFF_TEXT)
        question.write({'state': 'escalated', 'response': HANDOFF_TEXT})
        return

    Run = env['cristal.agent.run'].sudo()
    run = Run.create({
        'trigger': 'employee_question', 'state': 'running',
        'partner_id': session.employee.id,
        'incoming_message_id': question.message_id.id,
        'incoming_text': question.text,
        'employee_res_model': session.record._name, 'employee_res_id': session.record.id,
    })
    question.run_id = run
    text = question.text or ''
    complex_task = text.count('?') > 1 or bool(RE_CALC.search(text))
    tools = EmployeeTools([EscalateToSergio(session), MarkOwnActivityDone(session)])
    prompt = (config.system_prompt_employee or '').replace('{empleado}', session.first_name)
    try:
        client = EmployeeClaudeClient(env, tools, run=run, complex_task=complex_task)
        result = client.run_conversation(
            stable_system=prompt,
            dynamic_system=session.context(),
            user_message=f"{session.first_name} escribió: \"{text}\"",
        ) or {}
        final = (result.get('final_text') or '').strip()
    except Exception as e:
        run.mark_error(str(e))
        raise
    handoff = 'lo paso a sergio' in final.lower()
    if handoff and not session.escalation:
        # El modelo dijo que lo pasa pero no llamó a la herramienta: lo hacemos igual.
        session.escalate(text, None, run=run)
    if session.escalation:
        session.post(HANDOFF_TEXT)
        question.write({'state': 'escalated', 'response': HANDOFF_TEXT})
    elif not final or SILENCE in final:
        question.write({'state': 'silent', 'response': final})
    else:
        session.post(final)
        question.write({'state': 'done', 'response': final})
    run.mark_done(final_response=final)
