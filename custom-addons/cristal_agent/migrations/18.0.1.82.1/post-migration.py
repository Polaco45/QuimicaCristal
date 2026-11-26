# -*- coding: utf-8 -*-
"""1.82.1 — Cupones de eventos SIN campaña aparte (Joaco, 26/11/2026).

"Esto es una campaña interna que solamente estamos auspiciando… que la gente escanee un QR…
y que vos los puedas atender a nivel consumidor final. Que les puedas ofrecer a nivel
consumidor final, pero no campaña aparte."

- Sin mensajes proactivos: cadencias A-E apagadas, parámetro event_coupon_followups = 0 y
  las 3 plantillas en borrador (nunca enviadas a Meta) archivadas.
- Se quedan el registro del día 0, la atención como consumidor final y la medición.
- OULTON15 se reconoce como OUTLON15 (el evento es CIMA Oulton; el código canjeable es OUTLON15).
- Regla de conocimiento 132 sin la parte de recordatorios.
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

KB_CONTENT = """EXCEPCIÓN DE MÁXIMA PRIORIDAD (Joaco, 26/11/2026). Tiene prioridad sobre las reglas de derivación de consumidor final / uso personal, SOLO para estos cupones.

CONTEXTO: Química Cristal auspicia dos eventos de fin de año (no es una campaña aparte). En la cartelera de la Sociedad Española y en los volantes de los premios de RMI (CIMA Oulton) hay un QR que abre WhatsApp a este número con un mensaje ya escrito. Quien escribe con el código es CONSUMIDOR FINAL: lo atendés como tal y le ofrecés productos para la casa para que haga su primera compra (web o local) antes del 31/01/2027.

DISPARADOR: el cliente escribe 'Hola! Quiero mi cupón del 15% - Código HISPANO15' o '... OUTLON15' (también puede escribir OULTON15: es el mismo cupón, el código que se canjea es OUTLON15), o menciona el cupón junto con la Sociedad Española (HISPANO15) o RMI / CIMA / Oulton (OUTLON15). El SISTEMA lo detecta y te muestra en el contexto del cliente el bloque «🎟️ CUPÓN DE EVENTO» con el texto exacto: usalo tal cual. Si no se sabe de qué evento viene, preguntale en qué evento vio el QR. NUNCA inventes otro código ni otro porcentaje.

PASO 1 — RESPONDÉ CON EL CUPÓN (enseguida, sin preguntas previas):
'¡Hola! Gracias por escribirnos 🙌 Tu cupón es *HISPANO15*: 15% de descuento en tu primera compra desde $20.000.
🛒 Web: ingresalo al pagar en quimicacristal.com.ar
🏪 Local: mostralo en San Martín 2350, Río Cuarto
Válido hasta el 31/01/2027.'
(con el código que corresponda).

PASO 2 — NOMBRE: si todavía no lo sabemos, pedilo UNA sola vez al final de ese mensaje ('¿Me decís tu nombre así te agendamos?'). Cuando lo diga, guardalo con update_partner(name=...). El registro (etiqueta 'Evento <código>', oportunidad, lista del evento y origen) lo hace el SISTEMA.

PASO 3 — ATENDELO COMO CONSUMIDOR FINAL (no es mayorista: no lo califiques ni lo derives). Si consulta, recomendale productos para la casa: de fabricación propia, jabón líquido para ropa, suavizante, perfume para ropa, desodorante de pisos y detergente; también lavandina (es fraccionada: NO la presentes como fabricación propia) y los combos para la casa. Ayudalo a elegir para que use el cupón. El cupón se canjea en la web (tiene envío a domicilio) o en el local. Si quiere hacer el pedido por WhatsApp con envío o tiene una consulta que no podés resolver, escalá a Joaco con el detalle; no armes vos un pedido con el 15% aplicado.

NO HAY CAMPAÑA APARTE: no hay recordatorios ni seguimientos por este cupón. No agendes actividades ni le escribas después por tu cuenta; si vuelve a escribir, lo atendés normal.

BAJA: si dice 'no me escribas', 'baja' o algo equivalente: mark_opt_out(kind='no_escribir') y confirmale la baja en UNA línea, sin insistir.

CONDICIONES (comunicalas si preguntan): 15% sobre el total de la compra, compra mínima $20.000, válido hasta el 31/01/2027, solo primera compra, NO acumulable con otras promociones (tampoco con el 20% OFF de primera compra mayorista ni con descuentos por nivel: si es mayorista de Río Cuarto se aplica el mejor de los dos, no ambos). Después del 31/01/2027 el cupón está vencido: decíselo y derivá a la web o al local.

SI ES MAYORISTA / REVENDEDOR: dale igual el cupón (paso 1) y después seguí el flujo mayorista normal (calificación, lista mayorista).

NO mandes este cupón a quien no lo pidió ni lo ofrezcas en otras conversaciones: es solo para quienes llegan desde los eventos (el control al enviar lo frena)."""


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['ir.config_parameter'].sudo().set_param('cristal_agent.event_coupon_followups', '0')

    cads = env['cristal.agent.cadence'].sudo().with_context(active_test=False).search(
        [('trigger_event', 'in', ('event_coupon', 'event_coupon_purchase'))])
    cads.write({'active': False})
    _logger.info("1.82.1: %s cadencias de cupones de eventos apagadas.", len(cads))

    WT = env['whatsapp.template'].sudo().with_context(active_test=False)
    tpls = WT.search([('template_name', 'in', ('cupon_evento_recordatorio', 'cupon_evento_combo',
                                                'cupon_evento_vence')),
                      ('status', '=', 'draft')])
    if tpls:
        tpls.write({'active': False})
    _logger.info("1.82.1: %s plantillas en borrador archivadas (nunca se enviaron a Meta).",
                 len(tpls))

    ev = env['cristal.agent.event'].sudo().with_context(active_test=False).search(
        [('code', '=', 'OUTLON15')], limit=1)
    if ev:
        ev.write({'code_aliases': 'OULTON15', 'name': 'RMI / CIMA Oulton (premios)'})

    KB = env['cristal.agent.knowledge'].sudo().with_context(active_test=False)
    kb = KB.browse(132).exists()
    if not kb or 'HISPANO15' not in (kb.name or ''):
        kb = KB.search([('name', 'ilike', 'HISPANO15')], limit=1)
    if kb:
        kb.write({'content': KB_CONTENT})
        _logger.info("1.82.1: KB %s sin recordatorios (atención consumidor final).", kb.id)
