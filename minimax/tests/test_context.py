"""Behavior tests; database cases use real seekdb, never a SQLite substitute."""
import asyncio
import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from sdd_context.repository import EngineeringRepository, load_documents, project_fingerprints
from sdd_context.state import reuse_state


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "project"
    shutil.copytree(ROOT / "sample", root, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    manifest = json.loads((root / "manifest.json").read_text())
    manifest["project_id"] = "test_" + uuid.uuid4().hex
    (root / "manifest.json").write_text(json.dumps(manifest))
    return root


def cli(project, directory, command, *extra):
    output = directory / f"{command}-{uuid.uuid4().hex}.json"
    result = subprocess.run([sys.executable, "-m", "sdd_context", command, "--project", str(project),
                             "--state", str(directory / "state"), "--output", str(output), *extra],
                            cwd=ROOT, capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(output.read_text(encoding="utf-8")), output


def test_manifest_rejects_source_escape_before_import(project):
    manifest = json.loads((project / "manifest.json").read_text())
    manifest["documents"][0]["path"] = "../outside.md"
    (project / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="within"):
        load_documents(project)


def test_changing_only_spec_status_invalidates_old_validation(project):
    project_id, documents = load_documents(project)
    before = project_fingerprints(project_id, documents)
    manifest = json.loads((project / "manifest.json").read_text())
    manifest["documents"][0]["status"] = "superseded"
    (project / "manifest.json").write_text(json.dumps(manifest))
    _, updated = load_documents(project)
    after = project_fingerprints(project_id, updated)
    assert before["specs/archive_policy.md"] == after["specs/archive_policy.md"]
    assert before["@manifest"] != after["@manifest"]
    assert reuse_state({"state": {"fingerprints": before}}, after)["validation_applicable"] is False


def test_real_powercontext_restart_and_source_change(project, tmp_path):
    empty, _ = cli(project, tmp_path, "resume")
    assert empty["state"] is None
    before, record = cli(project, tmp_path, "validate")
    assert [item["exit_code"] for item in before["results"]] == [1, 0]
    log = record.parent / record.stem / "target.log"
    assert "3 failed, 2 passed" in log.read_text()
    saved, _ = cli(project, tmp_path, "save", "--record", str(record))
    resumed, _ = cli(project, tmp_path, "resume")
    assert saved["pid"] != resumed["pid"]
    assert saved["reference"] == resumed["reference"]
    assert resumed["state"] == saved["state"]
    assert resumed["validation_applicable"] is True
    assert resumed["state"]["todo"]
    code = project / "taskboard.py"
    code.write_text(code.read_text() + "\n# Source changed after prior validation.\n")
    stale, _ = cli(project, tmp_path, "resume")
    assert stale["validation_applicable"] is False
    assert "rerun tests" in stale["next_action"]


@pytest.fixture
def database(tmp_path):
    if os.environ.get("SDD_REAL_DATABASE_TESTS") != "1":
        pytest.skip("Set SDD_REAL_DATABASE_TESTS=1 for real seekdb verification")
    repository = EngineeringRepository(tmp_path / "database.jsonl")
    repository.initialize()
    yield repository
    repository.close()


def test_real_database_selection_reimport_and_project_isolation(database, project):
    first = database.import_project(project)
    context = database.context(project, "archive")
    expected = {"specs/archive_policy.md", "taskboard.py", "tests/test_archive.py", "tests/test_compatibility.py"}
    assert {doc["path"] for doc in context["sources"]} == expected
    assert all(doc["score"] > 0 for doc in context["sources"])
    assert "specs/archive_policy_legacy.md" not in {doc["path"] for doc in context["sources"]}
    spec = project / "specs/archive_policy.md"
    spec.write_text(spec.read_text() + "\nR4: archive retrieval must include the updated-spec-marker.\n")
    with pytest.raises(ValueError, match="re-import"):
        database.context(project, "archive")
    updated = database.import_project(project)
    context = database.context(project, "archive")
    assert updated["fingerprints"] != first["fingerprints"]
    assert any("updated-spec-marker" in doc["body"] for doc in context["sources"])
    # Another project has its own import; retrieval cannot see this project's marker.
    manifest = json.loads((project / "manifest.json").read_text())
    manifest["project_id"] = "isolated_" + uuid.uuid4().hex
    (project / "manifest.json").write_text(json.dumps(manifest))
    assert database.context(project, "archive")["sources"] == []


def test_invalid_snapshot_does_not_erase_committed_documents(database, project):
    original = database.import_project(project)
    manifest = json.loads((project / "manifest.json").read_text())
    manifest["documents"].append({"path": "missing.py", "kind": "code", "status": "active"})
    (project / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="Missing"):
        database.import_project(project)
    rows = database.execute("SELECT path,sha256 FROM sdd_documents WHERE project_id=%s",
                            (original["project_id"],))
    assert {row["path"]: row["sha256"] for row in rows} == {
        key: value for key, value in original["fingerprints"].items() if key != "@manifest"}
