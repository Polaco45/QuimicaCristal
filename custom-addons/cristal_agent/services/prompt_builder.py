# -*- coding: utf-8 -*-
"""
Prompt builder.

Construye el system prompt y el user message iniciales de cada conversación
con Claude. El system prompt incluye:
- El prompt base (Claudio v2)
- Contexto del cliente (si existe)
- Conocimiento relevante de la KB
- Ofertas vigentes aplicables al cliente

El user message incluye:
- Datos técnicos del mensaje entrante (mobile, channel, etc.)
- El texto del cliente
- Instrucciones específicas del disparador
"""
import json
import logging
from datetime import datetime

_logger = logging.getLogger(__name__)


def build_system_prompt(env, partner=None, base_prompt=None):
    """
    Construye el system prompt completo para Claude.

    El system prompt se compone de:
    1. Base prompt (Claudio v2) — la personalidad y reglas
    2. Contexto del cliente actual (si lo hay)
    3. Conocimiento relevante de la KB
    4. Ofertas vigentes aplicables
    5. Datos del momento (fecha, hora, día de la semana)
    6. Reglas duras (CRM, escalación, limitaciones técnicas)
    """
    Config = env['cristal.agent.config'].sudo()
    config = Config.get_active()

    parts = []

    # ─── 1. Base prompt ───
    if base_prompt:
        parts.append(base_prompt)
    else:
        parts.append(config.system_prompt or "")

    # ─── 2. Contexto temporal ───
    now = datetime.now()
    weekdays = ['lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo']
    parts.append(f"\n\n## CONTEXTO TEMPORAL\n"
                 f"- Ahora: {now.strftime('%Y-%m-%d %H:%M')} ({weekdays[now.weekday()]})\n"
                 f"- Horario de atención: lunes a viernes 8:30 - 21:00")

    # ─── 3. Capacidades habilitadas (feature flags) ───
    parts.append(_build_capabilities_status(env, config))

    # ─── 4. Contexto del cliente actual ───
    if partner:
        parts.append(_build_partner_context(env, partner))

    # ─── 5. Conocimiento relevante de la KB ───
    parts.append(_build_knowledge_context(env, partner))

    # ─── 6. Ofertas vigentes ───
    parts.append(_build_offers_context(env, partner))

    # ─── 7. REGLAS DURAS (siempre al final, máxima prioridad) ───
    parts.append(_build_hard_rules())

    return "\n".join(parts)


def _build_capabilities_status(env, config):
    """Reporta al bot qué capacidades están apagadas para que no las intente."""
    disabled = []
    flag_labels = {
        'enable_send_whatsapp': 'mandar WhatsApp texto libre',
        'enable_send_whatsapp_templates': 'mandar templates de WhatsApp',
        'enable_create_leads': 'crear leads en CRM',
        'enable_update_leads': 'actualizar leads',
        'enable_schedule_activities': 'agendar actividades CRM',
        'enable_escalate_to_joaco': 'escalar a Joaco',
        'enable_create_sale_orders': 'crear cotizaciones',
        'enable_generate_quote_pdf': 'generar PDF de cotización',
        'enable_generate_pricelist_pdf': 'generar PDF de Lista Mayorista',
        'enable_confirm_sample': 'confirmar envío de muestras',
        'enable_apply_offers': 'aplicar ofertas vigentes',
        'enable_qualification': 'calificar nuevos mayoristas',
    }
    for flag, label in flag_labels.items():
        if not getattr(config, flag, True):
            disabled.append(f"- ❌ {label} ({flag}=False)")

    if not disabled:
        return ""

    text = "\n\n## ⚠️ CAPACIDADES DESHABILITADAS POR JOACO\n\n"
    text += "Las siguientes capacidades están **APAGADAS**. Si necesitás usar alguna, "
    text += "ESCALÁ a Joaco (no intentes la tool — el sistema la va a bloquear):\n\n"
    text += "\n".join(disabled)
    return text


