# -*- coding: utf-8 -*-
"""
Criterios de aceptación de la ruta del camión.

Los casos viven en `cristal.agent.route.selftest` (models/agent_route_selftest.py)
para poder correrlos también desde la UI de staging (Ruta del camión → Autotest),
donde no hay shell. Este test solo los ejecuta y exige que pasen todos.

Correr: odoo-bin -d <db> -u cristal_agent --test-tags /cristal_agent:route
"""
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'route')
class TestTruckRoute(TransactionCase):

    def test_route_acceptance(self):
        results = self.env['cristal.agent.route.selftest'].run_selftest()
        self.assertTrue(results, "El autotest no devolvió casos")
        failed = [f"{name}: {detail}" for name, ok, detail in results if not ok]
        self.assertFalse(failed, "Casos fallidos:\n" + "\n".join(failed))
