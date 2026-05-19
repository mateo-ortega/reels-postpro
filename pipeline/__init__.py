"""Reels Postpro pipeline package.

Modulos:
    audio: extraccion + denoise + loudnorm + mux.
    transcribe: Whisper small ES con word_timestamps.
    subtitles: Cue dataclass, SRT y ASS Sapiens, parsing.
    render: ffmpeg burn final con estilo Sapiens.
    paths: gestion de sesiones y cleanup.
"""
