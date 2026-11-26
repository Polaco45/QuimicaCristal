# -*- coding: utf-8 -*-
"""1.82.0 — Cupones de eventos HISPANO15 / OUTLON15 (Joaco, 26/11/2026).

- Eventos (cristal.agent.event) con su programa, etiquetas, lista de correo, equipo y pedido
  de la mercadería regalada (S07503 Sociedad Española, S07502 CIMA Oulton).
- Cadencias A/B/C (sin compra) y D/E (post-compra). A/B/C apuntan a plantillas NUEVAS que se
  crean en BORRADOR (hay que enviarlas a Meta); D y E reusan 259 y 258, ya aprobadas.
- Combo del paso B: Combo Lavadero Completo + Combo Ropa.
- Regla de conocimiento 132 reescrita para que no contradiga la cadencia.
Todo es idempotente: se puede correr de nuevo sin duplicar nada.
"""
import logging
from datetime import date

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

EVENTS = [
    {'code': 'HISPANO15', 'name': 'Sociedad Española (cartelera)', 'keywords':
     'sociedad espanola, sociedad española, espanola, española', 'gift': 'S07503'},
    {'code': 'OUTLON15', 'name': 'RMI / CIMA Oulton (premios)', 'keywords':
     'rmi, cima, oulton, outlon', 'gift': 'S07502'},
]

TEMPLATES = {
    'cupon_evento_recordatorio': (
        "Cupón evento — A recordatorio",
        "Hola {{1}}! Te recuerdo que tenés tu cupón {{2}} con 15% off en tu primera compra. "
        "Los más elegidos: jabón líquido para ropa, desodorante de pisos y detergente, todo de "
        "fabricación propia. Comprá en quimicacristal.com.ar o pasá por el local. ¿Te ayudo a "
        "armar el pedido?",
        [('{{1}}', 'Ana'), ('{{2}}', 'HISPANO15')]),
    'cupon_evento_combo': (
        "Cupón evento — B combo",
        "Hola {{1}}! Te armé una idea para usar tu cupón {{2}}: {{3}}. Lo podés pedir por la "
        "web con envío o retirarlo en San Martín 2350.",
        [('{{1}}', 'Ana'), ('{{2}}', 'HISPANO15'),
         ('{{3}}', 'Combo Lavadero Completo + Combo Ropa, de $25.390 a $21.582 con el 15% aplicado')]),
    'cupon_evento_vence': (
        "Cupón evento — C vence",
        "Hola {{1}}! Último aviso: tu cupón {{2}} del 15% vence el 31/01. Si querés "
        "aprovecharlo, estamos en quimicacristal.com.ar y en San Martín 2350.",
        [('{{1}}', 'Ana'), ('{{2}}', 'HISPANO15')]),
}

CADENCES = [
    # step, name, trigger, days, template, guide, seq
    ('A', 'Cupón evento A — recordatorio (día +3)', 'event_coupon', 3,
     'cupon_evento_recordatorio', '{{1}}=nombre, {{2}}=código del cupón', 901),
    ('B', 'Cupón evento B — combo con el 15% (día +10)', 'event_coupon', 10,
     'cupon_evento_combo', '{{1}}=nombre, {{2}}=código, {{3}}=combo con precio con el 15% '
     '(lo arma el sistema con los combos de la caja; ≥ $20.000)', 902),
    ('C', 'Cupón evento C — vence (lunes 25/01 o día +25, tope 29/01)', 'event_coupon', 25,
     'cupon_evento_vence', '{{1}}=nombre, {{2}}=código', 903),
    ('D', 'Cupón evento D — ¿qué tal los productos? (día +3 de la compra)',
     'event_coupon_purchase', 3, 'cristal_satisfaccion',
     '{{1}}=nombre, {{2}}=fecha de la compra (dd/mm). La respuesta queda en observaciones.', 904),
    ('E', 'Cupón evento E — recompra sin descuento (día +30 de la compra)',
     'event_coupon_purchase', 30, 'cristal_reposicion',
     '{{1}}=nombre, {{2}}=producto principal que llevó', 905),
]

KB_NAME = ("🎟️ EXCEPCIÓN CF — Cupones de eventos HISPANO15 (Sociedad Española) y OUTLON15 "
           "(RMI / CIMA Oulton)")
