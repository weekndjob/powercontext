"""Reproduce the six official checks, or prepare evidence before MiniMax activation."""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

from sdd_context.repository import load_documents, project_fingerprints


ROOT = Path(__file__).resolve().parent
REQUIRED = {"specs/archive_policy.md", "taskboard.py", "tests/test_archive.py", "tests/test_compatibility.py"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="A new, nonexistent run directory")
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    project = out / "project"
    shutil.copytree(ROOT / "sample", project, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    manifest = json.loads((project / "manifest.json").read_text())
    manifest["project_id"] = "demo_" + uuid.uuid4().hex
    (project / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    def invoke(name, command, *extra):
        output = out / f"{name}.json"
        cmd = [sys.executable, "-m", "sdd_context", command, "--project", str(project),
               "--state", str(out / "state"), "--output", str(output), *extra]
        completed = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                                   encoding="utf-8", errors="replace", timeout=240)
        (out / f"{name}.process.log").write_text(completed.stdout + completed.stderr, encoding="utf-8")
        with (out / "commands.jsonl").open("a", encoding="utf-8") as log:
            log.write(json.dumps({"command": cmd, "exit_code": completed.returncode}) + "\n")
        if completed.returncode != 0:
            raise RuntimeError(f"Step {name} failed; see {out / (name + '.process.log')}")
        return json.loads(output.read_text(encoding="utf-8"))

    def check_context(value):
        sources = {item["path"]: item for item in value["sources"]}
        assert REQUIRED.issubset(sources), "Required source was not retrieved"
        assert "specs/archive_policy_legacy.md" not in sources
        return sources

    versions = {name: importlib.metadata.version(name) for name in ("powercontext", "PyMySQL", "httpx", "pytest")}
    (out / "versions.json").write_text(json.dumps(versions, indent=2))
    invoke("import", "import")
    initial = invoke("initial-context", "context")
    check_context(initial)
    assert initial["progress"]["state"] is None
    before = invoke("before-tests", "validate")
    assert [row["exit_code"] for row in before["results"]] == [1, 0]
    assert "3 failed, 2 passed" in (out / "before-tests/target.log").read_text()
    saved = invoke("saved-before", "save", "--record", str(out / "before-tests.json"))
    resumed = invoke("resumed-before", "resume")
    assert saved["pid"] != resumed["pid"]
    assert saved["state"] == resumed["state"]
    assert resumed["validation_applicable"] is True
    assert resumed["state"]["todo"]

    # Re-import a genuine source update; it must change the next model context.
    spec = project / "specs/archive_policy.md"
    marker = "archive-spec-updated: R1-C2 remain required after a task handoff."
    spec.write_text(spec.read_text() + "\n" + marker + "\n", encoding="utf-8")
    invoke("updated-import", "import")
    updated = invoke("updated-context", "context")
    sources = check_context(updated)
    assert marker in sources["specs/archive_policy.md"]["body"]
    assert updated["progress"]["validation_applicable"] is False

    checks = {"runnable": True, "minimax_actual": False, "context_correct": True,
              "database_actual": True, "state_reused": True, "code_modification_valid": False}
    if not args.prepare_only:
        invoke("development", "develop")
        project_id, documents = load_documents(project)
        current = project_fingerprints(project_id, documents)
        for path in ("tests/test_archive.py", "tests/test_compatibility.py"):
            assert current[path] == before["fingerprints"][path], "Tests were modified"
        after = invoke("after-tests", "validate")
        assert after["passed"], "Generated change did not pass the fixed tests"
        saved = invoke("saved-after", "save", "--record", str(out / "after-tests.json"))
        resumed = invoke("resumed-after", "resume")
        assert saved["pid"] != resumed["pid"] and saved["state"] == resumed["state"]
        assert resumed["validation_applicable"] and resumed["state"]["verification"]["passed"]
        invoke("final-import", "import")
        final = invoke("final-context", "context")
        assert final["progress"]["state"]["verification"]["passed"]
        checks.update(minimax_actual=True, code_modification_valid=True)
    report = {"checks": checks, "status": "ready_for_submission" if all(checks.values()) else "awaiting_minimax",
              "required_sources": sorted(REQUIRED), "versions": versions}
    (out / "readiness.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
