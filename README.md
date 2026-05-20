# Reels Postpro

Desktop application for Instagram Reels post-production under the Sapiens visual identity. Cleans the audio (high-pass + DeepFilterNet 3 denoising + loudnorm to -16 LUFS), transcribes Spanish speech with OpenAI Whisper small, and burns Sapiens styled Quote-Card subtitles using libass through ffmpeg. Optional OpenCV face detection keeps the hook clear of the speaker's face.

Built with a Gradio web UI for end-to-end editing of the subtitle table before render. CPU only, runs locally without GPU.

## Features

* **5-stage CPU pipeline**: extract audio, high-pass 80 Hz, DeepFilterNet 3 denoise, loudnorm to -16 LUFS, mux back with the original video (`-c:v copy`).
* **Spanish transcription** via Whisper small with word-level timestamps.
* **Quote-Card subtitle style** (Sapiens): a single CAPS hook left-aligned with decorative quotes in the accent color, plus body blocks of 2 to 3 words in white.
* **Inline keyword highlighting** by wrapping a word in `*asterisks*` in the editable table; that word is rendered in the accent color (teal `#2B9E8F` or gold `#E8A838`).
* **Editable cue table** in the Gradio UI: text, timing and role (hook / body) can be corrected before re-rendering.
* **Automatic hook placement** using OpenCV Haar cascade face detection over the hook timespan, with a manual override (bottom) when needed.
* **Per-upload session directory** under `workspace/sessions/<uuid>/` keeps every intermediate artifact for inspection (raw HP wav, denoised wav, normalized wav, Whisper JSON, cues, SRT, ASS, final mp4).

## Pipeline

```
Raw video (.mp4 / .mov)
   |
   v
1. Audio
     extract  ->  high-pass 80 Hz  ->  DeepFilterNet 3  ->  loudnorm -16 LUFS
   |
   v
2. Mux clean audio + original video (-c:v copy)
   |
   v
3. Whisper small (es, word_timestamps)
   |
   v
4. Subtitles (Quote-Card style)
     Hook  = full opening sentence, CAPS left-aligned, " + keyword in accent color
     Body  = 2 to 3 word blocks, white Outfit Black
   |
   v
5. Final render
     ffmpeg -vf ass=... -c:v libx264 -crf 18 -preset slow
     MarginV in the IG vertical safe zone
```

## Tech Stack

