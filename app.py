"""Reels Postpro - UI Gradio para postproduccion de Reels Sapiens.

Flujo lineal en una sola pagina:
    1. Subir video (.mp4 / .mov) y procesar audio + transcribir.
    2. Editar la tabla de subtitulos si Whisper se equivoco.
    3. Renderizar el video final con subtitulos quemados estilo Sapiens.

Arrancar con: python app.py  ->  http://localhost:7860
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import gradio as gr

from pipeline import (
    audio as audio_mod,
    face as face_mod,
    paths,
    render,
    transcribe,
)
from pipeline.paths import cleanup_after_render, purge_old_sessions
from pipeline.subtitles import (
    DATAFRAME_HEADERS,
    build_cues,
    cues_to_rows,
    load_cues_json,
    rows_to_cues,
    save_cues_json,
    write_ass,
    write_srt,
)


# ---------- Verificacion al arrancar ----------

def _check_ffmpeg() -> str:
    try:
        out = subprocess.run(
            ["ffmpeg", "-version"], capture_output=True, text=True, check=True
        )
        first = out.stdout.splitlines()[0] if out.stdout else "ffmpeg disponible"
        return first
    except (FileNotFoundError, subprocess.CalledProcessError):
        return "ERROR: ffmpeg no encontrado en PATH. Descarga: https://www.gyan.dev/ffmpeg/builds/"


def _check_fonts() -> str:
    fdir = paths.font_dir()
    needed = ["Outfit-Black.ttf"]
    missing = [n for n in needed if not (fdir / n).exists()]
    if missing:
        return f"WARN: faltan fonts en {fdir}: {missing} (corre install.ps1)"
    return f"Fonts Sapiens OK ({fdir})"


# ---------- Backends de la UI ----------

def _resolve_hook_layout(sdir: Path, cues, hook_position: str):
    """Decide el hook_layout (alignment, margin_v) a partir del envelope cacheado.

    Si no hay envelope o cues vacio, devuelve None (= default Sapiens bottom-left).
    Si hay envelope, llama decide_hook_layout con el modo elegido por el usuario.
    """
    if not cues:
        return None
    envelope = face_mod.load_envelope(sdir / "face_envelope.json")
    if envelope is None:
        envelope = face_mod._fallback_envelope()
    layout = face_mod.decide_hook_layout(envelope, cues[0].text, mode=hook_position)
    return (layout.alignment, layout.margin_v)


def do_process(
    video_file,
    words_per_chunk,
    hook_max_seconds,
    color_scheme,
    hook_position,
    language,
    state,
    progress=gr.Progress(track_tqdm=False),
):
    """Etapa 1: copia video, limpia audio, transcribe, construye cues."""
    if video_file is None:
        return [], state, "Sube un video primero (.mp4 o .mov)."

    src = Path(video_file)
    if not src.exists():
        return [], state, f"Archivo no encontrado: {src}"

    progress(0.05, desc="Creando sesion...")
    sdir = paths.new_session()
    original = sdir / f"original{src.suffix.lower()}"
    shutil.copyfile(src, original)

    try:
        progress(0.10, desc="Validando streams...")
        audio_mod.probe_streams(original)

        progress(0.15, desc="Procesando audio (high-pass + DeepFilterNet + loudnorm)...")
        opts = audio_mod.AudioOptions()
        video_clean = audio_mod.process_audio_full(original, sdir, options=opts)

        lang = (language or "es").strip().lower()
        if lang not in ("es", "en"):
            lang = "es"
        progress(0.55, desc=f"Transcribiendo con Whisper [{lang}] (puede tardar)...")
        result = transcribe.whisper_transcribe(video_clean, language=lang)
        (sdir / "whisper_result.json").write_text(
            json.dumps(result, ensure_ascii=False), encoding="utf-8",
        )

        progress(0.80, desc="Construyendo subtitulos...")
        cues = build_cues(
            result,
            words_per_chunk=int(words_per_chunk),
            hook_max_seconds=float(hook_max_seconds),
        )
        save_cues_json(cues, sdir / "cues.json")
        write_srt(cues, sdir / "subtitles.srt")

        progress(0.88, desc="Detectando cara para posicionar el hook...")
        envelope = face_mod._fallback_envelope()
        if cues:
            envelope = face_mod.detect_hook_envelope(
                Path(video_clean), cues[0].start, cues[0].end,
            )
        face_mod.save_envelope(envelope, sdir / "face_envelope.json")
        hook_layout = _resolve_hook_layout(sdir, cues, hook_position)

        progress(0.95, desc="Generando ASS...")
        write_ass(
            cues, sdir / "subtitles.ass",
            color_scheme=color_scheme, hook_layout=hook_layout,
        )

        progress(1.0, desc="Listo.")
        new_state = {
            "session_dir": str(sdir),
            "video_clean": str(video_clean),
            "words_per_chunk": int(words_per_chunk),
            "hook_max_seconds": float(hook_max_seconds),
            "color_scheme": color_scheme,
            "hook_position": hook_position,
            "language": lang,
        }
        face_msg = (
            f"cara detectada (conf {envelope.confidence:.0%})"
            if envelope.detected else "sin cara detectada (fallback bottom)"
        )
        msg = (
            f"OK. Sesion: {sdir.name}\n"
            f"Cues generados: {len(cues)} (1 hook + {len(cues)-1 if cues else 0} body).\n"
            f"Hook: {face_msg}.\n"
            f"Edita la tabla si hace falta y luego renderiza."
        )
        return cues_to_rows(cues), new_state, msg

    except Exception as exc:  # se reporta a la UI, no se propaga
        return [], state, f"ERROR procesando: {exc}"


def do_reload_from_whisper(words_per_chunk, hook_max_seconds, color_scheme, hook_position, state):
    """Reconstruye los cues desde el ultimo whisper_result (descarta ediciones)."""
    if not state or not state.get("session_dir"):
        return [], state, "No hay sesion activa. Procesa un video primero."
    sdir = Path(state["session_dir"])
    wpath = sdir / "whisper_result.json"
    if not wpath.exists():
        return [], state, "whisper_result.json no encontrado en la sesion."
    result = json.loads(wpath.read_text(encoding="utf-8"))
    cues = build_cues(
        result,
        words_per_chunk=int(words_per_chunk),
        hook_max_seconds=float(hook_max_seconds),
    )
    save_cues_json(cues, sdir / "cues.json")
    write_srt(cues, sdir / "subtitles.srt")
    hook_layout = _resolve_hook_layout(sdir, cues, hook_position)
    write_ass(
        cues, sdir / "subtitles.ass",
        color_scheme=color_scheme, hook_layout=hook_layout,
    )
    state["words_per_chunk"] = int(words_per_chunk)
    state["hook_max_seconds"] = float(hook_max_seconds)
    state["color_scheme"] = color_scheme
    state["hook_position"] = hook_position
    return cues_to_rows(cues), state, "Cues regenerados desde Whisper."


def do_save_edits(rows, color_scheme, hook_position, state):
    """Guarda las ediciones de la tabla a cues.json + .srt + .ass."""
    if not state or not state.get("session_dir"):
        return state, "No hay sesion activa."
    sdir = Path(state["session_dir"])
    cues = rows_to_cues(rows)
    if not cues:
        return state, "No hay filas validas que guardar."
    save_cues_json(cues, sdir / "cues.json")
    write_srt(cues, sdir / "subtitles.srt")
    hook_layout = _resolve_hook_layout(sdir, cues, hook_position)
    write_ass(
        cues, sdir / "subtitles.ass",
        color_scheme=color_scheme, hook_layout=hook_layout,
    )
    state["color_scheme"] = color_scheme
    state["hook_position"] = hook_position
    return state, f"Guardado. {len(cues)} cues en disco."


def do_render(rows, color_scheme, hook_position, state, progress=gr.Progress(track_tqdm=False)):
    """Etapa 3: regenera ASS desde la tabla actual y quema sobre video_clean."""
    if not state or not state.get("session_dir") or not state.get("video_clean"):
        return None, None, "No hay sesion activa. Procesa un video primero."

    sdir = Path(state["session_dir"])
    video_clean = Path(state["video_clean"])
    if not video_clean.exists():
        return None, None, f"video_clean no existe: {video_clean}"

    cues = rows_to_cues(rows)
    if not cues:
        # Fallback al cues.json en disco si la tabla esta vacia.
        cjson = sdir / "cues.json"
        if cjson.exists():
            cues = load_cues_json(cjson)
    if not cues:
        return None, None, "No hay subtitulos que renderizar."

    progress(0.10, desc="Regenerando ASS desde la tabla...")
    save_cues_json(cues, sdir / "cues.json")
    write_srt(cues, sdir / "subtitles.srt")
    hook_layout = _resolve_hook_layout(sdir, cues, hook_position)
    ass_path = write_ass(
        cues, sdir / "subtitles.ass",
        color_scheme=color_scheme, hook_layout=hook_layout,
    )
    state["hook_position"] = hook_position

    final = sdir / "final.mp4"
    progress(0.30, desc="Quemando subtitulos (libx264 crf 18 slow)...")
    try:
        render.burn_subtitles(
            video_in=video_clean,
            ass_path=ass_path,
            video_out=final,
            fonts_dir=paths.font_dir(),
        )
    except Exception as exc:
        return None, None, f"ERROR renderizando: {exc}"

    progress(1.0, desc="Render listo.")
    cleanup_after_render(sdir)
    return str(final), str(final), f"Render OK: {final.name} ({final.stat().st_size//1024} KB)"


def do_open_session(state):
    """Abre la carpeta de la sesion en el gestor de archivos (util para inspeccion)."""
    if not state or not state.get("session_dir"):
        return "No hay sesion activa."
    sdir = Path(state["session_dir"])
    if sys.platform == "win32":
        opener = ["explorer", str(sdir)]
    elif sys.platform == "darwin":
        opener = ["open", str(sdir)]
    else:
        opener = ["xdg-open", str(sdir)]
    try:
        subprocess.Popen(opener)
        return f"Abriendo {sdir}..."
    except Exception as exc:
        return f"No se pudo abrir: {exc}"


# ---------- Construccion de la UI ----------

CSS = """
.gradio-container { max-width: 1100px !important; }
.section-title { font-size: 1.15rem; font-weight: 600; margin-top: 0.5rem; }
"""


def build_ui() -> gr.Blocks:
    ffmpeg_status = _check_ffmpeg()
    fonts_status = _check_fonts()

    with gr.Blocks(title="Reels Postpro Sapiens", css=CSS) as demo:
        gr.Markdown("# Reels Postpro - Sapiens")
        gr.Markdown(
            f"`{ffmpeg_status}`  \n`{fonts_status}`",
        )

        state = gr.State({})

        # ----- Seccion 1: Upload + procesar -----
        gr.Markdown("## 1. Subir video crudo", elem_classes="section-title")
        with gr.Row():
            video_in = gr.File(
                label="Video crudo (.mp4 o .mov)",
                file_types=[".mp4", ".mov", ".MP4", ".MOV"],
                type="filepath",
            )
        with gr.Row():
            words_per_chunk = gr.Slider(
                2, 3, value=3, step=1,
                label="Palabras por bloque (body)",
            )
            hook_max_s = gr.Slider(
                1.0, 30.0, value=30.0, step=0.5,
                label="Duracion maxima del hook (s)",
            )
        with gr.Row():
            color_scheme = gr.Radio(
                choices=["teal", "gold"],
                value="teal",
                label="Color de acento",
            )
            hook_position = gr.Radio(
                choices=["auto", "abajo"],
                value="auto",
                label="Posicion del hook (auto = detectar cara)",
            )
            language = gr.Radio(
                choices=["es", "en"],
                value="es",
                label="Idioma de Whisper (es / en)",
            )

        process_btn = gr.Button("Procesar audio + transcribir", variant="primary")
        process_status = gr.Markdown("")

        # ----- Seccion 2: Editar subtitulos -----
        gr.Markdown("## 2. Editar subtitulos", elem_classes="section-title")
        gr.Markdown(
            "_Edita texto, timing o cambia el `role` (hook/body) directo en la tabla. "
            "Recuerda guardar antes de renderizar._"
        )
        cues_table = gr.Dataframe(
            headers=DATAFRAME_HEADERS,
            datatype=["number", "number", "number", "str", "str"],
            interactive=True,
            row_count=(0, "dynamic"),
            col_count=(5, "fixed"),
            wrap=True,
        )
        with gr.Row():
            reload_btn = gr.Button("Recargar desde Whisper")
            save_btn = gr.Button("Guardar cambios")
        edit_status = gr.Markdown("")

        # ----- Seccion 3: Renderizar -----
        gr.Markdown("## 3. Renderizar y descargar", elem_classes="section-title")
        render_btn = gr.Button("Renderizar final", variant="primary")
        with gr.Row():
            video_out = gr.Video(label="Resultado", interactive=False)
            file_out = gr.File(label="Descargar final.mp4")
        render_status = gr.Markdown("")
        with gr.Row():
            open_btn = gr.Button("Abrir carpeta de la sesion")
            open_status = gr.Markdown("")

        # ----- Wiring -----
        process_btn.click(
            do_process,
            inputs=[
                video_in,
                words_per_chunk, hook_max_s, color_scheme, hook_position, language, state,
            ],
            outputs=[cues_table, state, process_status],
        )
        reload_btn.click(
            do_reload_from_whisper,
            inputs=[words_per_chunk, hook_max_s, color_scheme, hook_position, state],
            outputs=[cues_table, state, edit_status],
        )
        save_btn.click(
            do_save_edits,
            inputs=[cues_table, color_scheme, hook_position, state],
            outputs=[state, edit_status],
        )
        render_btn.click(
            do_render,
            inputs=[cues_table, color_scheme, hook_position, state],
            outputs=[video_out, file_out, render_status],
        )
        open_btn.click(
            do_open_session,
            inputs=[state],
            outputs=[open_status],
        )

    return demo


if __name__ == "__main__":
    purge_old_sessions(max_age_hours=24)
    ui = build_ui()
    ui.launch(
        server_name="127.0.0.1",
        show_error=True,
        inbrowser=True,
        show_api=False,
        quiet=True,
    )
