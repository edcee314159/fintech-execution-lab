"""One strict, portable experiment bundle is the source of every output."""
import csv
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import platform
import subprocess
from . import __version__
from .schedule import make_twap, make_ac
from .types import Experiment

def _provenance():
    package = Path(__file__).resolve().parent
    digest = hashlib.sha256()
    for path in sorted(package.glob("*.py")):
        digest.update(path.name.encode())
        digest.update(b"\0")
        digest.update(path.read_bytes().replace(b"\r\n", b"\n"))
        digest.update(b"\0")
    commit, dirty = None, None
    root = package.parent.parent
    if (root / ".git").exists():
        try:
            commit = subprocess.check_output(["git", "rev-parse", "HEAD"],
                cwd=root, text=True, stderr=subprocess.DEVNULL, timeout=5).strip()
            status = subprocess.check_output(["git", "status", "--porcelain", "--", "src"],
                cwd=root, text=True, stderr=subprocess.DEVNULL, timeout=5)
            dirty = bool(status.strip())
        except (OSError, subprocess.SubprocessError):
            pass
    return {"software_version": __version__, "python": platform.python_version(),
        "platform": platform.system(),
        "dependencies": {name: version(name) for name in ("numpy", "scipy", "matplotlib")},
        "source_digest_sha256": digest.hexdigest(), "source_commit": commit,
        "source_modified": dirty, "created_utc": datetime.now(timezone.utc).isoformat()}

def _schedule_data(schedule):
    return {"strategy": schedule.strategy, "integer": schedule.integer,
        "quantities": schedule.quantities.tolist(), "inventory": schedule.inventory.tolist()}

def build_bundle(experiment: Experiment, summary: dict) -> dict:
    e = experiment
    references = {"twap": make_twap(e.config, integer=False),
        "ac_simplified": make_ac(e.config, integer=False)}
    return {"schema_version": "1.0", "model_type": "linear_temporary_impact_reference",
        "config": e.config.to_dict(), "provenance": _provenance(),
        "schedules": {name: _schedule_data(s) for name, s in e.schedules.items()},
        "continuous_references": {name: _schedule_data(s) for name, s in references.items()},
        "price_innovations": None if e.price_innovations is None else e.price_innovations.tolist(),
        "accounting": e.accounting, "prices": e.prices.tolist(), "fills": {name: v.tolist() for name, v in e.fills.items()},
        "fills_semantics": "execution_price_per_share; planned quantities are guaranteed filled",
        "costs": {name: v.tolist() for name, v in e.costs.items()},
        "valid_pairs": e.valid_pairs.tolist(), "invalid_reasons": e.invalid_reasons,
        "summary": summary}

def export_bundle(bundle: dict, output_dir: Path) -> dict[str, Path]:
    from .plotting import render_figures
    from .report import render_note
    output_dir = Path(output_dir)
    serialized = json.dumps(bundle, indent=2, allow_nan=False) + "\n"
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {"results.json": output_dir / "results.json", "metrics.csv": output_dir / "metrics.csv",
        "study-note.md": output_dir / "study-note.md"}
    paths["results.json"].write_text(serialized, encoding="utf-8", newline="\n")
    with paths["metrics.csv"].open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(["strategy", "scope", "count", "mean_currency", "variance_currency_squared",
            "standard_error_currency", "ci95_low", "ci95_high"])
        rows = dict(bundle["summary"]["strategies"])
        rows["ac_minus_twap"] = bundle["summary"]["paired"]
        for name, row in rows.items():
            for scope in ("empirical", "all_paths"):
                stat = row[scope]
                ci = stat["ci95_mean"] or [None, None]
                writer.writerow([name, stat["label"], stat["count"], stat["mean"], stat["variance"],
                    stat["standard_error"], *ci])
    paths["study-note.md"].write_text(render_note(bundle), encoding="utf-8", newline="\n")
    paths.update(render_figures(bundle, output_dir))
    manifest = {"schema_version": "1.0",
        "sha256": {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in paths.items()}}
    target = output_dir / "manifest.json"
    target.write_text(json.dumps(manifest, indent=2, allow_nan=False)+"\n", encoding="utf-8", newline="\n")
    paths["manifest.json"] = target
    return paths
