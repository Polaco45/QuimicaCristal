# -*- coding: utf-8 -*-
"""
Tool: update_qualification_data

v1.9.1 — Para el flow INSTITUCIONAL. Permite al bot guardar progreso
transitorio de la calificación en `cristal.agent.memory.qualification_data`
sin tocar todavía res.partner ni crm.lead. Los datos definitivos se vuelcan
al cerrar la calificación vía complete_institutional_qualification.

El bot llama esta tool DESPUÉS de cada respuesta del cliente para acumular
lo recolectado. Es un merge: los campos no incluidos en el call NO se
sobrescriben.

Campos esperados en `data` (todos opcionales):
- contact_name: string
- company_name: string
- rubro_label: string (etiqueta interpretada, ej: "Gastronomía")
- rubro_partner_category_id: int (ID de res.partner.category)
- necesita_factura: bool
- fiscal_name: string
- vat: string (CUIT)
- rol: string
- street: string
- city: string ("Río Cuarto" o "Las Higueras")
- disponibilidad: string
- notas_extra: string (cosas que el cliente comentó fuera del flow)
"""
import logging
from .base import AgentTool
from ..tool_registry import ToolRegistry

_logger = logging.getLogger(__name__)


@ToolRegistry.register
class UpdateQualificationData(AgentTool):
    name = "update_qualification_data"
    description = (
        "Guarda progreso transitorio de la calificación institucional en la "
        "memoria del cliente. Es un MERGE — los campos no incluidos en data "
        "NO se sobrescriben. Llamala después de cada respuesta del cliente "
        "para acumular lo recolectado (contact_name, company_name, "
        "rubro_label, rubro_partner_category_id, necesita_factura, fiscal_name, "
        "vat, rol, street, city, disponibilidad, notas_extra). "
        "Los datos NO van a res.partner ni a crm.lead todavía — eso lo hace "
        "complete_institutional_qualification al final."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "partner_id": {
                "type": "integer",
                "description": "ID del partner cliente.",
            },
            "data": {
                "type": "object",
                "description": (
                    "Diccionario con los campos a actualizar. Solo los "
                    "incluidos se modifican. Ejemplo: "
                    "{'contact_name': 'Marisa', 'company_name': 'Los Olivos', "
                    "'rubro_label': 'Gastronomía', 'rubro_partner_category_id': 15}"
                ),
            },
        },
        "required": ["partner_id", "data"],
    }

    def _execute(self, env, partner_id, data, **kwargs):
        if not partner_id:
            return {"ok": False, "error": "partner_id requerido"}
        if not isinstance(data, dict) or not data:
            return {"ok": False, "error": "data debe ser un dict no vacío"}

        partner = env['res.partner'].sudo().browse(partner_id)
        if not partner.exists():
            return {"ok": False, "error": f"Partner {partner_id} no existe"}

        memory = env['cristal.agent.memory'].sudo().get_or_create(partner)
        if not memory:
            return {"ok": False, "error": "No se pudo crear/obtener memoria"}

        # Merge con datos previos
        current = dict(memory.qualification_data or {})
        current.update(data)

        memory.write({
            'qualification_data': current,
            # Si el flow_state está en idle o detecting_type, marcamos que
            # estamos en pleno flow institucional
            'client_type': 'institucional' if memory.client_type in (False, 'unknown') else memory.client_type,
        })

        _logger.info(
            "💾 qualification_data actualizado para %s — fields: %s",
            partner.name, list(data.keys())
        )

        return {
            "ok": True,
            "partner_id": partner_id,
            "fields_updated": list(data.keys()),
            "qualification_data_full": current,
            "message": (
                f"Datos guardados en memoria. Campos en buffer: "
                f"{list(current.keys())}"
            ),
        }
