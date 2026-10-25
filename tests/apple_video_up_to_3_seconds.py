#!/usr/bin/env python3
"""Preview, move or restore iPhone videos using an exact 3.100-second cutoff.

macOS setup:
    brew install ffmpeg

Preview videos eligible to move:
    python3 apple_video_max_3_1_seconds.py
Move only videos whose measured duration is <= 3.100 seconds:
    python3 apple_video_max_3_1_seconds.py --move

Undo an earlier over-broad "under 4 seconds" move (dry run first):
    python3 apple_video_max_3_1_seconds.py --restore-over-limit
    python3 apple_video_max_3_1_seconds.py --restore-over-limit --move

Default source: ~/Desktop/AppleVideoCheckOrigin
Default moved-video folder: ~/Desktop/AppleVideoUpTo3Seconds

Video duration is measured by ffprobe. This script uses unrounded seconds,
checks both video stream and container duration (the maximum, to be
conservative), and never overwrites existing destination files.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import sys
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

DEFAULT_LIMIT = Decimal("3.100")
VIDEO_EXTENSIONS = {".mov", ".m4v", ".3gp"}


def parse_seconds(value: object) -> Decimal | None:
    """Parse ffprobe's precise decimal string; ignore missing/invalid values."""
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return number if number.is_finite() and number > 0 else None


