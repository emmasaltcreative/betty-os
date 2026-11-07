"""End-to-end Illustration Studio workflow, against a fake image provider.

Covers the brief's acceptance criteria 2-6 and 9 without needing an API key.
"""

from __future__ import annotations

import io
import os
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from tests.test_illustration_vault import QUATREFOIL_SVG, SIGNATURE_SVG

PRODUCT_ID = "a_woman_remembered_10ml"


class FakeProvider:
    """Deterministic stand-in: returns a plain painterly-ish ground."""

    name = "fake"

    def __init__(self, *, size: tuple[int, int] = (1024, 1024), fail_times: int = 0) -> None:
        self.size = size
        self.calls: list = []
        self.fail_times = fail_times

    def is_configured(self) -> bool:
        return True

    def supports_edit(self) -> bool:
        return True

    def supports_mask(self) -> bool:
        return True

    def unavailable_reason(self) -> str:
        return ""

    def estimate_cost(self, request):
        from illustration.provider import CostEstimate

        return CostEstimate(per_image=0.1, total=0.1 * request.n,
                            basis="fake", is_known=True)

    def generate(self, request):
        from illustration.provider import ImageResult, ProviderError

        self.calls.append(request)
        if self.fail_times > 0:
            self.fail_times -= 1
            raise ProviderError("transient upstream failure")
        images = []
        for index in range(max(1, request.n)):
            canvas = Image.new("RGB", self.size, (246, 241, 231))
            canvas.putpixel((0, 0), (index, 40, 60))
            buffer = io.BytesIO()
            canvas.save(buffer, "PNG")
            images.append(buffer.getvalue())
        return ImageResult(
            images=images, provider=self.name, model="fake-image-1",
            params={"size": f"{request.width}x{request.height}"},
        )


class WorkflowTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._previous = os.environ.get("BETTY_OS_DATA_DIR")
        os.environ["BETTY_OS_DATA_DIR"] = self._tmp.name
        self.src = Path(self._tmp.name) / "_sources"
        self.src.mkdir(parents=True, exist_ok=True)
        self._seed_vault()

    def tearDown(self) -> None:
        if self._previous is None:
            os.environ.pop("BETTY_OS_DATA_DIR", None)
        else:
            os.environ["BETTY_OS_DATA_DIR"] = self._previous
        self._tmp.cleanup()

    def _seed_vault(self) -> None:
        from illustration import vault

        flower = self.src / "flower.svg"
        flower.write_text(QUATREFOIL_SVG, encoding="utf-8")
        signature = self.src / "signature.svg"
        signature.write_text(SIGNATURE_SVG, encoding="utf-8")

        self.mark = vault.import_asset(
            flower, category="official_marks", display_name="House quatrefoil",
            roles=["mark_source"], state="locked", tags=["quatrefoil"],
            is_private=False,
        )
        self.signature = vault.import_asset(
            signature, category="official_marks", display_name="House signature",
            roles=["mark_source"], state="locked", tags=["signature"],
            is_private=False,
        )
        # One approved, API-cleared character anchor per role.
        self.anchors = {}
        for index, character_id in enumerate(
            ["young_betty", "present_betty", "timeless_betty", "golden_betty",
             "betty_remembered"]
        ):
            path = self.src / f"{character_id}.png"
            image = Image.new("RGB", (640, 640), (235, 230, 220))
            image.putpixel((0, 0), (index * 20, 10, 10))
            image.save(path)
            self.anchors[character_id] = vault.import_asset(
                path, category="character_masters",
                display_name=f"{character_id} anchor", roles=["character_reference"],
                state="approved", character_ids=[character_id],
                is_private=False, third_party_api_opt_in=True,
            )

    def _brief(self, **kwargs):
        from illustration import service

        return service.build_brief(product_id=PRODUCT_ID, **kwargs)


