"""Construccion de subtitulos: Cue dataclass, SRT y ASS estilo Sapiens.

La fuente de verdad es la lista de Cue en memoria (persistida como cues.json
en la sesion). El SRT es un export legible/editable; el ASS se regenera siempre
antes de renderizar y nunca se edita a mano (tiene los estilos hook/body).
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

# Paleta Sapiens (ver Sapiens_Brand_Kit/tokens/sapiens_tokens_light.json).
# ASS espera color en formato &H00BBGGRR (BGR invertido, no RGB).
SAPIENS_GOLD_HEX = "E8A838"
SAPIENS_TEAL_HEX = "2B9E8F"
SAPIENS_WHITE_HEX = "FFFFFF"
SAPIENS_BLACK_HEX = "000000"

# Estilo Quote-Card Sapiens para Reels 1080x1920.
HOOK_FONT = "Outfit Black"      # display font (Outfit-Black.ttf en %LOCALAPPDATA%)
BODY_FONT = "Outfit Black"
HOOK_FONTSIZE = 90
BODY_FONTSIZE = 72
HOOK_OUTLINE = 0
BODY_OUTLINE = 0
HOOK_SHADOW = 2
BODY_SHADOW = 2
HOOK_SPACING = -1               # tracking apretado para CAPS Outfit Black
SAFE_MARGIN_V = 420
SAFE_MARGIN_LR = 75
HOOK_MAX_CHARS_PER_LINE = 18    # ~18 chars max a 90pt Outfit Black, left-aligned

QUOTE_CHAR = "“"           # " LEFT DOUBLE QUOTATION MARK
QUOTE_FS = 100                  # fontsize comillas decorativas

# Limites de la logica de chunks.
WORDS_PER_CHUNK_DEFAULT = 3
HOOK_MAX_SECONDS_DEFAULT = 30.0  # hook = frase completa de apertura
LONG_WORD_THRESHOLD = 1.5        # >1.5s -> palabra va sola en su chunk


@dataclass
class Cue:
    """Bloque de subtitulo. role determina el estilo en el ASS."""
    index: int
    start: float       # segundos
    end: float
    text: str
    role: str          # "hook" o "body"


# ---------- Construccion desde Whisper ----------

def _cleanup_text(text: str) -> str:
    """Limpia espacios y caracteres raros del output de Whisper."""
    return re.sub(r"\s+", " ", text).strip()


def build_cues(
    whisper_result: dict,
    *,
    words_per_chunk: int = WORDS_PER_CHUNK_DEFAULT,
    hook_max_seconds: float = HOOK_MAX_SECONDS_DEFAULT,
) -> list[Cue]:
    """Construye los Cue: 1 hook al inicio + N bloques de 2-3 palabras."""
    segments = whisper_result.get("segments", [])
    if not segments:
        return []

    cues: list[Cue] = []

    # 1) Hook = primer segment (en MAYUSCULAS), recortado a hook_max_seconds.
    first = segments[0]
    first_words = first.get("words") or []
    hook_start = float(first.get("start", 0.0))
    hook_end = float(first.get("end", hook_start + 0.1))
    hook_text = _cleanup_text(first.get("text", ""))

    if first_words and (hook_end - hook_start) > hook_max_seconds:
        # Recorta palabras que entren en hook_max_seconds desde el inicio.
        cutoff = hook_start + hook_max_seconds
        kept = [w for w in first_words if w.get("end", 0) <= cutoff]
        if kept:
            hook_end = float(kept[-1]["end"])
            hook_text = _cleanup_text(" ".join(w["word"] for w in kept))

    cues.append(Cue(
        index=1,
        start=hook_start,
        end=hook_end,
        text=hook_text.upper(),
        role="hook",
    ))

    # 2) Resto: aplanar palabras de los siguientes segments.
    rest_words: list[dict] = []
    for seg in segments[1:]:
        rest_words.extend(seg.get("words") or [])

    # Si el hook se recorto, las palabras sobrantes del primer seg van al body.
    if first_words and cues[0].end < float(first.get("end", 0.0)):
        leftover = [w for w in first_words if w.get("start", 0) >= cues[0].end]
        rest_words = leftover + rest_words

    chunks = _chunk_words(rest_words, words_per_chunk)
    for i, chunk in enumerate(chunks, start=2):
        text = _cleanup_text(" ".join(w["word"] for w in chunk))
        if not text:
            continue
        cues.append(Cue(
            index=i,
            start=float(chunk[0]["start"]),
            end=float(chunk[-1]["end"]),
            text=text,
            role="body",
        ))

    # Reindexar limpio.
    for new_idx, c in enumerate(cues, start=1):
        c.index = new_idx
    return cues


def _chunk_words(words: list[dict], n: int) -> list[list[dict]]:
    """Agrupa palabras de a n. Palabras anomalamente largas van solas."""
    out: list[list[dict]] = []
    buf: list[dict] = []
    for w in words:
        dur = float(w.get("end", 0)) - float(w.get("start", 0))
        if dur > LONG_WORD_THRESHOLD:
            if buf:
                out.append(buf)
                buf = []
            out.append([w])
            continue
        buf.append(w)
        if len(buf) >= n:
            out.append(buf)
            buf = []
    if buf:
        out.append(buf)
    return out


# ---------- Persistencia JSON (source of truth en disco) ----------

def save_cues_json(cues: list[Cue], path: Path) -> None:
    path.write_text(
        json.dumps([asdict(c) for c in cues], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_cues_json(path: Path) -> list[Cue]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [Cue(**d) for d in data]


# ---------- Export SRT ----------

def _fmt_srt_time(t: float) -> str:
    """Formato SRT: HH:MM:SS,mmm."""
    if t < 0:
        t = 0
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    ms = int(round((t - int(t)) * 1000))
    if ms == 1000:
        ms = 0
        s += 1
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def cues_to_srt(cues: list[Cue]) -> str:
    """Genera el contenido SRT estandar."""
    blocks = []
    for c in cues:
        blocks.append(
            f"{c.index}\n"
            f"{_fmt_srt_time(c.start)} --> {_fmt_srt_time(c.end)}\n"
            f"{c.text}\n"
        )
    return "\n".join(blocks)


def write_srt(cues: list[Cue], path: Path) -> Path:
    path.write_text(cues_to_srt(cues), encoding="utf-8")
    return path


# ---------- Export ASS Sapiens (con estilos hook/body) ----------

def _hex_to_ass_color(hex_rgb: str) -> str:
    """RGB '#E8A838' o 'E8A838' -> '&H0038A8E8' (formato ASS &H00BBGGRR)."""
    h = hex_rgb.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H00{b}{g}{r}".upper()


def _fmt_ass_time(t: float) -> str:
    """Formato ASS: H:MM:SS.cc (centisegundos)."""
    if t < 0:
        t = 0
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    cs = int(round((t - int(t)) * 100))
    if cs == 100:
        cs = 0
        s += 1
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _wrap_hook(text: str, max_chars: int = HOOK_MAX_CHARS_PER_LINE) -> str:
    """Parte el hook en lineas balanceadas con \\N si excede max_chars."""
    if len(text) <= max_chars:
        return text
    words = text.split()
    if len(words) <= 1:
        return text
    # Greedy: ir acumulando hasta llenar linea, luego salto.
    lines: list[str] = []
    current: list[str] = []
    for w in words:
        tentative = (" ".join(current + [w])).strip()
        if len(tentative) > max_chars and current:
            lines.append(" ".join(current))
            current = [w]
        else:
            current.append(w)
    if current:
        lines.append(" ".join(current))
    return "\\N".join(lines)


def _ass_escape(text: str) -> str:
    """Escapa caracteres reservados de ASS."""
    return text.replace("{", "(").replace("}", ")")


def _apply_keyword_color(text: str, accent_ass: str) -> str:
    """Convierte *WORD* en inline color ASS. *texto* → {\\c<acento>}texto{\\c<blanco>}."""
    white_ass = _hex_to_ass_color(SAPIENS_WHITE_HEX)
    parts = text.split("*")
    out: list[str] = []
    for i, part in enumerate(parts):
        if i % 2 == 0:
            out.append(part)
        else:
            out.append("{\\c" + accent_ass + "}" + part + "{\\c" + white_ass + "}")
    return "".join(out)


def cues_to_ass_sapiens(
    cues: list[Cue],
    *,
    color_scheme: str = "teal",
    hook_layout: tuple[int, int] | None = None,
    play_res: tuple[int, int] = (1080, 1920),
) -> str:
    """Genera el archivo ASS estilo Quote-Card Sapiens.

    Hook: Outfit Black 90pt CAPS left-aligned, comillas decorativas en color
    acento, keyword *marcada* resaltada en color acento.
    Body: mismo estilo sin comillas, 72pt, bottom-center.
    color_scheme: 'teal' (#2B9E8F) o 'gold' (#E8A838).
    hook_layout: (alignment, margin_v) para override del estilo Hook. None =
        default bottom-left con MarginV=SAFE_MARGIN_V. Solo el hook se mueve
        segun deteccion de cara; el body siempre va bottom-center MarginV=360.
    play_res: (PlayResX, PlayResY) del ASS. Default (1080, 1920) para Reels
        vertical. Pasa (1920, 1080) para video horizontal 16:9.
    """
    accent_hex = SAPIENS_TEAL_HEX if color_scheme == "teal" else SAPIENS_GOLD_HEX
    accent = _hex_to_ass_color(accent_hex)
    white  = _hex_to_ass_color(SAPIENS_WHITE_HEX)
    black  = _hex_to_ass_color(SAPIENS_BLACK_HEX)

    if hook_layout is None:
        hook_align, hook_margin_v = 1, SAFE_MARGIN_V
    else:
        hook_align, hook_margin_v = hook_layout

    play_x, play_y = play_res
    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {play_x}\n"
        f"PlayResY: {play_y}\n"
        "WrapStyle: 2\n"
        "ScaledBorderAndShadow: yes\n"
        "YCbCr Matrix: TV.709\n"
        "\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Hook,{HOOK_FONT},{HOOK_FONTSIZE},{white},&H000000FF,{black},"
        f"&H00000000,1,0,0,0,100,100,{HOOK_SPACING},0,1,{HOOK_OUTLINE},{HOOK_SHADOW},"
        f"{hook_align},{SAFE_MARGIN_LR},{SAFE_MARGIN_LR},{hook_margin_v},1\n"
        f"Style: Body,{BODY_FONT},{BODY_FONTSIZE},{white},&H000000FF,{black},"
        f"&H00000000,1,0,0,0,100,100,{HOOK_SPACING},0,1,{BODY_OUTLINE},{BODY_SHADOW},"
        f"2,{SAFE_MARGIN_LR},{SAFE_MARGIN_LR},{SAFE_MARGIN_V},1\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, "
        "MarginV, Effect, Text\n"
    )

    lines = [header]
    for c in cues:
        style = "Hook" if c.role == "hook" else "Body"
        text = _ass_escape(c.text)
        if c.role == "hook":
            text = _wrap_hook(text)
        text = _apply_keyword_color(text, accent)
        if c.role == "hook":
            text = (
                "{\\fs" + str(QUOTE_FS) + "\\c" + accent + "}" +
                QUOTE_CHAR + "  " +
                "{\\fs" + str(HOOK_FONTSIZE) + "\\c" + white + "}" +
                text
            )
        lines.append(
            f"Dialogue: 0,{_fmt_ass_time(c.start)},{_fmt_ass_time(c.end)},"
            f"{style},,0,0,0,,{{\\fad(120,120)}}{text}\n"
        )
    return "".join(lines)


def write_ass(
    cues: list[Cue],
    path: Path,
    *,
    color_scheme: str = "teal",
    hook_layout: tuple[int, int] | None = None,
    play_res: tuple[int, int] = (1080, 1920),
) -> Path:
    path.write_text(
        cues_to_ass_sapiens(
            cues,
            color_scheme=color_scheme,
            hook_layout=hook_layout,
            play_res=play_res,
        ),
        encoding="utf-8",
    )
    return path


# ---------- Helpers UI Gradio (Cue <-> tabla) ----------

DATAFRAME_HEADERS = ["#", "start", "end", "role", "text"]


def cues_to_rows(cues: list[Cue]) -> list[list]:
    """Cue list -> rows para gr.Dataframe."""
    return [[c.index, round(c.start, 2), round(c.end, 2), c.role, c.text] for c in cues]


def rows_to_cues(rows) -> list[Cue]:
    """Rows de gr.Dataframe -> Cue list. Tolerante a tipos string/float."""
    cues: list[Cue] = []
    if rows is None:
        return cues
    # Soporta pandas DataFrame o list[list].
    if hasattr(rows, "values"):
        iterable = rows.values.tolist()
    else:
        iterable = list(rows)
    for i, r in enumerate(iterable, start=1):
        if r is None or len(r) < 5:
            continue
        try:
            start = float(r[1])
            end = float(r[2])
        except (TypeError, ValueError):
            continue
        text = ("" if r[4] is None else str(r[4])).strip()
        if not text:
            continue
        role = (str(r[3]) or "body").strip().lower()
        if role not in ("hook", "body"):
            role = "body"
        cues.append(Cue(index=i, start=start, end=end, text=text, role=role))
    return cues
