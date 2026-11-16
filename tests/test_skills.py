"""Behavioral package tests; scenario fixtures are contracts, not model eval results."""

import hashlib
import json
from pathlib import Path
import shutil
import stat
import tempfile
import unittest
import zipfile
from unittest.mock import patch

from monarchy.skills import InvalidPackage, build_package, inspect_package, load_registry


ROOT = Path(__file__).resolve().parents[1]
CORE = {"monarchy-" + name for name in (
    "intake", "adopt", "compose", "dispatch", "supervise", "decide", "steer",
    "checkpoint", "handoff", "recover", "verify", "complete")}


def digest(data):
    return hashlib.sha256(data).hexdigest()


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "source"
        self.root.mkdir()
        self.output = Path(self.temp.name) / "worker.zip"
        self.registry_path = self.root / ".agents/skills/registry.json"
        self.add_skill("monarchy-intake")
        self.add_skill("monarchy-verify")
        self.write_registry()

    def add_skill(self, name):
        base = self.root / ".agents/skills" / name
        (base / "references").mkdir(parents=True)
        (base / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: Test package contents.\n---\n"
            "Read [output](references/output.md).\n", encoding="utf-8")
        (base / "references/output.md").write_text("Verified evidence only.\n", encoding="utf-8")
        (base / "unlisted.txt").write_text("Private material must not ship.\n", encoding="utf-8")

    def write_registry(self, mutate=None):
        entries = []
        for name in ("monarchy-intake", "monarchy-verify"):
            prefix = f".agents/skills/{name}/"
            files = [{"path": prefix + suffix,
                      "sha256": digest((self.root / (prefix + suffix)).read_bytes())}
                     for suffix in ("SKILL.md", "references/output.md")]
            entries.append({"name": name, "version": "1.0.0",
                            "entrypoint": prefix + "SKILL.md", "files": files})
        value = {"schema_version": 1, "package_version": "0.1.0", "skills": entries}
        if mutate:
            mutate(value)
        self.registry_path.write_text(json.dumps(value), encoding="utf-8")
        return value

    def build(self, **kwargs):
        return build_package(self.root, ["monarchy-intake"], self.output, **kwargs)

    def test_archive_is_self_contained_after_source_disappears(self):
        result = self.build()
        shutil.rmtree(self.root)
        manifest = inspect_package(self.output)
        self.assertEqual(manifest, result)
        self.assertEqual(manifest["skills"][0]["name"], "monarchy-intake")
        with zipfile.ZipFile(self.output) as archive:
            self.assertEqual(archive.read("skills/monarchy-intake/references/output.md"),
                             b"Verified evidence only.\n")
            self.assertNotIn("skills/monarchy-verify/SKILL.md", archive.namelist())
            self.assertFalse(any("unlisted" in name for name in archive.namelist()))
            self.assertTrue(all(stat.S_IMODE(item.external_attr >> 16) == 0o444
                                for item in archive.infolist()))

    def test_output_is_deterministic_and_pins_registry(self):
        first = self.build()
        other = self.output.with_name("again.zip")
        build_package(self.root, ["monarchy-intake"], other)
        self.assertEqual(self.output.read_bytes(), other.read_bytes())
        self.assertEqual(first["registry_sha256"], digest(self.registry_path.read_bytes()))

    def test_project_policy_is_explicit_and_pinned(self):
        project = Path(self.temp.name) / "project"
        project.mkdir()
        policy = project / "AGENTS.md"
        policy.write_text("Use the project's review gates.\n", encoding="utf-8")
        manifest = self.build(context_root=project,
                              context_files={"AGENTS.md": digest(policy.read_bytes())})
        self.assertEqual(manifest["project_context"], ["project/AGENTS.md"])
        with zipfile.ZipFile(self.output) as archive:
            self.assertEqual(archive.read("project/AGENTS.md"), policy.read_bytes())

    def test_changed_project_policy_fails_without_partial_output(self):
        with self.assertRaises(InvalidPackage):
            self.build(context_root=self.root,
                       context_files={".agents/skills/registry.json": "0" * 64})
        self.assertFalse(self.output.exists())

    def test_context_paths_cannot_escape_or_use_symlinks(self):
        target = self.root / "outside.txt"
        target.write_text("sensitive", encoding="utf-8")
        (self.root / "link.txt").symlink_to(target)
        for path in ("../outside.txt", str(target), "link.txt", "C:/outside.txt"):
            with self.subTest(path=path), self.assertRaises(InvalidPackage):
                self.build(context_root=self.root, context_files={path: digest(b"sensitive")})

    def test_registry_hash_and_selected_file_pins_can_be_required(self):
        pins = {".agents/skills/registry.json": digest(self.registry_path.read_bytes())}
        self.build(expected_hashes=pins)
        self.output.unlink()
        with self.assertRaises(InvalidPackage):
            self.build(expected_hashes={".agents/skills/registry.json": "0" * 64})
        with self.assertRaises(InvalidPackage):
            self.build(expected_hashes={"unknown.md": "0" * 64})

    def test_changed_skill_fails_closed(self):
        path = self.root / ".agents/skills/monarchy-intake/SKILL.md"
        path.write_text(path.read_text() + "Changed after selection.\n", encoding="utf-8")
        with self.assertRaises(InvalidPackage):
            self.build()
        self.assertFalse(self.output.exists())

    def test_archive_pin_is_checked_on_receipt(self):
        manifest = self.build()
        self.assertEqual(inspect_package(self.output, expected_sha256=digest(self.output.read_bytes())), manifest)
        with self.assertRaises(InvalidPackage):
            inspect_package(self.output, expected_sha256="0" * 64)

    def test_missing_declared_resource_fails_without_output(self):
        (self.root / ".agents/skills/monarchy-intake/references/output.md").unlink()
        with self.assertRaises(InvalidPackage):
            self.build()
        self.assertFalse(self.output.exists())

    def test_source_hardlink_rejected(self):
        import os
        source = self.root / ".agents/skills/monarchy-intake/references/output.md"
        os.link(source, self.root / "alias.md")
        with self.assertRaises(InvalidPackage):
            self.build()

    def test_package_size_limit_includes_manifest(self):
        registry = json.loads(self.registry_path.read_text())
        total = len(self.registry_path.read_bytes()) + sum(
            len((self.root / item["path"]).read_bytes()) for item in registry["skills"][0]["files"])
        with patch("monarchy.skills.MAX_TOTAL_BYTES", total + 1):
            with self.assertRaises(InvalidPackage):
                self.build()
        self.assertFalse(self.output.exists())

    def test_resource_unicode_and_file_directory_collisions_rejected(self):
        prefix = ".agents/skills/monarchy-intake/"
        for paths in ((prefix + "caf\u00e9.md", prefix + "cafe\u0301.md"),
                      (prefix + "references", prefix + "references/other.md")):
            with self.subTest(paths=paths):
                self.write_registry(lambda data: data["skills"][0]["files"].extend(
                    {"path": path, "sha256": "0" * 64} for path in paths))
                with self.assertRaises(InvalidPackage):
                    load_registry(self.root)

    def test_registry_rejects_unsafe_paths(self):
        for path in ("../SKILL.md", "/tmp/SKILL.md", "C:/SKILL.md",
                     ".agents//skills/monarchy-intake/SKILL.md",
                     ".agents/skills/monarchy-intake/./SKILL.md",
                     ".agents\\skills\\monarchy-intake\\SKILL.md"):
            with self.subTest(path=path):
                self.write_registry(lambda data: data["skills"][0]["files"][0].update(path=path))
                with self.assertRaises(InvalidPackage):
                    load_registry(self.root)

    def test_resource_must_belong_to_its_skill(self):
        self.write_registry(lambda data: data["skills"][0]["files"].append(
            {"path": ".agents/skills/monarchy-verify/SKILL.md", "sha256": "0" * 64}))
        with self.assertRaises(InvalidPackage):
            load_registry(self.root)

    def test_registry_rejects_case_collisions_duplicate_keys_and_bad_versions(self):
        for change in (
            lambda data: data["skills"].append(data["skills"][0]),
            lambda data: data["skills"][0]["files"].append(
                {"path": ".agents/skills/monarchy-intake/skill.md", "sha256": "0" * 64}),
            lambda data: data.update(schema_version=True),
            lambda data: data["skills"][0].update(version="latest"),
        ):
            self.write_registry(change)
            with self.assertRaises(InvalidPackage):
                load_registry(self.root)
        self.registry_path.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
        with self.assertRaises(InvalidPackage):
            load_registry(self.root)

    def test_missing_entrypoint_rejected(self):
        self.write_registry(lambda data: data["skills"][0]["files"].pop(0))
        with self.assertRaises(InvalidPackage):
            load_registry(self.root)

    def test_file_and_ancestor_symlinks_rejected(self):
        target = self.root / ".agents/skills/monarchy-intake/references/output.md"
        elsewhere = self.root / "elsewhere.md"
        target.rename(elsewhere)
        target.symlink_to(elsewhere)
        with self.assertRaises(InvalidPackage):
            self.build()
        target.unlink()
        elsewhere.rename(target)
        parent = target.parent
        parent.rename(parent.with_name("other"))
        parent.symlink_to(parent.with_name("other"), target_is_directory=True)
        with self.assertRaises(InvalidPackage):
            self.build()

    def test_symlink_root_rejected(self):
        link = self.root.with_name("source-link")
        link.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(InvalidPackage):
            build_package(link, ["monarchy-intake"], self.output)

    def test_unsupported_selection_and_empty_package_rejected(self):
        for names in ([], ["not-installed"], ["monarchy-intake", "monarchy-intake"]):
            with self.subTest(names=names), self.assertRaises(InvalidPackage):
                build_package(self.root, names, self.output)

    def test_destination_is_never_overwritten_or_followed(self):
        self.output.write_bytes(b"existing")
        with self.assertRaises(InvalidPackage):
            self.build()
        self.assertEqual(self.output.read_bytes(), b"existing")
        self.output.unlink()
        self.output.symlink_to(self.registry_path)
        with self.assertRaises(InvalidPackage):
            self.build()

    def test_output_parent_symlink_rejected(self):
        link = self.root / "output-link"
        link.symlink_to(self.output.parent, target_is_directory=True)
        with self.assertRaises(InvalidPackage):
            build_package(self.root, ["monarchy-intake"], link / "worker.zip")

    def test_partial_context_inputs_rejected(self):
        for kwargs in ({"context_root": self.root}, {"context_files": {"AGENTS.md": "0" * 64}}):
            with self.subTest(kwargs=kwargs), self.assertRaises(InvalidPackage):
                self.build(**kwargs)

    def mutate_archive(self, transform):
        self.build()
        with zipfile.ZipFile(self.output) as original:
            entries = [(item, original.read(item)) for item in original.infolist()]
        self.output.unlink()
        entries = transform(entries)
        with zipfile.ZipFile(self.output, "w") as archive:
            for info, payload in entries:
                archive.writestr(info, payload)

    def test_tampered_archive_rejected(self):
        self.mutate_archive(lambda entries: [(info, b"tampered" if info.filename.endswith("SKILL.md") else data)
                                            for info, data in entries])
        with self.assertRaises(InvalidPackage):
            inspect_package(self.output)

    def test_extra_archive_file_rejected(self):
        self.mutate_archive(lambda entries: entries + [("unexpected.txt", b"not in manifest")])
        with self.assertRaises(InvalidPackage):
            inspect_package(self.output)

    def test_traversal_and_symlink_archive_members_rejected(self):
        for name, mode in (("../escaped", stat.S_IFREG | 0o444),
                           ("link", stat.S_IFLNK | 0o777)):
            with self.subTest(name=name):
                if self.output.exists():
                    self.output.unlink()
                info = zipfile.ZipInfo(name)
                info.create_system = 3
                info.external_attr = mode << 16
                self.mutate_archive(lambda entries: entries + [(info, b"target")])
                with self.assertRaises(InvalidPackage):
                    inspect_package(self.output)
        self.assertFalse((self.output.parent / "escaped").exists())

    def test_manifest_file_list_and_skill_selection_are_validated(self):
        def change(entries):
            result = []
            for info, data in entries:
                if info.filename == "manifest.json":
                    value = json.loads(data)
                    value["skills"][0]["entrypoint"] = "skills/other/SKILL.md"
                    data = json.dumps(value).encode()
                result.append((info, data))
            return result
        self.mutate_archive(change)
        with self.assertRaises(InvalidPackage):
            inspect_package(self.output)

    def test_archive_duplicates_rejected(self):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            self.mutate_archive(lambda entries: entries + [entries[0]])
        with self.assertRaises(InvalidPackage):
            inspect_package(self.output)

    def test_invalid_zip_rejected_without_extracting(self):
        self.output.write_bytes(b"not a zip")
        with self.assertRaises(InvalidPackage):
            inspect_package(self.output)