class BriefTests(WorkflowTestCase):
    def test_references_are_auto_selected_without_reupload(self) -> None:
        brief = self._brief()
        roles = {r.role for r in brief.references}
        self.assertIn("mark_source", roles)
        self.assertIn("character_reference", roles)
        self.assertEqual(
            sum(1 for r in brief.references if r.role == "character_reference"), 5
        )

    def test_generation_brief_lists_facts_and_deterministic_layers(self) -> None:
        from illustration import service

        plan = service.plan_draft(self._brief(), provider=FakeProvider())
        text = plan.generation.human_readable

        self.assertIn("Non-negotiable product facts", text)
        self.assertIn("gold", text.lower())
        self.assertIn("Composited deterministically afterwards", text)
        # The model is told NOT to draw the label text.
        self.assertIn("DO NOT render the printed label text", plan.generation.prompt)

    def test_unverified_product_is_flagged_not_claimed_verified(self) -> None:
        """Acceptance 5: a missing verified mockup triggers review, not a pass."""
        from illustration import service

        plan = service.plan_draft(self._brief(), provider=FakeProvider())
        fields = [c.field for c in plan.generation.conflicts]
        self.assertIn("product_accuracy", fields)
        self.assertTrue(plan.can_generate)  # flagged, but not blocked

    def test_private_asset_without_opt_in_blocks_generation(self) -> None:
        from illustration import service, vault

        private = self.src / "nana.png"
        Image.new("RGB", (400, 400), (200, 190, 180)).save(private)
        asset = vault.import_asset(
            private, category="character_masters", display_name="family photo",
            roles=["character_reference"], state="approved", is_private=True,
        )
        brief = self._brief()
        from illustration.models import ReferenceSelection

        brief.references.append(
            ReferenceSelection(
                asset_id=asset.asset_id, role="character_reference",
                precedence="approved_character_anchor",
            )
        )
        plan = service.plan_draft(brief, provider=FakeProvider())
        self.assertFalse(plan.can_generate)
        self.assertTrue(any("opt-in" in b for b in plan.blockers()))

    def test_rejected_reference_cannot_anchor(self) -> None:
        from illustration import service, vault
        from illustration.models import ReferenceSelection

        path = self.src / "bad.png"
        Image.new("RGB", (300, 300), (10, 10, 10)).save(path)
        bad = vault.import_asset(
            path, category="style_anchors", display_name="rejected board",
            state="rejected", is_private=False,
        )
        brief = self._brief()
        brief.references.append(
            ReferenceSelection(asset_id=bad.asset_id, role="style_only",
                               precedence="approved_style_anchor")
        )
        plan = service.plan_draft(brief, provider=FakeProvider())
        self.assertFalse(plan.can_generate)


class GenerationTests(WorkflowTestCase):
    def test_draft_generates_with_full_metadata(self) -> None:
        """Acceptance 3: a five-Betty scene produces a draft with metadata."""
        from illustration import service

        created = service.generate_draft(self._brief(), provider=FakeProvider())
        self.assertEqual(len(created), 1)
        version = created[0]

        self.assertEqual(version.provider, "fake")
        self.assertEqual(version.model, "fake-image-1")
        self.assertEqual(len(version.brief.character_ids), 5)
        self.assertEqual((version.source_width, version.source_height), (1024, 1024))
        self.assertTrue(version.qa_results)
        self.assertEqual(len(version.human_checklist), 8)
        self.assertEqual(version.accuracy_status, "requires_product_verification")

    def test_official_marks_are_composited_not_generated(self) -> None:
        """Acceptance 2: marks come from saved source art."""
        from illustration import service

        version = service.generate_draft(self._brief(), provider=FakeProvider())[0]
        layers = version.layer_manifest.names()

        self.assertIn("house_mark", layers)
        self.assertIn("house_signature", layers)
        self.assertIn("ghost_motif_repeat", layers)
        marks_check = next(
            c for c in version.qa_results if c["check_id"] == "marks_locked"
        )
        self.assertEqual(marks_check["outcome"], "pass")

    def test_label_invariants_are_recorded(self) -> None:
        from illustration import service

        version = service.generate_draft(self._brief(), provider=FakeProvider())[0]
        manifest = version.layer_manifest

        base = manifest.find("label_base")
        self.assertTrue(base["transparent"])
        self.assertEqual(base["alpha_in_negative_space"], 0)

        ghost = manifest.find("ghost_motif_repeat")
        self.assertAlmostEqual(ghost["opacity"], 0.5, places=2)

        signature = manifest.find("house_signature")
        self.assertTrue(signature["below_edp"])
        self.assertTrue(signature["aspect_preserved"])

        notes = manifest.find("label_notes_line")
        self.assertIsNone(notes["text"])
        self.assertFalse(notes["invented"])

        placement = manifest.find("product_label")
        self.assertEqual(placement["orientation"], "lengthwise")

    def test_both_gold_ends_are_asserted(self) -> None:
        from illustration import service

        version = service.generate_draft(self._brief(), provider=FakeProvider())[0]
        check = next(c for c in version.qa_results if c["check_id"] == "gold_ends")
        self.assertEqual(check["outcome"], "pass")

    def test_variations_produce_separate_versions(self) -> None:
        from illustration import service

        created = service.generate_draft(
            self._brief(variations=3), provider=FakeProvider()
        )
        self.assertEqual(len(created), 3)
        self.assertEqual(len({v.version_id for v in created}), 3)

    def test_transient_failure_is_not_reported_as_success(self) -> None:
        from illustration import service
        from illustration.provider import ProviderError

        with self.assertRaises(ProviderError):
            service.generate_draft(
                self._brief(), provider=FakeProvider(fail_times=1)
            )

    def test_no_provider_raises_instead_of_faking_success(self) -> None:
        """Acceptance 9: nothing is labelled Ready that cannot really run."""
        from illustration import service
        from illustration.provider import NullProvider, ProviderUnavailable

        with self.assertRaises(ProviderUnavailable):
            service.generate_draft(self._brief(), provider=NullProvider())


