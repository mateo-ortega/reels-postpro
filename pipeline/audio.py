"""Cadena de procesamiento de audio: high-pass -> DeepFilterNet -> loudnorm -16 LUFS -> mux.

La calidad del audio es la prioridad #1 del pipeline. Los Reels en feed compiten
con musica producida profesionalmente; voz cruda con rumble o nivel bajo se
salta automaticamente. Por eso aplicamos tres etapas y normalizamos al estandar
de Instagram (-16 LUFS integrated, -1.5 dBTP true peak).

Soporta entrada .mp4 y .mov (ffmpeg demuxea ambos sin logica especial).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


class AudioError(RuntimeError):
    """Error en la cadena de audio (ffmpeg o DeepFilterNet)."""


@dataclass
class AudioOptions:
    """Opciones de la cadena de audio expuestas en la UI."""
    atten_lim_db: int = 100        # DeepFilterNet: 30 (suave) a 100 (max)
    bypass_highpass: bool = False
    bypass_loudnorm: bool = False


def _run(cmd: list[str], *, capture: bool = True) -> subprocess.CompletedProcess:
    """Ejecuta un comando capturando stderr para diagnosticos legibles."""
    try:
        return subprocess.run(
            cmd,
            check=True,
            capture_output=capture,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.CalledProcessError as exc:
        tail = (exc.stderr or "")[-1500:]
        raise AudioError(
            f"Comando fallo: {' '.join(cmd[:4])}...\nStderr:\n{tail}"
        ) from exc
    except FileNotFoundError as exc:
        raise AudioError(f"Ejecutable no encontrado: {cmd[0]}") from exc


def probe_streams(video_in: Path) -> dict:
    """Devuelve metadata de streams via ffprobe. Valida que haya video y audio."""
    cmd = [
        "ffprobe", "-v", "error", "-print_format", "json",
        "-show_streams", "-show_format", str(video_in),
    ]
    res = _run(cmd)
    data = json.loads(res.stdout)
    streams = data.get("streams", [])
    has_video = any(s.get("codec_type") == "video" for s in streams)
    has_audio = any(s.get("codec_type") == "audio" for s in streams)
    if not has_video:
        raise AudioError(f"El archivo no contiene stream de video: {video_in.name}")
    if not has_audio:
        raise AudioError(f"El archivo no contiene stream de audio: {video_in.name}")
    return data


def extract_audio_wav(
    video_in: Path,
    wav_out: Path,
    *,
    apply_highpass: bool = True,
) -> Path:
    """Extrae audio como mono 48kHz PCM.

    Cadena de filtros:
        1. high-pass 80Hz  — elimina rumble, HVAC de baja frecuencia, plosivas
    """
    filters: list[str] = []
    if apply_highpass:
        filters.append("highpass=f=80")
    af_chain = ",".join(filters) if filters else "anull"
    cmd = [
        "ffmpeg", "-y", "-i", str(video_in),
        "-vn", "-af", af_chain,
        "-acodec", "pcm_s16le", "-ar", "48000", "-ac", "1",
        str(wav_out),
    ]
    _run(cmd)
    if not wav_out.exists() or wav_out.stat().st_size == 0:
        raise AudioError(f"extract_audio_wav: salida vacia en {wav_out}")
    return wav_out


def denoise_deepfilter(
    wav_in: Path,
    wav_out: Path,
    *,
    atten_lim_db: int = 100,
) -> Path:
    """Aplica DeepFilterNet 3 al wav usando la API Python (no subprocess).

    Llamar df.enhance via subprocess falla en Windows con torch>=2.x por
    un bug del DataLoader en procesos hijos. La API Python es directa y robusta.
    """
    try:
        from df.enhance import enhance, init_df
        from df.io import load_audio, save_audio
    except ImportError as exc:
        raise AudioError(f"DeepFilterNet no instalado: {exc}") from exc

    # log_file=None evita crear enhance.log en el directorio de trabajo.
    model, df_state, _ = init_df(
        config_allow_defaults=True,
        log_file=None,
        log_level="ERROR",
    )

    # load_audio devuelve (Tensor [C, T], AudioMetaData). DF espera 48kHz mono.
    audio, _meta = load_audio(str(wav_in), sr=df_state.sr(), verbose=False)

    enhanced = enhance(
        model,
        df_state,
        audio,
        atten_lim_db=float(atten_lim_db),
    )

    save_audio(str(wav_out), enhanced, df_state.sr())

    if not wav_out.exists() or wav_out.stat().st_size == 0:
        raise AudioError(f"DeepFilterNet: salida vacia en {wav_out}")
    return wav_out


_LOUDNORM_KEYS = (
    "input_i", "input_tp", "input_lra", "input_thresh", "target_offset",
)


def _measure_loudness(wav_in: Path) -> dict[str, str]:
    """Pasada 1 de loudnorm: extrae mediciones del audio."""
    cmd = [
        "ffmpeg", "-hide_banner", "-nostats", "-i", str(wav_in),
        "-af", "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json",
        "-f", "null", "-",
    ]
    proc = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0:
        raise AudioError(
            f"loudnorm pasada-1 fallo. Stderr:\n{proc.stderr[-1500:]}"
        )
    match = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", proc.stderr, re.DOTALL)
    if not match:
        raise AudioError("loudnorm pasada-1: no se encontro JSON de mediciones.")
    measured = json.loads(match.group(0))
    missing = [k for k in _LOUDNORM_KEYS if k not in measured]
    if missing:
        raise AudioError(f"loudnorm pasada-1: faltan claves {missing}")
    return measured


def normalize_loudness(wav_in: Path, wav_out: Path) -> Path:
    """Two-pass loudnorm a -16 LUFS / -1.5 dBTP (estandar Instagram)."""
    m = _measure_loudness(wav_in)
    af = (
        "loudnorm="
        "I=-16:TP=-1.5:LRA=11:"
        f"measured_I={m['input_i']}:"
        f"measured_TP={m['input_tp']}:"
        f"measured_LRA={m['input_lra']}:"
        f"measured_thresh={m['input_thresh']}:"
        f"offset={m['target_offset']}:"
        "linear=true:print_format=summary"
    )
    cmd = [
        "ffmpeg", "-y", "-i", str(wav_in),
        "-af", af,
        "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le",
        str(wav_out),
    ]
    _run(cmd)
    return wav_out


def mux_clean_audio(video_in: Path, wav_in: Path, video_out: Path) -> Path:
    """Reemplaza el audio del video con wav limpio. -c:v copy preserva el video."""
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_in),
        "-i", str(wav_in),
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k",
        "-map", "0:v:0", "-map", "1:a:0",
        "-shortest",
        "-movflags", "+faststart",
        str(video_out),
    ]
    _run(cmd)
    return video_out


def process_audio_full(
    video_in: Path,
    session_dir: Path,
    *,
    options: AudioOptions | None = None,
) -> Path:
    """Orquesta toda la cadena. Devuelve la ruta del video_clean.mp4 generado.

    Conserva los wav intermedios para inspeccion hasta cleanup explicito.
    """
    options = options or AudioOptions()
    probe_streams(video_in)

    raw_hp = session_dir / "01_raw_hp.wav"
    denoised = session_dir / "02_denoised.wav"
    normalized = session_dir / "03_normalized.wav"
    video_clean = session_dir / "video_clean.mp4"

    extract_audio_wav(
        video_in, raw_hp,
        apply_highpass=not options.bypass_highpass,
    )
    denoise_deepfilter(raw_hp, denoised, atten_lim_db=options.atten_lim_db)

    if options.bypass_loudnorm:
        shutil.copyfile(denoised, normalized)
    else:
        normalize_loudness(denoised, normalized)

    mux_clean_audio(video_in, normalized, video_clean)
    return video_clean
