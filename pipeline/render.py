"""Render final: ffmpeg quema el ASS sobre el video limpio (libx264 crf 18 slow).

Estrategia de fonts en Windows:
    El filtro `ass` de ffmpeg no acepta la opcion `fontsdir` con paths que
    contienen drive letter (C:) en Windows — el parser de filtros interpreta ':'
    como separador de opciones aunque este escapado. La solucion es instalar las
    fonts al directorio de usuario de Windows (%LOCALAPPDATA%\Microsoft\Windows\Fonts),
    que no requiere permisos de admin (Windows 10+) y es reconocido por libass
    automaticamente. De esta forma el filtro es simplemente `ass=<path>` sin fontsdir.

HDR / iPhone HEVC:
    iPhone 4K graba en bt2020/HLG (arib-std-b67, yuv420p10le). Sin tonemapping,
    libx264 -pix_fmt yuv420p produce colores erroneos (sobre-exposicion, contraste
    alterado). Detectamos HDR via ffprobe y aplicamos la cadena zscale recomendada:
        zscale linear → format gbrpf32le → zscale bt709 → tonemap hable → format yuv420p
    Para SDR el filtro solo es: format=yuv420p,ass=sub.ass
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from .audio import AudioError


def _run_cwd(cmd: list[str], *, cwd: Path) -> None:
    """Ejecuta cmd desde cwd, capturando stderr para diagnosticos legibles."""
    try:
        subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(cwd),
        )
    except subprocess.CalledProcessError as exc:
        tail = (exc.stderr or "")[-1500:]
        raise AudioError(
            f"Comando fallo: {' '.join(cmd[:4])}...\nStderr:\n{tail}"
        ) from exc
    except FileNotFoundError as exc:
        raise AudioError(f"Ejecutable no encontrado: {cmd[0]}") from exc


_WIN_USER_FONTS = Path.home() / "AppData" / "Local" / "Microsoft" / "Windows" / "Fonts"


def _ensure_user_fonts(fonts_dir: Path) -> None:
    """Copia las fonts Sapiens al directorio de fonts de usuario de Windows.

    Windows 10+ permite instalar fonts por usuario sin privilegios de admin.
    libass las encuentra automaticamente desde ahi sin necesidad de fontsdir.
    Solo copia si el archivo no existe ya (idempotente).
    """
    _WIN_USER_FONTS.mkdir(parents=True, exist_ok=True)
    for ttf in fonts_dir.glob("*.ttf"):
        dst = _WIN_USER_FONTS / ttf.name
        if not dst.exists():
            shutil.copyfile(ttf, dst)


def _stage_ass(ass_path: Path) -> tuple[Path, Path]:
    """Copia el ASS a un directorio temp como 'sub.ass' (nombre fijo, sin espacios).

    El filtro ffmpeg usa path relativo desde cwd=tmp_root, evitando el problema
    del drive letter en Windows.
    """
    tmp_root = Path(tempfile.mkdtemp(prefix="reels_pp_"))
    ass_dst = tmp_root / "sub.ass"
    shutil.copyfile(ass_path, ass_dst)
    return tmp_root, ass_dst


def _detect_hdr(video_in: Path) -> bool:
    """Devuelve True si el video tiene color_transfer HDR (HLG o PQ).

    iPhone 4K HEVC usa 'arib-std-b67' (HLG). Algunos Android usan 'smpte2084' (PQ).
    Cualquiera de los dos necesita tonemapping para convertir a H.264 SDR correctamente.
    """
    HDR_TRANSFERS = {"arib-std-b67", "smpte2084", "bt2020-10", "bt2020-12"}
    try:
        cmd = [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=color_transfer",
            "-print_format", "json",
            str(video_in),
        ]
        proc = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        data = json.loads(proc.stdout or "{}")
        streams = data.get("streams", [])
        if not streams:
            return False
        transfer = streams[0].get("color_transfer", "")
        return transfer in HDR_TRANSFERS
    except Exception:
        return False


def _build_vf(is_hdr: bool) -> str:
    """Construye la cadena -vf completa segun si el video es HDR o SDR.

    HDR (HLG/PQ):
        zscale tonemap chain recomendada por la comunidad ffmpeg para bt2020→bt709.
        - zscale=t=linear:npl=203  convierte gamma a linear light (npl=203 cd/m² es
          el reference white para HLG, equivalente al SDR reference level).
        - format=gbrpf32le          necesario para tonemap (trabaja en float RGB).
        - zscale=p=bt709            convierte primaries bt2020→bt709.
        - tonemap=hable:desat=0     aplica curva S de Hable (suave, preserva saturacion).
        - zscale=t=bt709:m=bt709:r=tv  gamma bt709 + full→limited (broadcast range).
        - format=yuv420p            pixfmt compatible con libx264.

    SDR:
        Solo aseguramos yuv420p (desde yuv420p10le u otros formatos de camara).
    """
    if is_hdr:
        return (
            "zscale=t=linear:npl=203,"
            "format=gbrpf32le,"
            "zscale=p=bt709,"
            "tonemap=tonemap=hable:desat=0,"
            "zscale=t=bt709:m=bt709:r=tv,"
            "format=yuv420p,"
            "ass=sub.ass"
        )
    return "format=yuv420p,ass=sub.ass"


def burn_subtitles(
    video_in: Path,
    ass_path: Path,
    video_out: Path,
    fonts_dir: Path,
) -> Path:
    """Quema los subtitulos ASS sobre el video con codificacion premium.

    Detecta automaticamente si el video es HDR (iPhone HLG / Android PQ) y aplica
    la cadena zscale de tonemapping para producir colores correctos en H.264 SDR.

    -c:v libx264 -crf 18 -preset slow = calidad muy alta para subir a IG.
    -c:a copy preserva el audio limpio del paso anterior.
    """
    if not ass_path.exists():
        raise AudioError(f"ASS no encontrado: {ass_path}")
    if not video_in.exists():
        raise AudioError(f"Video de entrada no encontrado: {video_in}")
    if not fonts_dir.exists():
        raise AudioError(f"fonts_dir no encontrado: {fonts_dir}")

    _ensure_user_fonts(fonts_dir)

    is_hdr = _detect_hdr(video_in)
    vf = _build_vf(is_hdr)

    tmp_root, _ = _stage_ass(ass_path)
    try:
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_in.resolve()),
            "-vf", vf,
            "-c:v", "libx264", "-crf", "18", "-preset", "slow",
            "-c:a", "copy",
            "-movflags", "+faststart",
            str(video_out.resolve()),
        ]
        _run_cwd(cmd, cwd=tmp_root)
        if not video_out.exists() or video_out.stat().st_size == 0:
            raise AudioError(f"Render fallo: salida vacia en {video_out}")
        return video_out
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)