* Python 3.11+
* [Gradio](https://www.gradio.app/) 5.x for the web UI
* [OpenAI Whisper](https://github.com/openai/whisper) small, Spanish, word timestamps
* [DeepFilterNet](https://github.com/Rikorose/DeepFilterNet) 3 for speech enhancement
* [OpenCV](https://opencv.org/) Haar cascades for face detection
* PyTorch 2.2 CPU + Torchaudio
* ffmpeg full build (libass + libx264) on PATH

## Installation

Prerequisites on PATH:

* Python 3.11+
* ffmpeg full build from https://www.gyan.dev/ffmpeg/builds/ (the libass enabled one)

```powershell
git clone https://github.com/mateo-ortega/reels-postpro.git
cd reels-postpro
powershell -ExecutionPolicy Bypass -File install.ps1
```

The install script:

1. Verifies ffmpeg is reachable.
2. Creates `.venv\` with the system Python.
3. Installs PyTorch CPU (~200 MB) + Whisper + DeepFilterNet + Gradio.
4. Stages Sapiens fonts into `assets\fonts\`. The renderer expects `Outfit-Black.ttf` in that directory; place it manually if you do not have a Sapiens font bundle to copy from.

First Whisper run downloads the `small` model (~466 MB) into your HuggingFace cache.

## Usage

```powershell
.\.venv\Scripts\Activate.ps1
python app.py
```

The UI opens at http://localhost:7860.

### Workflow

1. Upload a vertical Reel (`.mp4` or `.mov`).
2. Tune the options if needed:
   * **Words per body block** (2 or 3, default 3).
   * **Max hook duration** (1 to 30 s, default 30 s, used to cap the opening sentence).
   * **Accent color**: `teal` (#2B9E8F) or `gold` (#E8A838).
   * **Hook position**: `auto` (face-aware) or `abajo` (force bottom).
3. Click **Procesar audio + transcribir**.
4. Review the **subtitle table**:
   * Edit the text if Whisper misheard a word.
   * Adjust timing if needed.
   * Change `role` (`hook` or `body`) to reassign blocks.
   * Wrap the primary keyword in `*asterisks*` to highlight it in the accent color (example: `INTENTAR PROHIBIR *INTELIGENCIA ARTIFICIAL* EN CASA`).
5. Click **Guardar cambios** (writes `cues.json`, `subtitles.srt`, `subtitles.ass`).
6. Click **Renderizar final**.
7. Preview or download `final.mp4`.

## Project Structure

```
reels-postpro/
├── app.py                            Gradio UI entry point
├── install.ps1                       One-shot Windows installer
├── requirements.txt
├── LICENSE
├── README.md
├── pipeline/
│   ├── audio.py                      High-pass, DeepFilterNet, loudnorm, mux
│   ├── transcribe.py                 Whisper small ES
│   ├── subtitles.py                  Cue model, SRT and ASS (Sapiens) writers
│   ├── render.py                     ffmpeg subtitle burn (auto-install fonts)
│   ├── face.py                       OpenCV face detection for hook layout
│   └── paths.py                      Session management and cleanup
├── scripts/
│   └── preview_subtitle_style.py     Standalone ASS style preview helper
├── assets/
│   └── fonts/                        Brand fonts (populated by install.ps1)
└── workspace/
    └── sessions/<uuid>/              Per-upload working directory (gitignored)
        ├── original.mp4|mov
        ├── 01_raw_hp.wav             after high-pass
        ├── 02_denoised.wav           after DeepFilterNet
        ├── 03_normalized.wav         after loudnorm -16 LUFS
        ├── video_clean.mp4           original video + clean audio
        ├── whisper_result.json       raw Whisper output
        ├── cues.json                 source of truth for subtitles
        ├── subtitles.srt             readable export
        ├── subtitles.ass             Sapiens styled (regenerated on each render)
        ├── face_envelope.json        face detection result over the hook
        └── final.mp4                 final video with burned-in subtitles
```


## End-to-end Verification

1. Upload a vertical ~15 s `.mp4` clip.
2. After processing, open `workspace\sessions\<id>\` and compare `01_raw_hp.wav` against `03_normalized.wav` in Audacity. The second should sound clean and consistently leveled.
3. The cue table should show one `role=hook` row (all caps) and N `role=body` rows (2 to 3 words each).
4. Render and play `final.mp4`:
   * Hook in the accent color, body in white.
   * Subtitles sit above the Instagram caption area (MarginV ~ 360).
5. Repeat with a `.mov` from an iPhone, should behave identically.

Loudness check:

```powershell
ffmpeg -i workspace\sessions\<id>\03_normalized.wav -af loudnorm=I=-16:print_format=summary -f null -
```

`Input Integrated` should land near `-16 LUFS`.


## Troubleshooting

* **"ffmpeg not found"**: install the full Gyan build and add it to PATH.
* **Robotic voice after denoising**: in the advanced options, lower DeepFilterNet `--atten-lim` to 50 or 30.
* **Silent audio in `final.mp4`**: verify `03_normalized.wav` is not empty, otherwise check the loudnorm log in the console.
* **Whisper takes too long**: expected on CPU, a 60 s Reel takes ~3 to 5 minutes.
* **Fonts not rendering**: confirm `assets\fonts\Outfit-Black.ttf` exists, then re-run `install.ps1`. On Windows the renderer also copies the fonts into `%LOCALAPPDATA%\Microsoft\Windows\Fonts` so libass can pick them up without `fontsdir`.

## License

[MIT](LICENSE)

## Author

**Mateo Ortega**
[teo.ritmos@gmail.com](mailto:teo.ritmos@gmail.com) · [github.com/mateo-ortega](https://github.com/mateo-ortega)
