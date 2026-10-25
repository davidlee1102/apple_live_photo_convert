# Video Cleanup Utilities

Optional video-organisation tools for the [Apple Live Photo Convert](https://github.com/davidlee1102/apple_live_photo_convert) project.

This README belongs in **`tests/README.md`**, not at the repository root. The main [project README](../README.md) explains how to package HEIC + MOV pairs as Live Photos. These two utilities **do not create Live Photos or delete files permanently**.

## Included scripts

| Script | What it does |
| --- | --- |
| `apple_video_up_to_3_seconds.py` | Measures video duration and optionally moves videos **at or below 3.100 seconds** into a separate folder. |
| `compare_unique_videos.py` | Compares **full filenames including extensions** between two folders and optionally moves videos present only in `AppleVideoCheckOrigin`. |

Both scan subfolders recursively. Both are **preview-only by default**; add `--move` to move files.

## Requirements

- macOS with Python 3.10 or newer.
- FFmpeg / `ffprobe` for duration measurement.
- Optional: ExifTool if using `--require-live-id`.

Install using Homebrew:

```bash
brew install ffmpeg
# Optional:
brew install exiftool
```

Clone the repository and enter its root folder:

```bash
git clone https://github.com/davidlee1102/apple_live_photo_convert.git
cd apple_live_photo_convert
```

The examples below are run **from the repository root**. If already inside `tests/`, omit `tests/` from the command.

## 1. Separate videos lasting 3.100 seconds or less

**Script:** `tests/apple_video_up_to_3_seconds.py`

**Default source:** `~/Desktop/AppleVideoCheckOrigin`  
**Destination:** `~/Desktop/AppleVideoUpTo3Seconds`  
**CSV reports:** `~/Desktop/AppleVideoDurationReports`

| Measured duration | Action with `--move` |
| --- | --- |
| 2.900 s | Move |
| 3.000 s | Move |
| **3.100 s** | **Move** |
| 3.101 s | Keep |
| 3.500 s | Keep |
| 4.000 s | Keep |

The script measures duration with `ffprobe` and checks track/container values without rounding to whole seconds. It currently scans **MOV, M4V and 3GP** (not MP4).

### Preview only

```bash
python3 tests/apple_video_up_to_3_seconds.py
```

### Move qualifying short videos

```bash
python3 tests/apple_video_up_to_3_seconds.py --move
```

### MOV files only (optional)

```bash
python3 tests/apple_video_up_to_3_seconds.py --mov-only --move
```

### Require Apple Live Photo identifier (optional)

```bash
python3 tests/apple_video_up_to_3_seconds.py --mov-only --require-live-id --move
```

This requires ExifTool. A Live Photo identifier is useful evidence but does not verify that the corresponding still image is available.

### Return previously moved videos longer than 3.100 seconds

Preview:

```bash
python3 tests/apple_video_up_to_3_seconds.py --restore-over-limit
```

Restore:

```bash
python3 tests/apple_video_up_to_3_seconds.py --restore-over-limit --move
```

This returns over-limit videos from `AppleVideoUpTo3Seconds` to `AppleVideoCheckOrigin`.

## 2. Find videos missing from the reference folder

**Script:** `tests/compare_unique_videos.py`

This script compares **only filenames**, case-insensitively, **including extensions**. It does **not** compare file contents or video hashes.

| Video in Origin | Video in Check | Action with `--move` |
| --- | --- | --- |
| `007.MP4` | `007.MP4` | Skip; filename already exists |
| `007.MP4` | `007.MOV` | Move; extension differs |
| `008.MOV` | `008.mov` | Skip; case is ignored |
| `009.MOV` | Not present | Move |

**Default folders:**

```text
~/Desktop/
├── AppleVideoCheckOrigin/  # Source: files to inspect and potentially move
├── AppleVideoCheck/        # Reference: read-only in default mode
└── AppleVideoUnique/       # Destination: unmatched videos
```

### Preview only

```bash
python3 tests/compare_unique_videos.py
```

### Move videos present only in Origin

```bash
python3 tests/compare_unique_videos.py --move
```

Videos with matching names stay in `AppleVideoCheckOrigin`. Files inside `AppleVideoCheck` are left unchanged. A CSV report is written to `AppleVideoUnique` after a move.

### Use custom folders

```bash
python3 tests/compare_unique_videos.py \
  --origin "$HOME/Desktop/AppleVideoUpTo3Seconds" \
  --check "$HOME/Desktop/AppleVideoCheck" \
  --output "$HOME/Desktop/AppleVideoUnique"
```

Add `--move` after preview to move unmatched videos.

> **Avoid `--both --move`** if `AppleVideoCheck` must remain unchanged: that optional mode can move unmatched files from the reference folder too.

## Recommended combined workflow

1. **Preview short videos:**

   ```bash
   python3 tests/apple_video_up_to_3_seconds.py
   ```

2. **Move videos at or below 3.100 seconds:**

   ```bash
   python3 tests/apple_video_up_to_3_seconds.py --move
   ```

3. **Preview which short videos are absent from the reference folder:**

   ```bash
   python3 tests/compare_unique_videos.py \
     --origin "$HOME/Desktop/AppleVideoUpTo3Seconds" \
     --check "$HOME/Desktop/AppleVideoCheck" \
     --output "$HOME/Desktop/AppleVideoUnique"
   ```

4. **Move only those unmatched short videos:** repeat the previous command with `--move` at the end.

## Safety notes

- These tools **move**, rather than permanently delete, media.
- A **short video is not necessarily** part of a Live Photo.
- Identical filenames **do not guarantee** identical video contents; a MOV and MP4 with the same basename are treated as different.
- Files in subfolders are included. Relative folder paths are preserved when moving.
- Destination files are not overwritten deliberately.
- Back up your original media and review the generated CSV reports before large moves.
- If a MOV belongs to a HEIC Live Photo, moving the MOV could separate the two components. Restore and verify the Live Photo before discarding source media.

For converting `HEIC + MOV` pairs into importable `.pvt` packages, use the [main Live Photo tool](../README.md) instead.
