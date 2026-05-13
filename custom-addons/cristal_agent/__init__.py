# -*- coding: utf-8 -*-
import os
import logging

from . import models
from . import services
from . import controllers

_logger = logging.getLogger(__name__)


# IDs específicos del entorno productivo de Joaco. Se intenta asignarlos al
# instalar; si alguno no existe en la DB destino, se ignora (no es fatal).
DEFAULT_IDENTITIES = {
    'bot_partner_id': 80799,        # Claudio (claudio.quimicacristal)
    'owner_partner_id': 65374,      # Joaquín (Joaco)
    'owner_user_id': 18,            # Joaco como res.users
    'bot_user_id': 721,             # Claudio como res.users
    'internal_channel_id': 969,     # Canal interno Joaco↔Claudio
}

DEFAULT_IDENTITIES_MODELS = {
    'bot_partner_id': 'res.partner',
    'owner_partner_id': 'res.partner',
    'owner_user_id': 'res.users',
    'bot_user_id': 'res.users',
    'internal_channel_id': 'discuss.channel',
}


def post_init_load_prompt(env):
    """
    Hook que se ejecuta UNA VEZ al instalar el módulo. Hace:
    1. Carga el contenido de data/prompts/claudio_v3.md (con fallback a v2) en el campo system_prompt
    2. Asigna las identidades técnicas (bot_partner_id, etc.) SI los IDs existen
       en la DB destino. Si no existen, los deja vacíos (Joaco los configura manual).
    """
    config = env['cristal.agent.config'].sudo().search(
        [('active', '=', True)], limit=1
    )
    if not config:
        config = env['cristal.agent.config'].sudo().create({
            'name': 'Configuración principal',
        })

    # 1. Cargar el prompt completo (v3.1 con fallback a v3, después a v2)
    try:
        module_path = os.path.dirname(os.path.realpath(__file__))
        prompt_path = os.path.join(module_path, 'data', 'prompts', 'claudio_v3_1.md')
        version = 'claudio_v3_1'
        if not os.path.exists(prompt_path):
            prompt_path = os.path.join(module_path, 'data', 'prompts', 'claudio_v3.md')
            version = 'claudio_v3'
        if not os.path.exists(prompt_path):
            prompt_path = os.path.join(module_path, 'data', 'prompts', 'claudio_v2.md')
            version = 'claudio_v2'
        if os.path.exists(prompt_path):
            with open(prompt_path, 'r', encoding='utf-8') as f:
                content = f.read()
            config.write({
                'system_prompt': content,
                'prompt_version': version,
            })
            _logger.info(
                "✅ Prompt %s cargado (%s chars) en config id=%s",
                version, len(content), config.id
            )
        else:
            _logger.warning("post_init: no existe ningún prompt en data/prompts/")
    except Exception as e:
        _logger.exception("Error cargando prompt en post_init: %s", e)

    # 2. Asignar identidades técnicas con validación
    vals = {}
    for field_name, default_id in DEFAULT_IDENTITIES.items():
        model_name = DEFAULT_IDENTITIES_MODELS[field_name]
        try:
            rec = env[model_name].sudo().browse(default_id)
            if rec.exists():
                vals[field_name] = default_id
                _logger.info(
                    "✓ Identidad %s = %s (%s) encontrada y asignada",
                    field_name, default_id, rec.display_name
                )
            else:
                _logger.warning(
                    "⚠ Identidad %s = %s (%s) NO existe en esta DB. "
                    "Configurala manualmente desde Cristal Agent → Configuración.",
                    field_name, default_id, model_name
                )
        except Exception as e:
            _logger.warning("Error validando identidad %s: %s", field_name, e)

    if vals:
        try:
            config.write(vals)
            _logger.info("✅ %s identidades técnicas asignadas automáticamente.", len(vals))
        except Exception as e:
            _logger.exception("Error asignando identidades: %s", e)
