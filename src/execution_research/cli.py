"""One documented CLI for the core model and seven independent studies."""
import argparse
import importlib
import json
from pathlib import Path
import sys
from importlib.metadata import version
from .registry import STUDIES, default_input
from .runner import run_studies

EXPECTED_CORE = "0eab9ba5bf9201a7d456430c02a5a293236473c4f9c7f046e94043ef58ab36c1"

def doctor():
    from execution_lab.export import _provenance
    from execution_lab import __version__
    checks = {}
    for name, (module, _) in STUDIES.items():
        importlib.import_module(module)
        path = default_input(name)
        json.loads(path.read_text(encoding="utf-8"))
        checks[name] = path.is_file()
    historical = default_input("historical").parent / "source"
    metadata = json.loads((historical / "source-metadata.json").read_text(encoding="utf-8"))
    import hashlib
    checks["offline_archive"] = hashlib.sha256((historical / "eurofxref-hist.zip").read_bytes()).hexdigest() == metadata["archive_sha256"]
    digest = _provenance()["source_digest_sha256"]
    return {"ok": all(checks.values()) and digest == EXPECTED_CORE, "checks": checks,
        "distribution_version": version("trade-execution-lab"), "model_kernel_version": __version__,
        "core_source_sha256": digest, "package": str(Path(__file__).resolve().parent),
        "python": sys.version.split()[0]}

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    sub.add_parser("doctor")
    for command in ("run", "smoke"):
        p = sub.add_parser(command)
        p.add_argument("study", choices=[*STUDIES, "all"])
        p.add_argument("--output", required=True, type=Path, help="absolute, empty directory outside source")
    args = parser.parse_args(argv)
    try:
        if args.command == "list":
            print(json.dumps([{"name": name, "description": value[1]} for name, value in STUDIES.items()], indent=2))
        elif args.command == "doctor":
            result = doctor()
            print(json.dumps(result, indent=2))
            return 0 if result["ok"] else 1
        else:
            names = list(STUDIES) if args.study == "all" else [args.study]
            run_studies(names, args.output, smoke=args.command == "smoke")
        return 0
    except (ValueError, OSError, RuntimeError) as exc:
        parser.exit(2, f"error: {exc}\n")
