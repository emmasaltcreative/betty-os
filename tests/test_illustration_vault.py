"""Asset Vault: durability, privacy, safety and precedence."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path

from PIL import Image

QUATREFOIL_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width="100" '
    'height="100"><g fill="#2B2B2B"><ellipse cx="50" cy="26" rx="13" ry="22"/>'
    '<ellipse cx="50" cy="74" rx="13" ry="22"/><ellipse cx="26" cy="50" rx="22" '
    'ry="13"/><ellipse cx="74" cy="50" rx="22" ry="13"/></g></svg>'
)
SIGNATURE_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 90" width="400" '
    'height="90"><path d="M10 70 C40 10 70 80 100 40 S160 10 190 60" '
    'stroke="#2B2B2B" stroke-width="7" fill="none"/></svg>'
)


class VaultTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._previous = os.environ.get("BETTY_OS_DATA_DIR")
        os.environ["BETTY_OS_DATA_DIR"] = self._tmp.name
        self.src = Path(self._tmp.name) / "_sources"
        self.src.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        if self._previous is None:
            os.environ.pop("BETTY_OS_DATA_DIR", None)
        else:
            os.environ["BETTY_OS_DATA_DIR"] = self._previous
        self._tmp.cleanup()

    def _png(self, name: str, size: tuple[int, int] = (800, 800)) -> Path:
        """Distinct bytes per name, so checksum dedupe does not collapse them."""
        path = self.src / name
        seed = sum(ord(ch) for ch in name) % 200
        image = Image.new("RGB", size, (240, 236, 226))
        image.putpixel((0, 0), (seed, (seed * 7) % 256, (seed * 13) % 256))
        image.save(path)
        return path

    def _svg(self, name: str, body: str = QUATREFOIL_SVG) -> Path:
        path = self.src / name
        path.write_text(body, encoding="utf-8")
        return path


class ImportTests(VaultTestCase):
    def test_asset_survives_restart_without_reupload(self) -> None:
        """Acceptance 1: an uploaded master stays accessible after restart."""
        from illustration import vault

        record = vault.import_asset(
            self._svg("flower.svg"),
            category="official_marks",
            display_name="House quatrefoil",
            roles=["mark_source"],
            state="locked",
            tags=["quatrefoil"],
        )
        asset_id = record.asset_id

        # Simulate a restart: drop every cached module and re-read from disk.
        import importlib
        import illustration.vault as vault_module

        importlib.reload(vault_module)

        reloaded = vault_module.get_asset(asset_id)
        self.assertIsNotNone(reloaded)
        self.assertEqual(reloaded.display_name, "House quatrefoil")
        self.assertTrue(vault_module.asset_path(reloaded).is_file())
        self.assertTrue(reloaded.is_locked)

    def test_originals_are_preserved_and_checksummed(self) -> None:
        from illustration import vault

        source = self._png("master.png", (1200, 900))
        record = vault.import_asset(source, category="character_masters")

        self.assertEqual(record.sha256, vault.sha256_of(source))
        self.assertEqual((record.width, record.height), (1200, 900))
        stored = vault.asset_path(record)
        self.assertEqual(stored.stat().st_size, source.stat().st_size)

    def test_thumbnail_is_derived_not_a_replacement(self) -> None:
        from illustration import vault

        record = vault.import_asset(self._png("big.png", (2000, 2000)), category="style_anchors")
        self.assertIsNotNone(record.thumbnail_path)
        with Image.open(vault.asset_path(record)) as original:
            self.assertEqual(original.size, (2000, 2000))

    def test_identical_bytes_dedupe(self) -> None:
        from illustration import vault

        source = self._png("same.png")
        first = vault.import_asset(source, category="style_anchors")
        second = vault.import_asset(source, category="style_anchors")
        self.assertEqual(first.asset_id, second.asset_id)

    def test_private_binaries_live_outside_the_repository(self) -> None:
        from src.common import ROOT
        from illustration import vault

        record = vault.import_asset(self._png("family.png"), category="character_masters")
        stored = vault.asset_path(record).resolve()
        with self.assertRaises(ValueError):
            stored.relative_to(ROOT.resolve())


class SafetyTests(VaultTestCase):
    def test_scripted_svg_is_rejected(self) -> None:
        from illustration import vault

        evil = self._svg(
            "evil.svg",
            '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">'
            "<script>alert(1)</script></svg>",
        )
        with self.assertRaises(vault.VaultError):
            vault.import_asset(evil, category="official_marks")

    def test_event_handler_svg_is_rejected(self) -> None:
        from illustration import vault

        evil = self._svg(
            "onload.svg",
            '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10" '
            'onload="x()"><rect width="5" height="5"/></svg>',
        )
        with self.assertRaises(vault.VaultError):
            vault.import_asset(evil, category="official_marks")

    def test_unsupported_file_type_is_rejected(self) -> None:
        from illustration import vault

        bad = self.src / "payload.exe"
        bad.write_bytes(b"MZ\x00\x00")
        with self.assertRaises(vault.VaultError):
            vault.import_asset(bad, category="style_anchors")

    def test_zip_skips_unsafe_and_duplicate_members(self) -> None:
        from illustration import vault

        archive = self.src / "starter.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("marks/flower.svg", QUATREFOIL_SVG)
            zf.writestr("marks/flower_copy.svg", QUATREFOIL_SVG)
            zf.writestr("notes.txt", "ignore me")
            zf.writestr(
                "manifest.json",
                json.dumps(
                    {
                        "assets": [
                            {
                                "path": "marks/flower.svg",
                                "category": "official_marks",
                                "state": "locked",
                                "roles": ["mark_source"],
                                "tags": ["quatrefoil"],
                            }
                        ]
                    }
                ),
            )
        result = vault.import_zip(archive)
        self.assertEqual(len(result["imported"]), 1)
        self.assertEqual(result["imported"][0].state, "locked")
        reasons = " ".join(s["reason"] for s in result["skipped"])
        self.assertIn("unsupported file type", reasons)
        self.assertIn("duplicate", reasons)


class PrecedenceTests(VaultTestCase):
    def test_approved_outranks_draft_and_rejected_never_anchors(self) -> None:
        from illustration import vault

        draft = vault.import_asset(
            self._png("draft.png"), category="style_anchors",
            display_name="draft board", state="draft",
        )
        approved = vault.import_asset(
            self._png("approved.png"), category="style_anchors",
            display_name="approved board", state="approved",
        )
        rejected = vault.import_asset(
            self._png("rejected.png"), category="style_anchors",
            display_name="rejected board", state="rejected",
        )

        best = vault.best_asset(categories=["style_anchors"])
        self.assertEqual(best.asset_id, approved.asset_id)
        ranked = [a.asset_id for a in vault.search(categories=["style_anchors"])]
        self.assertLess(ranked.index(approved.asset_id), ranked.index(draft.asset_id))
        self.assertNotIn(rejected.asset_id, [
            a.asset_id for a in vault.search(categories=["style_anchors"])
            if a.state != "rejected"
        ])

    def test_replace_keeps_history_reachable(self) -> None:
        from illustration import vault

        original = vault.import_asset(
            self._png("v1.png"), category="product_truth", display_name="mockup"
        )
        replacement = vault.replace_with_new_version(
            original.asset_id, self._png("v2.png", (900, 900))
        )

        self.assertEqual(replacement.parent_id, original.asset_id)
        self.assertEqual(replacement.version, 2)
        self.assertTrue(vault.get_asset(original.asset_id).archived)
        self.assertTrue(vault.asset_path(vault.get_asset(original.asset_id)).is_file())
        chain = [a.asset_id for a in vault.version_lineage(replacement.asset_id)]
        self.assertEqual(chain, [original.asset_id, replacement.asset_id])

    def test_search_by_character_and_product(self) -> None:
        from illustration import vault

        vault.import_asset(
            self._png("golden.png"), category="character_masters",
            display_name="Golden anchor", character_ids=["golden_betty"],
            state="approved",
        )
        self.assertEqual(len(vault.search(character_id="golden_betty")), 1)
        self.assertEqual(len(vault.search(character_id="young_betty")), 0)


if __name__ == "__main__":
    unittest.main()


class DryRunTests(VaultTestCase):
    def _pack(self) -> Path:
        archive = self.src / "pack.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("marks/flower.svg", QUATREFOIL_SVG)
            zf.writestr("marks/signature.svg", SIGNATURE_SVG)
            zf.writestr("readme.txt", "notes")
            zf.writestr(
                "manifest.json",
                json.dumps(
                    {
                        "assets": [
                            {
                                "path": "marks/flower.svg",
                                "category": "official_marks",
                                "state": "locked",
                                "roles": ["mark_source"],
                                "tags": ["quatrefoil"],
                            },
                            {"path": "missing/ghost.png", "category": "botanical"},
                        ]
                    }
                ),
            )
        return archive

    def test_dry_run_writes_nothing(self) -> None:
        from illustration import vault

        before = len(vault.list_assets())
        vault.inspect_zip(self._pack())
        self.assertEqual(len(vault.list_assets()), before)

    def test_dry_run_reports_what_would_happen(self) -> None:
        from illustration import vault

        report = vault.inspect_zip(self._pack())
        paths = {p["path"]: p for p in report["planned"]}

        self.assertIn("marks/flower.svg", paths)
        self.assertEqual(paths["marks/flower.svg"]["state"], "locked")
        self.assertTrue(paths["marks/flower.svg"]["in_manifest"])
        self.assertFalse(paths["marks/signature.svg"]["in_manifest"])
        self.assertIn("marks/signature.svg", report["undescribed"])
        self.assertIn("missing/ghost.png", report["manifest_paths_not_in_zip"])
        self.assertIn(
            "unsupported file type",
            " ".join(s["reason"] for s in report["skipped"]),
        )

    def test_dry_run_and_real_import_agree(self) -> None:
        from illustration import vault

        archive = self._pack()
        planned = {p["path"] for p in vault.inspect_zip(archive)["planned"]}
        result = vault.import_zip(archive)
        imported = {a.original_filename for a in result["imported"]}
        self.assertEqual({Path(p).name for p in planned}, imported)

    def test_template_manifest_is_valid_and_uses_known_vocabulary(self) -> None:
        from src.common import BRANDS_DIR
        from illustration.models import (
            REFERENCE_ROLES, VAULT_CATEGORIES, VERIFICATION_STATES,
        )

        path = (
            BRANDS_DIR / "oh_betty_jaletti" / "starter_pack_manifest.template.json"
        )
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertTrue(payload["assets"])
        for entry in payload["assets"]:
            self.assertIn(entry["category"], VAULT_CATEGORIES)
            self.assertIn(entry["state"], VERIFICATION_STATES)
            for role in entry.get("roles", []):
                self.assertIn(role, REFERENCE_ROLES)
