# -*- coding: utf-8 -*-
"""
Tools del agente Claudio.

Cada archivo en este directorio define una tool que el agente puede llamar.
Al importarse, cada tool se registra automáticamente en el ToolRegistry
mediante el decorador @ToolRegistry.register.

Categorías de tools:
- Mensajería: send_whatsapp, escalate_to_joaco, view_attachment
- Partners: search_partners, read_partner, create_partner, update_partner,
            update_observation
- CRM: create_lead, update_lead, schedule_activity, mark_activity_done
- Conocimiento: search_knowledge, add_knowledge, search_offers
- Productos / Stock: search_products, check_stock
- Órdenes / Facturas: search_orders, search_invoices
- PDFs: generate_quote_pdf, generate_pricelist_pdf
- Niveles: compute_partner_level, set_partner_level
- Operativos: pause_bot, read_message_history
"""
# Importamos cada tool para que se registre. El orden no importa pero ayuda
# a tenerlo agrupado por categoría para encontrar archivos rápido.

# Base
from . import base

# Mensajería
from . import send_whatsapp
from . import send_whatsapp_template
from . import escalate_to_joaco
from . import view_attachment
from . import read_message_history

# Partners
from . import search_partners
from . import read_partner
from . import create_partner
from . import update_partner
from . import update_observation

# CRM
from . import create_lead
from . import update_lead
from . import schedule_activity
from . import mark_activity_done
from . import confirm_sample_sent
from . import create_sale_order

# Conocimiento y ofertas
from . import search_knowledge
from . import add_knowledge
from . import search_offers

# Productos
from . import search_products
from . import check_stock

# Órdenes y facturas
from . import search_orders
from . import search_invoices

# PDFs
from . import generate_quote_pdf
from . import generate_pricelist_pdf

# Niveles
from . import compute_partner_level
from . import set_partner_level

# Operativos
from . import pause_bot
