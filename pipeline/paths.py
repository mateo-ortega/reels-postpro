"""Gestion de sesiones de trabajo y cleanup."""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKSPACE = ROOT / "workspace"
SESSIONS = WORKSPACE / "sessions"
ASSETS_FONTS = ROOT / "assets" / "fonts"


def new_session() -> Path:
    """Crea workspace/sessions/<uuid8>/ y la devuelve."""
    SESSIONS.mkdir(parents=True, exist_ok=True)
    sid = uuid.uuid4().hex[:8]
    sdir = SESSIONS / sid
    sdir.mkdir(parents=True, exist_ok=False)
    return sdir


def cleanup_session(session_dir: Path, *, keep_final: bool = True) -> None:
    """Borra wavs intermedios. Conserva original/final/srt/ass si keep_final."""
    if not session_dir.exists():
        return
    if not keep_final:
        shutil.rmtree(session_dir, ignore_errors=True)
        return
    for f in session_dir.iterdir():
        if f.suffix == ".wav":
            f.unlink(missing_ok=True)


def font_dir() -> Path:
    """Devuelve la ruta absoluta a assets/fonts/."""
    return ASSETS_FONTS