KB_CONTENT = """EXCEPCIÓN DE MÁXIMA PRIORIDAD (Joaco, 26/11/2026; ajustada a la cadencia automática v1.82). Tiene prioridad sobre las reglas de derivación de consumidor final / uso personal, SOLO para estos cupones.

CONTEXTO: Química Cristal auspicia dos eventos de fin de año. En la cartelera de la Sociedad Española y en los volantes de los premios de RMI (CIMA Oulton) hay un QR que abre WhatsApp a este número con un mensaje ya escrito. El objetivo es sumar contactos a la base y que hagan su primera compra (web o local) antes del 31/01/2027.

DISPARADOR: el cliente escribe 'Hola! Quiero mi cupón del 15% - Código HISPANO15' o '... OUTLON15', o menciona el cupón junto con la Sociedad Española (HISPANO15) o RMI / CIMA / Oulton (OUTLON15). El SISTEMA lo detecta y te muestra en el contexto del cliente el bloque «🎟️ CUPÓN DE EVENTO» con el texto exacto: usalo tal cual. Si no se sabe de qué evento viene, preguntale en qué evento vio el QR. NUNCA inventes otro código ni otro porcentaje.

PASO 1 — RESPONDÉ CON EL CUPÓN (enseguida, sin preguntas previas):
'¡Hola! Gracias por escribirnos 🙌 Tu cupón es *HISPANO15*: 15% de descuento en tu primera compra desde $20.000.
🛒 Web: ingresalo al pagar en quimicacristal.com.ar
🏪 Local: mostralo en San Martín 2350, Río Cuarto
Válido hasta el 31/01/2027.'
(con el código que corresponda).

PASO 2 — NOMBRE: si todavía no lo sabemos, pedilo UNA sola vez al final de ese mensaje ('¿Me decís tu nombre así te agendamos?'). Cuando lo diga, guardalo con update_partner(name=...). El registro (etiqueta 'Evento <código>', oportunidad, lista del evento y origen) lo hace el SISTEMA: no hace falta que anotes nada a mano.

PASO 3 — SI QUIERE COMPRAR: el cupón se canjea en la web (tiene envío a domicilio) o en el local. Ofrecele ayuda: '¿Querés que te pase qué productos tenemos o te ayudo a elegir?'. Si quiere hacer el pedido por WhatsApp con envío o tiene una consulta que no podés resolver, escalá a Joaco con el detalle; no armes vos un pedido con el 15% aplicado.

SEGUIMIENTO: los recordatorios los manda el SISTEMA por plantilla (día +3 recordatorio, día +10 un combo con el 15% aplicado, y un último aviso a fin de enero), solo de lunes a viernes de 10 a 19, máximo 3, y se cortan solos si usa el cupón. Después de la compra, el sistema le pregunta qué tal los productos (día +3) y le recuerda reponer (día +30). VOS NO agendes seguimientos, actividades ni recordatorios por este cupón. Si contesta un recordatorio, conversá normal con estas mismas reglas.

BAJA: si dice 'no me escribas', 'baja' o algo equivalente: mark_opt_out(kind='no_escribir') y confirmale la baja en UNA línea, sin insistir (el sistema corta los recordatorios y lo saca de la lista).

CONDICIONES (comunicalas si preguntan): 15% sobre el total de la compra, compra mínima $20.000, válido hasta el 31/01/2027, solo primera compra, NO acumulable con otras promociones (tampoco con el 20% OFF de primera compra mayorista ni con descuentos por nivel: si es mayorista de Río Cuarto se aplica el mejor de los dos, no ambos). Después del 31/01/2027 el cupón está vencido: decíselo y derivá a la web o al local.

SI ES MAYORISTA / REVENDEDOR: dale igual el cupón (paso 1) y después seguí el flujo mayorista normal (calificación, lista mayorista). El sistema lo saca de los recordatorios del cupón.

NO mandes este cupón a quien no lo pidió ni lo ofrezcas en otras conversaciones: es solo para quienes llegan desde los eventos (el control al enviar lo frena)."""


def _ensure(model, domain, vals):
    rec = model.search(domain, limit=1)
    return rec or model.create(vals)


