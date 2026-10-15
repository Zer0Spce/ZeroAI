from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import imageio_ffmpeg


def stitch_videos(clips: list[str | Path], output_path: str | Path) -> Path:
    paths = [Path(p) for p in clips if Path(p).exists()]
    if not paths:
        raise RuntimeError("No generated scene clips were found")

    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if len(paths) == 1:
        shutil.copy2(paths[0], target)
        return target

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    concat_file = target.with_suffix(".concat.txt")
    concat_file.write_text("\n".join(f"file '{str(p.resolve())}'" for p in paths), encoding="utf-8")

    copy_cmd = [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file), "-c", "copy", str(target)]
    result = subprocess.run(copy_cmd, capture_output=True, text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode != 0:
        encode_cmd = [
            ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file),
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(target),
        ]
        result = subprocess.run(encode_cmd, capture_output=True, text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if result.returncode != 0:
            raise RuntimeError(result.stderr[-2000:] or "FFmpeg failed to stitch the scenes")
    concat_file.unlink(missing_ok=True)
    return target
