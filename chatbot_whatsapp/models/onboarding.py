from odoo import models, api
import re
import logging
from ..utils.utils import is_cotizado
from ..config.config import messages_config

_logger = logging.getLogger(__name__)

ONBOARDING_FLOWS = [
    'esperando_nombre_nuevo_cliente',
    'esperando_email_nuevo_cliente',
    'esperando_tipo_cliente',
]

class WhatsAppOnboardingHandler(models.AbstractModel):
    _name = 'chatbot.whatsapp.onboarding_handler'
    _description = "Onboarding progresivo y forzado de cliente por WhatsApp"

    def _is_valid_email(self, email):
        """Valida si un string tiene formato de email."""
        pattern = r"^[\w\.-]+@[\w\.-]+\.\w+$"
        return re.match(pattern, email)

    def _parse_cliente_tag(self, texto_usuario):
        """
        --- CORREGIDO ---
        Convierte la respuesta del usuario al nombre corto de la etiqueta.
        """
        OPCIONES = {
            '1': "Consumidor Final", 'consumidor final': "Consumidor Final",
            '2': "EMPRESA", 'institucion': "EMPRESA", 'empresa': "EMPRESA",
            '3': "Mayorista", 'mayorista': "Mayorista",
        }
        return OPCIONES.get(texto_usuario.strip().lower())

    def _check_missing_data(self, partner):
        """Verifica los datos faltantes en el partner. Devuelve una lista."""
        missing = []
        if not partner or not partner.name or 'WhatsApp:' in partner.name:
            missing.append('nombre')
        if not partner or not partner.email:
            missing.append('email')
        # Buscamos si tiene alguna etiqueta hija de "Tipo de Cliente"
        customer_type_parent = self.env.ref('__export__.res_partner_category_10', raise_if_not_found=False) or \
                               self.env['res.partner.category'].sudo().search([('name', '=', 'Tipo de Cliente')], limit=1)
        if not partner or not any(cat.parent_id == customer_type_parent for cat in partner.category_id):
            missing.append('tag')
        return missing

    @api.model
    def process_onboarding_flow(self, env, record, partner, plain_body, memory_model):
        if not partner:
            _logger.warning("El flujo de onboarding fue llamado sin un partner válido.")
            return False, ""

        memory = memory_model.search([('partner_id', '=', partner.id)], limit=1)
        if not memory:
            memory = memory_model.create({'partner_id': partner.id})
            
        current_flow = memory.flow_state

        is_new_contact = 'WhatsApp:' in (partner.name or '')
        if not is_new_contact and not current_flow:
            _logger.info(f"👍 Partner '{partner.name}' es un contacto existente. Omitiendo validación de onboarding.")
            return False, "" 

        if current_flow in ONBOARDING_FLOWS:
            if current_flow == 'esperando_nombre_nuevo_cliente':
                partner.write({'name': plain_body.strip()})
            
            elif current_flow == 'esperando_email_nuevo_cliente':
                if not self._is_valid_email(plain_body.strip()):
                    return True, "Ese correo no parece válido 🤔. ¿Podrías escribirlo de nuevo?"
                partner.write({'email': plain_body.strip()})
            
            elif current_flow == 'esperando_tipo_cliente':
                tag_name = self._parse_cliente_tag(plain_body)
                if not tag_name:
                    return True, "Opción no válida. Por favor, responde con 1, 2 o 3."
                
                # --- LÓGICA CORREGIDA PARA BUSCAR/CREAR ETIQUETAS ---
                
                # 1. Define el nombre de la categoría padre
                parent_category_name = "Tipo de Cliente"
                
                # 2. Busca la categoría padre o la crea si no existe
                parent_category = env['res.partner.category'].sudo().search(
                    [('name', '=', parent_category_name), ('parent_id', '=', False)], limit=1)
                if not parent_category:
                    parent_category = env['res.partner.category'].sudo().create({'name': parent_category_name})

                # 3. Busca la etiqueta hija específica dentro de la categoría padre
                tag = env['res.partner.category'].sudo().search(
                    [('name', '=', tag_name), ('parent_id', '=', parent_category.id)], limit=1)
                
                # 4. Si no existe, la crea como hija de la categoría padre
                if not tag:
                    tag = env['res.partner.category'].sudo().create({
                        'name': tag_name,
                        'parent_id': parent_category.id
                    })

                # 5. Prepara la lista de etiquetas finales para el partner
                #    Esto asegura que no tenga múltiples "Tipos de Cliente" y no borra otras etiquetas.
                all_customer_type_tags = env['res.partner.category'].sudo().search([('parent_id', '=', parent_category.id)])
                other_tags = partner.category_id.filtered(lambda r: r.id not in all_customer_type_tags.ids)
                
                final_tags = other_tags + tag
                partner.write({'category_id': [(6, 0, final_tags.ids)]})
                
                # --- FIN DE LA LÓGICA CORREGIDA ---
                
                if "Consumidor Final" not in tag_name:
                    self._create_crm_lead(env, partner)
            
            memory.write({'flow_state': False})
            current_flow = False # Reseteamos para que se re-evalúe si falta otro dato

        missing_data = self._check_missing_data(partner)
        
        if missing_data:
            next_step = missing_data[0]
            if next_step == 'nombre':
                memory.write({'flow_state': 'esperando_nombre_nuevo_cliente'})
                return True, "¡Hola! Para poder ayudarte, ¿me decís tu *nombre* completo?"
            elif next_step == 'email':
                memory.write({'flow_state': 'esperando_email_nuevo_cliente'})
                return True, f"Gracias, {partner.name.split()[0]} 😊. ¿Cuál es tu *correo electrónico*?"
            elif next_step == 'tag':
                memory.write({'flow_state': 'esperando_tipo_cliente'})
                return True, (
                    "¡Genial! Una última pregunta 😊\n"
                    "¿Qué tipo de cliente sos?\n"
                    "1 - Consumidor final\n"
                    "2 - Institución / Empresa\n"
                    "3 - Mayorista"
                )
        
        if not missing_data and memory.id and memory.read(['flow_state'])[0]['flow_state'] in ONBOARDING_FLOWS:
            memory.unlink()
            return True, "¡Ahora sí, gracias! Ya tenemos todos tus datos. ¿En qué te puedo ayudar?"

        return False, ""

    def _create_crm_lead(self, env, partner):
        """Crea una oportunidad (lead) en el CRM para el partner."""
        if env['crm.lead'].sudo().search_count([('partner_id', '=', partner.id)]):
            _logger.info(f"El partner '{partner.name}' ya tiene una oportunidad en el CRM.")
            return

        lead_vals = {
            'name': f"Nuevo cliente WhatsApp: {partner.name}", 'partner_id': partner.id,
            'contact_name': partner.name, 'email_from': partner.email, 'phone': partner.phone,
        }
        if partner.category_id:
            tag_name = partner.category_id[0].name
            crm_tag = env['crm.tag'].sudo().search([('name', '=', tag_name)], limit=1) or \
                      env['crm.tag'].sudo().create({'name': tag_name})
            lead_vals['tag_ids'] = [(6, 0, [crm_tag.id])]

        lead = env['crm.lead'].sudo().create(lead_vals)
        
        activity_type = env['mail.activity.type'].sudo().search([('name', 'ilike', 'Iniciativa de Venta')], limit=1)
        if activity_type:
            env['mail.activity'].sudo().create({
                'res_model_id': env.ref('crm.model_crm_lead').id, 'res_id': lead.id,
                'activity_type_id': activity_type.id, 'summary': 'Seguimiento nuevo contacto WhatsApp',
                'note': f'Contactar al cliente {partner.name} para cotizarlo.',
                'user_id': partner.user_id.id or env.user.id,
            })

        _logger.info(f"✨ Creada oportunidad '{lead.name}' para el partner '{partner.name}'.")