def get_duration(video: Path) -> tuple[Decimal | None, str]:
    """Measure video duration; use max(video-stream, container) for safety.

    A QuickTime MOV can have slightly different track and container durations.
    Using the larger prevents a 4-second clip from being classified as <=3.1
    merely because one stream reports a shorter duration.
    """
    command = [
        "ffprobe", "-v", "error", "-show_entries",
        "format=duration:stream=codec_type,duration,duration_ts,time_base",
        "-of", "json", str(video),
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
    except OSError as exc:
        return None, f"Cannot run ffprobe: {exc}"
    if result.returncode != 0:
        return None, f"ffprobe failed: {(result.stderr or '').strip()[:250]}"
    try:
        metadata = json.loads(result.stdout)
    except (ValueError, TypeError):
        return None, "Invalid ffprobe JSON"

    video_streams = [
        stream for stream in metadata.get("streams", [])
        if stream.get("codec_type") == "video"
    ]
    if not video_streams:
        return None, "No video stream"

    candidates: list[Decimal] = []
    container = parse_seconds(metadata.get("format", {}).get("duration"))
    if container is not None:
        candidates.append(container)

    for stream in video_streams:
        stream_seconds = parse_seconds(stream.get("duration"))
        if stream_seconds is not None:
            candidates.append(stream_seconds)
        # Some videos report a track duration only as ticks / time_base.
        duration_ticks = parse_seconds(stream.get("duration_ts"))
        fraction = stream.get("time_base")
        if duration_ticks is not None and isinstance(fraction, str) and "/" in fraction:
            top, bottom = fraction.split("/", 1)
            try:
                numerator, denominator = Decimal(top), Decimal(bottom)
                if denominator > 0 and numerator > 0:
                    candidates.append(duration_ticks * numerator / denominator)
            except InvalidOperation:
                pass

    if not candidates:
        return None, "Duration not provided by ffprobe"
    return max(candidates), ""


def has_live_id(video: Path) -> tuple[bool, str]:
    """Optional Apple content ID gate: a short MOV is not necessarily Live Photo."""
    try:
        process = subprocess.run(
            ["exiftool", "-s3", "-ContentIdentifier", str(video)],
            capture_output=True, text=True, check=False,
        )
    except OSError as exc:
        return False, f"Cannot run exiftool: {exc}"
    if process.returncode:
        return False, (process.stderr or "exiftool failed").strip()[:200]
    return bool(process.stdout.strip()), ""


def free_destination(destination: Path, reserved: set[Path]) -> Path:
    """Never overwrite files, including files scheduled earlier in this run."""
    result = destination
    n = 2
    while result.exists() or result in reserved:
        result = destination.with_name(f"{destination.stem}__copy{n}{destination.suffix}")
        n += 1
    reserved.add(result)
    return result


def run(args: argparse.Namespace) -> int:
    source = args.source.expanduser().resolve()
    moved_folder = args.output.expanduser().resolve()
    restore_mode = args.restore_over_limit
    scan_folder = moved_folder if restore_mode else source
    destination_folder = source if restore_mode else moved_folder

    if source == moved_folder or source in moved_folder.parents or moved_folder in source.parents:
        print("ERROR: Source and output folders must be separate, not nested.", file=sys.stderr)
        return 2
    if not scan_folder.is_dir():
        print(f"ERROR: Folder not found: {scan_folder}", file=sys.stderr)
        return 2
    if shutil.which("ffprobe") is None:
        print("ERROR: ffprobe missing; install with: brew install ffmpeg", file=sys.stderr)
        return 2
    if args.require_live_id and shutil.which("exiftool") is None:
        print("ERROR: exiftool missing; install with: brew install exiftool", file=sys.stderr)
        return 2

    extensions = {".mov"} if args.mov_only else VIDEO_EXTENSIONS
    files = sorted(
        (p for p in scan_folder.rglob("*") if p.is_file() and not p.is_symlink()
         and p.suffix.lower() in extensions),
        key=lambda p: str(p).lower(),
    )
    limit = DEFAULT_LIMIT
    action = "RESTORE" if restore_mode else "MOVE"
    print(f"Mode: {action} {'(ACTIVE)' if args.move else '(PREVIEW ONLY)'}")
    print(f"Scanning: {scan_folder}")
    print(f"Destination: {destination_folder}")
    print(f"Exact rule: {'duration >' if restore_mode else 'duration <='} {limit:.3f} seconds")
    print(f"Video files found: {len(files)}\n", flush=True)

    rows: list[dict[str, str]] = []
    reserved: set[Path] = set()
    selected = moved = kept = failures = 0
    for i, video in enumerate(files, 1):
        relative = video.relative_to(scan_folder)
        seconds, problem = get_duration(video)
        status = ""
        dest = ""
        if problem:
            status = "ERROR"
            failures += 1
        else:
            selected_by_duration = seconds > limit if restore_mode else seconds <= limit
            if not selected_by_duration:
                kept += 1
                status = "KEEP"
            else:
                if args.require_live_id:
                    has_id, id_problem = has_live_id(video)
                    if id_problem:
                        problem = id_problem
                        status = "ERROR"
                        failures += 1
                    elif not has_id:
                        status = "KEEP (NO LIVE ID)"
                        kept += 1
                if not status:
                    selected += 1
                    target = free_destination(destination_folder / relative, reserved)
                    dest = str(target)
                    if args.move:
                        try:
                            target.parent.mkdir(parents=True, exist_ok=True)
                            shutil.move(str(video), str(target))
                            status = "RESTORED" if restore_mode else "MOVED"
                            moved += 1
                        except OSError as exc:
                            status = "ERROR"
                            problem = f"Unable to move: {exc}"
                            failures += 1
                    else:
                        status = "WOULD_RESTORE" if restore_mode else "WOULD_MOVE"

        duration_display = f"{seconds:.3f}s" if seconds is not None else "unknown"
        print(f"[{i:>4}/{len(files)}] {status:<18} {duration_display:>10}  {relative}", flush=True)
        rows.append({
            "filename": str(relative),
            "duration_seconds": str(seconds) if seconds is not None else "",
            "status": status,
            "source": str(video),
            "destination": dest,
            "error": problem,
        })

    # Keep reports separate from videos. The reports do not affect subsequent scans.
    reports_dir = source.parent / "AppleVideoDurationReports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    report = reports_dir / f"{'restore' if restore_mode else 'filter'}_{stamp}.csv"
    with report.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["filename", "duration_seconds", "status", "source", "destination", "error"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nSummary: selected={selected}, actually moved={moved}, kept={kept}, errors={failures}")
    print(f"CSV report: {report}")
    if not args.move:
        print("Preview only: add --move to make the changes.")
    if restore_mode:
        print("Videos measuring <= 3.100 seconds remain in the short-video folder.")
    else:
        print("Videos measuring > 3.100 seconds remain in the source folder.")
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Move videos <=3.100s; optionally return longer videos moved by an older script.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "source", nargs="?", type=Path,
        default=Path.home() / "Desktop" / "AppleVideoCheckOrigin",
        help="Original video folder; subfolders scanned recursively",
    )
    parser.add_argument(
        "--output", type=Path,
        default=Path.home() / "Desktop" / "AppleVideoUpTo3Seconds",
        help="Folder for selected short videos (and old folder to inspect when restoring)",
    )
    parser.add_argument("--move", action="store_true", help="Actually move files (otherwise preview only)")
    parser.add_argument(
        "--restore-over-limit", action="store_true",
        help="Return videos >3.100s from --output to the original source; preview unless --move",
    )
    parser.add_argument("--mov-only", action="store_true", help="Only handle MOV videos")
    parser.add_argument(
        "--require-live-id", action="store_true",
        help="Only handle videos with an Apple Live Photo content identifier (requires exiftool)",
    )
    args = parser.parse_args(argv)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
