"""Preview del estilo Quote-Card para subtitulos de reels Sapiens.

Estilo: comillas decorativas en color acento + texto grande CAPS alineado
a la izquierda, Outfit Black, sin outline. Keyword principal en teal o gold.

Genera 2 PNGs sobre fondo oscuro (el caso real de los reels del usuario):
    - preview_quote_teal.png   (keyword + comillas en teal #2B9E8F)
    - preview_quote_gold.png   (keyword + comillas en gold #E8A838)

Uso (desde la raiz del repo):
    python reels-postpro/scripts/preview_subtitle_style.py
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# ---------- Paths ----------
REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLES_DIR = REPO_ROOT / "reels-postpro" / "samples"
SAMPLES_DIR.mkdir(parents=True, exist_ok=True)

# ---------- Estilo Quote-Card Sapiens ----------
# Texto de prueba — frase completa del reel del usuario.
# Saltos de linea calibrados para Outfit Black 90pt, frame 1080x1920,
# safe zone IG (L/R: 75px, bottom: 360px, top: 250px).
# ~18 chars max por linea a 90pt (medido empiricamente del render).
# Keyword marcada con *asteriscos* -> se colorea con el acento.
HOOK_TEXT = (
    "INTENTAR PROHIBIR\n"
    "EL USO DE\n"
    "*INTELIGENCIA\n"
    "ARTIFICIAL*\n"
    "EN CASA ES\n"
    "UNA BATALLA\n"
    "PERDIDA"
)

FONT      = "Outfit Black"   # display font oficial Sapiens
FONTSIZE  = 90               # grande y prominente
SPACING   = -1               # tracking apretado para CAPS pesado
OUTLINE   = 0                # sin stroke — el shadow da separacion
SHADOW    = 2
MARGIN_L  = 75
MARGIN_R  = 80
MARGIN_V  = 360              # desde el borde inferior (safe zone IG bottom)

QUOTE_FS  = 100              # fontsize comillas decorativas (inline, misma linea que el texto)
QUOTE_CHAR = "“"        # " LEFT DOUBLE QUOTATION MARK

SAPIENS_TEAL_HEX = "2B9E8F"
SAPIENS_GOLD_HEX = "E8A838"

BG_DARK_HEX = "261F2E"       # fondo ligeramente purpura oscuro (mas cinematico que puro negro)


# ---------- Helpers ASS ----------
def hex_to_ass(hex_rgb: str) -> str:
    """'E8A838' -> '&H0038A8E8' (ASS usa BGR invertido)."""
    h = hex_rgb.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H00{b}{g}{r}".upper()


def apply_keyword_color(text: str, accent_ass: str) -> str:
    """Convierte *WORD* en inline color ASS."""
    white_ass = hex_to_ass("FFFFFF")
    parts = text.split("*")
    out: list[str] = []
    for i, part in enumerate(parts):
        if i % 2 == 0:
            out.append(part)
        else:
            out.append("{\\c" + accent_ass + "}" + part + "{\\c" + white_ass + "}")
    return "".join(out)


def build_ass(accent_hex: str) -> str:
    """Genera el ASS como UN unico evento: comillas inline + salto + texto CAPS.

    Las comillas decorativas van en la primera 'linea' con fontsize mayor y
    color acento, seguidas de \\N. ASS las trata como parte del mismo bloque
    y las coloca sin gap matematico — el espaciado es natural al line-height
    del font, exactamente como en la referencia visual.
    """
    accent_ass = hex_to_ass(accent_hex)
    white_ass  = hex_to_ass("FFFFFF")

    lines      = HOOK_TEXT.split("\n")
    hook_body  = "\\N".join(lines)
    hook_color = apply_keyword_color(hook_body, accent_ass)

    # Las comillas van en la misma primera linea (sin \N) para evitar el
    # gap vacio que ASS introduce entre lineas de distinto fontsize.
    # Color acento + espacio + texto blanco en la misma linea.
    # El " es levemente mas grande (QUOTE_FS = 100 vs FONTSIZE = 90)
    # para dar protagonismo sin crear una linea separada.
    full_text = (
        "{\\fs" + str(QUOTE_FS) + "\\c" + accent_ass + "}" +
        QUOTE_CHAR + "  " +
        "{\\fs" + str(FONTSIZE) + "\\c" + white_ass + "}" +
        hook_color
    )

    return (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        "PlayResX: 1080\n"
        "PlayResY: 1920\n"
        "WrapStyle: 2\n"
        "ScaledBorderAndShadow: yes\n"
        "YCbCr Matrix: TV.709\n"
        "\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Hook,{FONT},{FONTSIZE},{white_ass},&H000000FF,&H00000000,"
        f"&H00000000,1,0,0,0,100,100,{SPACING},0,1,{OUTLINE},{SHADOW},"
        f"1,{MARGIN_L},{MARGIN_R},{MARGIN_V},1\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, "
        "MarginV, Effect, Text\n"
        f"Dialogue: 0,0:00:00.00,0:00:05.00,Hook,,0,0,0,,{full_text}\n"
    )


# ---------- Generacion de fondo ----------
def gen_bg_solid(hex_color: str, out_path: Path) -> None:
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi",
        "-i", f"color=c=0x{hex_color}:s=1080x1920:d=1",
        "-frames:v", "1", str(out_path),
    ], check=True)


# ---------- Render PNG ----------
def render_preview(bg_path: Path, ass_path: Path, out_path: Path) -> None:
    tmp_root = Path(tempfile.mkdtemp(prefix="reels_preview_"))
    try:
        ass_dst = tmp_root / "sub.ass"
        shutil.copyfile(ass_path, ass_dst)
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-loop", "1", "-i", str(bg_path.resolve()),
            "-vf", "format=yuv420p,ass=sub.ass",
            "-frames:v", "1",
            str(out_path.resolve()),
        ], check=True, cwd=str(tmp_root))
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)


# ---------- Main ----------
def main() -> int:
    work = SAMPLES_DIR / "_work"
    work.mkdir(exist_ok=True)

    print("Generando fondo oscuro...")
    bg = work / "bg_dark.png"
    gen_bg_solid(BG_DARK_HEX, bg)

    print("Generando ASS para teal y gold...")
    ass_teal = work / "quote_teal.ass"
    ass_gold = work / "quote_gold.ass"
    ass_teal.write_text(build_ass(SAPIENS_TEAL_HEX), encoding="utf-8")
    ass_gold.write_text(build_ass(SAPIENS_GOLD_HEX), encoding="utf-8")

    print("Renderizando previews...")
    for color, ass_file in [("teal", ass_teal), ("gold", ass_gold)]:
        out = SAMPLES_DIR / f"preview_quote_{color}.png"
        render_preview(bg, ass_file, out)
        print(f"  -> {out.relative_to(REPO_ROOT)}")

    print(f"\nListo. PNGs en {SAMPLES_DIR.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
