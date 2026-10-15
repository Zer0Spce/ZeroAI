# ZeroAI

**ZeroAI** is a Windows-only AI Influencer Video Studio built around MiniMax H3 workflows.

Drop in reference photos of an AI model/influencer, describe a topic or direction, let ZeroAI split the idea into short H3-friendly scenes, generate those scenes through ComfyUI, and stitch the results into one finished MP4.

## v0.2 features

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
- **Automatic ComfyUI folder detection on Windows**
- **One-click Download / Repair H3 setup**
- **Resumable official model downloads with progress and disk-space checks**
- **H3 readiness checks before generation**
- **Friendly missing-model / outdated-ComfyUI errors instead of raw workflow failures**
- Automatic H3 canvas and frame-grid normalization
- Automatic reference image upload
- Queue/poll/download flow for every scene
- Automatic final MP4 stitching with FFmpeg
- Built-in video preview
- Save/open `.zeroai.json` projects
- Portable Windows build via PyInstaller
- GitHub Actions Windows build artifact

## MiniMax H3 setup

ZeroAI talks to a running ComfyUI instance, normally at `http://127.0.0.1:8188`.

Open **Settings → MiniMax H3 — One-Click Setup**. ZeroAI can detect common Windows ComfyUI locations, or you can browse to the ComfyUI folder once. Click **Download / Repair H3** and ZeroAI downloads the official Comfy-Org Ref2VA stack directly into the correct folders.

The full stack is roughly 43 GB and includes:

```text
ComfyUI\models\diffusion_models\
  minimax_h3_ref2va_pruned_int8_convrot.safetensors

ComfyUI\models\text_encoders\
  qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors

ComfyUI\models\vae\
  minimax_h3_video_vae_fp16.safetensors
  minimax_h3_audio_vae_fp32.safetensors
```

Downloads resume from `.part` files after interruption. When setup finishes, completely restart ComfyUI so it rescans the model folders.

## Built-in H3 workflow

ZeroAI v0.2 defaults to its own compact **MiniMax H3 Ref2VA API workflow**. It automatically adapts to however many influencer reference images are currently attached, from 1 through 9.

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

For MiniMax H3 workflows, ZeroAI automatically normalizes the canvas to H3's native area/multiple-of-32 requirements and snaps duration to the model's `17k+5` frame grid at 24 fps.

## Quick start

1. Install/start an up-to-date ComfyUI on Windows.
2. Launch ZeroAI.
3. Open **Settings**.
4. Detect or browse to your ComfyUI folder.
5. Click **Download / Repair H3** if H3 is not ready.
6. Restart ComfyUI after the model installation completes.
7. Add 1–9 influencer reference images in ZeroAI.
8. Type the topic/direction.
9. Click **Plan Scenes**, review them if desired, then **Generate Video**.

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

MiniMax H3 is a large model. ZeroAI is the controller/UI; generation performance and VRAM requirements depend on your GPU, ComfyUI configuration and H3 model stack.

Review the MiniMax H3 license before redistribution or commercial deployment, and clearly disclose AI-generated content where required.
