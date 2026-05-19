"""Transcripcion con OpenAI Whisper (modelo small, espanol, word_timestamps)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

_MODEL_CACHE: dict[str, Any] = {}


def _get_model(name: str = "small"):
    """Singleton del modelo Whisper (carga ~1GB para 'small')."""
    if name not in _MODEL_CACHE:
        import whisper  # import lazy: torch tarda en cargar
        _MODEL_CACHE[name] = whisper.load_model(name, device="cpu")
    return _MODEL_CACHE[name]


def whisper_transcribe(
    media_in: Path,
    *,
    model_name: str = "small",
    language: str = "es",
) -> dict:
    """Transcribe con word_timestamps=True. Devuelve el dict crudo de Whisper.

    Estructura: {"text": str, "segments": [{"start","end","text","words":[...]}]}
    Cada word tiene: {"word", "start", "end", "probability"}.
    """
    model = _get_model(model_name)
    result = model.transcribe(
        str(media_in),
        language=language,
        word_timestamps=True,
        fp16=False,           # CPU no soporta fp16
        verbose=False,
        condition_on_previous_text=False,  # menos drift en clips cortos
    )
    return result
