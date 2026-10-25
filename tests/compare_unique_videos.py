#!/usr/bin/env python3
"""Move videos with filenames not present in another folder (macOS friendly).

Examples:
  python3 compare_unique_videos.py             # preview only
  python3 compare_unique_videos.py --move      # move unmatched videos from Origin
  python3 compare_unique_videos.py --both --move  # unmatched videos from both folders

Filename comparison is case-insensitive and INCLUDES the file extension:
    007.MP4 vs 007.mp4  -> duplicate
    007.MP4 vs 007.MOV  -> different

This is intentionally a *filename* comparison, not a file-content comparison.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime
from pathlib import Path
import shutil
import sys
import unicodedata

VIDEO_EXTENSIONS = {
    ".mov", ".mp4", ".m4v", ".avi", ".mkv", ".3gp", ".webm",
    ".mpg", ".mpeg", ".mts", ".m2ts", ".wmv", ".flv", ".ts",
}


def filename_key(path: Path) -> str:
    """Compare whole names, including extensions, without case differences."""
    return unicodedata.normalize("NFC", path.name).casefold()


def collect_videos(folder: Path) -> list[Path]:
    """Recursively collect regular videos; don't move symbolic links."""
    return sorted(
        (
            path for path in folder.rglob("*")
            if path.is_file()
            and not path.is_symlink()
            and path.suffix.casefold() in VIDEO_EXTENSIONS
        ),
        key=lambda p: str(p).casefold(),
    )


def is_inside(path: Path, directory: Path) -> bool:
    try:
        path.relative_to(directory)
        return True
    except ValueError:
        return False


def parse_args() -> argparse.Namespace:
    desktop = Path.home() / "Desktop"
    parser = argparse.ArgumentParser(
        description="Find videos with filenames missing from the other folder. "
                    "Preview by default; use --move to move the unmatched videos."
    )
    parser.add_argument(
        "--origin", type=Path, default=desktop / "AppleVideoCheckOrigin",
        help="Original folder to scan (default: ~/Desktop/AppleVideoCheckOrigin)",
    )
    parser.add_argument(
        "--check", type=Path, default=desktop / "AppleVideoCheck",
        help="Comparison folder (default: ~/Desktop/AppleVideoCheck)",
    )
    parser.add_argument(
        "--output", type=Path, default=desktop / "AppleVideoUnique",
        help="Destination for unmatched videos (default: ~/Desktop/AppleVideoUnique)",
    )
    parser.add_argument(
        "--move", action="store_true",
        help="Actually move unmatched videos (otherwise only preview)",
    )
    parser.add_argument(
        "--both", action="store_true",
        help="Move videos unique to EITHER folder, not just Origin. "
             "Results are separated into subfolders named after their sources.",
    )
    parser.add_argument(
        "--show", type=int, default=25,
        help="Maximum number of preview matches to display (default: 25)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    origin = args.origin.expanduser().resolve()
    check = args.check.expanduser().resolve()
    output = args.output.expanduser().resolve()

    for label, folder in (("Origin", origin), ("Check", check)):
        if not folder.is_dir():
            print(f"ERROR: {label} folder doesn't exist: {folder}", file=sys.stderr)
            return 2

    if origin == check:
        print("ERROR: Origin and Check must be different folders.", file=sys.stderr)
        return 2
    if is_inside(origin, check) or is_inside(check, origin):
        print("ERROR: Origin and Check cannot contain each other.", file=sys.stderr)
        return 2
    if any(is_inside(output, folder) or is_inside(folder, output)
           for folder in (origin, check)):
        print("ERROR: Output must be a separate folder outside both input folders.",
              file=sys.stderr)
        return 2

    print("Scanning folders recursively...")
    origin_files = collect_videos(origin)
    check_files = collect_videos(check)
    origin_names = {filename_key(p) for p in origin_files}
    check_names = {filename_key(p) for p in check_files}

    origin_unique = [p for p in origin_files if filename_key(p) not in check_names]
    check_unique = [p for p in check_files if filename_key(p) not in origin_names]
    origin_duplicates = len(origin_files) - len(origin_unique)
    check_duplicates = len(check_files) - len(check_unique)

    print(f"\nOrigin: {origin} ({len(origin_files)} video files)")
    print(f"Check:  {check} ({len(check_files)} video files)")
    print(f"Move to: {output}")
    print(f"Matched full filenames found in both folders:")
    print(f"  Origin entries skipped: {origin_duplicates}")
    print(f"  Check entries skipped:  {check_duplicates}")
    print(f"Only in Origin: {len(origin_unique)}")
    print(f"Only in Check:  {len(check_unique)}")
    print("Comparison: entire filename + extension; case-insensitive; not file contents.\n")

    planned: list[tuple[Path, Path, str]] = []
    for path in origin_unique:
        relative = path.relative_to(origin)
        target = output / origin.name / relative if args.both else output / relative
        planned.append((path, target, "Origin"))
    if args.both:
        for path in check_unique:
            target = output / check.name / path.relative_to(check)
            planned.append((path, target, "Check"))

    print(f"Mode: {'MOVE' if args.move else 'PREVIEW (nothing moves)'}")
    print(f"Selected unmatched video files: {len(planned)}")
    if not args.move:
        for path, target, _ in planned[:max(0, args.show)]:
            print(f"  {path}  ->  {target}")
        if len(planned) > args.show:
            print(f"  ... plus {len(planned) - args.show} more")
        print("\nRun again with --move to move these files.")
        print("Tip: --both --move will move files unique to either folder.")
        return 0

    if not planned:
        print("No unmatched files to move. Nothing changed.")
        return 0

    moved = existing = errors = 0
    rows = []
    for i, (source, target, side) in enumerate(planned, start=1):
        status = ""
        error = ""
        try:
            # Deliberately never overwrite an existing destination file.
            if target.exists():
                status = "SKIPPED_DESTINATION_EXISTS"
                existing += 1
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(source), str(target))
                status = "MOVED"
                moved += 1
        except (OSError, shutil.Error) as exc:
            status = "ERROR"
            error = str(exc)
            errors += 1
        rows.append({
            "source_folder": side,
            "filename": source.name,
            "source_path": str(source),
            "destination_path": str(target),
            "status": status,
            "error": error,
        })
        print(f"[{i}/{len(planned)}] {status}: {source.name}", flush=True)

    output.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report = output / f"video_move_report_{timestamp}.csv"
    with report.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=[
            "source_folder", "filename", "source_path", "destination_path",
            "status", "error",
        ])
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nDone. Moved: {moved}; skipped (already exists): {existing}; errors: {errors}")
    print(f"Report: {report}")
    print("Source files with duplicate filenames were not touched.")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
