# ZeroAI

**ZeroAI** is a Windows-only AI Influencer Video Studio built around MiniMax H3 workflows.

Drop in reference photos of an AI model/influencer, describe a topic or direction, let ZeroAI split the idea into short H3-friendly scenes, generate those scenes through ComfyUI, and stitch the results into one finished MP4.

## v0.1 features

- Windows-only PySide6 desktop UI
- Drag/drop up to 9 influencer reference images
- 15 / 30 / 45 / 60 / 90 / 120 second projects
- 9:16, 16:9 and 1:1 formats
- UGC/TikTok, Vlog, Cinematic, Commercial, Storytime and News Presenter styles
- Automatic scene planning
- Optional local Ollama planner for better hooks/dialogue
- Scene-by-scene prompt inspection/editing
- MiniMax H3 generation through ComfyUI's HTTP API
- Automatic reference image upload
- Queue/poll/download flow for every scene
- Automatic final MP4 stitching with FFmpeg
- Built-in video preview
- Save/open `.zeroai.json` projects
- Portable Windows build via PyInstaller
- GitHub Actions Windows build artifact

## How the H3 integration works

ZeroAI talks to a running ComfyUI instance (default `http://127.0.0.1:8188`). In **Settings**, select an H3 workflow exported in ComfyUI's **API format**.

ZeroAI supports placeholder tokens inside that workflow:

| Token | Value |
|---|---|
| `{{PROMPT}}` | generated scene prompt |
| `{{WIDTH}}` | target width |
| `{{HEIGHT}}` | target height |
| `{{DURATION}}` | scene seconds |
| `{{FRAMES}}` | seconds × 24 |
| `{{SEED}}` | random seed |
| `{{REFERENCE_1}}` … `{{REFERENCE_9}}` | uploaded ComfyUI input image names |

Put these tokens into the appropriate node inputs before exporting the workflow API JSON. This keeps ZeroAI compatible with official H3 workflows and community low-VRAM variants instead of hard-coding one exact node graph.

## Recommended H3 mode for influencers

Use MiniMax H3 **Ref2VA / reference-to-video** when character identity is important. H3 supports multiple reference images and synchronized audio/video generation. The official ComfyUI H3 workflow is the best starting point.

## Quick start

1. Install Python 3.12 on Windows.
2. Install and start ComfyUI with a working MiniMax H3 Ref2VA workflow.
3. Double-click `run_zeroai.bat`.
4. Open **Settings** and select your exported H3 API workflow JSON.
5. Add influencer reference images.
6. Type the topic/direction.
7. Click **Plan Scenes**, review them if desired, then **Generate Video**.

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

MiniMax H3 is a large model. ZeroAI is the controller/UI; generation performance and VRAM requirements depend on the H3 workflow and model variant you install in ComfyUI.

Review the MiniMax H3 license before redistribution or commercial deployment, and clearly disclose AI-generated content where required.
