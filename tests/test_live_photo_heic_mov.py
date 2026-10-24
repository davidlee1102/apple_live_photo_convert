"""Offline unit tests: no personal photos or macOS tools needed."""

from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import live_photo_heic_mov as lp


class ScanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def create(self, name: str, content: bytes = b"test") -> Path:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def test_pairs_only_matching_heic_mov_within_same_folder(self):
        self.create("A/IMG_0023.HEIC")
        self.create("A/IMG_0023.MOV")
        self.create("A/IMG_0023.JPG", b"different photo")
        self.create("B/IMG_9999.MOV")
        self.create("B/IMG_0023.HEIC")
        self.create("C/IMG_0023.MOV")
        pairs, issues = lp.scan(self.root)
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0][0].name, "IMG_0023.HEIC")
        self.assertTrue(any(reason == "NO_MATCHING_HEIC" for reason, _ in issues))
        self.assertTrue(any(reason == "NO_MATCHING_MOV" for reason, _ in issues))

    def test_ambiguous_case_variants_not_guessed(self):
        self.create("IMG_0023.HEIC")
        self.create("img_0023.heic", b"another")
        self.create("IMG_0023.MOV")
        pairs, issues = lp.scan(self.root)
        self.assertFalse(pairs)
        self.assertEqual(issues[0][0], "MULTIPLE_CANDIDATES")

    def test_scanner_ignores_existing_packages_and_photos_library(self):
        self.create("IMG_0001.HEIC")
        self.create("IMG_0001.MOV")
        self.create("Already.pvt/IMG_0002.HEIC")
        self.create("Already.pvt/IMG_0002.MOV")
        self.create("System.photoslibrary/IMG_0003.HEIC")
        self.create("System.photoslibrary/IMG_0003.MOV")
        pairs, _ = lp.scan(self.root)
        self.assertEqual(len(pairs), 1)


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.input = self.root / "input"
        self.output = self.root / "output"
        self.backup = self.root / "backup"
        self.input.mkdir()
        self.image = self.input / "2026" / "IMG_0023.HEIC"
        self.movie = self.input / "2026" / "IMG_0023.MOV"
        self.image.parent.mkdir()
        self.image.write_bytes(b"image source content")
        self.movie.write_bytes(b"movie source content")
        self.asset_id = "11111111-2222-3333-4444-555555555555"

    def tearDown(self):
        self.temp.cleanup()

    def fake_shell(self, argv: list[str], timeout: int = 900):
        if "--pvt" in argv:
            image = Path(argv[-2])
            movie = Path(argv[-1])
            pkg = image.with_suffix(".pvt")
            pkg.mkdir()
            (pkg / image.name).write_bytes(image.read_bytes() + b" tagged")
            (pkg / movie.name).write_bytes(movie.read_bytes() + b" tagged")
            (pkg / "metadata.plist").write_text("plist")
        from subprocess import CompletedProcess
        return CompletedProcess(argv, 0, "", "")

    def test_create_verify_and_rerun_without_overwrite(self):
        with patch.object(lp, "shell", side_effect=self.fake_shell), patch.object(
            lp, "check_pair", return_value=self.asset_id
        ):
            status, aid, package = lp.make_package(
                self.image, self.movie, self.input, self.output, ["makelive"], self.asset_id
            )
            self.assertEqual(status, "CREATED_VERIFIED")
            self.assertEqual(aid, self.asset_id)
            self.assertEqual(package, self.output / "2026" / "IMG_0023.pvt")
            self.assertTrue((package / "metadata.plist").exists())
            self.assertEqual(self.image.read_bytes(), b"image source content")
            status2, _, package2 = lp.make_package(
                self.image, self.movie, self.input, self.output, ["makelive"], self.asset_id
            )
            self.assertEqual(status2, "EXISTS_VERIFIED")
            self.assertEqual(package, package2)

    def test_changed_source_refuses_old_package(self):
        with patch.object(lp, "shell", side_effect=self.fake_shell), patch.object(
            lp, "check_pair", return_value=self.asset_id
        ):
            lp.make_package(self.image, self.movie, self.input, self.output, ["makelive"], self.asset_id)
            self.image.write_bytes(b"changed")
            with self.assertRaisesRegex(RuntimeError, "different or changed"):
                lp.make_package(self.image, self.movie, self.input, self.output, ["makelive"], self.asset_id)

    def test_move_sources_preserves_originals_in_backup(self):
        archived = lp.archive_sources(self.image, self.movie, self.input, self.backup)
        self.assertEqual(len(archived), 2)
        self.assertFalse(self.image.exists())
        self.assertFalse(self.movie.exists())
        self.assertEqual((self.backup / "2026" / "IMG_0023.HEIC").read_bytes(), b"image source content")
        self.assertEqual((self.backup / "2026" / "IMG_0023.MOV").read_bytes(), b"movie source content")

    def test_move_sources_does_not_overwrite_backup(self):
        already = self.backup / "2026" / "IMG_0023.MOV"
        already.parent.mkdir(parents=True)
        already.write_bytes(b"do not overwrite")
        with self.assertRaisesRegex(RuntimeError, "destination exists"):
            lp.archive_sources(self.image, self.movie, self.input, self.backup)
        self.assertTrue(self.image.exists())
        self.assertTrue(self.movie.exists())

    def test_report_format(self):
        path = self.root / "report.csv"
        lp.save_report(path, [{"status": "PACKAGED_ALREADY_LIVE", "heic": "IMG_1.HEIC", "mov": "IMG_1.MOV", "asset_id": "", "package": "", "backup": "", "note": ""}])
        with path.open(encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(rows[0]["status"], "PACKAGED_ALREADY_LIVE")


if __name__ == "__main__":
    unittest.main()
