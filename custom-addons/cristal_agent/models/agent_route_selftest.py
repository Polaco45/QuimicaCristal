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
        for circ, d in ((so, date(2026, 10, 15)), (este, date(2026, 10, 29))):
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

        next_thu = date.today() + timedelta(days=14)
        while next_thu.weekday() != 3:
            next_thu += timedelta(days=1)

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
            assert d and d.date == date(2026, 10, 15), f"Sampacho: {d.date if d else None}"
            cl = d.get_cutoff_local()
            assert (cl.date(), cl.hour, cl.minute) == (date(2026, 10, 13), 18, 0), (
                f"Cierre Sampacho: {cl}")
            d2 = este.get_next_departure(ref)
            assert d2 and d2.date == date(2026, 10, 29), f"Ucacha: {d2.date if d2 else None}"
            p = mk_partner('InfoSampacho', 'Sampacho')
            gi = gri.execute(env=env, run=None, partner_id=p.id)
            assert gi.get('zone') == 'ruta_camion' and gi.get('circuit') == 'Sur-Oeste', gi
            return "Sampacho → jue 15/10 (cierre mar 13/10 18 h); Ucacha → jue 29/10"
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
            assert local_commit.weekday() == 3, "la entrega no cae jueves"
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
            return "$60k no crea; $80k borrador + flete $9.000 + jueves + etiqueta + escalado; $120k sin flete"
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

        # 5) Zona horaria: martes 17:59 entra, 18:01 pasa a la siguiente
        def c_timezone():
            tc = Circuit.create({'name': 'ZZ Autotest TZ', 'sequence': 99,
                                 'first_departure_date': next_thu})
            d1 = Dep.create({'circuit_id': tc.id, 'date': next_thu})
            d2 = Dep.create({'circuit_id': tc.id, 'date': next_thu + timedelta(days=28)})
            cl = d1.get_cutoff_local()
            assert (cl.weekday(), cl.hour, cl.minute) == (1, 18, 0), f"cierre local {cl}"
            cut = d1.get_preventa_cutoff()
            got1 = tc.get_next_departure(cut - timedelta(minutes=1))
            got2 = tc.get_next_departure(cut + timedelta(minutes=1))
            assert got1 == d1, f"17:59 → {got1.date if got1 else None}"
            assert got2 == d2, f"18:01 → {got2.date if got2 else None}"
            return f"cierre mar {cl.strftime('%d/%m')} 18:00 (Córdoba); 17:59 entra, 18:01 pasa"
        self._case(results, "5. Cierre de preventa y zona horaria", c_timezone)

        # 6) Rescate (Plan B)
        def c_rescate():
            rc_c = Circuit.create({'name': 'ZZ Autotest Rescate', 'sequence': 98,
                                   'first_departure_date': next_thu})
            courtesy = env['product.product'].sudo().create(
                {'name': 'ZZ Autotest Cortesía', 'type': 'consu', 'sale_ok': True})
            dep = Dep.create({'circuit_id': rc_c.id, 'date': next_thu, 'state': 'rescate',
                              'courtesy_product_id': courtesy.id})
            cl = dep.get_cutoff_local()
            assert (cl.weekday(), cl.hour) == (2, 12), f"cierre rescate {cl}"
            p = mk_partner('Rescate', 'ZZ Pueblo', circuit=rc_c)
            r = quote(p, 80000)
            order = SaleOrder.browse(r['order_id'])
            assert r.get('ok') and not freight_lines(order), "rescate $80k: sin flete"
            assert r.get('courtesy_product'), "no ofrece cortesía"
            gi = gri.execute(env=env, run=None, partner_id=p.id)
            assert gi.get('free_shipping_from') == 75000 and gi.get('rescate'), gi
            return "$80k sin flete (umbral $75.000), ofrece cortesía, cierre mié 12 h"
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

        # 8) Río Cuarto nunca jueves
        def c_rio_cuarto():
            p = mk_partner('RC', 'Rio Cuarto')
            gi = gri.execute(env=env, run=None, partner_id=p.id)
            assert gi.get('zone') == 'rio_cuarto' and 'departure_date' not in gi, gi
            assert 'JUEVES' in gi.get('message_for_bot', ''), gi
            r = quote(p, 80000)
            order = SaleOrder.browse(r['order_id'])
            assert r.get('ok') and not r.get('route'), r
            assert 'jueves' in (r.get('route_note') or '').lower(), r.get('route_note')
            assert not order.commitment_date and not order.route_departure_id, (
                "a Río Cuarto no se le asigna salida de jueves")
            return "sin salida de ruta y aviso de NO jueves"
        self._case(results, "8. Río Cuarto nunca jueves", c_rio_cuarto)

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