def _build_hard_rules():
    """Reglas duras que el bot no puede violar — siempre al final del prompt."""
    return """

## ⚠️ REGLAS DURAS (NO NEGOCIABLES)

### 1. CRM — creación obligatoria de leads
Cuando un cliente NUEVO se identifica como Mayorista o Empresa Y te da nombre + algún dato más (productos, ubicación, volumen, email):
- LLAMÁ a `create_partner` si el partner no existe
- LLAMÁ a `create_lead` con los datos que tengas (incluso parciales)
- LLAMÁ a `schedule_activity` para agendar el siguiente seguimiento
NO esperes a tener TODOS los datos para crear el lead. Mejor crear lead parcial y completarlo después con `update_lead`. El lead vive en CRM y se asigna automáticamente al vendedor correcto.

### 2. Adjuntos por WhatsApp
PODÉS adjuntar PDFs por WhatsApp:
- Para mandar una cotización: llamá a `generate_quote_pdf(sale_order_id=X)` → te devuelve attachment_id → pasáselo a `send_whatsapp(..., attachment_ids=[attachment_id])`
- Para mandar lista de precios: llamá a `generate_pricelist_pdf(pricelist_name='Lista Mayorista')` → mismo flujo
NO digas "te lo paso por mail" si podés mandarlo directo por WA. Solo escalás a Joaco si te pide algo que no sea un PDF estándar (catálogo con fotos, listado custom, etc.).

### 3. Observaciones obligatorias
Cuando aprendés algo del cliente (preferencia, dato comercial, episodio destacado), LLAMÁ a `update_observation(partner_id, observation)` antes de terminar la conversación. Sé conciso (1 línea).

### 4. Escalación obligatoria
SIEMPRE escalá a Joaco con `escalate_to_joaco` en estos casos:
- Reclamo o queja
- Audio del cliente (todavía no procesamos audios)
- Cliente cita a Joaco ("Joaco me dijo X")
- Decisión de descuento/plazo fuera de la política estándar
- Cliente nuevo es Empresa (no Mayorista)
- Producto que no manejamos
Si escalás, NO sigas avanzando con el cliente — pausá con `pause_bot(partner_id, duration_hours=2)`.

### 5. Eficiencia de tokens
Lectá UNA vez el historial del canal por conversación. NO llames a `read_message_history` 2 veces seguidas. Si necesitás más datos del cliente, usá `read_partner` UNA vez.

### 6. Cuando NO sepas
Si no entendés qué quiere el cliente o no estás seguro de cómo responder, ESCALÁ a Joaco con un resumen breve. NO inventes. NO digas que tenés un "problema técnico". Sé honesto: "Te paso esto con Joaquín que te resuelve mejor."
"""


def _build_partner_context(env, partner):
    """Sección con contexto del cliente actual."""
    lines = ["\n## CONTEXTO DEL CLIENTE ACTUAL"]
    lines.append(f"- partner_id: {partner.id}")
    lines.append(f"- name: {partner.name or '(sin nombre)'}")
    lines.append(f"- mobile: {partner.mobile or partner.phone or '(sin tel)'}")
    lines.append(f"- email: {partner.email or '(sin email)'}")

    # Etiquetas
    tags = [t.name for t in partner.category_id]
    lines.append(f"- etiquetas: {', '.join(tags) if tags else '(sin etiquetas)'}")

    # Tipo de cliente (helpers)
    if partner.is_mayorista():
        lines.append("- TIPO: MAYORISTA — aplica la estrategia comercial completa")
    elif partner.is_consumidor_final():
        lines.append("- TIPO: CONSUMIDOR FINAL — atención simple, derivá si pide algo concreto")
    elif partner.is_empresa():
        lines.append("- TIPO: EMPRESA — derivá a Joaco, NO avances ciclo comercial")
    else:
        lines.append("- TIPO: SIN ETIQUETA (cliente nuevo) — pregunta si es CF, Mayorista o Empresa")

    # Nivel
    if partner.agent_level and partner.agent_level != 'none':
        lines.append(f"- nivel: {partner.agent_level.upper()}")
        lines.append(f"- volumen mensual promedio: ${partner.agent_monthly_volume_avg:,.0f}")

    # Fase comercial
    if partner.agent_strategy_phase and partner.agent_strategy_phase != 'not_qualified':
        phase_label = dict(partner._fields['agent_strategy_phase'].selection).get(
            partner.agent_strategy_phase, partner.agent_strategy_phase
        )
        lines.append(f"- fase comercial: {phase_label}")

    # Última compra
    if partner.agent_last_purchase_at:
        lines.append(f"- última compra: {partner.agent_last_purchase_at.strftime('%Y-%m-%d')}")
        lines.append(f"- días desde última compra: {partner.agent_days_since_last_purchase}")

    # Observaciones acumuladas
    if partner.agent_observations:
        lines.append(f"\n### Observaciones acumuladas sobre este cliente:\n{partner.agent_observations}")

    return "\n".join(lines)


