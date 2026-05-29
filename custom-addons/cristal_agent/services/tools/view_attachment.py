# -*- coding: utf-8 -*-
"""
Tool: view_attachment

Lee un attachment (imagen) de Odoo y lo devuelve en formato base64 para que
Claude lo pueda analizar visualmente. Útil para:
- Foto de producto que mandó el cliente (identificar qué es)
- Comprobante de pago/transferencia (recibido, escalar)
- Captura de pantalla (entender qué pidió)

Solo soporta imágenes (PNG, JPG). Para PDFs el cliente no debería mandarlos por
WA en general; si llega uno, escalá a Joaco.
"""
import base64
import logging
from .base import AgentTool
from ..tool_registry import ToolRegistry

_logger = logging.getLogger(__name__)

SUPPORTED_IMAGE_MIMES = {
    'image/png', 'image/jpeg', 'image/jpg', 'image/webp', 'image/gif',
}


@ToolRegistry.register
class ViewAttachment(AgentTool):
    name = "view_attachment"
    description = (
        "Lee un attachment (imagen) que mandó el cliente. Te devuelve los bytes en base64 "
        "para que la próxima vez que me hables de la imagen yo te puedo describir lo que vés. "
        "(En la versión actual del agente, devolvemos los bytes y un summary; el análisis "
        "visual viene en V2). "
        "Si el attachment es PDF u otro formato no-imagen, escalá a Joaco."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "attachment_id": {
                "type": "integer",
                "description": "ID del ir.attachment a leer.",
            },
        },
        "required": ["attachment_id"],
    }

    def _execute(self, env, run=None, attachment_id=None, **kwargs):
        if not attachment_id:
            return {"error": "attachment_id es obligatorio"}

        att = env['ir.attachment'].sudo().browse(int(attachment_id))
        if not att.exists():
            return {"error": f"Attachment id={attachment_id} no existe"}

        mimetype = att.mimetype or ''
        is_image = mimetype.startswith('image/')

        result = {
            "ok": True,
            "attachment_id": att.id,
            "name": att.name or '',
            "mimetype": mimetype,
            "is_image": is_image,
            "file_size_bytes": att.file_size or 0,
        }

        if is_image and mimetype in SUPPORTED_IMAGE_MIMES:
            try:
                # En Odoo, datos del attachment están en .datas (ya base64)
                # o se pueden obtener con .raw para los bytes crudos
                if att.datas:
                    # datas ya viene base64
                    raw = base64.b64decode(att.datas)
                    # Limitar tamaño (max 5MB para no explotar el contexto)
                    if len(raw) > 5 * 1024 * 1024:
                        result['warning'] = "Imagen >5MB, no la devolvemos completa"
                        result['summary'] = (
                            "Imagen demasiado grande. Si necesitás verla, escalá a Joaco."
                        )
                    else:
                        result['data_base64'] = att.datas if isinstance(att.datas, str) else att.datas.decode()
                        result['summary'] = (
                            f"Imagen leída ({len(raw)} bytes, {mimetype}). "
                            f"Para análisis visual completo se requiere V2 del agente con visión."
                        )
                else:
                    result['warning'] = "El attachment no tiene datos"
            except Exception as e:
                _logger.exception("Error leyendo attachment: %s", e)
                result['error'] = f"Error leyendo attachment: {e}"
        else:
            result['summary'] = (
                f"Attachment no es imagen soportada (mimetype={mimetype}). "
                f"Si es importante (comprobante, audio, PDF), escalá a Joaco."
            )

        return result
