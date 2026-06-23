# -*- coding: utf-8 -*-
"""
Transcripción de notas de voz (speech-to-text).

La API de Claude NO acepta audio como input (solo texto, imágenes y PDF), así que
las notas de voz de WhatsApp se transcriben primero con un servicio externo y el
TEXTO resultante entra al loop normal de Claudio como si el cliente lo hubiera
escrito.

Proveedor: OpenAI (endpoint /v1/audio/transcriptions, modelo gpt-4o-transcribe).
WhatsApp manda las notas de voz como .ogg/opus, que OpenAI acepta directo (no hay
que transcodificar). La API key se carga en la config del agente (campo
openai_api_key) y se guarda en ir.config_parameter por seguridad.

Si la transcripción falla (sin key, error de red, audio raro), devolvemos None y
el inbound avisa a Joaco para que escuche el audio a mano — nunca rompemos la
recepción del mensaje.
"""
import base64
import logging

_logger = logging.getLogger(__name__)

OPENAI_TRANSCRIBE_URL = "https://api.openai.com/v1/audio/transcriptions"

# Mapa mimetype → extensión, para que OpenAI detecte el formato por el nombre del
# archivo. WhatsApp usa audio/ogg (opus) para las notas de voz.
_EXT_BY_MIME = {
    'audio/ogg': 'ogg',
    'audio/oga': 'oga',
    'audio/opus': 'ogg',
    'audio/mpeg': 'mp3',
    'audio/mp3': 'mp3',
    'audio/mp4': 'mp4',
    'audio/m4a': 'm4a',
    'audio/x-m4a': 'm4a',
    'audio/wav': 'wav',
    'audio/x-wav': 'wav',
    'audio/webm': 'webm',
    'audio/flac': 'flac',
}

# Límite duro de OpenAI: 25 MB por archivo. Una nota de voz típica pesa unos
# pocos KB/MB, así que esto es un guardarraíl, no una restricción real.
_MAX_BYTES = 25 * 1024 * 1024


def transcribe_audio_attachment(attachment, api_key, model='gpt-4o-transcribe',
                                language='es', timeout=60):
    """
    Transcribe un ir.attachment de audio. Devuelve el texto (str) o None si falla.

    :param attachment: ir.attachment de audio (con .datas en base64).
    :param api_key: API key de OpenAI.
    :param model: modelo de transcripción (gpt-4o-transcribe / whisper-1).
    :param language: código ISO del idioma esperado ('es'). Mejora precisión y
                     baja latencia. Vacío = autodetección.
    :param timeout: timeout HTTP en segundos.
    """
    if not attachment or not api_key:
        return None

    try:
        import requests
    except ImportError:
        _logger.warning("Transcripción: falta el paquete 'requests'.")
        return None

    if not attachment.datas:
        _logger.warning("Transcripción: el attachment %s no tiene datos.", attachment.id)
        return None

    try:
        raw = base64.b64decode(attachment.datas)
    except Exception as e:
        _logger.warning("Transcripción: no se pudo decodificar el audio %s: %s",
                        attachment.id, e)
        return None

    if not raw:
        return None
    if len(raw) > _MAX_BYTES:
        _logger.warning("Transcripción: audio %s > 25MB (%s bytes), no se envía.",
                        attachment.id, len(raw))
        return None

    mimetype = (attachment.mimetype or 'audio/ogg').split(';')[0].strip().lower()
    ext = _EXT_BY_MIME.get(mimetype, 'ogg')
    filename = "voice.%s" % ext

    files = {'file': (filename, raw, mimetype or 'audio/ogg')}
    data = {'model': model or 'gpt-4o-transcribe'}
    if language:
        data['language'] = language
    headers = {'Authorization': 'Bearer %s' % api_key}

    try:
        resp = requests.post(
            OPENAI_TRANSCRIBE_URL,
            headers=headers,
            files=files,
            data=data,
            timeout=timeout,
        )
    except requests.RequestException as e:
        _logger.warning("Transcripción: error de red contra OpenAI: %s", e)
        return None

    if resp.status_code != 200:
        _logger.warning("Transcripción: OpenAI respondió %s: %s",
                        resp.status_code, (resp.text or '')[:300])
        return None

    try:
        text = ((resp.json() or {}).get('text') or '').strip()
    except ValueError:
        _logger.warning("Transcripción: respuesta de OpenAI no es JSON válido.")
        return None

    if not text:
        return None

    _logger.info("🎙️ Audio %s transcripto (%s chars).", attachment.id, len(text))
    return text
