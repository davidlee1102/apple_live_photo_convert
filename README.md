# Live Photo HEIC + MOV Packager

**Turn iPhone `.HEIC` + `.MOV` pairs into importable Apple Live Photo `.pvt` packages on macOS.**

This project helps when an iPhone photo transfer leaves Live Photos split into a still image and a short QuickTime video. It searches an input folder recursively, identifies matching image/movie pairs by **basename and parent folder**, checks Apple pairing metadata, and creates `.pvt` packages that Apple Photos can import as Live Photos.

> **Safety first:** Preview is read-only. Packaging does **not** modify the source HEIC/MOV files. Moving originals is optional and needs two explicit flags. Nothing is permanently deleted. Back up your photo library and verify restored Live Photos in Apple Photos and on your iPhone before removing any original files.

## What it does

- Finds `IMG_0023.HEIC` + `IMG_0023.MOV` in the **same directory**, including subdirectories.
- Packages pairs **even if they are already valid Live Photos**, preserving their existing asset ID.
- For pairs without Apple identifiers, can build new Live Photos when the MOV has a plausible duration (default **1–8.5 seconds**); these require **manual visual review** because a filename match does not prove the two files are related.
- Refuses to rewrite pairs with conflicting or partially present Apple identifiers.
- Skips ambiguous pairs rather than choosing at random.
- Creates importable `.pvt` packages in a **separate output folder**; retains the original folder structure.
- Displays progress (`42/500`, percentage, current filename, approximate ETA).
- Writes a CSV report for successes, failures, skipped/ambiguous items, and source backup destinations.
- Supports idempotent reruns: an existing package can be reused only if its source manifest and pairing check match.
- Optionally moves source HEIC/MOV files into a **separate backup folder** after package verification and your explicit confirmation that you imported them.

### What it deliberately does *not* do

- It does **not** pair JPG/JPEG/PNG with MOV. Those files remain untouched. This is intentional: identical names can correspond to **different photographs**.
- It does **not** deduplicate files by name or delete media from iPhone, iCloud, or Apple Photos.
- It does **not** inspect your Apple Photos library or confirm successful iCloud sync.
- It does **not** guarantee a 3-second video belongs to a HEIC solely because the filenames match.
- It does **not** upload your photos. All processing is local on your Mac.

## How a Live Photo is represented

```text
LivePhotoInput/
├── IMG_0023.HEIC       # still from an original Live Photo
├── IMG_0023.MOV        # motion companion
└── IMG_0023.JPG        # unrelated regular photo (ignored)

RecoveredLivePhotos_HEIC_MOV/
└── IMG_0023.pvt/       # one importable Finder package
    ├── IMG_0023.HEIC
    ├── IMG_0023.MOV
    └── metadata.plist
```

Finder may show `.pvt` as a single package even though it contains both the image and video. A `.pvt` package's *contents* are two media files, but Apple Photos should import it as **one Live Photo**.

## Requirements