def _templates(env):
    WT = env['whatsapp.template'].sudo()
    account = env['whatsapp.account'].sudo().search([('name', '=', 'Cristal Mayorista')], limit=1)
    partner_model = env['ir.model']._get('res.partner')
    out = {}
    for tname, (label, body, variables) in TEMPLATES.items():
        tpl = WT.with_context(active_test=False).search([('template_name', '=', tname)], limit=1)
        if not tpl:
            try:
                with env.cr.savepoint():
                    tpl = WT.create({
                        'name': label, 'template_name': tname, 'body': body,
                        'wa_account_id': account.id if account else False,
                        'lang_code': 'es_AR', 'template_type': 'marketing',
                        'model_id': partner_model.id, 'phone_field': 'mobile',
                    })
                    # Odoo puede generar las variables solo desde el cuerpo: se completan.
                    Var = env['whatsapp.template.variable'].sudo()
                    for n, demo in variables:
                        var = tpl.variable_ids.filtered(
                            lambda v, n=n: v.name == n and v.line_type == 'body')
                        vvals = {'field_type': 'free_text', 'demo_value': demo}
                        if var:
                            var.write(vvals)
                        else:
                            Var.create(dict(vvals, wa_template_id=tpl.id, name=n,
                                            line_type='body'))
                _logger.info("1.82: plantilla %s creada en borrador (id %s).", tname, tpl.id)
            except Exception as e:  # noqa: BLE001
                _logger.exception("1.82: no pude crear la plantilla %s: %s", tname, e)
                tpl = WT.browse()
        out[tname] = tpl
    for tname in ('cristal_satisfaccion', 'cristal_reposicion'):
        dom = [('template_name', '=', tname)]
        if account:
            dom.append(('wa_account_id', '=', account.id))
        out[tname] = WT.search(dom, limit=1)
    return out


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Event = env['cristal.agent.event'].sudo().with_context(active_test=False)
    team = env['crm.team'].sudo().search([('name', '=', 'Website')], limit=1)
    for spec in EVENTS:
        code = spec['code']
        rule = env['loyalty.rule'].sudo().with_context(active_test=False).search(
            [('code', '=', code)], limit=1)
        tag_p = _ensure(env['res.partner.category'].sudo(), [('name', '=', f'Evento {code}')],
                        {'name': f'Evento {code}'})
        tag_c = _ensure(env['crm.tag'].sudo(), [('name', '=', f'Evento {code}')],
                        {'name': f'Evento {code}'})
        mlist = _ensure(env['mailing.list'].sudo(), [('name', '=', f'Evento {code}')],
                        {'name': f'Evento {code}'})
        gift = env['sale.order'].sudo().search([('name', '=', spec['gift'])], limit=1)
        vals = {
            'name': spec['name'], 'code': code, 'keywords': spec['keywords'],
            'program_id': rule.program_id.id if rule else False,
            'date_start': rule.program_id.date_from if rule and rule.program_id.date_from
            else date(2026, 11, 24),
            'date_end': rule.program_id.date_to if rule and rule.program_id.date_to
            else date(2027, 1, 31),
            'partner_tag_id': tag_p.id, 'crm_tag_id': tag_c.id,
            'mailing_list_id': mlist.id, 'team_id': team.id or False,
            'gift_order_id': gift.id or False,
        }
        ev = Event.search([('code', '=', code)], limit=1)
        if ev:
            ev.write(vals)
        else:
            ev = Event.create(vals)
        _logger.info("1.82: evento %s (programa %s, regalo %s).", code,
                     vals['program_id'], spec['gift'] if gift else '—')

    tpls = _templates(env)
    Cad = env['cristal.agent.cadence'].sudo().with_context(active_test=False)
    for step, name, trig, days, tname, guide, seq in CADENCES:
        vals = {'name': name, 'step_code': step, 'trigger_event': trig,
                'trigger_days_offset': days, 'client_type': 'both', 'phase': 'any',
                'whatsapp_template_id': tpls.get(tname).id if tpls.get(tname) else False,
                'template_variables_guide': guide, 'max_runs_per_partner': 1,
                'sequence': seq,
                'description': ("Cupones de eventos (v1.82). La ejecuta el cron 'Cupones de "
                                "eventos' (no Claudio): L-V 10-19, máx. 3 sin compra, se corta "
                                "con la compra o la baja. Ver docs/plan-cupones-eventos.md.")}
        cad = Cad.search([('step_code', '=', step), ('trigger_event', '=', trig)], limit=1)
        if cad:
            cad.write(vals)
        else:
            Cad.create(dict(vals, active=True))

    # Combo del paso B: Lavadero Completo + Ropa (si alguno no está, el sistema elige solo).
    Param = env['ir.config_parameter'].sudo()
    if not Param.get_param('cristal_agent.event_coupon_combo_ids'):
        ids = []
        for nm in ('Combo Lavadero Completo', 'Combo Ropa'):
            p = env['product.product'].sudo().search([('name', '=', nm), ('type', '=', 'combo')],
                                                     limit=1)
            if p:
                ids.append(str(p.id))
        Param.set_param('cristal_agent.event_coupon_combo_ids', ','.join(ids))

    # Regla de conocimiento 132 (por id, o por el nombre si en esta base es otro id).
    KB = env['cristal.agent.knowledge'].sudo().with_context(active_test=False)
    kb = KB.browse(132).exists()
    if not kb or 'HISPANO15' not in (kb.name or ''):
        kb = KB.search([('name', 'ilike', 'HISPANO15')], limit=1)
    if kb:
        kb.write({'name': KB_NAME, 'content': KB_CONTENT})
        _logger.info("1.82: KB %s reescrita para la cadencia de cupones.", kb.id)
    else:
        _logger.warning("1.82: no encontré la KB de los cupones HISPANO15/OUTLON15.")