def _build_knowledge_context(env, partner=None):
    """Sección con conocimiento relevante de la KB.

    Las entries con priority >= 100 (campañas activas, alertas críticas) se
    muestran COMPLETAS en una sección destacada al inicio, sin truncar.
    El resto se trunca a 350 chars para ahorrar tokens.
    """
    Knowledge = env['cristal.agent.knowledge'].sudo()
    level = partner.agent_level if partner and partner.agent_level != 'none' else None
    partner_id = partner.id if partner else None

    entries = Knowledge.search_for_agent(
        category=None,
        partner_id=partner_id,
        level=level,
        limit=15,
    )

    if not entries:
        return ""

    # Separar entries críticas (priority >= 100) del resto
    criticas = [e for e in entries if e.get('priority', 0) >= 100]
    normales = [e for e in entries if e.get('priority', 0) < 100]

    lines = []

    # ─── Bloque CRÍTICO: campañas y alertas, contenido COMPLETO ───
    if criticas:
        lines.append("\n## 🚨 CAMPAÑAS / ALERTAS ACTIVAS — APLICAR OBLIGATORIAMENTE")
        lines.append(
            "⚠️ Lo siguiente tiene prioridad sobre cualquier otra regla. "
            "Cuando aplica, seguilo TEXTUAL — no resumas, no simplifiques, "
            "no omitas partes. Si la entrada incluye una plantilla de "
            "respuesta, usala con todos sus puntos.\n"
        )
        for item in criticas:
            lines.append(f"### {item['name']}")
            lines.append(item['content'])  # Sin truncar
            lines.append("")

    # ─── Bloque NORMAL: knowledge general, contenido truncado ───
    if normales:
        lines.append("\n## CONOCIMIENTO ACTIVO (revisalo antes de responder)")
        by_category = {}
        for e in normales:
            by_category.setdefault(e['category'], []).append(e)

        for category, items in by_category.items():
            lines.append(f"\n### {category}")
            for item in items:
                content = item['content']
                if len(content) > 350:
                    content = content[:350] + "..."
                lines.append(f"- **{item['name']}**: {content}")

    return "\n".join(lines)


def _build_offers_context(env, partner=None):
    """Sección con ofertas vigentes aplicables. Incluye productos exactos
    asociados (campo product_ids) para que el bot NO invente que aplica
    a productos no incluidos."""
    Offer = env['cristal.agent.offer'].sudo()
    level = partner.agent_level if partner and partner.agent_level != 'none' else None

    # Buscar las offer records directamente para tener acceso a product_ids
    from datetime import date
    today = date.today()
    domain = [
        ('active', '=', True),
        '|', ('valid_from', '=', False), ('valid_from', '<=', today),
        '|', ('valid_until', '=', False), ('valid_until', '>=', today),
    ]
    offers = Offer.search(domain, limit=5, order='priority desc, write_date desc')

    if not offers:
        return ""

    lines = ["\n## OFERTAS VIGENTES ACTUALMENTE"]
    lines.append(
        "⚠️ IMPORTANTE: cada oferta tiene productos específicos asociados. "
        "Si el cliente pregunta '¿aplica a todos?' la respuesta es NO, "
        "aplica SOLO a los productos listados. Si quiere otros productos → "
        "precio normal de lista, NO mencionar el descuento de la oferta."
    )
    for o in offers:
        line = f"\n- **{o.name}**"
        if o.offer_type:
            line += f" (tipo: {dict(o._fields['offer_type'].selection).get(o.offer_type, o.offer_type)})"
        if o.description:
            line += f"\n  Descripción literal: \"{o.description}\""
        if o.valid_until:
            line += f"\n  Vigente hasta: {o.valid_until}"
        if o.discount_percent:
            line += f"\n  Descuento: {o.discount_percent}%"

        # Productos asociados (CRÍTICO)
        product_ids_field = None
        for fname in ['product_ids', 'product_tmpl_ids', 'products_ids']:
            if fname in o._fields:
                product_ids_field = fname
                break
        if product_ids_field:
            products = getattr(o, product_ids_field, False)
            if products:
                product_names = [p.display_name if hasattr(p, 'display_name') else p.name for p in products]
                line += f"\n  ✅ APLICA EXCLUSIVAMENTE A: {', '.join(product_names)}"
            else:
                line += f"\n  ⚠️ Sin productos específicos asignados — preguntá a Joaco antes de ofrecerla"

        lines.append(line)

    return "\n".join(lines)


