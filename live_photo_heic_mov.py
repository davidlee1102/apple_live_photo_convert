#!/usr/bin/env python3
"""HEIC + MOV -> verified .pvt packages for Apple Photos (macOS).

Designed for existing iPhone libraries with image/video files split by transfer.
Packaging an already-valid pair is always supported; no JPG/JPEG/PNG processed.
Default is read-only preview. --run writes separate .pvt packages; --move-sources
additionally moves BOTH HEIC and MOV to a separate recoverable source backup only
AFTER the .pvt has been verified and the user confirms import. No permanent deletion.

Requires macOS and MakeLive (makelive or uvx makelive). For fresh unpaired pairs,
requires ffprobe to confirm short video duration, and exiftool to prevent
rewriting conflicting pre-existing Apple content identifiers.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ASSET_RE = re.compile(r'\bare Live Photos:\s*([a-fA-F0-9-]{36})\b', re.I)

def key(s: str) -> str:
    return unicodedata.normalize('NFC', s).casefold()

def digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open('rb') as f:
        for data in iter(lambda: f.read(1024 * 1024), b''):
            sha.update(data)
    return sha.hexdigest()

def shell(argv: list[str], timeout: int = 900) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              text=True, errors='replace', check=False, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f'Cannot run {argv[0]}: {exc}') from exc

def makelive_command() -> list[str]:
    if shutil.which('makelive'):
        return ['makelive']
    if shutil.which('uvx'):
        return ['uvx', 'makelive']
    raise RuntimeError('MakeLive not installed. Run: brew install uv && uv tool install makelive')

def check_pair(cmd: list[str], image: Path, movie: Path) -> str | None:
    proc = shell(cmd + ['--check', '--manual', str(image), str(movie)], timeout=240)
    output = proc.stdout + '\n' + proc.stderr
    found = ASSET_RE.search(output)
    if found and proc.returncode == 0:
        return found.group(1).lower()
    if 'traceback' in output.lower() or 'permission denied' in output.lower():
        raise RuntimeError('MakeLive check error: ' + output[-500:].strip())
    return None

def content_ids(path: Path) -> set[str] | None:
    if not shutil.which('exiftool'):
        return None
    p = shell(['exiftool', '-j', '-a', '-s', '-ContentIdentifier', str(path)], timeout=120)
    if p.returncode != 0:
        raise RuntimeError('ExifTool inspection failed: ' + p.stderr[-300:].strip())
    try:
        rows = json.loads(p.stdout)
    except ValueError as exc:
        raise RuntimeError('Unexpected ExifTool output') from exc
    return {str(v).strip().lower() for row in rows for k,v in row.items()
            if 'contentidentifier' in k.lower() and str(v).strip()}

def duration(path: Path) -> float | None:
    if not shutil.which('ffprobe'):
        return None
    p = shell(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
               '-of', 'default=noprint_wrappers=1:nokey=1', str(path)], timeout=120)
    if p.returncode != 0:
        return None
    try:
        return float(p.stdout.strip())
    except ValueError:
        return None

def scan(folder: Path) -> tuple[list[tuple[Path,Path]], list[tuple[str,str]]]:
    grouped = defaultdict(lambda: {'image': [], 'video': []})
    for base, dirs, filenames in os.walk(folder, followlinks=False):
        dirs[:] = [d for d in dirs if not d.startswith('.') and not (Path(base)/d).is_symlink()
                   and (Path(base)/d).suffix.casefold() not in {'.pvt', '.photoslibrary', '.app'}]
        for filename in filenames:
            src = Path(base)/filename
            if src.is_symlink() or not src.is_file():
                continue
            ext = src.suffix.casefold()
            if ext not in {'.heic', '.mov'}:
                continue
            grouped[(src.parent,key(src.stem))]['image' if ext == '.heic' else 'video'].append(src)
    pairs, issues = [], []
    for (base,stem), parts in sorted(grouped.items(), key=lambda item: str(item[0])):
        images, videos = parts['image'], parts['video']
        if len(images) == len(videos) == 1:
            pairs.append((images[0], videos[0]))
        else:
            names = ' | '.join(x.name for x in images+videos)
            reason = 'NO_MATCHING_' + ('MOV' if not videos else 'HEIC') if not (images and videos) else 'MULTIPLE_CANDIDATES'
            issues.append((reason, f'{base}: {names}'))
    return pairs, issues

def within_or_same(child: Path, parent: Path) -> bool:
    return child == parent or parent in child.parents

def manifest_path(package: Path) -> Path:
    return package.with_name(package.name + '.source.json')

def source_data(image: Path, movie: Path, root: Path) -> dict:
    return {'heic': image.relative_to(root).as_posix(), 'mov': movie.relative_to(root).as_posix(),
            'heic_sha256': digest(image), 'mov_sha256': digest(movie)}

def validate_pkg(pkg: Path, image: Path, movie: Path, cmd: list[str]) -> str:
    if not pkg.is_dir() or not (pkg/'metadata.plist').is_file():
        raise RuntimeError('Missing .pvt directory or metadata.plist')
    heic = pkg/image.name
    mov = pkg/movie.name
    if not (heic.is_file() and mov.is_file() and heic.stat().st_size and mov.stat().st_size):
        raise RuntimeError('Incomplete .pvt: source HEIC/MOV components not found')
    aid = check_pair(cmd, heic, mov)
    if not aid:
        raise RuntimeError('The .pvt HEIC/MOV content identifiers do not match')
    return aid

def make_package(image: Path, movie: Path, root: Path, out: Path, cmd: list[str], prior_id: str|None):
    dest = out / image.relative_to(root).with_suffix('.pvt')
    manifest = manifest_path(dest)
    source = source_data(image, movie, root)
    if dest.exists():
        if not manifest.exists():
            raise RuntimeError('Package exists without source manifest. Refusing overwrite; select a new --output folder.')
        try: prev = json.loads(manifest.read_text(encoding='utf-8'))
        except Exception as exc: raise RuntimeError('Could not read package manifest') from exc
        if any(prev.get(k) != v for k,v in source.items()):
            raise RuntimeError('Existing package belongs to different or changed originals')
        aid = validate_pkg(dest, image, movie, cmd)
        if prior_id and aid != prior_id:
            raise RuntimeError('Existing .pvt asset ID does not match original Live Photo ID')
        return 'EXISTS_VERIFIED',aid,dest
    if manifest.exists():
        raise RuntimeError('Orphan manifest exists but .pvt absent; refusing silent overwrite')
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.live_heic_mov_', dir=dest.parent) as tmpname:
        work = Path(tmpname)
        still = work/image.name
        clip = work/movie.name
        shutil.copy2(image, still)
        shutil.copy2(movie, clip)
        res = shell(cmd + ['--pvt', '--manual', str(still), str(clip)], timeout=1200)
        if res.returncode:
            raise RuntimeError('MakeLive conversion error: '+(res.stderr or res.stdout)[-600:])
        pkg = still.with_suffix('.pvt')
        new_id = validate_pkg(pkg, image, movie, cmd)
        if prior_id and new_id != prior_id:
            raise RuntimeError('MakeLive changed the original Live Photo asset identifier')
        if source_data(image, movie, root) != source:
            raise RuntimeError('Original files changed while creating .pvt; refusing to finish')
        shutil.move(str(pkg), str(dest))
        # Manifest is written only after the completed .pvt package is in place.
        # If this fails, retry requires choosing a clean output folder.
        manifest.write_text(json.dumps({**source,'asset_id':new_id},indent=2),encoding='utf-8')
    return 'CREATED_VERIFIED',new_id,dest

def archive_sources(image: Path, movie: Path, root: Path, backup: Path):
    targets = [(src,backup/src.relative_to(root)) for src in (image,movie)]
    for src,dst in targets:
        if not src.is_file() or src.is_symlink():
            raise RuntimeError('Source no longer exists or is symlink: '+str(src))
        if dst.exists() or dst.is_symlink():
            raise RuntimeError('Backup destination exists; refusing overwrite: '+str(dst))
    completed = []
    try:
        for src,dst in targets:
            dst.parent.mkdir(parents=True,exist_ok=True)
            shutil.move(str(src),str(dst))
            completed.append((src,dst))
    except Exception:
        for src,dst in reversed(completed):
            if dst.exists() and not src.exists():
                src.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(dst),str(src))
        raise
    return [str(dst) for _,dst in completed]

def save_report(path: Path, data: list[dict]):
    path.parent.mkdir(parents=True,exist_ok=True)
    columns = ['status','heic','mov','asset_id','package','backup','note']
    with path.open('w',newline='',encoding='utf-8-sig') as handle:
        writer=csv.DictWriter(handle,fieldnames=columns)
        writer.writeheader()
        writer.writerows(data)

def main(argv=None):
    parser = argparse.ArgumentParser(description='HEIC + MOV Live Photos -> verified .pvt packages (including already paired files)')
    parser.add_argument('folder',type=Path,help='Your original mixed folder; recursively scans only .HEIC and .MOV')
    parser.add_argument('--run',action='store_true',help='Generate and verify .pvt packages (default is preview only)')
    parser.add_argument('--move-sources',action='store_true',help='With --run and --confirm-imported, move verified HEIC/MOV sources to backup')
    parser.add_argument('--confirm-imported',action='store_true',help='Confirm that the generated packages were tested in Apple Photos before --move-sources')
    parser.add_argument('--limit',type=int,default=None,help='Maximum HEIC/MOV pairs to process')
    parser.add_argument('--name',type=str,default=None,help='Process only one matching basename, e.g. IMG_0023 (not a filename with extension)')
    parser.add_argument('--output',type=Path,default=Path.home()/'Desktop'/'RecoveredLivePhotos_HEIC_MOV')
    parser.add_argument('--source-backup',type=Path,default=Path.home()/'Desktop'/'LivePhotoSourceBackup_HEIC_MOV')
    parser.add_argument('--min-duration',type=float,default=1.0)
    parser.add_argument('--max-duration',type=float,default=8.5)
    args=parser.parse_args(argv)
    root = args.folder.expanduser().resolve()
    out = args.output.expanduser().resolve()
    backup = args.source_backup.expanduser().resolve()
    if not root.is_dir(): parser.error('Folder does not exist: '+str(root))
    if root in (Path('/'),Path.home().resolve(),(Path.home()/'Desktop').resolve(),(Path.home()/'Downloads').resolve(),(Path.home()/'Pictures').resolve()):
        parser.error('Choose your photo collection folder, not the whole Desktop/Home/Pictures folder')
    if any(within_or_same(a,b) or within_or_same(b,a) for a,b in ((root,out),(root,backup),(out,backup))):
        parser.error('Input, output, and backup directories must be separate and non-overlapping')
    if args.move_sources and not args.run: parser.error('--move-sources requires --run')
    if args.move_sources and not args.confirm_imported: parser.error('--move-sources requires --confirm-imported; verify packages in Apple Photos first')
    if args.confirm_imported and not args.move_sources: parser.error('--confirm-imported only applies with --move-sources')
    if args.limit is not None and args.limit<=0: parser.error('--limit must be a positive number')
    if args.min_duration < 0 or args.max_duration <= args.min_duration: parser.error('Invalid duration limits')
    if sys.platform != 'darwin': parser.error('Apple Live Photo packaging requires macOS (MakeLive uses Apple frameworks)')
    try: cmd=makelive_command()
    except RuntimeError as exc: parser.error(str(exc))
    pairs,issues = scan(root)
    if args.name:
        basename = key(Path(args.name).stem)
        pairs = [(im,mov) for im,mov in pairs if key(im.stem) == basename]
        issues = [(reason,desc) for reason,desc in issues if basename in key(desc)]
    print('Live Photo HEIC + MOV Packager — GitHub edition')
    print('Input:',root,'\nPackages:',out,'\nSource backups:',backup)
    print('Mode:','RUN' if args.run else 'PREVIEW ONLY')
    print(f'Found {len(pairs):,} matching HEIC+MOV pair(s); {len(issues):,} unmatched/ambiguous groups')
    print('JPG, JPEG, PNG, HEIF and all other files are ignored and left untouched.')
    if not shutil.which('exiftool'):
        print('WARNING: exiftool missing. Pairs without confirmed existing IDs will be skipped for safety.')
    if not shutil.which('ffprobe'):
        print('WARNING: ffprobe missing. Pairs without confirmed existing IDs will be skipped for safety.')
    report=[]
    for reason,name in issues:
        report.append({'status':reason,'heic':'','mov':'','asset_id':'','package':'','backup':'','note':name})
    start=time.monotonic(); counts=Counter()
    selected=pairs[:args.limit] if args.limit else pairs
    for i,(image,movie) in enumerate(selected,1):
        label=image.relative_to(root).as_posix()
        status,aid,pkg,archived,note='SKIPPED','','','',''
        try:
            matched = check_pair(cmd,image,movie)
            if matched:
                kind='ALREADY_LIVE'
                aid=matched
            else:
                kind='UNTAGGED_OR_UNPAIRED'
                # If either source already has an ID (matched or not), don't
                # overwrite metadata, because it may be another Live Photo.
                ids1, ids2 = content_ids(image), content_ids(movie)
                if ids1 is None or ids2 is None:
                    raise RuntimeError('Cannot check for conflicting IDs without exiftool; install with brew install exiftool')
                if ids1 or ids2:
                    raise RuntimeError('Existing Apple identifier(s) do not match; manual review required')
                length=duration(movie)
                if length is None:
                    raise RuntimeError('Cannot read video duration; install with brew install ffmpeg')
                if not args.min_duration<=length<=args.max_duration:
                    raise RuntimeError(f'MOV duration {length:.2f}s is outside short Live Photo range')
                note=f'New pair from matching HEIC/MOV basename; duration {length:.2f}s. Visually review before import.'
            if not args.run:
                status='READY_'+kind
            else:
                status,aid,result = make_package(image,movie,root,out,cmd,matched)
                pkg=str(result)
                if args.move_sources:
                    archived=' | '.join(archive_sources(image,movie,root,backup))
                    status='SOURCES_MOVED_AFTER_VERIFICATION'
                elif kind=='ALREADY_LIVE':
                    status='PACKAGED_ALREADY_LIVE' if status=='CREATED_VERIFIED' else status
        except Exception as exc:
            status='NEEDS_REVIEW' if not args.run else 'FAILED_OR_SKIPPED'
            note=str(exc)
        counts[status]+=1
        elapsed=time.monotonic()-start
        eta=(elapsed/i)*(len(selected)-i) if i else 0
        pct=i/len(selected)*100 if selected else 100
        print(f'[{i:,}/{len(selected):,} {pct:5.1f}% | ETA ~{eta/60:.1f} min] {status}: {label}'
              + (f' — {note[:130]}' if note else ''),flush=True)
        report.append({'status':status,'heic':image.relative_to(root).as_posix(),
                       'mov':movie.relative_to(root).as_posix(), 'asset_id':aid,
                       'package':pkg,'backup':archived,'note':note})
    stamp=datetime.now().strftime('%Y%m%d_%H%M%S')
    report_path=out/f'heic_mov_report_{stamp}.csv' if args.run else root.parent/f'{root.name}_heic_mov_preview_{stamp}.csv'
    save_report(report_path,report)
    print('\nSummary:',dict(counts))
    print('Report:',report_path)
    if args.run:
        print('Packages:',out)
        print('Source files:', 'moved to backup ONLY for verified packages' if args.move_sources else 'left unchanged')
    else:
        print('PREVIEW ONLY — nothing was changed.')
    return 0 if counts['FAILED_OR_SKIPPED']==0 and counts['NEEDS_REVIEW']==0 else 2

if __name__=='__main__':
    sys.exit(main())
