# ZeroAI

**ZeroAI** is a Windows-only AI Influencer Video Studio built around MiniMax H3 workflows.

Drop in reference photos of an AI model/influencer, describe a topic or direction, let ZeroAI split the idea into short H3-friendly scenes, generate those scenes through ComfyUI, and stitch the results into one finished MP4.

## v0.3.0 — performance controls + live progress

- **Real ComfyUI sampler progress** over WebSocket instead of sitting at 0% until a scene finishes.
- Generation status now shows phases such as **Loading H3 model**, **Encoding references**, **Sampling 5/12**, **Decoding**, **Muxing**, **Saving**, and **Downloading**.
- Sampling status includes an ETA once enough real progress has been observed.
- New **Settings → H3 Performance** panel.
- **Auto (GPU-aware)** preset reads ComfyUI `/system_stats` and selects a safer profile based on VRAM/RAM.
- Built-in **RTX 3060 Laptop / Low VRAM** preset: `0.40 MP`, `12 steps`, first `3` references, `ref_image_size=match`.
- Fast Preview, Balanced, Native Quality, and Custom presets.
- Resolution can be set to `0.40`, `0.70`, `0.90`, or native `0.98 MP`.
- Sampling steps can be set from 4–40.
- Reference limit can be set from 1–9 so low-memory machines do not pay the cost of all nine references on every scene.
- Reference image sizing can use `match` (faster / lower memory) or `max` (stronger identity / slower).
- H3 no longer forces every render back to the native 0.98 MP canvas when a lower preview resolution is selected.

### Recommended RTX 3060 Laptop settings

For a typical RTX 3060 Laptop GPU with about 6 GB VRAM and 16 GB system RAM, start with:

```text
Preset:          Auto (GPU-aware) or RTX 3060 Laptop / Low VRAM
Resolution:      0.40 MP
Steps:           12
Reference limit: 3
Reference size:  match
```

For a final render, try `0.70 MP` and 16–20 steps if the preview is stable. Native `0.98 MP / 20 steps` is the H3 quality target but can be extremely slow on a 6 GB laptop GPU because the 33B model has to offload heavily to system memory.

## v0.2.1 hotfix

- Fixes Comfy Desktop installations that keep models in a shared/launcher-managed directory instead of `<ComfyUI>\models`.
- Reads the **running ComfyUI process arguments** from `/system_stats` and follows `--models-directory`, `--base-directory`, and `--extra-model-paths-config`.
- Understands current Comfy Desktop shared model libraries plus the legacy Desktop `basePath` configuration.
- Automatically replaces stale v0.2 model paths with the model library actually used by the running backend.
- **Reuses already-downloaded H3 files** from the old v0.2 location. On the same NTFS volume ZeroAI uses hard links, so there is no second 43 GB copy; otherwise it moves the files before attempting any new download.
- Settings reports H3 status against the **active** model library, matching what ComfyUI itself sees.

## Core features

- Windows-only PySide6 desktop UI
- Drag/drop up to 9 influencer reference images
- 15 / 30 / 45 / 60 / 90 / 120 second projects
- 9:16, 16:9 and 1:1 formats
- UGC/TikTok, Vlog, Cinematic, Commercial, Storytime and News Presenter styles
- Automatic scene planning
- Optional local Ollama planner for better hooks/dialogue
- Scene-by-scene prompt inspection/editing
- MiniMax H3 Ref2VA generation through ComfyUI's HTTP API
- **Built-in ZeroAI H3 API workflows — no manual JSON setup required**
- **Adaptive 1–9 reference workflow selection**
- **Automatic ComfyUI model-library detection on Windows**
- **One-click Download / Repair H3 setup**
- **Resumable official model downloads with progress and disk-space checks**
- **H3 readiness checks before generation**
- Automatic H3 canvas and frame-grid normalization
- Automatic reference image upload
- Queue/progress/download flow for every scene
- Automatic final MP4 stitching with FFmpeg
- Built-in video preview
- Save/open `.zeroai.json` projects
- Portable Windows build via PyInstaller
- GitHub Actions Windows build artifact

## MiniMax H3 setup

ZeroAI talks to a running ComfyUI instance, normally at `http://127.0.0.1:8188`.

Open **Settings → MiniMax H3 — One-Click Setup**. ZeroAI first reads the model paths used by the running ComfyUI backend. This matters for **Comfy Desktop**, where the active model library can be a shared folder separate from the ComfyUI source/install directory.

Click **Download / Repair H3**. ZeroAI first searches known old/current model locations for existing H3 files and reuses them when possible. Only files that are still genuinely missing are downloaded from the official Comfy-Org repository.

The full stack is roughly 43 GB and includes:

```text
models\diffusion_models\
  minimax_h3_ref2va_pruned_int8_convrot.safetensors

models\text_encoders\
  qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors

models\vae\
  minimax_h3_video_vae_fp16.safetensors
  minimax_h3_audio_vae_fp32.safetensors
```

Downloads resume from `.part` files after interruption. When setup/repair finishes, completely restart ComfyUI so it rescans the model folders.

## Built-in H3 workflow

ZeroAI defaults to its own compact **MiniMax H3 Ref2VA API workflow**. It automatically adapts to however many influencer reference images are currently attached, from 1 through 9.

Ready-to-edit JSON copies are also written to:

```text
%LOCALAPPDATA%\ZeroAI\workflows\
```

You can still select a custom ComfyUI API workflow in Settings. Custom workflows continue to support these placeholder tokens:

| Token | Value |
|---|---|
| `{{PROMPT}}` | generated scene prompt |
| `{{WIDTH}}` | target width |
| `{{HEIGHT}}` | target height |
| `{{DURATION}}` | scene seconds |
| `{{FRAMES}}` | scene frame count |
| `{{SEED}}` | random seed |
| `{{REFERENCE_1}}` … `{{REFERENCE_9}}` | uploaded ComfyUI input image names |

For MiniMax H3 workflows, ZeroAI normalizes the canvas to a multiple of 32 and snaps duration to the model's `17k+5` frame grid at 24 fps. The selected H3 Performance resolution controls the target pixel count, capped at H3's native canvas.

## Quick start

1. Install/start an up-to-date ComfyUI or Comfy Desktop on Windows.
2. Launch ZeroAI.
3. Open **Settings**.
4. Click **Detect** while ComfyUI is running; ZeroAI will resolve the active model library.
5. Click **Download / Repair H3** if H3 is not ready.
6. In **H3 Performance**, leave **Auto (GPU-aware)** selected or choose a preset.
7. Restart ComfyUI after model repair/install if needed.
8. Add your influencer reference images in ZeroAI.
9. Type the topic/direction.
10. Click **Plan Scenes**, review them if desired, then **Generate Video**.

### Optional local AI planner

Install Ollama and a small instruct model, then set **Planner → Ollama (local)** in ZeroAI Settings. If Ollama fails, ZeroAI automatically falls back to its built-in scene planner.

## Build the portable Windows app

Run:

```bat
build_windows.bat
```

The portable ZIP is written to:

```text
dist\ZeroAI-Windows-x64.zip
```

No installer is required.

## Notes

MiniMax H3 is a very large model. ZeroAI is the controller/UI; generation performance and memory pressure depend on your GPU, ComfyUI configuration, resolution, step count, scene duration, and number of reference images.

Review the MiniMax H3 license before redistribution or commercial deployment, and clearly disclose AI-generated content where required.