class RevisionTests(WorkflowTestCase):
    def test_revision_links_to_parent_and_preserves_it(self) -> None:
        """Acceptance 4: a masked change creates a linked revision."""
        from illustration import service, versions

        parent = service.generate_draft(self._brief(), provider=FakeProvider())[0]
        parent_bytes = versions.resolve(parent.source_image_path).read_bytes()

        child = service.revise(
            parent.version_id,
            "make only the scarf's repeating motif the official four-petal logo",
            region="scarf",
            provider=FakeProvider(),
        )

        self.assertEqual(child.parent_version_id, parent.version_id)
        self.assertNotEqual(child.version_id, parent.version_id)
        self.assertEqual(child.masked_region, "scarf")

        # The parent's bytes and record are untouched.
        self.assertEqual(
            versions.resolve(parent.source_image_path).read_bytes(), parent_bytes
        )
        refreshed = versions.require_version(parent.version_id)
        self.assertEqual(refreshed.source_image_path, parent.source_image_path)

        chain = [v.version_id for v in versions.lineage(child.version_id)]
        self.assertEqual(chain, [parent.version_id, child.version_id])

    def test_revision_prompt_demands_preserving_everything_else(self) -> None:
        from illustration import service

        parent = service.generate_draft(self._brief(), provider=FakeProvider())[0]
        fake = FakeProvider()
        service.revise(parent.version_id, "correct the eyes", region="eyes", provider=fake)
        prompt = fake.calls[-1].prompt

        self.assertIn("Preserve everything else", prompt)
        self.assertIn("Change only the eyes", prompt)

    def test_locked_layers_are_reapplied_after_a_generative_edit(self) -> None:
        from illustration import service

        parent = service.generate_draft(self._brief(), provider=FakeProvider())[0]
        child = service.revise(
            parent.version_id, "warm the backdrop", provider=FakeProvider()
        )
        self.assertIn("house_mark", child.layer_manifest.names())
        self.assertIn("product_label", child.layer_manifest.names())

    def test_deterministic_overlay_needs_no_model_call(self) -> None:
        from illustration import service

        parent = service.generate_draft(self._brief(), provider=FakeProvider())[0]
        child = service.deterministic_overlay_revision(
            parent.version_id, note="re-apply exact signature"
        )
        self.assertEqual(child.provider, "deterministic")
        self.assertEqual(child.parent_version_id, parent.version_id)
        self.assertIn("house_signature", child.layer_manifest.names())