class CoreSkillContractTests(unittest.TestCase):
    def test_all_core_skills_are_registered_and_hash_pinned(self):
        registry = load_registry(ROOT)
        self.assertEqual({entry["name"] for entry in registry["skills"]}, CORE)
        for entry in registry["skills"]:
            with self.subTest(skill=entry["name"]):
                for item in entry["files"]:
                    self.assertEqual(digest((ROOT / item["path"]).read_bytes()), item["sha256"])

    def test_every_skill_has_trigger_contract_and_honest_eval_fixtures(self):
        for entry in load_registry(ROOT)["skills"]:
            base = ROOT / Path(entry["entrypoint"]).parent
            body = (base / "SKILL.md").read_text()
            with self.subTest(skill=entry["name"]):
                self.assertTrue(body.startswith(f"---\nname: {entry['name']}\ndescription: "))
                for heading in ("## Inputs", "## Workflow", "## Output", "## Authority",
                                "## Failure and no-op", "## Project overrides"):
                    self.assertIn(heading, body)
                self.assertIn(".agents/config.md", body)
                self.assertNotIn("Chamberlain", body)
                metadata = (base / "agents/openai.yaml").read_text()
                self.assertIn(f"${entry['name']}", metadata)
                self.assertIn("allow_implicit_invocation: true", metadata)
                fixtures = json.loads((base / "evals.json").read_text())
                self.assertEqual(fixtures["status"], "not_run")
                self.assertEqual(fixtures["skill"], entry["name"])
                for category in ("positive", "negative", "boundary"):
                    matching = [case for case in fixtures["cases"] if case["category"] == category]
                    self.assertGreaterEqual(len(matching), 2)
                    for case in matching:
                        self.assertTrue(case["input"])
                        self.assertTrue(case["expected_output"])
                        self.assertTrue(case["must_not"])

    def test_all_core_skills_roundtrip_with_declared_resources(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "core.zip"
            manifest = build_package(ROOT, sorted(CORE), path)
            self.assertEqual(inspect_package(path), manifest)
            self.assertEqual({item["name"] for item in manifest["skills"]}, CORE)
            with zipfile.ZipFile(path) as archive:
                for name in CORE:
                    self.assertIn(f"skills/{name}/references/output.md", archive.namelist())


if __name__ == "__main__":
    unittest.main()
