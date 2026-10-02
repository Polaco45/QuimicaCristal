# -*- coding: utf-8 -*-
"""
Autotest de la ruta del camión.

Corre los criterios de aceptación de la ruta sobre los datos reales de la base
(staging), dentro de un SAVEPOINT que SIEMPRE se revierte: no deja partners,
órdenes, salidas ni mensajes creados. Se dispara desde un botón (Ruta del camión →
Autotest) y muestra el resultado caso por caso. tests/test_route.py corre los
mismos casos, así hay una sola fuente de verdad.
"""
import logging
from datetime import date, datetime, time, timedelta

import pytz

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class _SelftestRollback(Exception):
    """Fuerza el rollback del savepoint del autotest."""


class CristalAgentRouteSelftest(models.TransientModel):
    _name = 'cristal.agent.route.selftest'
    _description = 'Autotest de la ruta del camión'

    result_html = fields.Html(string="Resultado", readonly=True, sanitize=False)
    passed = fields.Integer(string="OK", readonly=True)
    failed = fields.Integer(string="Fallidos", readonly=True)

    def action_run(self):
        results = self.run_selftest()
        passed = sum(1 for _n, ok, _d in results if ok)
        rows = ''.join(
            f"<tr><td>{'✅' if ok else '❌'}</td><td><b>{name}</b></td>"
            f"<td>{detail}</td></tr>" for name, ok, detail in results)
        html = ("<table class='table table-sm'><thead><tr><th></th><th>Caso</th>"
                f"<th>Detalle</th></tr></thead><tbody>{rows}</tbody></table>")
        wiz = self.create({'result_html': html, 'passed': passed,
                           'failed': len(results) - passed})
        return {
            'type': 'ir.actions.act_window', 'res_model': self._name,
            'res_id': wiz.id, 'view_mode': 'form', 'target': 'new',
            'name': f"Autotest ruta: {passed}/{len(results)} OK",
        }

    @api.model
    def run_selftest(self):
        """Devuelve [(caso, ok, detalle)]. Nada de lo que crea queda en la base."""
        results = []
        try:
            with self.env.cr.savepoint():
                self._run_all(results)
                raise _SelftestRollback()
        except _SelftestRollback:
            pass
        except Exception as e:  # el savepoint se rompió (p. ej. rollback interno)
            _logger.exception("Autotest de ruta abortado: %s", e)
            results.append(("Ejecución", False, f"Autotest abortado: {e}"))
            self.env.cr.rollback()
        self.env.invalidate_all()
        return results

    # ───────────────────────── Helpers ─────────────────────────
    def _case(self, results, name, fn):
        try:
            with self.env.cr.savepoint():
                detail = fn()
            results.append((name, True, detail or 'OK'))
        except AssertionError as e:
            results.append((name, False, str(e)))
        except Exception as e:
            results.append((name, False, f"Excepción: {e}"))

    def _utc_from_local(self, day, hour, minute=0):
        tz = pytz.timezone('America/Argentina/Cordoba')
        local_dt = tz.localize(datetime.combine(day, time(hour, minute)))
        return local_dt.astimezone(pytz.utc).replace(tzinfo=None)

    # ───────────────────────── Casos ─────────────────────────
    def _run_all(self, results):
        from ..services.tool_registry import ToolRegistry
        env = self.env
        Circuit = env['cristal.agent.circuit'].sudo()
        Dep = env['cristal.agent.route.departure'].sudo()
        SaleOrder = env['sale.order'].sudo()
        Partner = env['res.partner'].sudo()

        config = env['cristal.agent.config'].sudo().get_active()
        freight = config.route_freight_product_id or env['product.product'].sudo().search(
            [('default_code', '=', 'FLETE-ZONA')], limit=1)
        config.write({'enable_truck_route': True, 'route_freight_product_id': freight.id})
        so = Circuit.search([('name', '=', 'Sur-Oeste')], limit=1)
        este = Circuit.search([('name', '=', 'Este')], limit=1)
        if not (so and este and freight):
            results.append(("Preparación", False,
                            "Faltan los circuitos Sur-Oeste/Este o el producto de flete."))
            return

        # Salidas fijas para el caso del 29/09/2026 (idempotente).
        for circ, d in ((so, date(2026, 10, 14)), (este, date(2026, 10, 28))):
            dep = Dep.search([('circuit_id', '=', circ.id), ('date', '=', d)], limit=1)
            if not dep:
                dep = Dep.create({'circuit_id': circ.id, 'date': d})
            dep.state = 'preventa'
        # Hay que tener una salida abierta para los pedidos de hoy.
        Dep.generate_upcoming(weeks=12)

        product = env['product.product'].sudo().create({
            'name': 'ZZ Autotest Ruta', 'type': 'consu', 'list_price': 1.0,
            'sale_ok': True, 'taxes_id': [(6, 0, [])]})
        cso = ToolRegistry.get('create_sale_order')
        gri = ToolRegistry.get('get_route_info')
        channel = config.internal_channel_id

        def mk_partner(name, city, cat=None, circuit=None):
            vals = {'name': f'ZZ Autotest {name}', 'city': city or False,
                    'mobile': '+5493580000000'}
            if cat:
                vals['category_id'] = [(4, cat.id)]
            p = Partner.create(vals)
            if circuit:
                p.truck_circuit_id = circuit.id
            return p

        def quote(partner, amount):
            return cso.execute(env=env, run=None, partner_id=partner.id, lines=[
                {'product_id': product.id, 'qty': 1, 'price_unit': amount}])

        def freight_lines(order):
            return order.order_line.filtered(lambda l: l.product_id == freight)

        next_dep = date.today() + timedelta(days=14)
        while next_dep.weekday() != 2:  # miércoles (v1.35)
            next_dep += timedelta(days=1)

        # 1) Normalización
        def c_normalizacion():
            cases = [
                ('chajàn', 'circuit', 'Sur-Oeste', 'Chaján'),
                ('Chajén', 'circuit', 'Sur-Oeste', 'Chaján'),
                ('Vicuña Maquena', 'circuit', 'Sur-Oeste', 'Vicuña Mackenna'),
                ('Moldes', 'circuit', 'Sur-Oeste', 'Coronel Moldes'),
                ('GRAL CABRERA', 'circuit', 'Norte', 'General Cabrera'),
                ('adelia maria', 'circuit', 'Sur-Este', 'Adelia María'),
                ('Rio Cuarto', 'rio_cuarto', None, 'Río Cuarto'),
                ('Laboulaye', 'fuera_zona', None, 'Laboulaye'),
            ]
            for text, kind, circ, canon in cases:
                info = Circuit.classify_city(text)
                got_c = info['circuit'].name if info.get('circuit') else None
                assert (info['kind'], got_c, info['canonical']) == (kind, circ, canon), (
                    f"'{text}' → {info['kind']}/{got_c}/{info['canonical']} "
                    f"(esperado {kind}/{circ}/{canon})")
            return f"{len(cases)} localidades OK"
        self._case(results, "1. Normalización de localidades", c_normalizacion)

        # 2) Próxima salida al 29/09/2026
        def c_fechas():
            ref = self._utc_from_local(date(2026, 9, 29), 12)
            d = so.get_next_departure(ref)
            assert d and d.date == date(2026, 10, 14), f"Sampacho: {d.date if d else None}"
            cl = d.get_cutoff_local()
            assert (cl.date(), cl.hour, cl.minute) == (date(2026, 10, 12), 18, 0), (
                f"Cierre Sampacho: {cl}")
            d2 = este.get_next_departure(ref)
            assert d2 and d2.date == date(2026, 10, 28), f"Ucacha: {d2.date if d2 else None}"
            p = mk_partner('InfoSampacho', 'Sampacho')
            gi = gri.execute(env=env, run=None, partner_id=p.id)
            assert gi.get('zone') == 'ruta_camion' and gi.get('circuit') == 'Sur-Oeste', gi
            return "Sampacho → mié 14/10 (cierre lun 12/10 18 h); Ucacha → mié 28/10"
        self._case(results, "2. Próxima salida (29/09/2026)", c_fechas)

        # 3) Pedido en Sampacho: $60k / $80k / $120k
        def c_pedidos():
            p60 = mk_partner('S60', 'Sampacho')
            r = quote(p60, 60000)
            assert r.get('blocked_route_min') and r.get('order_created') is False, r
            assert not SaleOrder.search_count([('partner_id', '=', p60.id)]), (
                "$60.000 no debía crear orden")

            p80 = mk_partner('S80', 'Sampacho')
            r = quote(p80, 80000)
            assert r.get('ok') and r.get('route'), r
            order = SaleOrder.browse(r['order_id'])
            fl = freight_lines(order)
            assert order.state == 'draft', f"estado {order.state}"
            assert len(fl) == 1 and fl.price_unit == 9000 and fl.discount == 0, (
                f"flete: {[(l.price_unit, l.discount) for l in fl]}")
            dep = so.get_next_departure()
            assert order.route_departure_id == dep, "salida de la orden"
            assert order.commitment_date == dep.get_commitment_datetime(), (
                f"commitment_date {order.commitment_date}")
            local_commit = pytz.utc.localize(order.commitment_date).astimezone(
                pytz.timezone('America/Argentina/Cordoba'))
            assert local_commit.weekday() == 2, "la entrega no cae miércoles"
            assert 'Ruta Sur-Oeste' in order.tag_ids.mapped('name'), "etiqueta de circuito"
            if channel:
                esc = env['mail.message'].sudo().search_count([
                    ('model', '=', 'discuss.channel'), ('res_id', '=', channel.id),
                    ('body', 'ilike', order.name)])
                assert esc, "no se escaló a Joaco"

            p120 = mk_partner('S120', 'Sampacho')
            r = quote(p120, 120000)
            order = SaleOrder.browse(r['order_id'])
            assert r.get('ok') and not freight_lines(order), "$120.000 no lleva flete"
            return "$60k no crea; $80k borrador + flete $9.000 + miércoles + etiqueta + escalado; $120k sin flete"
        self._case(results, "3. Pedidos en Sampacho", c_pedidos)

        # 4) Mínimo y envío gratis SIN contar el flete
        def c_sin_flete():
            p = mk_partner('S95', 'Sampacho')
            r = quote(p, 95000)
            order = SaleOrder.browse(r['order_id'])
            assert freight_lines(order), "$95.000 debía llevar flete"
            assert order.amount_untaxed == 104000, f"total s/IVA {order.amount_untaxed}"
            assert r.get('product_subtotal') == 95000, r.get('product_subtotal')
            return "$95.000 → flete → total s/IVA $104.000, sigue con flete"
        self._case(results, "4. Umbrales sin contar el flete", c_sin_flete)

        # 5) Zona horaria: lunes 17:59 entra, 18:01 pasa a la siguiente
        def c_timezone():
            tc = Circuit.create({'name': 'ZZ Autotest TZ', 'sequence': 99,
                                 'first_departure_date': next_dep})
            d1 = Dep.create({'circuit_id': tc.id, 'date': next_dep})
            d2 = Dep.create({'circuit_id': tc.id, 'date': next_dep + timedelta(days=28)})
            cl = d1.get_cutoff_local()
            assert (cl.weekday(), cl.hour, cl.minute) == (0, 18, 0), f"cierre local {cl}"
            cut = d1.get_preventa_cutoff()
            got1 = tc.get_next_departure(cut - timedelta(minutes=1))
            got2 = tc.get_next_departure(cut + timedelta(minutes=1))
            assert got1 == d1, f"17:59 → {got1.date if got1 else None}"
            assert got2 == d2, f"18:01 → {got2.date if got2 else None}"
            return f"cierre lun {cl.strftime('%d/%m')} 18:00 (Córdoba); 17:59 entra, 18:01 pasa"
        self._case(results, "5. Cierre de preventa y zona horaria", c_timezone)

        # 6) Rescate (Plan B)
        def c_rescate():
            rc_c = Circuit.create({'name': 'ZZ Autotest Rescate', 'sequence': 98,
                                   'first_departure_date': next_dep})
            courtesy = env['product.product'].sudo().create(
                {'name': 'ZZ Autotest Cortesía', 'type': 'consu', 'sale_ok': True})
            dep = Dep.create({'circuit_id': rc_c.id, 'date': next_dep, 'state': 'rescate',
                              'courtesy_product_id': courtesy.id})
            cl = dep.get_cutoff_local()
            assert (cl.weekday(), cl.hour) == (1, 12), f"cierre rescate {cl}"
            p = mk_partner('Rescate', 'ZZ Pueblo', circuit=rc_c)
            r = quote(p, 80000)
            order = SaleOrder.browse(r['order_id'])
            assert r.get('ok') and not freight_lines(order), "rescate $80k: sin flete"
            assert r.get('courtesy_product'), "no ofrece cortesía"
            gi = gri.execute(env=env, run=None, partner_id=p.id)
            assert gi.get('free_shipping_from') == 75000 and gi.get('rescate'), gi
            return "$80k sin flete (umbral $75.000), ofrece cortesía, cierre mar 12 h"
        self._case(results, "6. Rescate (Plan B)", c_rescate)

        # 7) Sin localidad
        def c_sin_ciudad():
            p = mk_partner('SinCiudad', False)
            r = quote(p, 80000)
            assert r.get('blocked_no_city') and r.get('needs_city'), r
            assert not SaleOrder.search_count([('partner_id', '=', p.id)]), "creó orden"
            gi = gri.execute(env=env, run=None, partner_id=p.id)
            assert gi.get('needs_city'), gi
            return "no cotiza y pide la localidad"
        self._case(results, "7. Cliente sin localidad", c_sin_ciudad)

        # 8) Río Cuarto nunca miércoles (v1.35)
        def c_rio_cuarto():
            p = mk_partner('RC', 'Rio Cuarto')
            gi = gri.execute(env=env, run=None, partner_id=p.id)
            assert gi.get('zone') == 'rio_cuarto' and 'departure_date' not in gi, gi
            assert 'MIÉRCOLES' in gi.get('message_for_bot', ''), gi
            r = quote(p, 80000)
            order = SaleOrder.browse(r['order_id'])
            assert r.get('ok') and not r.get('route'), r
            assert 'miércoles' in (r.get('route_note') or '').lower(), r.get('route_note')
            assert not order.commitment_date and not order.route_departure_id, (
                "a Río Cuarto no se le asigna salida de ruta")
            return "sin salida de ruta y aviso de NO miércoles"
        self._case(results, "8. Río Cuarto nunca miércoles", c_rio_cuarto)

        # 9) Backfill: la etiqueta manda, la ciudad solo si no hay etiqueta
        def c_backfill():
            cat = so.partner_category_id
            assert cat, "Sur-Oeste no tiene etiqueta de contacto (Ruta Sur-Oeste)"
            a = mk_partner('BackfillTag', 'Laboulaye', cat=cat)
            b = mk_partner('BackfillCity', 'Ucacha')
            Circuit.action_backfill_truck_circuits(partner_ids=[a.id, b.id])
            assert a.truck_circuit_id == so and cat in a.category_id, (
                f"con etiqueta: {a.truck_circuit_id.name}")
            assert b.truck_circuit_id == este, f"por ciudad: {b.truck_circuit_id.name}"
            return "etiqueta 35 + Laboulaye → Sur-Oeste; sin etiqueta + Ucacha → Este"
        self._case(results, "9. Backfill de circuitos", c_backfill)

        # ───────────────────── Reglas de oro (v1.33) ─────────────────────
        from ..services.helpers import date_context_ar, within_contact_hours
        tz = pytz.timezone('America/Argentina/Cordoba')

        # 10) Fecha de Argentina (no UTC)
        def c_fecha_ar():
            # Bug real: a las 21:26 del lunes 28/09 (00:26 UTC del 29) Claudio decía
            # "tu pedido sale esta mañana". En hora Argentina sigue siendo el 28.
            utc = pytz.utc.localize(datetime(2026, 9, 29, 0, 26))
            cal = date_context_ar(env, now=utc.astimezone(tz))
            assert cal['hoy'] == 'lunes 28/09/2026', cal['hoy']
            assert cal['manana'] == 'martes 29/09', cal['manana']
            assert cal['pasado'] == 'miércoles 30/09', cal['pasado']
            assert cal['hora'] == '21:26', cal['hora']
            real = date_context_ar(env)
            assert real['now'].date() == datetime.now(tz).date(), "hoy no es hora Argentina"
            return f"00:26 UTC del 29/09 → HOY {cal['hoy']} 21:26; mañana {cal['manana']}"
        self._case(results, "10. Fecha y día de Argentina", c_fecha_ar)

        # 11) Ventana para iniciar mensajes (7:30 a 21:30, todos los días)
        def c_horario():
            cfg = env['cristal.agent.config'].sudo().get_active()
            cfg.write({'work_hours_start': 7.5, 'work_hours_end': 21.5})
            day = date(2026, 10, 4)  # domingo: también vale
            checks = [((7, 29), False), ((7, 30), True), ((21, 29), True),
                      ((21, 30), False), ((0, 57), False), ((5, 24), False)]
            for (h, m), expected in checks:
                now = tz.localize(datetime.combine(day, time(h, m)))
                got = within_contact_hours(env, now=now)
                assert got == expected, f"{h:02d}:{m:02d} → {got} (esperado {expected})"
            return "7:29 no · 7:30 sí · 21:29 sí · 21:30 no · 00:57 no · 05:24 no"
        self._case(results, "11. Horario para iniciar mensajes", c_horario)

        # 12) Bidones: aviso siempre, cobro correcto y precio fijo
        def c_bidones():
            cfg = env['cristal.agent.config'].sudo().get_active()
            bidon = cfg.bidon_product_id or env['product.product'].sudo().search(
                [('default_code', '=', 'DA0355')], limit=1)
            assert bidon, "no hay producto de bidón (DA0355)"
            cfg.write({'bidon_product_id': bidon.id, 'bidon_price': 3500.0})
            granel = env['product.product'].sudo().create({
                'name': 'ZZ Autotest Lavandina a granel', 'type': 'consu',
                'sale_ok': True, 'taxes_id': [(6, 0, [])]})
            p = mk_partner('Bidones', 'Rio Cuarto')
            line = {'product_id': granel.id, 'qty': 40, 'price_unit': 2000}
            # a) No se sabe si tiene vacíos para canjear → avisa y pide preguntar
            r = cso.execute(env=env, run=None, partner_id=p.id, lines=[line])
            assert r.get('ok'), r
            b = r.get('bidones') or {}
            assert b.get('needed') == 2 and not b.get('answered'), b
            summ = r.get('client_summary', '')
            assert 'bidones de 20 L' in summ and '$3.500' in summ, summ
            assert 'preguntale' in (r.get('bidones_note') or '').lower(), r.get('bidones_note')
            # b) Le faltan 2 (y aunque venga con 20% OFF, el bidón no se descuenta)
            r = cso.execute(env=env, run=None, partner_id=p.id, lines=[line],
                            bidones_nuevos=2, discount_percent=20)
            order = SaleOrder.browse(r['order_id'])
            bl = order.order_line.filtered(lambda l: l.product_id == bidon)
            assert len(bl) == 1 and bl.product_uom_qty == 2 and bl.price_unit == 3500 \
                and bl.discount == 0, f"bidón: {[(l.product_uom_qty, l.price_unit, l.discount) for l in bl]}"
            assert '2 nuevo' in r.get('client_summary', ''), r.get('client_summary')
            # c) Tiene todos los vacíos para el canje → se saca el cargo
            r = cso.execute(env=env, run=None, partner_id=p.id, lines=[line], bidones_nuevos=0)
            order = SaleOrder.browse(r['order_id'])
            assert not order.order_line.filtered(lambda l: l.product_id == bidon), "quedó el cargo"
            assert 'de recambio' in r.get('client_summary', ''), r.get('client_summary')
            # d) Bajo el mínimo también avisa los bidones (caso real de staging)
            p2 = mk_partner('BidonesChico', 'Rio Cuarto')
            r = cso.execute(env=env, run=None, partner_id=p2.id, lines=[
                {'product_id': granel.id, 'qty': 20, 'price_unit': 1000}])
            assert r.get('blocked_min_compra') and 'BIDONES' in (r.get('bidones_note') or ''), r
            return ("avisa y pregunta · 2 nuevos a $3.500 sin 20% · con vacíos no se cobra "
                    "· también bajo el mínimo")
        self._case(results, "12. Bidones de 20 L", c_bidones)

        # 13) Sanitizador de tono (muletillas en medio del mensaje)
        def c_tono():
            from ..services.helpers import sanitize_tone
            cases = [
                ("Hola, soy Claudio de Química Cristal. Perfecto, te doy los precios:",
                 "Hola, soy Claudio de Química Cristal. Te doy los precios:"),
                ("Veo que tiene una despensa — perfecto, te atendemos.",
                 "Veo que tiene una despensa — te atendemos."),
                ("El jabón es excelente, se lo recomiendo.",
                 "El jabón es excelente, se lo recomiendo."),
                ("Soy Claudio de Química Cristal. \U0001F44B Perfecto, tengo todo.",
                 "Soy Claudio de Química Cristal. \U0001F44B Tengo todo."),
            ]
            for src, expected in cases:
                got = sanitize_tone(src)
                assert got == expected, f"'{src}' → '{got}'"
            return "saca 'Perfecto' tras punto y tras guión; respeta 'es excelente'"
        self._case(results, "13. Sanitizador de tono", c_tono)

        # 14) Aviso de bidones garantizado al enviar
        def c_aviso_bidones():
            from ..services.helpers import ensure_bidones_notice
            falta = ensure_bidones_notice(
                env, 0, "<p>Sobre los 20 L de detergente: ¿cuál preferís?</p>")
            assert 'bidones de 20 L' in falta and '$3.500' in falta, falta
            nada = "<p>Te paso la lista de precios.</p>"
            assert ensure_bidones_notice(env, 0, nada) == nada, "agregó sin hablar de granel"
            ya = "<p>Son 40 L de lavandina: van en 2 bidones de recambio.</p>"
            assert ensure_bidones_notice(env, 0, ya) == ya, "duplicó el aviso"
            return "agrega el aviso si habla de granel sin bidones; no duplica ni ensucia"
        self._case(results, "14. Aviso de bidones al enviar", c_aviso_bidones)

        # ───────────────────── Precios (v1.34) ─────────────────────
        # 15) "jabón líquido" trae los jabones a granel del catálogo mayorista
        def c_busqueda_jabon():
            sp = ToolRegistry.get('search_products')
            r = sp.execute(env=env, run=None, query='jabón líquido')
            names = [p['name'] for p in r.get('products') or []]
            granel = [n for n in names if 'granel' in n.lower() and 'jabon b/e' in n.lower()]
            assert granel, f"no trajo jabones a granel: {names[:6]}"
            assert names[0] in granel or r['products'][0]['is_mayorista_catalog'], (
                f"el catálogo no va primero: {names[:3]}")
            return f"trae {len(granel)} jabones B/E a granel primero ({granel[0]})"
        self._case(results, "15. Búsqueda 'jabón líquido'", c_busqueda_jabon)

        # 16) Control de precios al enviar (mensaje real del 02/10)
        def c_control_precios():
            import json as _json
            from ..services.helpers import verify_prices
            log = [{'tool_name': 'search_products', 'output': {'products': [
                {'name': 'Jabon Liquido Ariel Platinum x 3 Lts', 'price': 10512},
                {'name': 'Detergente Magistral Limón a granel', 'price': 720},
                {'name': 'Detergente Magistral Marina a  granel', 'price': 720},
                {'name': 'Jabon B/E Extra c/Desmanchador y sauv a granel', 'price': 600},
            ]}}]
            run = env['cristal.agent.run'].sudo().create({
                'trigger': 'whatsapp_message', 'tool_calls_log': _json.dumps(log)})
            real = ("<p><b>JABONES LÍQUIDOS (a granel):</b></p><p>• Jabon B/E Ariel: $720/L<br>"
                    "• Jabon B/E Skip: $720/L</p><p>• Detergente Magistral Limón: $720/L<br>"
                    "• Detergente Magistral Marina: $720/L</p>")
            bad = verify_prices(env, run, real)
            assert len(bad) == 2 and 'Ariel' in bad[0] and 'Skip' in bad[1], bad
            ok_msgs = [
                "<p>• Detergente Magistral Limón: $720/L</p>",
                "<p>Con el 20% le queda el Magistral Limón a $576 el litro.</p>",
                "<p>Te paso el precio: $408/L</p>",
            ]
            for msg in ok_msgs:
                assert not verify_prices(env, run, msg), f"bloqueó de más: {msg}"
            return "bloquea Ariel/Skip a $720 (inventados); deja Magistral $720, el 20% y frases sin producto"
        self._case(results, "16. Control de precios al enviar", c_control_precios)

        # ───────────────────── Ruta de los miércoles (v1.35) ─────────────────────
        # 17) Todas las salidas abiertas de los circuitos reales caen miércoles, y
        #     Río Cuarto no tiene reparto ese día.
        def c_miercoles():
            from ..services.helpers import rc_no_delivery_day, route_weekday
            real = Circuit.search([('active', '=', True), ('name', 'not ilike', 'ZZ Autotest')])
            assert real and all(c.weekday == '2' for c in real), (
                f"circuitos: {[(c.name, c.weekday) for c in real]}")
            deps = Dep.search([('circuit_id', 'in', real.ids),
                               ('date', '>=', date.today()),
                               ('state', 'in', ('preventa', 'rescate'))])
            bad = deps.filtered(lambda d: d.date.weekday() != 2)
            assert deps and not bad, f"salidas que no caen miércoles: {bad.mapped('name')}"
            assert rc_no_delivery_day(env) == 'miércoles', rc_no_delivery_day(env)
            assert route_weekday(env) == 'miércoles', route_weekday(env)
            return f"{len(deps)} salidas abiertas, todas miércoles; RC sin reparto el miércoles"
        self._case(results, "17. Ruta de los miércoles", c_miercoles)