class ExportTests(WorkflowTestCase):
    def test_export_returns_real_decodable_2048_square(self) -> None:
        """Acceptance 6: a real 2048x2048 JPG and PNG, matching their filenames."""
        from illustration import service, versions

        version = service.generate_draft(self._brief(), provider=FakeProvider())[0]
        exported = service.export_version(version.version_id)

        self.assertIn("jpg", exported.export_paths)
        self.assertIn("png", exported.export_paths)
        for kind in ("jpg", "png"):
            path = versions.resolve(exported.export_paths[kind])
            self.assertTrue(path.is_file(), f"{kind} file missing on disk")
            self.assertEqual(path.suffix, f".{kind}")
            with Image.open(path) as img:
                img.load()
                self.assertEqual(img.size, (2048, 2048))
            self.assertGreater(path.stat().st_size, 1024)

    def test_filename_matches_the_actual_file(self) -> None:
        from illustration import service, versions

        version = service.generate_draft(self._brief(), provider=FakeProvider())[0]
        exported = service.export_version(version.version_id)
        expected = service.export_basename(exported)

        for kind in ("jpg", "png"):
            path = versions.resolve(exported.export_paths[kind])
            self.assertEqual(path.stem, expected)
            self.assertTrue(path.name.startswith("OBJ_"))
            self.assertIn("2048", path.name)

    def test_rectangular_source_is_not_stretched(self) -> None:
        from illustration import service, versions

        version = service.generate_draft(
            self._brief(), provider=FakeProvider(size=(1536, 864))
        )[0]
        exported = service.export_version(version.version_id, fit_mode="contain")
        path = versions.resolve(exported.export_paths["png"])
        with Image.open(path) as img:
            self.assertEqual(img.size, (2048, 2048))
        # Padded onto the cream ground, so the corners are background.
        with Image.open(path) as img:
            self.assertEqual(img.convert("RGB").getpixel((4, 4)), (246, 241, 231))

    def test_bundle_manifest_describes_real_files(self) -> None:
        import json
        import zipfile
        from illustration import service

        version = service.generate_draft(self._brief(), provider=FakeProvider())[0]
        service.export_version(version.version_id)
        bundle = service.export_bundle([version.version_id])

        self.assertTrue(bundle.is_file())
        with zipfile.ZipFile(bundle) as zf:
            names = zf.namelist()
            self.assertIn("manifest.json", names)
            manifest = json.loads(zf.read("manifest.json"))
            entry = manifest["versions"][0]
            for meta in entry["files"].values():
                self.assertTrue(meta["exists"])
                self.assertGreater(meta["bytes"], 0)
                self.assertTrue(
                    any(n.endswith(meta["filename"]) for n in names)
                )

    def test_upscaling_is_recorded_not_claimed_as_detail(self) -> None:
        from illustration import service

        version = service.generate_draft(
            self._brief(), provider=FakeProvider(size=(512, 512))
        )[0]
        exported = service.export_version(version.version_id)
        check = next(
            c for c in exported.qa_results if c["check_id"] == "source_resolution"
        )
        self.assertEqual(check["outcome"], "warning")
        self.assertIn("does not recover detail", check["detail"])


class StatusLadderTests(WorkflowTestCase):
    def test_accuracy_cannot_be_claimed_without_a_verified_mockup(self) -> None:
        from illustration import service, versions

        version = service.generate_draft(self._brief(), provider=FakeProvider())[0]
        versions.approve(version.version_id, product_accurate=True)
        checked = service.run_qa(version.version_id)

        # The product profile is unverified, so the claim is rejected downstream.
        self.assertEqual(checked.accuracy_status, "requires_product_verification")
        claim = next(
            c for c in checked.qa_results if c["check_id"] == "accuracy_claim"
        )
        self.assertIn(claim["outcome"], {"warning", "fail"})

    def test_approval_does_not_overwrite_the_source(self) -> None:
        from illustration import service, versions

        version = service.generate_draft(self._brief(), provider=FakeProvider())[0]
        before = versions.resolve(version.source_image_path).read_bytes()
        versions.approve(version.version_id)
        after = versions.resolve(
            versions.require_version(version.version_id).source_image_path
        ).read_bytes()
        self.assertEqual(before, after)

    def test_rejected_version_stays_reachable(self) -> None:
        from illustration import service, versions

        version = service.generate_draft(self._brief(), provider=FakeProvider())[0]
        versions.reject(version.version_id, note="eyes wrong")
        found = versions.require_version(version.version_id)
        self.assertEqual(found.status, "rejected")
        self.assertTrue(versions.resolve(found.source_image_path).is_file())

    def test_versions_are_never_overwritten(self) -> None:
        from illustration import versions
        from illustration.models import GenerationVersion, IllustrationBrief

        brief = IllustrationBrief(
            brief_id="b", brand_id="oh_betty_jaletti",
            template_id="bettys_together_pdp", scene_text="x",
        )
        version = GenerationVersion(
            version_id="ill_v001", brand_id="oh_betty_jaletti", brief=brief
        )
        versions.append_version(version)
        with self.assertRaises(versions.VersionError):
            versions.append_version(version)


class ReuseTests(WorkflowTestCase):
    def test_approved_result_can_become_a_reference(self) -> None:
        from illustration import service, vault

        version = service.generate_draft(self._brief(), provider=FakeProvider())[0]
        promoted = service.promote_to_vault(
            version.version_id, category="style_anchors",
            roles=["style_only"], display_name="approved collage",
        )
        self.assertEqual(promoted.category, "style_anchors")
        self.assertEqual(promoted.state, "approved")
        self.assertIn(version.version_id, promoted.tags)
        self.assertTrue(vault.asset_path(promoted).is_file())


if __name__ == "__main__":
    unittest.main()
