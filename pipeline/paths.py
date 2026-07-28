"""Gestion de sesiones de trabajo y cleanup."""

from __future__ import annotations

import shutil
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKSPACE = ROOT / "workspace"
SESSIONS = WORKSPACE / "sessions"
ASSETS_FONTS = ROOT / "assets" / "fonts"

_INTERMEDIATES = {
    "01_raw_hp.wav",
    "02_denoised.wav",
    "03_normalized.wav",
    "video_clean.mp4",
    "whisper_result.json",
    "face_envelope.json",
}


def new_session() -> Path:
    """Crea workspace/sessions/<uuid8>/ y la devuelve."""
    SESSIONS.mkdir(parents=True, exist_ok=True)
    sid = uuid.uuid4().hex[:8]
    sdir = SESSIONS / sid
    sdir.mkdir(parents=True, exist_ok=False)
    return sdir


def cleanup_after_render(session_dir: Path) -> None:
    """Borra intermedios pesados tras render exitoso; conserva final.mp4 y subtitulos."""
    if not session_dir.exists():
        return
    for f in session_dir.iterdir():
        if f.name in _INTERMEDIATES or (f.suffix == ".wav"):
            f.unlink(missing_ok=True)
        elif f.stem.startswith("original"):
            f.unlink(missing_ok=True)


def purge_old_sessions(max_age_hours: float = 24.0) -> int:
    """Elimina sesiones mas viejas que max_age_hours. Devuelve cuantas se borraron."""
    if not SESSIONS.exists():
        return 0
    cutoff = time.time() - max_age_hours * 3600
    removed = 0
    for sdir in SESSIONS.iterdir():
        if sdir.is_dir() and sdir.stat().st_mtime < cutoff:
            shutil.rmtree(sdir, ignore_errors=True)
            removed += 1
    return removed


def font_dir() -> Path:
    """Devuelve la ruta absoluta a assets/fonts/."""
    return ASSETS_FONTS
