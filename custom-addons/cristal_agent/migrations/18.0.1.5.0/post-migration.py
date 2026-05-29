# -*- coding: utf-8 -*-
"""
Migración a v18.0.1.5.0:
- Carga el prompt Claudio v3.1 (tono refinado + reglas de pago)
- Agrega KB entry sobre formas de pago Mayorista
- Inicializa el mapping de fase→stage CRM buscando stages por nombre típico
- Si encuentra leads con agent_strategy_phase, los sincroniza al stage correcto
"""
import os
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    from odoo import api, SUPERUSER_ID
    env = api.Environment(cr, SUPERUSER_ID, {})

    # 1. Cargar prompt v3.1
    _load_prompt_v3_1(env)

    # 2. Agregar/actualizar KB de formas de pago
    _ensure_payment_kb(env)

    # 3. Inicializar mapping de stages CRM
    _initialize_stage_mapping(env)

    # 4. Resincronizar leads existentes
    _resync_existing_leads(env)


def _load_prompt_v3_1(env):
    try:
        migration_path = os.path.dirname(os.path.realpath(__file__))
        module_path = os.path.dirname(os.path.dirname(migration_path))
        prompt_path = os.path.join(module_path, 'data', 'prompts', 'claudio_v3_1.md')

        if not os.path.exists(prompt_path):
            _logger.warning("MIGRATION 1.5.0: no se encontró claudio_v3_1.md")
            return

        with open(prompt_path, 'r', encoding='utf-8') as f:
            content = f.read()

        config = env['cristal.agent.config'].sudo().search(
            [('active', '=', True)], limit=1
        )
        if config:
            config.write({
                'system_prompt': content,
                'prompt_version': 'claudio_v3_1',
            })
            _logger.info(
                "✅ MIGRATION 1.5.0: prompt actualizado a Claudio v3.1 (%s chars)",
                len(content)
            )
    except Exception as e:
        _logger.exception("MIGRATION 1.5.0 [prompt]: %s", e)


def _ensure_payment_kb(env):
    """Crea o actualiza la entry de KB sobre formas de pago Mayorista."""
    try:
        Knowledge = env['cristal.agent.knowledge'].sudo()
        # Buscar entry existente con el nombre
        existing = Knowledge.search([
            ('name', '=', 'Formas de pago Mayorista'),
        ], limit=1)

        content = (
            "Formas de pago disponibles para Mayoristas (las ÚNICAS, no hay otras):\n"
            "1. Efectivo a contraentrega (al recibir el pedido).\n"
            "2. Transferencia previa a la confirmación del pedido.\n"
            "3. Cheque a 30 días MÁXIMO.\n\n"
            "NUNCA OFRECER CUENTA CORRIENTE. No existe cuenta corriente para Mayoristas "
            "bajo ningún punto de vista, ni 'más adelante', ni 'cuando tengamos historial'. "
            "Si el cliente la pide, explicarle las 3 opciones anteriores."
        )

        if existing:
            existing.write({
                'content': content,
                'priority': 100,
                'active': True,
            })
            _logger.info("✅ MIGRATION 1.5.0: KB 'Formas de pago Mayorista' actualizada")
        else:
            Knowledge.create({
                'name': 'Formas de pago Mayorista',
                'category': 'politica_comercial',
                'content': content,
                'priority': 100,
                'source': 'default',
                'applies_to': 'all',
                'active': True,
            })
            _logger.info("✅ MIGRATION 1.5.0: KB 'Formas de pago Mayorista' creada")

        # Desactivar entries viejas que pudieran tener mención a cuenta corriente
        cc_entries = Knowledge.search([
            ('content', 'ilike', 'cuenta corriente'),
            ('name', '!=', 'Formas de pago Mayorista'),
            ('active', '=', True),
        ])
        if cc_entries:
            _logger.warning(
                "MIGRATION 1.5.0: encontradas %s entries de KB con 'cuenta corriente' — "
                "se desactivan: %s",
                len(cc_entries), cc_entries.mapped('name')
            )
            cc_entries.write({'active': False})
    except Exception as e:
        _logger.exception("MIGRATION 1.5.0 [KB pagos]: %s", e)


def _initialize_stage_mapping(env):
    """Busca stages típicos por nombre y los asigna al mapping de fases."""
    try:
        config = env['cristal.agent.config'].sudo().search(
            [('active', '=', True)], limit=1
        )
        if not config:
            return

        Stage = env['crm.stage'].sudo()

        stage_name_map = {
            'crm_stage_phase_1_id': ['Nuevo', 'New', 'Contactado'],
            'crm_stage_phase_2_sample_id': ['Muestra entregada', 'Muestra'],
            'crm_stage_phase_2_quoted_id': ['Propuesta', 'Cotizacion enviada', 'Cotización enviada'],
            'crm_stage_phase_3_won_id': ['Ganado', 'Won'],
        }

        vals = {}
        for field_name, possible_names in stage_name_map.items():
            current = getattr(config, field_name, False)
            if current:
                continue  # ya configurado
            stage = Stage.search([
                ('name', 'in', possible_names),
            ], limit=1)
            if stage:
                vals[field_name] = stage.id
                _logger.info(
                    "MIGRATION 1.5.0: %s → stage '%s' (id=%s)",
                    field_name, stage.name, stage.id
                )

        if vals:
            config.write(vals)
            _logger.info("✅ MIGRATION 1.5.0: mapping de stages CRM inicializado")
        else:
            _logger.warning(
                "MIGRATION 1.5.0: no encontré stages para mapear. "
                "Configuralos manualmente en Configuración del agente."
            )
    except Exception as e:
        _logger.exception("MIGRATION 1.5.0 [stage mapping]: %s", e)


def _resync_existing_leads(env):
    """Para los leads agent_managed con phase asignada, mueve al stage correcto."""
    try:
        Lead = env['crm.lead'].sudo()
        leads = Lead.search([
            ('agent_managed', '=', True),
            ('active', '=', True),
            ('agent_strategy_phase', '!=', False),
        ])
        if leads:
            leads._sync_agent_phase_to_stage()
            _logger.info(
                "✅ MIGRATION 1.5.0: resincronizados %s leads al stage CRM correspondiente",
                len(leads)
            )
    except Exception as e:
        _logger.exception("MIGRATION 1.5.0 [resync leads]: %s", e)
