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
            'name': 'ZZ Autotest Ruta', 'type': 'consu', 'list_price': 1.0, 'is_storable': False,
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
            gratis = max(120000, (config.route_free_shipping_from or 0) + 1000)
            r = quote(p120, gratis)
            order = SaleOrder.browse(r['order_id'])
            assert r.get('ok') and not freight_lines(order), f"${gratis:,.0f} no lleva flete"
            return (f"$60k no crea; $80k borrador + flete $9.000 + miércoles + etiqueta + "
                    f"escalado; ${gratis:,.0f} sin flete")
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
            # Una salida que el equipo movió a mano (ej. Sur-Oeste al viernes 23/10)
            # es válida: solo se exige miércoles a las que generó el sistema.
            moved = deps.filtered(lambda d: d.date.weekday() != 2 and d.write_uid.id != 1)
            bad = deps.filtered(lambda d: d.date.weekday() != 2) - moved
            assert deps and not bad, f"salidas que no caen miércoles: {bad.mapped('name')}"
            assert rc_no_delivery_day(env) == 'miércoles', rc_no_delivery_day(env)
            assert route_weekday(env) == 'miércoles', route_weekday(env)
            extra = f" (movidas a mano: {', '.join(moved.mapped('name'))})" if moved else ""
            return (f"{len(deps)} salidas abiertas, las generadas caen miércoles{extra}; "
                    f"RC sin reparto el miércoles")
        self._case(results, "17. Ruta de los miércoles", c_miercoles)
        # ───────────────────── Sin muestras gratis (v1.34.1) ─────────────────────
        # 18) Joaco sacó la promo de 3 muestras gratis con compras de +$60.000: la
        #     herramienta no existe más y el cotizador no la sugiere.
        def c_sin_muestras():
            assert ToolRegistry.get('add_free_samples') is None, "add_free_samples sigue registrada"
            p = mk_partner('PromoOff', 'Rio Cuarto')
            r = quote(p, 90000)
            assert r.get('ok'), r
            assert 'samples_hint' not in r, "el cotizador sigue sugiriendo muestras"
            txt = str(r).lower()
            assert 'muestras gratis' not in txt and 'add_free_samples' not in txt, (
                "la respuesta del cotizador sugiere muestras")
            order = SaleOrder.browse(r['order_id'])
            assert not order.order_line.filtered(
                lambda l: 'muestra' in (l.product_id.name or '').lower()), "la orden trae muestras"
            return "sin herramienta de muestras; pedido de $90k sin muestras ni aviso"
        self._case(results, "18. Sin muestras gratis", c_sin_muestras)

        # ═════════════════ Correcciones del 13/10 (v1.36) ═════════════════
        # 19) 20% de primera compra: SOLO Río Cuarto / Las Higueras.
        def c_veinte_zona():
            from ..services.helpers import first_purchase_discount_status
            prod = env['product.product'].sudo().create({
                'name': 'ZZ Autotest Lista', 'type': 'consu', 'list_price': 200000.0, 'is_storable': False,
                'sale_ok': True, 'taxes_id': [(6, 0, [])]})
            mayorista_pl = env['product.pricelist'].sudo().search(
                [('name', '=', 'Lista Mayorista')], limit=1)
            env['product.pricelist.item'].sudo().create({
                'pricelist_id': mayorista_pl.id, 'applied_on': '0_product_variant',
                'product_id': prod.id, 'product_tmpl_id': prod.product_tmpl_id.id,
                'compute_price': 'fixed', 'fixed_price': 160000.0})
            ps = mk_partner('Veinte Sampacho', 'Sampacho')
            assert first_purchase_discount_status(env, ps)[0] == 'blocked'
            r = cso.execute(env=env, run=None, partner_id=ps.id, discount_percent=20,
                            lines=[{'product_id': prod.id, 'qty': 1}])
            assert r.get('zone_discount_blocked'), f"Sampacho: no bloqueó el 20% ({r})"
            if r.get('order_id'):
                o = SaleOrder.browse(r['order_id'])
                assert not o.order_line.filtered(lambda l: l.discount), "Sampacho con descuento"
            prc = mk_partner('Veinte RC', 'Rio Cuarto')
            assert first_purchase_discount_status(env, prc)[0] == 'allowed'
            r = cso.execute(env=env, run=None, partner_id=prc.id, discount_percent=20,
                            lines=[{'product_id': prod.id, 'qty': 1}])
            assert r.get('ok') and not r.get('zone_discount_blocked'), r
            o = SaleOrder.browse(r['order_id'])
            assert o.order_line.filtered(lambda l: l.product_id == prod).discount == 20, (
                "Río Cuarto sin el 20%")
            pf = mk_partner('Veinte Laboulaye', 'Laboulaye')
            assert first_purchase_discount_status(env, pf)[0] == 'blocked'
            pn = mk_partner('Veinte SinCiudad', False)
            assert first_purchase_discount_status(env, pn)[0] == 'unknown'
            return "Sampacho sin 20% · Río Cuarto con 20% · Laboulaye bloqueado · sin ciudad: no se ofrece"
        self._case(results, "19. 20% solo Río Cuarto", c_veinte_zona)

        # 20) Localidades mal escritas: alias + parecido (pregunta, no fuera de zona).
        def c_localidades():
            casos = [('Olver', 'circuit', 'Holmberg'), ('olmberg', 'circuit', 'Holmberg'),
                     ('Holver', 'circuit', 'Holmberg'), ('Moldes', 'circuit', 'Coronel Moldes'),
                     ('Cnel Moldes', 'circuit', 'Coronel Moldes'),
                     ('Vicuña', 'circuit', 'Vicuña Mackenna'),
                     ('Mackena', 'circuit', 'Vicuña Mackenna'),
                     ('Gral Cabrera', 'circuit', 'General Cabrera'),
                     ('Deheza', 'circuit', 'General Deheza'),
                     ('La Carlota', 'circuit', 'La Carlota'),
                     ('Adelia', 'circuit', 'Adelia María'),
                     ('Rio IV', 'rio_cuarto', 'Río Cuarto'),
                     ('Laboulaye', 'fuera_zona', None)]
            for text, kind, canon in casos:
                info = Circuit.classify_city(text)
                got = info['canonical'] if info['kind'] != 'fuera_zona' else None
                assert (info['kind'], got) == (kind, canon), f"'{text}' → {info['kind']}/{got}"
            maybe = Circuit.classify_city('Berrotaram')
            assert maybe['kind'] == 'maybe' and maybe['candidate'] == 'Berrotarán', maybe
            p = mk_partner('Tipeo', 'Berrotaram')
            gi = gri.execute(env=env, run=None, partner_id=p.id)
            assert gi.get('needs_confirmation') and gi.get('candidate_city') == 'Berrotarán', gi
            r = cso.execute(env=env, run=None, partner_id=p.id,
                            lines=[{'product_id': product.id, 'qty': 1, 'price_unit': 90000}])
            assert r.get('needs_city_confirmation'), f"cotizó con localidad dudosa: {r}"
            p2 = mk_partner('TipeoUpd', False)
            up = ToolRegistry.get('update_partner').execute(
                env=env, run=None, partner_id=p2.id, city='Berrotaram')
            assert up.get('needs_confirmation') and p2.agent_zone != 'fuera_zona', up
            fz = env['res.partner.category'].sudo().search([('name', '=', 'Fuera de zona')], limit=1)
            assert not fz or fz not in p2.category_id, "lo etiquetó Fuera de zona"
            return "Olver/olmberg/Moldes/Vicuña/Gral Cabrera… OK · Laboulaye fuera · 'Berrotaram' → pregunta"
        self._case(results, "20. Localidades mal escritas", c_localidades)

        # 21) Feriados y días cerrados.
        def c_feriados():
            from ..services.helpers import (closed_day_reason, business_status,
                                            next_business_day, attention_status_line)
            tz = pytz.timezone('America/Argentina/Cordoba')
            assert 'feriado' in (closed_day_reason(env, date(2026, 10, 12)) or ''), "12/10"
            assert closed_day_reason(env, date(2026, 10, 13)) is None, "13/10 es hábil"
            assert closed_day_reason(env, date(2026, 10, 18)) == 'domingo'
            st = business_status(env, tz.localize(datetime(2026, 10, 12, 10, 0)))
            assert st['closed_today'] and not st['open_now'], st
            assert st['confirm_when'] == 'el martes 13/10', st['confirm_when']
            line = attention_status_line(env, tz.localize(datetime(2026, 10, 12, 10, 0)))
            assert 'HOY NO ATENDEMOS' in line, line
            st = business_status(env, tz.localize(datetime(2026, 10, 16, 20, 30)))  # vie 20:30
            assert not st['open_now'] and st['confirm_when'] == 'el sábado 17/10', st
            st = business_status(env, tz.localize(datetime(2026, 10, 13, 10, 0)))  # mar 10 h
            assert st['open_now'] and st['confirm_when'] == 'hoy', st
            config.closed_dates = "2026-10-14 Inventario"
            assert closed_day_reason(env, date(2026, 10, 14)) == 'Inventario'
            assert next_business_day(env, date(2026, 10, 13)) == date(2026, 10, 15)
            config.closed_dates = False
            hc = Circuit.create({'name': 'ZZ Autotest Feriado', 'sequence': 97,
                                 'first_departure_date': date(2026, 12, 8)})
            Dep.create({'circuit_id': hc.id, 'date': date(2026, 12, 8)})
            ph = mk_partner('Feriado', 'ZZ Pueblo', circuit=hc)
            gi = gri.execute(env=env, run=None, partner_id=ph.id)
            assert gi.get('departure_on_closed_day'), f"salida en feriado sin aviso: {gi}"
            return ("12/10 feriado → 'hoy no atendemos', confirma el martes 13/10 · vie 20:30 "
                    "→ sábado · config · salida 8/12 no se promete")
        self._case(results, "21. Feriados y días cerrados", c_feriados)

        # 22) Controles al enviar: 20%, "Joaquín coordina", minutos, entrega RC.
        def c_controles_envio():
            import json as _json
            from ..services.send_guards import apply_send_guards
            ch = config.internal_channel_id.id
            pz = mk_partner('GuardSampacho', 'Sampacho')
            prc = mk_partner('GuardRC', 'Rio Cuarto')
            run = env['cristal.agent.run'].sudo().create({
                'trigger': 'whatsapp_message', 'partner_id': pz.id})

            def guard(body, partner):
                return apply_send_guards(env, run, ch, body, partner)

            _b, err = guard("<p>Le paso la lista. Su primer pedido lleva 20% OFF.</p>", pz)
            assert err and err['guard'] == 'first_purchase_zone', err
            _b, err = guard("<p>Le paso la lista. Su primer pedido lleva 20% OFF.</p>", prc)
            assert not err, f"bloqueó el 20% a Río Cuarto: {err}"
            _b, err = guard("<p>Para su localidad el envío lo coordina Joaquín.</p>", pz)
            assert err and err['guard'] == 'coordina_envio', err
            _b, err = guard("<p>Dejame chequear con Joaco, te aviso en un minuto.</p>", pz)
            assert err and err['guard'] == 'promesa_minutos', err
            _b, err = guard("<p>Te lo llevamos el lunes 19/10 a las 11 h.</p>", prc)
            assert err and err['guard'] == 'entrega_rc', err
            _b, err = guard("<p>Pasamos por Sampacho el miércoles 11/11; tomamos pedidos "
                            "hasta el lunes 09/11 a las 18 h.</p>", pz)
            assert not err, f"bloqueó la fecha de la ruta: {err}"
            _b, err = guard("<p>¿Cuántos litros llevás hoy?</p>", prc)
            assert not err, f"bloqueó una pregunta común: {err}"
            # 2da vez en la misma corrida: corrige y manda.
            run.tool_calls_log = _json.dumps([{'tool_name': 'send_whatsapp', 'output': {
                'error': 'x', 'guard': 'first_purchase_zone'}}])
            body, err = guard("<p>Le paso la lista. Su primer pedido lleva 20% OFF. "
                              "¿Le armo la cotización?</p>", pz)
            assert not err and '20%' not in body and 'cotización' in body, body
            return ("20% zona · 'Joaquín coordina' · 'en un minuto' · entrega RC: bloqueados; "
                    "ruta y preguntas OK; 2da vez corrige")
        self._case(results, "22. Controles al enviar", c_controles_envio)

        # 23) Una escalación por pedido (se actualiza, no se duplica).
        def c_escalacion_unica():
            esc = ToolRegistry.get('escalate_to_joaco')
            ch = config.internal_channel_id
            assert ch, "sin canal interno"
            pe = mk_partner('Escala', 'Rio Cuarto')
            Msg = env['mail.message'].sudo()
            n0 = Msg.search_count([('model', '=', 'discuss.channel'), ('res_id', '=', ch.id)])
            r1 = esc.execute(env=env, run=None, related_partner_id=pe.id,
                             message="PEDIDO PARA CONFIRMAR — ZZ Escala. Cotización S99999, total $90.000.")
            r2 = esc.execute(env=env, run=None, related_partner_id=pe.id,
                             message="Ruta: el cliente sumó 20 L de lavandina a S99999.")
            r3 = esc.execute(env=env, run=None, related_partner_id=pe.id,
                             message="Pregunta si hay gamuzas.")
            n1 = Msg.search_count([('model', '=', 'discuss.channel'), ('res_id', '=', ch.id)])
            assert r1.get('ok') and r2.get('updated_existing') and r3.get('updated_existing'), (
                r1, r2, r3)
            assert n1 - n0 == 1, f"se crearon {n1 - n0} mensajes (esperado 1)"
            body = Msg.browse(r2['escalation_message_id']).body
            assert 'lavandina' in body and 'gamuzas' in body, "no agregó las novedades"
            return "3 escalaciones del mismo pedido/cliente → 1 mensaje actualizado"
        self._case(results, "23. Una escalación por pedido", c_escalacion_unica)

        # 24) Duplicados y adjuntos inventados (canal 2997: mismo texto 2 veces).
        def c_duplicados():
            import json as _json
            from ..services.send_guards import check_attachments, duplicate_recent
            run = env['cristal.agent.run'].sudo().create({'trigger': 'whatsapp_message'})
            att = env['ir.attachment'].sudo().create({'name': 'ZZ autotest.pdf', 'raw': b'%PDF'})
            err = check_attachments(env, run, [att.id])
            assert err and err['guard'] == 'attachment', "aceptó un adjunto que no generó ninguna tool"
            run.tool_calls_log = _json.dumps([{'tool_name': 'generate_pricelist_pdf',
                                               'output': {'attachment_id': att.id}}])
            assert check_attachments(env, run, [att.id]) is None, "rechazó el PDF de la tool"
            ch = config.internal_channel_id.id
            bot = config.bot_partner_id.id if config.bot_partner_id else 2
            text = "<p>ZZ autotest: Hola Carla, te paso la lista mayorista.</p>"
            assert not duplicate_recent(env, ch, text, bot)
            env['mail.message'].sudo().with_context(from_cristal_agent=True).create({
                'author_id': bot, 'body': text, 'message_type': 'comment',
                'model': 'discuss.channel', 'res_id': ch})
            assert duplicate_recent(env, ch, text, bot), "no detectó el duplicado"
            return "adjunto inventado → bloqueado · PDF de la tool OK · mismo texto en segundos → no se repite"
        self._case(results, "24. Duplicados y adjuntos", c_duplicados)

        # 25) Sin stock: la línea no se carga y se ofrecen alternativas.
        def c_sin_stock():
            categ = env['product.category'].sudo().create({'name': 'ZZ Autotest Categ'})
            sin = env['product.product'].sudo().create({
                'name': 'ZZ Aromatizante sin stock', 'type': 'consu', 'is_storable': True,
                'list_price': 5000.0, 'sale_ok': True, 'categ_id': categ.id})
            alt = env['product.product'].sudo().create({
                'name': 'ZZ Aromatizante a granel', 'type': 'consu',
                'list_price': 5000.0, 'sale_ok': True, 'categ_id': categ.id})
            p = mk_partner('Stock', 'Rio Cuarto')
            r = cso.execute(env=env, run=None, partner_id=p.id, lines=[
                {'product_id': sin.id, 'qty': 2},
                {'product_id': product.id, 'qty': 1, 'price_unit': 90000}])
            assert r.get('ok'), r
            o = SaleOrder.browse(r['order_id'])
            assert sin not in o.order_line.mapped('product_id'), "cargó el producto sin stock"
            ns = r.get('no_stock_lines') or []
            assert ns and any(a['product_id'] == alt.id for a in ns[0]['alternativas']), ns
            assert 'FALTA DE STOCK' in (r.get('no_stock_note') or ''), r.get('no_stock_note')
            return "producto sin stock no se carga; ofrece alternativa del mismo tipo"
        self._case(results, "25. Productos sin stock", c_sin_stock)

        # 26) Cliente que no entiende: mensaje corto + escalar.
        def c_no_entiende():
            from ..services import send_guards as sg
            assert sg._RE_NO_ENTIENDE.search("no entiendo nada")
            assert sg._RE_PIDE_AUDIO.search("me podés mandar un audio?")
            assert sg._RE_PIDE_AUDIO.search("llamame por favor")
            original = sg.confusion_signal
            sg.confusion_signal = lambda *a, **k: (2, False)
            try:
                largo = "<p>" + "Le explico cómo funciona la ruta del camión. " * 8 + "</p>"
                _b, err = sg.apply_send_guards(env, None, 0, largo, None)
                assert err and err['guard'] == 'cliente_no_entiende', err
                _b, err = sg.apply_send_guards(
                    env, None, 0, "<p>Le pido a Joaquín que lo llame.</p>", None)
                assert not err, err
            finally:
                sg.confusion_signal = original
            return "2 'no entiendo' o pedido de audio → bloquea textos largos y pide escalar"
        self._case(results, "26. Cliente que no entiende", c_no_entiende)

        # 27) Modelo: Sonnet 5.5 sin temperature y con esfuerzo; precios correctos.
        def c_modelo():
            from ..services.claude_client import _is_modern_model
            assert _is_modern_model('claude-sonnet-5-5') and _is_modern_model('claude-opus-5-5')
            assert not _is_modern_model('claude-haiku-4-5-20251001')
            Run = env['cristal.agent.run']
            p = Run._prices_for_model('claude-sonnet-5-5')
            assert (p['in'], p['out'], p['cr']) == (2.0, 10.0, 0.20), p
            assert Run._prices_for_model('claude-haiku-4-5-20251001')['in'] == 1.0
            assert config.anthropic_model == 'claude-sonnet-5-5', config.anthropic_model
            assert config.anthropic_effort in ('low', 'medium', 'high')
            assert config.max_tokens >= 16000, config.max_tokens
            return (f"modelo {config.anthropic_model} · esfuerzo {config.anthropic_effort} · "
                    f"max_tokens {config.max_tokens} · sin temperature · precios Sonnet 5.5 OK")
        self._case(results, "27. Modelo Sonnet 5.5", c_modelo)

        # ═════════════════ Envío sin cargo desde config (v1.37) ═════════════════
        free_from = config.route_free_shipping_from

        # 28) Umbral: free_from - 1 → flete; free_from → sin flete. Base: todo menos flete.
        def c_umbral_envio():
            pa = mk_partner('Umbral A', 'Sampacho')
            r = quote(pa, free_from - 1)
            o = SaleOrder.browse(r['order_id'])
            fl = freight_lines(o)
            assert r.get('ok') and len(fl) == 1 and fl.price_unit == config.route_freight_amount, (
                f"${free_from - 1:,.0f} debía llevar flete: {r.get('route_note')}")
            pb = mk_partner('Umbral B', 'Sampacho')
            r = quote(pb, free_from)
            o = SaleOrder.browse(r['order_id'])
            assert r.get('ok') and not freight_lines(o), f"${free_from:,.0f} no lleva flete"
            # Base: solo productos — ni el flete ni los bidones nuevos suman.
            bidon = config.bidon_product_id
            assert bidon, "falta el producto bidón en la config"
            o.write({'order_line': [(0, 0, {'product_id': bidon.id, 'product_uom_qty': 2,
                                            'price_unit': 3500.0})]})
            base = o._cristal_shipping_base(config)
            assert base == free_from, f"base {base} (esperado {free_from}: sin bidones)"
            pc = mk_partner('Umbral C', 'Sampacho')
            r = quote(pc, free_from - 5000)
            o = SaleOrder.browse(r['order_id'])
            o.write({'order_line': [(0, 0, {'product_id': bidon.id, 'product_uom_qty': 2,
                                            'price_unit': 3500.0})]})
            freight, base = o._cristal_apply_route_freight(config, free_from)
            assert freight and len(freight_lines(o)) == 1, (
                f"${free_from - 5000:,.0f} + 2 bidones: los bidones no suman, debía llevar flete")
            return (f"${free_from - 1:,.0f} → flete ${config.route_freight_amount:,.0f} · "
                    f"${free_from:,.0f} → sin flete · los bidones no suman (como el mínimo)")
        self._case(results, "28. Envío sin cargo desde la config", c_umbral_envio)

        # 29) Envío sin cargo acordado: nunca flete, ni al re-cotizar; Claudio no lo toca.
        def c_envio_acordado():
            p = mk_partner('Acordado', 'Sampacho')
            r = quote(p, 120000)
            o = SaleOrder.browse(r['order_id'])
            assert freight_lines(o), "$120.000 sin acuerdo debía llevar flete"
            o.write({'route_free_shipping_granted': True})
            assert not freight_lines(o), "al marcar el acuerdo no se sacó el flete"
            r2 = cso.execute(env=env, run=None, partner_id=p.id, lines=[
                {'product_id': product.id, 'qty': 1, 'price_unit': 120000},
                {'product_id': product2.id, 'qty': 1, 'price_unit': 5000}])
            o2 = SaleOrder.browse(r2['order_id'])
            assert o2 == o, "no re-usó el borrador"
            assert r2.get('ok') and not freight_lines(o2), (
                f"re-cotizado con el acuerdo y $125.000: no debía llevar flete ({r2.get('route_note')})")
            o2.with_context(from_cristal_agent=True).write({'route_free_shipping_granted': False})
            assert o2.route_free_shipping_granted, "Claudio pudo sacar el envío acordado"
            return "$120.000 con acuerdo → sin flete, también al re-cotizar; Claudio no lo puede cambiar"
        product2 = env['product.product'].sudo().create({
            'name': 'ZZ Autotest Ruta 2', 'type': 'consu', 'list_price': 1.0,
            'is_storable': False, 'sale_ok': True, 'taxes_id': [(6, 0, [])]})
        self._case(results, "29. Envío sin cargo acordado", c_envio_acordado)

        # 30) Upsell al umbral: cuánto falta + UNA opción, solo promos vigentes.
        def c_upsell_umbral():
            env['cristal.agent.offer'].sudo().create({
                'name': 'ZZ Promo 5+1 suavizante', 'description': 'ZZ autotest',
                'offer_type': 'other', 'valid_from': date.today(),
                'valid_until': date.today(), 'active': True, 'applies_to_levels': 'all',
                'priority': 99})
            p = mk_partner('Upsell', 'Sampacho')
            r = quote(p, 100000)
            up = r.get('free_shipping_upsell') or ''
            falta = '${:,.0f}'.format(free_from - 100000).replace(',', '.')
            assert falta in up and 'ZZ Promo 5+1 suavizante' in up, up
            assert 'UNA sola opción' in up and 'NUNCA inventes' in up, up
            assert 'Kit Cloro' not in up, "sugirió una promo de consumidor final"
            return f"$100.000 → 'le faltan {falta}', sugiere UNA opción de las promos vigentes"
        self._case(results, "30. Upsell al envío sin cargo", c_upsell_umbral)

        # ═════════════════ Retiro en planta sin mínimo (v1.38) ═════════════════
        # 31) Caso Valeria: 1 bidón para retirar → se cotiza sin mínimo ni flete.
        def c_retiro_sin_minimo():
            def q(partner, amount, mode=None):
                kw = {'delivery_mode': mode} if mode else {}
                return cso.execute(env=env, run=None, partner_id=partner.id, lines=[
                    {'product_id': product.id, 'qty': 1, 'price_unit': amount}], **kw)
            p1 = mk_partner('Retiro RC', 'Rio Cuarto')
            r = q(p1, 13120, 'retiro')
            assert r.get('ok') and not r.get('blocked_min_compra') and not r.get('upsell'), r
            o = SaleOrder.browse(r['order_id'])
            assert o.cristal_delivery_mode == 'retiro', o.cristal_delivery_mode
            assert 'RETIRO EN PLANTA' in (r.get('route_note') or ''), r.get('route_note')
            p2 = mk_partner('Envio RC', 'Rio Cuarto')
            r = q(p2, 13120)
            assert r.get('blocked_min_compra'), "con envío $13.120 debía frenar por el mínimo"
            assert "delivery_mode='retiro'" in r.get('message_for_bot', ''), "no ofrece el retiro"
            p3 = mk_partner('Retiro Sampacho', 'Sampacho')
            r = q(p3, 30000, 'retiro')
            o = SaleOrder.browse(r['order_id']) if r.get('order_id') else SaleOrder
            assert r.get('ok') and not r.get('blocked_route_min'), r
            assert not freight_lines(o) and not o.route_departure_id, "retiro con flete o salida"
            p4 = mk_partner('Retiro sin ciudad', False)
            r = q(p4, 13120, 'retiro')
            assert r.get('ok') and not r.get('needs_city'), r
            return ("RC 1 bidón ($13.120) retirando → se cotiza · con envío → mínimo + ofrece "
                    "retiro · Sampacho $30.000 retirando → sin mínimo, flete ni salida · "
                    "sin localidad retirando → OK")
        self._case(results, "31. Retiro en planta sin mínimo", c_retiro_sin_minimo)

        # ═════════════════ Ventana cerrada → plantilla (v1.39) ═════════════════
        # 32) Caso Margarita: seguimiento con la ventana cerrada sale solo por la
        # plantilla genérica; no se repite si la anterior no se contestó; si no
        # sale, la tool lo dice (not_sent) para que no se anote como enviado.
        def c_ventana_plantilla():
            from unittest.mock import patch
            from ..services.helpers import (template_text_from_html,
                                            closed_window_template)
            t = template_text_from_html(
                "<p>Hola Margarita, ¿pudo ver la cotización?</p><p>Le faltan 20 L.</p>")
            assert t == "¿Pudo ver la cotización? Le faltan 20 L.", t
            t = template_text_from_html("<p>Hola, ¿cómo está? Le escribo por el pedido.</p>")
            assert t == "Le escribo por el pedido.", t
            t = template_text_from_html("<p>Mañana sale el camión.</p>")
            assert t == "Mañana sale el camión.", t
            tpl = env['whatsapp.template'].sudo().search(
                [('template_name', '=', 'hola_mayorista_crm'), ('status', '=', 'approved')],
                limit=1)
            assert tpl, "no está la plantilla aprobada hola_mayorista_crm"
            acc = tpl.wa_account_id.id
            assert closed_window_template(env, acc) == tpl, "no elige hola_mayorista_crm"
            p = mk_partner('Ventana cerrada', 'Rio Cuarto')
            p.mobile = '+5493589990032'
            ch = env['discuss.channel'].sudo().create({
                'name': 'ZZ Autotest ventana', 'channel_type': 'group',
                'channel_member_ids': [(0, 0, {'partner_id': p.id})]})
            sw = ToolRegistry.get('send_whatsapp')
            tool = ToolRegistry.get('send_whatsapp_template')
            calls = []

            def fake_execute(**kw):
                calls.append(kw)
                return {'ok': True, 'wa_message_id': False}
            with patch.object(tool, 'execute', fake_execute):
                body = "<p>Hola Ventana, ¿pudo ver la cotización? Si me confirma, la dejo lista.</p>"
                r = sw._execute(env=env, run=None, channel_id=ch.id, body=body,
                                wa_account_id=acc, mobile_number=p.mobile)
                assert r.get('ok') and r.get('sent_via_template') == 'hola_mayorista_crm', r
                assert calls and calls[0]['partner_id'] == p.id, calls
                assert calls[0]['variables'] == [
                    "¿Pudo ver la cotización? Si me confirma, la dejo lista."], calls[0]
                assert calls[0]['env'].context.get('from_cristal_agent'), "sin from_cristal_agent"
                # Plantilla anterior sin contestar → no se manda otra.
                WA = env['whatsapp.message'].sudo()
                sent = WA.create({'mobile_number': p.mobile, 'wa_account_id': acc,
                                  'wa_template_id': tpl.id, 'message_type': 'outbound',
                                  'state': 'sent'})
                env.cr.execute("UPDATE whatsapp_message SET create_date = "
                               "now() at time zone 'UTC' - interval '2 hours' WHERE id = %s",
                               (sent.id,))
                WA.invalidate_model(['create_date'])
                r = sw._execute(env=env, run=None, channel_id=ch.id,
                                body="<p>¿Lo vio? Quedo atento.</p>",
                                wa_account_id=acc, mobile_number=p.mobile)
                assert r.get('error') == 'TEMPLATE_PENDING' and r.get('not_sent'), r
                assert len(calls) == 1, "mandó otra plantilla sin respuesta a la anterior"
                # Texto largo → no sale y lo dice (sin la plantilla pendiente; un
                # inbound abriría la ventana y el mensaje saldría de verdad).
                sent.unlink()
                r = sw._execute(env=env, run=None, channel_id=ch.id,
                                body="<p>" + "Detalle del pedido. " * 60 + "</p>",
                                wa_account_id=acc, mobile_number=p.mobile)
                assert r.get('error') == 'TEMPLATE_TEXT_TOO_LONG' and r.get('not_sent'), r
            return ("saludo fuera del texto · ventana cerrada → hola_mayorista_crm con "
                    "from_cristal_agent · plantilla sin contestar → TEMPLATE_PENDING (no "
                    "manda otra) · texto largo → not_sent")
        self._case(results, "32. Ventana cerrada sale por plantilla", c_ventana_plantilla)

        # ═════════════════ Envío de los lunes (v1.40) ═════════════════
        # 33) Solo sale la oferta marcada para el envío, con su texto para el cliente, y
        # no le llega a los circuitos excluidos, a "Fuera de zona", a números repetidos
        # ni a quien recibió una plantilla en las últimas 24 h.
        def c_envio_lunes():
            from odoo.exceptions import ValidationError
            Offer = env['cristal.agent.offer'].sudo()
            Cat = env['res.partner.category'].sudo()
            may = Cat.search([('name', '=', 'Mayorista')], limit=1)
            fz = Cat.search([('name', '=', 'Fuera de zona')], limit=1)
            so = env['cristal.agent.circuit'].sudo().search([('name', '=', 'Sur-Oeste')], limit=1)
            assert may and fz and so, "faltan la etiqueta Mayorista/Fuera de zona o Sur-Oeste"
            today = fields.Date.context_today(Offer)
            Offer.create({'name': 'ZZ Autotest zona', 'description': 'interna',
                          'offer_type': 'other', 'valid_from': today,
                          'valid_until': today, 'priority': 98})
            off = Offer.create({'name': 'ZZ Autotest lunes', 'description': 'instrucción interna',
                                'offer_type': 'bonus', 'valid_from': today,
                                'valid_until': today, 'priority': 99,
                                'weekly_broadcast': True, 'broadcast_text': 'pack de regalo',
                                'excluded_circuit_ids': [(6, 0, so.ids)]})
            assert Offer.get_weekly_broadcast_offer() == off, "elige una oferta no marcada"
            try:
                with env.cr.savepoint():
                    Offer.create({'name': 'ZZ sin texto', 'description': 'x',
                                  'offer_type': 'other', 'valid_from': today,
                                  'valid_until': today, 'weekly_broadcast': True})
                raise AssertionError("dejó marcar el envío sin texto para el cliente")
            except ValidationError:
                pass

            def mk(name, number, cats, circuit=None):
                p = Partner.create({'name': f'ZZ Autotest {name}', 'mobile': number,
                                    'category_id': [(6, 0, cats.ids)]})
                if circuit:
                    p.truck_circuit_id = circuit.id
                return p
            ok = mk('Lunes RC', '+5493589330001', may)
            dup = mk('Lunes repetido', '+54 9 358 933-0001', may)
            sur = mk('Lunes Sur-Oeste', '+5493589330002', may, so)
            fuera = mk('Lunes fuera', '+5493589330003', may | fz)
            reciente = mk('Lunes reciente', '+5493589330004', may)
            tpl = env['whatsapp.template'].sudo().search([('status', '=', 'approved')], limit=1)
            env['whatsapp.message'].sudo().create({
                'mobile_number': '+5493589330004', 'wa_account_id': tpl.wa_account_id.id,
                'wa_template_id': tpl.id, 'message_type': 'outbound', 'state': 'sent'})
            got = env['cristal.agent.run']._weekly_broadcast_partners(off)
            assert len(got & (ok | dup)) == 1, "el mismo número tiene que salir una sola vez"
            assert sur not in got, "manda al circuito excluido"
            assert fuera not in got, "manda a Fuera de zona"
            assert reciente not in got, "manda a quien recibió una plantilla hoy"
            return ("solo la oferta marcada · sin texto no se puede marcar · excluye Sur-Oeste, "
                    "Fuera de zona, números repetidos y plantilla en 24 h")
        self._case(results, "33. Envío de los lunes", c_envio_lunes)
