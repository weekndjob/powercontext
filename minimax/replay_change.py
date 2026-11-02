"""Verify the recorded MiniMax change with unchanged tests, without a new API call."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil

from sdd_context.__main__ import run_tests, write_json
from sdd_context.repository import digest


ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, default=ROOT / "evidence/live")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    evidence = args.evidence.resolve()
    record = json.loads((evidence / "minimax/minimax-response.json").read_text(encoding="utf-8"))
    request = json.loads((evidence / "minimax/minimax-request.json").read_text(encoding="utf-8"))
    if record["provider"] != "MiniMax" or not record["response_id"]:
        raise ValueError("Missing actual model development record")
    context = json.loads(next(row["content"] for row in request["messages"] if row["role"] == "user"))
    sources = {row["path"]: row for row in context["sources"]}
    before_code = (evidence / "minimax/taskboard.before.py").read_bytes()
    after_code = (evidence / "minimax/taskboard.after.py").read_bytes()
    if digest(before_code) != record["before_sha256"] or digest(after_code) != record["after_sha256"]:
        raise ValueError("Code snapshot differs from the model record")
    if record["output"]["path"] != "taskboard.py" or record["output"]["content"].encode("utf-8") != after_code:
        raise ValueError("Saved code is not the recorded model output")
    if (ROOT / "sample/taskboard.py").read_bytes() != before_code:
        raise ValueError("Initial sample no longer matches the recorded task")
    tests = ("tests/test_archive.py", "tests/test_compatibility.py")
    for path in tests:
        if digest((ROOT / "sample" / path).read_bytes()) != sources[path]["sha256"]:
            raise ValueError("The fixed tests differ from the model's task context")
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    project = out / "project"
    shutil.copytree(ROOT / "sample", project, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    before = run_tests(project, out / "before-tests")
    if [row["exit_code"] for row in before["results"]] != [1, 0]:
        raise ValueError("Initial functional failure or compatibility result was not reproduced")
    if "3 failed, 2 passed" not in (out / "before-tests/target.log").read_text(encoding="utf-8"):
        raise ValueError("Initial test failure was not the required functional failure")
    (project / "taskboard.py").write_bytes(after_code)
    after = run_tests(project, out / "after-tests")
    if not after["passed"]:
        raise ValueError("Recorded MiniMax code does not pass the fixed tests")
    if any(before["fingerprints"][path] != after["fingerprints"][path] for path in tests):
        raise ValueError("Tests changed during replay")
    report = {"status": "recorded_change_verified", "response_id": record["response_id"],
              "new_model_request": False, "tests_unchanged": True,
              "before_sha256": record["before_sha256"], "after_sha256": record["after_sha256"],
              "before": before, "after": after}
    write_json(out / "replay.json", report)
    print(json.dumps({key: report[key] for key in ("status", "response_id", "new_model_request", "tests_unchanged")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
