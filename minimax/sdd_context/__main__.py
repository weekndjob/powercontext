"""Public CLI: import, context, validate, save, resume, develop."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

from .repository import EngineeringRepository, load_documents, project_fingerprints
from .state import reuse_state, task_state


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def run_tests(project: Path, evidence: Path):
    project_id, documents = load_documents(project)
    evidence.mkdir(parents=True, exist_ok=True)
    results = []
    for name, target in (("target", "tests/test_archive.py"), ("compatibility", "tests/test_compatibility.py")):
        command = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", target]
        env = os.environ.copy()
        # Generated sample code does not need model or database credentials.
        for key in list(env):
            if any(part in key.upper() for part in ("KEY", "TOKEN", "PASSWORD", "SECRET")):
                env.pop(key)
        env["PYTHONPATH"] = str(project)
        result = subprocess.run(command, cwd=project, env=env, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=60)
        (evidence / f"{name}.log").write_text(result.stdout + result.stderr, encoding="utf-8")
        results.append({"group": name, "command": command, "exit_code": result.returncode,
                        "log": f"{name}.log"})
    value = {"results": results, "fingerprints": project_fingerprints(project_id, documents),
             "python": sys.version, "passed": all(item["exit_code"] == 0 for item in results)}
    write_json(evidence / "tests.json", value)
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("import", "context", "validate", "save", "resume", "develop"))
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--state", type=Path, default=Path(".state"))
    parser.add_argument("--task", default="archive-filter")
    parser.add_argument("--query", default="archive")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--record", type=Path)
    args = parser.parse_args()
    project = args.project.resolve()
    project_id, documents = load_documents(project)
    fingerprints = project_fingerprints(project_id, documents)
    if args.command == "validate":
        value = run_tests(project, args.output.parent / args.output.stem)
    elif args.command == "save":
        if not args.record:
            parser.error("save requires --record")
        record = json.loads(args.record.read_text(encoding="utf-8"))
        if record.get("fingerprints") != fingerprints:
            raise ValueError("The recorded verification does not match the current project")
        value = asyncio.run(task_state(args.state, project_id, args.task, {
            "completed": ["Imported task specifications and retrieved context", "Ran target and compatibility tests"],
            "todo": [] if record["passed"] else ["Use MiniMax to fix archive filtering", "Run unchanged tests again"],
            "verification": record, "fingerprints": fingerprints,
        }))
    elif args.command == "resume":
        value = reuse_state(asyncio.run(task_state(args.state, project_id, args.task)), fingerprints)
    else:
        repository = EngineeringRepository(args.output.parent / "database.jsonl")
        try:
            repository.initialize()
            if args.command == "import":
                value = repository.import_project(project)
            else:
                value = repository.context(project, args.query)
                value["task_id"] = args.task
                value["progress"] = reuse_state(
                    asyncio.run(task_state(args.state, project_id, args.task)), fingerprints)
                if args.command == "develop":
                    from .agent import generate_change
                    value = generate_change(value, project, args.output.parent / "minimax")
        finally:
            repository.close()
    write_json(args.output, value)
    print(json.dumps(value, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
