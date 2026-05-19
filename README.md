# Reels Postpro — Sapiens

Postproducción local de Reels de Instagram bajo la identidad visual de Sapiens.
Sube `.mp4` o `.mov`, limpia el audio, transcribe, edita subtítulos en una tabla
y descarga el video final con subtítulos quemados al estilo Sapiens.

---

## Pipeline

```
Video crudo (.mp4 o .mov)
   ↓
1. Audio (prioridad)
     extract  →  high-pass 80Hz  →  DeepFilterNet 3  →  loudnorm -16 LUFS
   ↓
2. Mux audio limpio + video original (-c:v copy)
   ↓
3. Whisper small (es, word_timestamps)
   ↓
4. Subtítulos (estilo Quote-Card)
     Hook  = frase completa de apertura, CAPS left-aligned, " + keyword en color acento
     Body  = bloques de 2-3 palabras, blanco Outfit Black
   ↓
5. Render final
     ffmpeg -vf ass=… -c:v libx264 -crf 18 -preset slow
     MarginV=420 (safe zone IG)
```

---

## Instalación (una sola vez)

Requisitos previos en `PATH`:

- Python 3.11+
- ffmpeg (full build de https://www.gyan.dev/ffmpeg/builds/)

```powershell
cd reels-postpro
powershell -ExecutionPolicy Bypass -File install.ps1
```

El script:
1. Verifica ffmpeg.
2. Crea `.venv\` con Python.
3. Instala PyTorch CPU (≈ 200 MB) + Whisper + DeepFilterNet + Gradio.
4. Copia la font Sapiens (`Outfit-Black.ttf`) desde `..\skills\sapiens-carrusel\assets\` a `assets\fonts\`.

La primera ejecución de Whisper descarga el modelo `small` (~466 MB) a tu cache HF.

---

## Uso

```powershell
cd reels-postpro
.\.venv\Scripts\Activate.ps1
python app.py
```

La UI abre en http://localhost:7860.

### Flujo

1. **Subir video** (`.mp4` o `.mov`).
2. Ajustar opcionalmente:
   - **Palabras por bloque** (2 ó 3, default 3).
   - **Duración máxima del hook** (5-30 s, default 30 s — frase completa de apertura).
   - **Color de acento**: `teal` (#2B9E8F) o `gold` (#E8A838).
3. Click en **Procesar audio + transcribir**.
4. Cuando termine, revisar la **tabla de subtítulos**:
   - Editar texto si Whisper se equivocó.
   - Ajustar timing si hace falta.
   - Cambiar `role` (`hook` o `body`) si necesitas reasignar.
   - Marcar la keyword principal con `*asteriscos*` para resaltarla en el color de acento (ej: `INTENTAR PROHIBIR *INTELIGENCIA ARTIFICIAL* EN CASA`).
5. Click en **Guardar cambios** (escribe `cues.json`, `subtitles.srt`, `subtitles.ass`).
6. Click en **Renderizar final**.
7. Reproducir el preview o descargar `final.mp4`.

### Opciones avanzadas (acordeón)

- `--atten-lim` de DeepFilterNet (30-100, default 100). Bajalo si la voz suena "robótica" en clips muy ruidosos.
- Saltar high-pass / loudnorm (no recomendado).

---

## Estructura

```
reels-postpro/
├── app.py                         # UI Gradio
├── install.ps1                    # instalador one-shot
├── requirements.txt
├── pipeline/
│   ├── audio.py                   # high-pass + DeepFilterNet + loudnorm + mux
│   ├── transcribe.py              # Whisper small ES
│   ├── subtitles.py               # Cue, SRT, ASS Sapiens
│   ├── render.py                  # ffmpeg burn final
│   └── paths.py                   # sesiones + cleanup
├── assets/fonts/                  # Outfit-Bold, InstrumentSans-Bold (poblado por install.ps1)
└── workspace/sessions/<uuid>/     # cada upload genera una sesion aislada
        ├── original.mp4|mov
        ├── 01_raw_hp.wav          # despues de high-pass
        ├── 02_denoised.wav        # despues de DeepFilterNet
        ├── 03_normalized.wav      # despues de loudnorm -16 LUFS
        ├── video_clean.mp4        # video original + audio limpio
        ├── whisper_result.json    # output crudo de Whisper
        ├── cues.json              # source of truth de subtitulos
        ├── subtitles.srt          # export legible
        ├── subtitles.ass          # estilizado Sapiens (regenerado en cada render)
        └── final.mp4              # video con subtitulos quemados
```

---

## Verificación end-to-end

1. Sube un clip vertical de ~15 s `.mp4`.
2. Tras procesar, abre `workspace\sessions\<id>\` y compara `01_raw_hp.wav` vs `03_normalized.wav` en Audacity — el segundo debe sonar limpio y al mismo nivel.
3. La tabla muestra 1 fila `role=hook` (todo MAYÚSCULAS) y N filas `role=body` (2-3 palabras).
4. Renderiza y reproduce `final.mp4`:
   - Hook en gold, body en blanco.
   - Subtítulos por encima de la zona de captions de IG (MarginV ≈ 420).
5. Repite con un `.mov` de iPhone — debe funcionar idéntico.

Verificación de loudness:
```powershell
ffmpeg -i workspace\sessions\<id>\03_normalized.wav -af loudnorm=I=-16:print_format=summary -f null -
```
`Input Integrated` debería estar cerca de `-16 LUFS`.

---

## Estilo Sapiens aplicado — Quote-Card

| Elemento | Valor |
|---|---|
| Fuente hook | Outfit Black, 90pt |
| Fuente body | Outfit Black, 72pt |
| Color base | `#FFFFFF` (blanco) |
| Color acento | `#2B9E8F` teal (default) o `#E8A838` gold |
| Outline | Ninguno (Outline=0) |
| Shadow | 2px blur |
| Tracking | -1 (HOOK_SPACING) |
| Alineación | Bottom-left (Alignment=1 en ASS) |
| MarginV | 360 (safe zone IG vertical 1080×1920) |
| MarginL/R | 75 |
| Hook | CAPS, comillas `"` en acento inline, keyword `*...*` en acento |
| Hook wrap | Máx 18 chars por línea a 90pt |
| Hook duración | Frase completa (hasta 30 s) |
| Body | 2-3 palabras por bloque, fade in/out 120 ms |
| Codec final | libx264, CRF 18, preset slow, yuv420p |

---

## Limitaciones conocidas

- Solo CPU (este equipo no tiene GPU NVIDIA). Whisper-small en CPU procesa ~30-60 s por minuto de audio.
- Solo español (`language="es"`).
- Un video por vez (no batch).
- No sube a Drive ni publica — descarga manual.

## Troubleshooting

- **"ffmpeg no encontrado"** → instala el full build de Gyan y agrégalo al PATH.
- **Voz "robótica" después del denoise** → en Opciones avanzadas, baja `--atten-lim` a 50 ó 30.
- **Audio mudo en final.mp4** → verifica que `03_normalized.wav` no esté vacío; si lo está, revisa el log de loudnorm en consola.
- **Whisper tarda mucho** → con CPU es esperado; un Reel de 60 s tarda ~3-5 min.
- **Fonts no aparecen** → verifica `assets\fonts\Outfit-Black.ttf`. Re-corre `install.ps1`.