def build_user_message_for_whatsapp(env, wa_message, partner, plain_text):
    """
    Arma el user message para una activación por mensaje WhatsApp entrante.
    """
    Config = env['cristal.agent.config'].sudo()
    config = Config.get_active()

    # Channel id si lo podemos determinar
    channel_id = None
    if wa_message.mail_message_id:
        channel_id = wa_message.mail_message_id.res_id

    # Detectar si el mobile del wa_message coincide con OTRO partner (duplicado).
    # Si hay duplicado, el bot tiene que saberlo para no saludar con el nombre
    # equivocado.
    import re
    mob_clean = re.sub(r'[^\d+]', '', wa_message.mobile_number or '')
    duplicados_info = ""
    if mob_clean and len(mob_clean) >= 10:
        last10 = mob_clean[-10:]
        otros = env['res.partner'].sudo().search([
            ('id', '!=', partner.id),
            '|', ('mobile', 'ilike', last10), ('phone', 'ilike', last10),
        ], limit=3)
        if otros:
            nombres = ", ".join([f"{p.name} (id={p.id})" for p in otros])
            duplicados_info = (
                f"\n⚠️ ATENCIÓN: el mismo número de WhatsApp está cargado en "
                f"otros partners: {nombres}. La persona que escribe puede "
                f"NO ser {partner.name}. Si no estás 100% seguro del nombre, "
                f"saludá con \"¡Hola!\" sin nombre — es preferible al nombre "
                f"equivocado."
            )

    parts = []
    parts.append("MENSAJE WHATSAPP ENTRANTE")
    parts.append("")
    parts.append(f"Datos técnicos del mensaje:")
    parts.append(f"- partner_id del cliente: {partner.id}")
    parts.append(f"- name: {partner.name}")
    parts.append(f"- mobile_number: {wa_message.mobile_number}")
    parts.append(f"- mail_message_id: {wa_message.mail_message_id.id if wa_message.mail_message_id else 'N/A'}")
    parts.append(f"- whatsapp_message_id: {wa_message.id}")
    parts.append(f"- wa_account_id: {wa_message.wa_account_id.id if wa_message.wa_account_id else 'N/A'}")
    if channel_id:
        parts.append(f"- channel_id (discuss.channel): {channel_id}")
    if duplicados_info:
        parts.append(duplicados_info)
    parts.append("")
    parts.append(f"Texto del cliente:")
    parts.append(f'"{plain_text}"')
    parts.append("")
    parts.append("Procedé según las reglas del system prompt. "
                 "Si hay CAMPAÑAS/ALERTAS ACTIVAS arriba, aplicalas SIN omitir partes. "
                 "Respondé al cliente vía send_whatsapp y, cuando termines, "
                 "devolveme un resumen de UNA línea de lo que hiciste.")

    return "\n".join(parts)


def build_user_message_for_cron(env, partner, cron_type, extra_context=None):
    """
    Arma el user message para una activación por cron.
    cron_type: 'cadence_step', 'level_recompute', 'churn_detection', 'recovery_45d', 'ritual', etc.
    """
    parts = [f"DISPARO POR CRON: {cron_type.upper()}"]
    parts.append("")
    parts.append(f"Cliente target: {partner.name} (id={partner.id})")
    if partner.mobile:
        parts.append(f"Mobile: {partner.mobile}")
    parts.append("")
    if extra_context:
        parts.append("Contexto adicional:")
        for k, v in extra_context.items():
            parts.append(f"- {k}: {v}")
        parts.append("")

    instructions = {
        'cadence_step_phase2': "El cliente recibió una muestra hace X días. Mandale el mensaje "
                               "que corresponda según la cadencia de Fase 2 (ver system prompt).",
        'cadence_step_phase3': "El cliente hizo su 1ra compra hace X días. Mandale el mensaje "
                               "que corresponda según la cadencia de Onboarding (Fase 3).",
        'level_change_up': "El cliente subió de nivel. Mandale el mensaje de felicitación con "
                           "los beneficios del nuevo nivel.",
        'level_change_down': "El cliente está por bajar de nivel (mes de gracia). Mandale el "
                             "mensaje de aviso para que pueda mantener el nivel.",
        'churn_alert': "El cliente muestra señales de churn. Evaluá si corresponde "
                       "mandarle un mensaje proactivo de chequeo.",
        'recovery_45d': "El cliente lleva 45+ días sin comprar. Activá el flujo de "
                        "recuperación: mensaje + escalar a Joaco para llamada.",
        'ritual_oro': "Es el ritual mensual de los clientes ORO. Mandales un audio (o texto) "
                      "personalizado.",
    }
    parts.append(instructions.get(cron_type, "Decidí qué hacer según el system prompt."))

    return "\n".join(parts)
