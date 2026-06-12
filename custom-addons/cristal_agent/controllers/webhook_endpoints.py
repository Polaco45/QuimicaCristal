# -*- coding: utf-8 -*-
"""
Endpoints HTTP del agente.

Estos endpoints permiten:
1. /cristal_agent/test_simulate: simular una conversación con el bot sin mandar
   nada por WhatsApp. Útil para test/debug. Solo administradores.

2. /cristal_agent/manual_trigger: disparar el agente para un partner específico
   con un mensaje custom. Útil para QA.

3. /cristal_agent/health: endpoint público de health check.
"""
import json
import logging
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class CristalAgentController(http.Controller):

    @http.route('/cristal_agent/health', type='http', auth='public', methods=['GET'], csrf=False)
    def health(self):
        """Health check público."""
        try:
            config = request.env['cristal.agent.config'].sudo().get_active()
            data = {
                'status': 'ok',
                'enabled': config.enabled,
                'model': config.anthropic_model,
                'prompt_version': config.prompt_version,
                'runs_today': config.runs_today,
            }
            return request.make_response(
                json.dumps(data),
                headers=[('Content-Type', 'application/json')],
            )
        except Exception as e:
            return request.make_response(
                json.dumps({'status': 'error', 'message': str(e)}),
                headers=[('Content-Type', 'application/json')],
                status=500,
            )

    @http.route('/cristal_agent/test_simulate', type='json', auth='user', methods=['POST'], csrf=False)
    def test_simulate(self, **post):
        """
        Simula una conversación con el bot sin mandar nada por WhatsApp.
        Solo para administradores.

        Body JSON: {"partner_id": 65374, "message": "Hola, quiero precios"}
        """
        if not request.env.user.has_group('base.group_system'):
            return {'error': 'Solo administradores pueden simular conversaciones'}

        partner_id = post.get('partner_id')
        message = post.get('message')
        if not (partner_id and message):
            return {'error': 'partner_id y message son obligatorios'}

        partner = request.env['res.partner'].sudo().browse(int(partner_id))
        if not partner.exists():
            return {'error': f'partner_id={partner_id} no existe'}

        # Crear un run sintético con trigger 'manual'
        from ..services.claude_client import ClaudeClient
        from ..services.prompt_builder import build_system_prompt

        Run = request.env['cristal.agent.run'].sudo()
        run = Run.create({
            'trigger': 'manual',
            'partner_id': partner.id,
            'incoming_text': message,
            'state': 'running',
        })

        try:
            stable_system, dynamic_system = build_system_prompt(request.env, partner=partner)
            client = ClaudeClient(request.env, run=run)
            result = client.run_conversation(
                stable_system=stable_system,
                dynamic_system=dynamic_system,
                user_message=f"SIMULACIÓN INTERACTIVA — partner_id={partner.id}\n\nCliente dice: \"{message}\"",
            )
            run.mark_done(final_response=result.get('final_text', ''))
            return {
                'ok': True,
                'run_id': run.id,
                'final_text': result.get('final_text', ''),
                'iterations': result.get('iterations', 0),
                'tool_calls': result.get('tool_calls', 0),
                'cost_usd': run.cost_usd,
            }
        except Exception as e:
            _logger.exception("Error en test_simulate: %s", e)
            run.mark_error(str(e))
            return {'ok': False, 'error': str(e)}
