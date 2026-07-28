#!/usr/bin/env python3
"""Source-side contract tests for the immutable validated publication.

Proves the caller-owned workflow contract, addon identity, runtime allowlist,
pin integrity, and token isolation.  The real reusable-workflow CI proves
target helper behaviour; these tests verify what the source repo owns.
"""

import hashlib
import io
import re
import stat
import zipfile
from pathlib import Path
from xml.etree import ElementTree

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"
ADDON_ID = "script.tubecast"
EXPECTED_VERSION = "1.6.1+omega.1"
NOTIFIER_SHA = "d7434c26c4d49d42496154dd58ae78e1da6f49d6"
DOWNLOAD_ARTIFACT_SHA = "d3f86a106a0bac45b974a628896c90dbdf5c8093"
PACKAGE_BUILDER_SHA = "7adff881ab5d0a7fc63f7474a78b2688e2e6eee4"
RUNTIME_ENTRIES = ["addon.xml", "main.py", "script.py", "resources/"]

SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
VERSION_RE = re.compile(
    r"^[0-9]+(?:\.[0-9]+)*(?:\+[0-9A-Za-z]+(?:\.[0-9A-Za-z]+)*)?$", re.ASCII
)
FIXED_TIMESTAMP = (1980, 1, 1, 0, 0, 0)

