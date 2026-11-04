"""Turn the frames a run streamed into a video of what the glasses saw, at their real timing.

    make pov                        the newest recording with a stream/ folder
    uv run --project server python server/scripts/pov_video.py <recording> [out.mp4]

The frames exist only when the server ran with ITLOGS_RECORD_STREAM=1. The file name of each frame
is its time in milliseconds since Start, so the video lines up with the rest of the footage.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def concat_list(frames: list[Path]) -> str:
    """ffmpeg's list of frames, each held until the next one arrived."""
    out = []
    for now, after in zip(frames, frames[1:], strict=False):
        out.append(f"file '{now}'\nduration {(int(after.stem) - int(now.stem)) / 1000:.3f}")
    out.append(f"file '{frames[-1]}'\nduration 0.150\nfile '{frames[-1]}'")
    return "\n".join(out) + "\n"


def main() -> int:
    if len(sys.argv) < 2:
        sys.exit("usage: pov_video.py <recording folder> [out.mp4], or a folder of recordings")
    folder = Path(sys.argv[1])
    if not (folder / "stream").is_dir():
        runs = sorted(p.parent for p in folder.glob("*/stream") if p.is_dir())
        if not runs:
            sys.exit(f"no stream/ folder under {folder}: was ITLOGS_RECORD_STREAM=1 on?")
        folder = runs[-1]
    frames = sorted(p for p in (folder / "stream").glob("[0-9]*.jpg"))
    if len(frames) < 2:
        sys.exit(f"fewer than two frames in {folder / 'stream'}")
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else folder / "pov.mp4"
    listing = folder / "pov-frames.txt"
    listing.write_text(concat_list(frames))
    command = [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(listing),
    ]
    command += ["-vf", "fps=30,format=yuv420p", "-c:v", "libx264", "-crf", "18", str(out)]
    subprocess.run(command, check=True)
    seconds = (int(frames[-1].stem) - int(frames[0].stem)) / 1000
    print(f"{out}: {len(frames)} frames, {seconds:.0f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
