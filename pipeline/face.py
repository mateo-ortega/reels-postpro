"""Deteccion de cara para decidir posicion del hook.

Solo aplica al hook; los body siempre van abajo (ver subtitles.py).

Logica clave (alignment=1 = bottom-left en ASS):
    text_bottom = PLAY_RES_Y - margin_v
    text_top    = PLAY_RES_Y - margin_v - hook_height

Para que el texto quede DEBAJO de la cara:
    text_top > face_ymax + SAFE_GAP
    => margin_v < PLAY_RES_Y - hook_height - face_ymax - SAFE_GAP

Por lo tanto, margin_v PEQUENO = texto abajo (lejos de la cara).
margin_v GRANDE = texto arriba (mas cerca de la cara). Contraintuitivo.

Cuando no hay deteccion de cara se usa DEFAULT_FACE_YMAX (850px = ~44% del frame)
como estimacion conservadora de un plano cercano talking-head.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

from .subtitles import (
    HOOK_FONTSIZE,
    HOOK_MAX_CHARS_PER_LINE,
    _wrap_hook,
)

PLAY_RES_Y = 1920
PLAY_RES_X = 1080

SAFE_GAP = 80           # padding entre cara y tope del bloque hook

# Line-height de libass con Outfit Black. Empiricamente ~1.45x el fontsize.
LINE_HEIGHT_FACTOR = 1.45
# Padding extra por bordes de linea, espaciado interno y error de estimacion.
HOOK_HEIGHT_PADDING = 80

# Asuncion de face_ymax cuando la deteccion falla (plano cercano conservador).
DEFAULT_FACE_YMAX = 850  # ~44% de 1920px

# Margen inferior minimo para el hook (por encima de la barra de perfil de IG).
MIN_BOTTOM_HOOK = 150

# Confidence minima de deteccion Haar para confiar en el envelope.
MIN_FACE_CONFIDENCE = 0.20


@dataclass
class FaceEnvelope:
    """Envelope vertical de cara durante el rango del hook."""
    face_ymin: int
    face_ymax: int
    confidence: float
    detected: bool


@dataclass
class HookLayout:
    """Layout del hook en el ASS: siempre alignment=1 (bottom-left)."""
    alignment: int   # siempre 1
    margin_v: int


def _fallback_envelope() -> FaceEnvelope:
    return FaceEnvelope(face_ymin=0, face_ymax=0, confidence=0.0, detected=False)


def _sample_timestamps(start: float, end: float, n: int) -> list[float]:
    if end <= start:
        return [max(start, 0.0)]
    if n <= 1:
        return [(start + end) / 2.0]
    step = (end - start) / (n + 1)
    return [start + step * (i + 1) for i in range(n)]


def _extract_frame(video_path: Path, t: float):
    """Extrae 1 frame en el segundo t via ffmpeg pipe. Devuelve ndarray BGR o None."""
    try:
        import cv2          # type: ignore
        import numpy as np  # type: ignore
    except ImportError:
        return None

    cmd = [
        "ffmpeg", "-v", "error",
        "-ss", f"{max(t, 0.0):.3f}",
        "-i", str(video_path),
        "-frames:v", "1",
        "-f", "image2pipe",
        "-vcodec", "png",
        "-",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    if not proc.stdout:
        return None
    buf = np.frombuffer(proc.stdout, dtype=np.uint8)
    frame = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    return frame


def _load_cascade(name: str):
    """Carga un clasificador Haar de OpenCV por nombre de archivo."""
    try:
        import cv2  # type: ignore
        path = cv2.data.haarcascades + name
        c = cv2.CascadeClassifier(path)
        return None if c.empty() else c
    except Exception:
        return None


def detect_hook_envelope(
    video_path: Path,
    hook_start: float,
    hook_end: float,
    *,
    n_samples: int = 12,
) -> FaceEnvelope:
    """Sample N frames del rango del hook y detecta cara con Haar cascades.

    Devuelve el envelope (face_ymin, face_ymax) en pixeles del frame 1080x1920.
    Si la confianza es baja (< MIN_FACE_CONFIDENCE) devuelve detected=False.
    """
    try:
        import cv2  # type: ignore
    except ImportError:
        print("[face] opencv no disponible, usando posicion estimada")
        return _fallback_envelope()

    if not video_path.exists():
        print(f"[face] video no encontrado: {video_path}")
        return _fallback_envelope()

    # Intentar con dos cascadas: default primero, alt2 como fallback.
    cascade = _load_cascade("haarcascade_frontalface_default.xml")
    if cascade is None:
        cascade = _load_cascade("haarcascade_frontalface_alt2.xml")
    if cascade is None:
        print("[face] Haar cascade no disponible, usando posicion estimada")
        return _fallback_envelope()

    timestamps = _sample_timestamps(hook_start, hook_end, n_samples)
    ymins_norm: list[float] = []
    ymaxs_norm: list[float] = []

    for t in timestamps:
        frame = _extract_frame(video_path, t)
        if frame is None:
            continue
        h, w = frame.shape[:2]
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        # Ecualizar histograma mejora la deteccion en iluminacion variable.
        gray = cv2.equalizeHist(gray)
        # scaleFactor=1.05 y minNeighbors=3 dan mayor sensibilidad.
        faces = cascade.detectMultiScale(
            gray,
            scaleFactor=1.05,
            minNeighbors=3,
            minSize=(80, 80),
        )
        if len(faces) == 0:
            # Segunda pasada con parametros mas permisivos.
            faces = cascade.detectMultiScale(
                gray, scaleFactor=1.1, minNeighbors=2, minSize=(50, 50),
            )
        if len(faces) == 0:
            continue
        biggest = max(faces, key=lambda f: f[2] * f[3])
        fx, fy, fw, fh = biggest
        y0 = max(0.0, min(1.0, fy / h))
        y1 = max(0.0, min(1.0, (fy + fh) / h))
        ymins_norm.append(y0)
        ymaxs_norm.append(y1)

    n_detected = len(ymins_norm)
    confidence = n_detected / max(len(timestamps), 1)
    print(f"[face] deteccion: {n_detected}/{len(timestamps)} frames (conf={confidence:.0%})")

    if confidence < MIN_FACE_CONFIDENCE:
        print(f"[face] confianza baja, usando posicion estimada (DEFAULT_FACE_YMAX={DEFAULT_FACE_YMAX})")
        return _fallback_envelope()

    face_ymin = int(round(min(ymins_norm) * PLAY_RES_Y))
    face_ymax = int(round(max(ymaxs_norm) * PLAY_RES_Y))
    print(f"[face] cara detectada: face_ymin={face_ymin} face_ymax={face_ymax}")
    return FaceEnvelope(
        face_ymin=face_ymin,
        face_ymax=face_ymax,
        confidence=confidence,
        detected=True,
    )


def estimate_hook_height(hook_text: str) -> int:
    """Estima la altura en px del bloque hook renderizado por libass.

    Usa LINE_HEIGHT_FACTOR=1.45 (empirico para Outfit Black en libass) mas
    HOOK_HEIGHT_PADDING para absorber error de estimacion y bordes de linea.
    """
    wrapped = _wrap_hook(hook_text, HOOK_MAX_CHARS_PER_LINE)
    n_lines = max(1, wrapped.count("\\N") + 1)
    line_h = int(HOOK_FONTSIZE * LINE_HEIGHT_FACTOR)
    return n_lines * line_h + HOOK_HEIGHT_PADDING


def _margin_v_for_face(hook_h: int, face_ymax_used: int) -> int:
    """Calcula el margin_v que posiciona el hook debajo de face_ymax.

    Con alignment=1:  text_top = PLAY_RES_Y - margin_v - hook_h
    Para text_top > face_ymax + SAFE_GAP:
        margin_v < PLAY_RES_Y - hook_h - face_ymax - SAFE_GAP

    Se usa el valor maximo que aun cumple esa condicion (texto lo mas
    alto posible dentro de la zona "debajo de cara"), con piso en MIN_BOTTOM_HOOK.
    """
    margin_v = PLAY_RES_Y - hook_h - face_ymax_used - SAFE_GAP
    margin_v = max(MIN_BOTTOM_HOOK, margin_v)
    text_top = PLAY_RES_Y - margin_v - hook_h
    if text_top < face_ymax_used + SAFE_GAP:
        print(
            f"[face] WARN: hook no cabe del todo debajo de la cara "
            f"(text_top={text_top}, face_ymax+gap={face_ymax_used + SAFE_GAP}). "
            f"Overlap minimo inevitable para este plano."
        )
    return margin_v


def decide_hook_layout(
    envelope: FaceEnvelope,
    hook_text: str,
    mode: str = "auto",
) -> HookLayout:
    """Calcula el margin_v del hook para que quede debajo de la cara.

    alignment siempre es 1 (bottom-left). margin_v PEQUENO = texto abajo.

    Args:
        envelope: resultado de detect_hook_envelope.
        hook_text: texto del hook (para estimar altura).
        mode: "auto" (usar envelope o estimacion) | "abajo" (DEFAULT_FACE_YMAX fijo).
    """
    hook_h = estimate_hook_height(hook_text)

    if envelope.detected and mode == "auto":
        face_ymax_used = envelope.face_ymax
        print(f"[face] usando face_ymax detectado={face_ymax_used}")
    else:
        face_ymax_used = DEFAULT_FACE_YMAX
        reason = "modo=abajo" if mode == "abajo" else "sin deteccion"
        print(f"[face] usando DEFAULT_FACE_YMAX={face_ymax_used} ({reason})")

    margin_v = _margin_v_for_face(hook_h, face_ymax_used)
    print(f"[face] hook_h={hook_h} margin_v={margin_v} "
          f"text_top={PLAY_RES_Y - margin_v - hook_h}")
    return HookLayout(alignment=1, margin_v=margin_v)


# ---------- Cache en sesion ----------

def save_envelope(envelope: FaceEnvelope, path: Path) -> None:
    path.write_text(
        json.dumps(asdict(envelope), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_envelope(path: Path) -> FaceEnvelope | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return FaceEnvelope(**data)
    except (json.JSONDecodeError, TypeError, KeyError):
        return None