- **macOS** (MakeLive relies on Apple's native frameworks)
- **Python 3.10+**
- **[MakeLive](https://github.com/RhetTbull/makelive)** installed as `makelive` or available through `uvx makelive`
- For **previously unpaired** files: [ExifTool](https://exiftool.org/) and `ffprobe` (supplied with FFmpeg). Already-valid Live Photo pairs can be packaged without these two tools.
- Sufficient free disk space for output packages (each `.pvt` contains copies of its media).

Install dependencies via [Homebrew](https://brew.sh/) (if you already have it):

```bash
brew install uv exiftool ffmpeg
uv tool install makelive
```

Confirm that the commands are available:

```bash
python3 --version
makelive --help
exiftool -ver
ffprobe -version
```

The project itself uses **only Python's standard library** and the above external command-line tools. There are no additional Python requirements to install for the script.

## Installation

### Option A — Clone from GitHub

```bash
git clone https://github.com/davidlee1102/apple_live_photo_convert.git
cd live-photo-heic-mov
```


### Option B — Download a ZIP

Download or extract the project and open Terminal in the extracted folder:

```bash
cd ~/Downloads/live-photo-heic-mov
```

You can run the script directly without installing it:

```bash
python3 live_photo_heic_mov.py --help
```

Or optionally install it in editable mode:

```bash
python3 -m pip install -e .
live-photo-heic-mov --help
```

The direct `python3 live_photo_heic_mov.py ...` commands below work without `pip install`.

## Quick start

Assume your original media are stored in `~/Desktop/LivePhotoInput`.

### 1. Preview: no files changed

```bash
python3 live_photo_heic_mov.py ~/Desktop/LivePhotoInput
```

The report is written beside the input folder. The preview may check metadata using MakeLive, ExifTool and FFprobe; it does not write or move your media.

### 2. Try one specific pair

```bash
python3 live_photo_heic_mov.py ~/Desktop/LivePhotoInput --run --name IMG_0023
```

The output appears at:

```text
~/Desktop/RecoveredLivePhotos_HEIC_MOV/IMG_0023.pvt
```

If the pair is in a subfolder, the package appears under the same relative subfolder in the output directory.

You can also select the first matching pair with:

```bash
python3 live_photo_heic_mov.py ~/Desktop/LivePhotoInput --run --limit 1
```

### 3. Verify in Apple Photos

1. In Finder, open `~/Desktop/RecoveredLivePhotos_HEIC_MOV`.
2. Double-click the generated `.pvt` package to import it into **Photos**. If macOS does not open it, use **Photos → File → Import**.
3. Complete the import if Photos presents a review screen.
4. Check **Photos → Media Types → Live Photos**, select the imported photo, and verify the **LIVE** badge and moving image.
5. Test at least one Live Photo on your iPhone using AirDrop before performing a large-scale transfer.

**Important:** A message such as `CREATED_VERIFIED` means the package structure and matching identifiers were validated; it does **not** prove Apple Photos or iCloud imported it successfully.

### 4. Process the full collection

```bash
python3 live_photo_heic_mov.py ~/Desktop/LivePhotoInput --run
```

The default output folder is `~/Desktop/RecoveredLivePhotos_HEIC_MOV`. Original media remain untouched.

### 5. Optional: move only packaged source pairs to backup

**Use this only after verifying that all packages you intend to move have been imported and work.**

```bash
python3 live_photo_heic_mov.py ~/Desktop/LivePhotoInput \
  --run --move-sources --confirm-imported
```

The script revalidates the package against the original files and then moves the two source files to:

```text
~/Desktop/LivePhotoSourceBackup_HEIC_MOV/
```

It never permanently deletes anything. It doesn't touch unmatched HEICs, unrelated JPGs or unrelated MOVs. Do not empty or discard the backup until you have independent backups and have verified iPhone playback.

**Tip:** To move only one tested pair, add `--name IMG_0023`. To move a specific number of already-tested pairs, add `--limit N` (inspect the order before using it).

## Command-line options

| Option | Meaning |
|---|---|
| `folder` | Input directory, recursively scanned |
| `--run` | Create/verify packages; without this flag it only previews |
| `--name IMG_0023` | Process one basename across subdirectories |
| `--limit 5` | Process at most 5 matching pairs |
| `--output PATH` | Custom output directory |
| `--source-backup PATH` | Custom backup directory for moved source files |
| `--min-duration 1.0` | Minimum duration for a new, untagged MOV pair |
| `--max-duration 8.5` | Maximum duration for a new, untagged MOV pair |
| `--move-sources` | Move source HEIC/MOV pairs to backup after package validation |
| `--confirm-imported` | Required with `--move-sources` to acknowledge successful import testing |

Examples:

```bash
# Preview all pairs
python3 live_photo_heic_mov.py ~/Desktop/LivePhotoInput

# Package IMG_0077.HEIC + IMG_0077.MOV, leaving IMG_0077.JPG alone
python3 live_photo_heic_mov.py ~/Desktop/LivePhotoInput --run --name IMG_0077

# Create/verify all eligible packages under a new output directory
python3 live_photo_heic_mov.py ~/Desktop/LivePhotoInput --run \
  --output ~/Desktop/MyLivePhotoPackages

# Back up the originals of an already imported and verified one-pair test
python3 live_photo_heic_mov.py ~/Desktop/LivePhotoInput \
  --run --name IMG_0077 --move-sources --confirm-imported
```

## Statuses and CSV reports

| Status | Meaning |
|---|---|
| `READY_ALREADY_LIVE` | HEIC/MOV share an Apple Live Photo identifier; ready to package |
| `READY_UNTAGGED_OR_UNPAIRED` | Matching filename with no existing identifiers and plausible short MOV; check content before importing |
| `PACKAGED_ALREADY_LIVE` | `.pvt` created for an existing Live Photo pair |
| `CREATED_VERIFIED` | New `.pvt` created and its pair identifiers agree |
| `EXISTS_VERIFIED` | Existing package and its source manifest still verify |
| `SOURCES_MOVED_AFTER_VERIFICATION` | Verified pair's source files moved into backup |
| `NEEDS_REVIEW` | Preview couldn't safely classify or package a pair |
| `FAILED_OR_SKIPPED` | Run-mode error; read `note` in CSV |
| `NO_MATCHING_HEIC` / `NO_MATCHING_MOV` | No companion file in the same folder |
| `MULTIPLE_CANDIDATES` | Duplicate filename candidates; no automatic guess |

Reports are named `heic_mov_report_YYYYMMDD_HHMMSS.csv` in the output directory for `--run`; previews are saved next to the input folder.

## Pairing rules and limitations

1. The script considers **only HEIC and MOV**. The parent directory and basename must match. Upper/lowercase name differences are normalized.
2. If the pair has matching Apple Live Photo IDs, it can be packaged without rewriting the originals.
3. If either file already has a content identifier but the pair does not match, the script **refuses to overwrite existing metadata**.
4. If neither file has an ID, it checks that the MOV is within the requested duration range and then creates a new pair using MakeLive **inside the new package only**. **Matching names and short duration cannot guarantee the content belongs together.** Manually verify the generated animation.
5. `.pvt` packaging may rewrite metadata or re-encode image/video data **within the package**. Keep the original files. MakeLive's documentation describes these limitations.
6. An existing package is reused only if its accompanying `.source.json` manifest matches the current source SHA-256 hashes. The manifest is an implementation file, not a file to import into Photos.
7. Scanning explicitly excludes `.pvt`, `.photoslibrary`, and `.app` directory contents; it also avoids following symlinked directories.
8. The script refuses input, output and source-backup folders that overlap and refuses to overwrite an unrelated existing package or backup file.

## Why `IMG_0023.JPG` is not converted

The JPG could show a completely different photo despite its matching basename. For example:

```text
IMG_0023.HEIC  → person standing in snow
IMG_0023.MOV   → person standing in snow
IMG_0023.JPG   → someone sitting on an airplane
```

This script uses **only** the `.HEIC` + `.MOV` pair and leaves the JPG in the source folder.

## Troubleshooting

**`makelive: command not found`**  
Install it using `brew install uv` and `uv tool install makelive`. Reopen Terminal if the PATH has not updated.

**No `.pvt` generated for a particular basename**  
Try `--name IMG_0023` and read the relevant row in the CSV report. Missing companions, multiple competing matches, conflicts in IDs, a video beyond the duration range, or a MakeLive error may explain it.

**`NEEDS_REVIEW: Existing Apple identifier(s) do not match`**  
Do not force-repair the files. They may belong to different Live Photos, despite having similar filenames.

**`FAILED_OR_SKIPPED`**  
Check the CSV report's `note` field. MakeLive may fail on a damaged or unsupported image/movie; try a single pair to diagnose it.

**`.pvt` exists but isn't visible in Apple Photos**  
Double-click the `.pvt` Finder package and complete the import; look under **Imports** and **Media Types → Live Photos**. The original capture date may place it in an earlier section of the library. Be sure you're not looking at an import preview screen.

**Files seem unchanged in Finder**  
That is normal: the originals remain untouched, and a Live Photo package internally still contains both image and video. Look for the `.pvt` package in the output directory.

**I have Finder-synced images on my iPhone**  
Take special care when changing Finder photo-sync settings, as changes can remove Finder-synced media. Test a small batch with AirDrop first, or use iCloud Photos carefully with a backup.

## Development and testing

The included tests are **offline**, use temporary fake media files, and mock the MakeLive packaging step:

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile live_photo_heic_mov.py
```

A GitHub Actions workflow runs these tests on each push and pull request. CI validates control flow and safety checks; **it cannot validate real macOS Apple Photos imports**. Final validation requires actual media on a Mac.

## Repository structure

```text
live-photo-heic-mov/
├── .github/workflows/tests.yml
├── .gitignore
├── LICENSE
├── README.md
├── live_photo_heic_mov.py
├── pyproject.toml
└── tests/
    └── test_live_photo_heic_mov.py
```

## License

MIT — see [LICENSE](LICENSE). Replace the generic copyright holder with the appropriate copyright details for your project, if desired.