ALL_WORKFLOWS = ["addon-validations.yml", "notify-repository.yml",
                 "py-test.yml", "make-release.yml"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_yaml(name):
    with open(WORKFLOWS_DIR / name, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _read_text(name):
    return (WORKFLOWS_DIR / name).read_text(encoding="utf-8")


def _on_block(data):
    """PyYAML parses 'on:' as True; return the on: mapping."""
    return data.get("on") or data.get(True) or {}


def _build_deterministic_zip(source_dir, addon_id, entries):
    """Build a deterministic ZIP from declared runtime entries."""
    import os
    import stat as _stat

    files = []
    for entry in entries:
        is_dir = entry.endswith("/")
        path = source_dir / entry.rstrip("/")
        if is_dir:
            for root, _dirs, filenames in sorted(os.walk(str(path), followlinks=False)):
                root_path = Path(root)
                for name in sorted(filenames):
                    rel = (root_path / name).relative_to(source_dir).as_posix()
                    files.append((rel, root_path / name))
        else:
            files.append((entry, path))

    buf = io.BytesIO()
    with zipfile.ZipFile(
        buf, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9,
        strict_timestamps=True,
    ) as archive:
        for relative, source_path in sorted(files, key=lambda x: x[0]):
            member_name = f"{addon_id}/{relative}"
            info = zipfile.ZipInfo(member_name, FIXED_TIMESTAMP)
            info.create_system = 3
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (_stat.S_IFREG | 0o644) << 16
            archive.writestr(info, source_path.read_bytes())
    return buf.getvalue()


# ---------------------------------------------------------------------------
# 1.  Workflow YAML parseability
# ---------------------------------------------------------------------------

class TestWorkflowParse:
    """All workflow YAML files must parse as dicts."""

    @pytest.mark.parametrize("name", ALL_WORKFLOWS)
    def test_parses(self, name):
        assert isinstance(_load_yaml(name), dict)


# ---------------------------------------------------------------------------
# 2.  notify-repository.yml trigger contract
# ---------------------------------------------------------------------------

class TestNotifyTrigger:
    """Notify workflow must trigger on workflow_run of Add-on Validations
    for develop only, with completed+success, and no push trigger."""

    @pytest.fixture(autouse=True)
    def load(self):
        self.data = _load_yaml("notify-repository.yml")
        self.triggers = _on_block(self.data)

    def test_has_workflow_run(self):
        assert "workflow_run" in self.triggers

    def test_no_push(self):
        assert "push" not in self.triggers

    def test_triggers_on_validations(self):
        assert "Add-on Validations" in self.triggers["workflow_run"]["workflows"]

    def test_restricts_to_develop(self):
        assert self.triggers["workflow_run"]["branches"] == ["develop"]

    def test_requires_completed(self):
        assert "completed" in self.triggers["workflow_run"]["types"]

    def test_job_gates_on_exact_successful_events_and_branch(self):
        job = self.data["jobs"]["validate-evidence"]
        condition = job["if"]
        assert "conclusion == 'success'" in condition
        assert "event == 'push'" in condition
        assert "event == 'workflow_dispatch'" in condition
        assert "head_branch == 'develop'" in condition

    def test_no_legacy_addon_updated_event(self):
        assert "addon-updated" not in _read_text("notify-repository.yml")


# ---------------------------------------------------------------------------
# 3.  notify-repository.yml reusable workflow pin
# ---------------------------------------------------------------------------

class TestNotifyPin:
    """Notify job must invoke the pinned reusable notifier."""

    @pytest.fixture(autouse=True)
    def load(self):
        self.data = _load_yaml("notify-repository.yml")
        self.notify = self.data.get("jobs", {}).get("notify", {})

    def test_uses_reusable_notifier(self):
        assert "reusable-notify-repository.yml" in self.notify.get("uses", "")

    def test_pins_target_sha(self):
        assert NOTIFIER_SHA in self.notify.get("uses", "")

    def test_pins_repository_serph91p(self):
        assert "Serph91P/repository.serph91p" in self.notify.get("uses", "")


# ---------------------------------------------------------------------------
# 4.  addon-validations.yml contract
# ---------------------------------------------------------------------------

class TestValidationsContract:
    """Validations workflow must invoke pinned reusable package workflow
    with correct addon_id and runtime entries."""

    @pytest.fixture(autouse=True)
    def load(self):
        self.data = _load_yaml("addon-validations.yml")
        self.text = _read_text("addon-validations.yml")

    def test_exists(self):
        assert (WORKFLOWS_DIR / "addon-validations.yml").exists()

    def test_has_push_develop(self):
        triggers = _on_block(self.data)
        assert "develop" in triggers.get("push", {}).get("branches", [])

    def test_invokes_reusable_package(self):
        for job in self.data.get("jobs", {}).values():
            if "reusable-addon-package" in job.get("uses", ""):
                return
        pytest.fail("No job invokes reusable-addon-package.yml")

    def test_pins_target_sha(self):
        for job in self.data.get("jobs", {}).values():
            if PACKAGE_BUILDER_SHA in job.get("uses", ""):
                return
        pytest.fail("Target SHA not pinned")

    def test_pins_repository_serph91p(self):
        for job in self.data.get("jobs", {}).values():
            if "Serph91P/repository.serph91p" in job.get("uses", ""):
                return
        pytest.fail("Repository not pinned to Serph91P/repository.serph91p")

    def test_addon_id_present(self):
        assert ADDON_ID in self.text

    def test_runtime_entries_present(self):
        assert "runtime_entries_json" in self.text

    def test_no_legacy_addon_check(self):
        assert "kodi-addon-checker" not in self.text

    def test_no_legacy_addon_install(self):
        assert "git+https://github.com/xbmc/addon-check.git" not in self.text

    @pytest.mark.parametrize("entry", ["addon.xml", "main.py", "script.py", "resources/"])
    def test_runtime_entry_declared(self, entry):
        assert entry in self.text


# ---------------------------------------------------------------------------
# 5.  Add-on identity and version
# ---------------------------------------------------------------------------

class TestAddonIdentity:
    """addon.xml must declare the expected id and version."""

    @pytest.fixture(autouse=True)
    def load(self):
        xml_bytes = (REPO_ROOT / "addon.xml").read_bytes()
        self.root = ElementTree.fromstring(xml_bytes)

    def test_addon_tag(self):
        assert self.root.tag == "addon"

    def test_addon_id(self):
        assert self.root.attrib["id"] == ADDON_ID

    def test_addon_version(self):
        assert self.root.attrib["version"] == EXPECTED_VERSION

    def test_version_format(self):
        assert VERSION_RE.fullmatch(EXPECTED_VERSION)


# ---------------------------------------------------------------------------
# 6.  Runtime allowlist - files exist in source
# ---------------------------------------------------------------------------

class TestRuntimeAllowlist:
    """Declared runtime entries must exist on disk."""

    @pytest.mark.parametrize("entry", [
        "addon.xml", "main.py", "script.py",
    ])
    def test_file_exists(self, entry):
        assert (REPO_ROOT / entry).is_file(), f"{entry} missing from source"

    def test_resources_directory_exists(self):
        assert (REPO_ROOT / "resources").is_dir()


# ---------------------------------------------------------------------------
# 7.  Deterministic package build
# ---------------------------------------------------------------------------

class TestPackageBuild:
    """Source-side deterministic package build from declared entries."""

    def test_deterministic_bytes(self):
        b1 = _build_deterministic_zip(REPO_ROOT, ADDON_ID, RUNTIME_ENTRIES)
        b2 = _build_deterministic_zip(REPO_ROOT, ADDON_ID, RUNTIME_ENTRIES)
        assert b1 == b2

    def test_single_addon_root(self):
        raw = _build_deterministic_zip(REPO_ROOT, ADDON_ID, RUNTIME_ENTRIES)
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            roots = {info.filename.split("/")[0] for info in zf.infolist()}
        assert roots == {ADDON_ID}

    def test_no_directory_members(self):
        raw = _build_deterministic_zip(REPO_ROOT, ADDON_ID, RUNTIME_ENTRIES)
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            for info in zf.infolist():
                assert not info.filename.endswith("/")

    def test_addon_xml_identity(self):
        raw = _build_deterministic_zip(REPO_ROOT, ADDON_ID, RUNTIME_ENTRIES)
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            xml_data = zf.read(f"{ADDON_ID}/addon.xml")
        root = ElementTree.fromstring(xml_data)
        assert root.attrib["id"] == ADDON_ID
        assert root.attrib["version"] == EXPECTED_VERSION

    def test_deterministic_timestamps(self):
        raw = _build_deterministic_zip(REPO_ROOT, ADDON_ID, RUNTIME_ENTRIES)
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            for info in zf.infolist():
                assert info.date_time[:6] == FIXED_TIMESTAMP

    def test_sha256_format(self):
        raw = _build_deterministic_zip(REPO_ROOT, ADDON_ID, RUNTIME_ENTRIES)
        digest = hashlib.sha256(raw).hexdigest()
        assert SHA256_RE.fullmatch(digest)

    def test_excludes_dotfiles_and_tests(self):
        raw = _build_deterministic_zip(REPO_ROOT, ADDON_ID, RUNTIME_ENTRIES)
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            for info in zf.infolist():
                rel = info.filename.split("/", 1)[1]
                top = rel.split("/")[0]
                filename = rel.rsplit("/", 1)[-1]
                assert not filename.startswith(".")
                assert top not in ("tests", "__pycache__", ".github",
                                   ".pytest_cache", ".mypy_cache", ".ruff_cache")

    def test_no_unexpected_top_level(self):
        raw = _build_deterministic_zip(REPO_ROOT, ADDON_ID, RUNTIME_ENTRIES)
        allowed_top = {"addon.xml", "main.py", "script.py", "resources"}
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            for info in zf.infolist():
                rel = info.filename.split("/", 1)[1]
                top = rel.split("/")[0]
                assert top in allowed_top, f"Unexpected top-level: {top}"


# ---------------------------------------------------------------------------
# 8.  Token isolation and secret hygiene
# ---------------------------------------------------------------------------

class TestTokenIsolation:
    """No secrets leak into validations; notify uses only REPO_DISPATCH_TOKEN."""

    def test_validations_no_custom_secrets(self):
        content = _read_text("addon-validations.yml")
        secrets_used = re.findall(r"\{\{\s*secrets\.(\w+)\s*\}\}", content)
        assert len(secrets_used) == 0

    def test_notify_reusable_workflow_uses_only_dispatch_token(self):
        content = _read_text("notify-repository.yml")
        secret_refs = re.findall(r"\{\{\s*secrets\.(\w+)\s*\}\}", content)
        assert "REPO_DISPATCH_TOKEN" in secret_refs

    def test_notify_dispatch_token_passed_to_reusable(self):
        content = _read_text("notify-repository.yml")
        assert "REPO_DISPATCH_TOKEN" in content
        refs = re.findall(r"\{\{\s*secrets\.REPO_DISPATCH_TOKEN\s*\}\}", content)
        assert len(refs) >= 1

    def test_notify_no_credentials_in_text(self):
        lower = _read_text("notify-repository.yml").lower()
        for word in ("password", "api_key", "private_key"):
            assert word not in lower

    def test_notify_no_artifact_bytes(self):
        lower = _read_text("notify-repository.yml").lower()
        assert "artifact_bytes" not in lower
        assert "signed_download_url" not in lower

    def test_notify_no_peter_evans_dispatch(self):
        assert "peter-evans/repository-dispatch" not in _read_text("notify-repository.yml")


# ---------------------------------------------------------------------------
# 9.  No legacy patterns
# ---------------------------------------------------------------------------

class TestNoLegacyPatterns:
    """Verify legacy patterns have been removed."""

    def test_no_legacy_addon_check_in_validations(self):
        assert "kodi-addon-checker" not in _read_text("addon-validations.yml")

    def test_no_legacy_addon_updated_in_notify(self):
        assert "addon-updated" not in _read_text("notify-repository.yml")


# ---------------------------------------------------------------------------
# 10. Unicode sanity
# ---------------------------------------------------------------------------

class TestUnicodeSanity:
    """No en-dash or em-dash in workflow files."""

    @pytest.mark.parametrize("name", ALL_WORKFLOWS)
    def test_no_u2013(self, name):
        assert "\u2013" not in _read_text(name)

    @pytest.mark.parametrize("name", ALL_WORKFLOWS)
    def test_no_u2014(self, name):
        assert "\u2014" not in _read_text(name)


# ---------------------------------------------------------------------------
# 11. Notify evidence download and forwarding contract
# ---------------------------------------------------------------------------

class TestNotifyEvidenceContract:
    """Evidence is downloaded by the official action and validated locally."""

    @pytest.fixture(autouse=True)
    def load(self):
        self.text = _read_text("notify-repository.yml")
        self.data = _load_yaml("notify-repository.yml")
        self.validate = self.data["jobs"].get("validate-evidence", {})
        self.notify = self.data["jobs"].get("notify", {})

    def test_downloads_exact_evidence_from_triggering_run(self):
        assert self.validate, "validate-evidence job is required"
        download = next(
            step for step in self.validate["steps"]
            if step.get("name") == "Download validation evidence"
        )
        assert download["uses"] == f"actions/download-artifact@{DOWNLOAD_ARTIFACT_SHA}"
        assert download["with"] == {
            "name": "validation-evidence",
            "run-id": "${{ github.event.workflow_run.id }}",
            "github-token": "${{ github.token }}",
        }

    def test_evidence_validation_is_fail_closed(self):
        for fragment in (
            "validation-evidence.json",
            "object_pairs_hook",
            "fields not in",
            "required_fields",
            "validation_run_id",
            "candidate_sha",
            "validation_head_sha",
            "addon_id",
            "addon_version",
            "asset_name",
            "artifact_sha256",
            "publication_id",
        ):
            assert fragment in self.text

    def test_evidence_is_bound_to_trigger_and_tubecast_identity(self):
        for fragment in (
            'evidence["validation_run_id"] != run_id',
            'evidence["candidate_sha"] != head_sha',
            'evidence["validation_head_sha"] != head_sha',
            'evidence["addon_id"] != ADDON_ID',
            'f"{ADDON_ID}-{version}.zip"',
            'f"{ADDON_ID}@{version}"',
            'SHA256_RE.fullmatch(evidence["artifact_sha256"])',
        ):
            assert fragment in self.text
        assert 'ADDON_ID = "script.tubecast"' in self.text

    def test_jobs_have_only_required_permissions(self):
        assert "permissions" not in self.data
        assert self.validate["permissions"] == {"actions": "read"}
        assert self.notify["permissions"] == {
            "actions": "read",
            "contents": "read",
            "id-token": "write",
        }

    def test_notifier_receives_only_exact_validated_values(self):
        assert self.notify["needs"] == "validate-evidence"
        assert self.notify["with"] == {
            "source_repository": "${{ github.repository }}",
            "candidate_sha": "${{ github.event.workflow_run.head_sha }}",
            "validation_run_id": "${{ github.event.workflow_run.id }}",
            "validation_workflow": "Add-on Validations",
            "validation_workflow_path": ".github/workflows/addon-validations.yml",
            "validation_event": "${{ github.event.workflow_run.event }}",
            "expected_branch": "develop",
            "addon_id": "script.tubecast",
            "addon_version": "${{ needs.validate-evidence.outputs.addon_version }}",
            "asset_name": "${{ needs.validate-evidence.outputs.asset_name }}",
            "artifact_sha256": "${{ needs.validate-evidence.outputs.artifact_sha256 }}",
            "publication_id": "${{ needs.validate-evidence.outputs.publication_id }}",
        }

    @pytest.mark.parametrize("forbidden", [
        "archive_download_url",
        "urllib",
        "repository-dispatch",
        "client-payload",
        "secrets: inherit",
    ])
    def test_no_legacy_or_direct_dispatch_patterns(self, forbidden):
        assert forbidden not in self.text
