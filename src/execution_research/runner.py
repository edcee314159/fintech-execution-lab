"""Isolated child-process orchestration; no financial calculation lives here."""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from .registry import STUDIES, default_input

def source_boundary():
    package = Path(__file__).resolve().parent
    source = package.parent
    return source.parent if (source.parent / "pyproject.toml").is_file() else source

def validate_output(path):
    path = Path(path)
    if not path.is_absolute():
        raise ValueError("output must be an absolute path")
    resolved = path.resolve()
    boundary = source_boundary().resolve()
    if resolved == boundary or boundary in resolved.parents:
        raise ValueError("output must be outside source or installation directory")
    # Installed code cannot infer its original checkout from __file__.
    # Inspect the requested destination ancestry before creating any paths.
    for ancestor in (resolved, *resolved.parents):
        if (ancestor / "pyproject.toml").is_file() or (ancestor / ".git").exists():
            raise ValueError("output must be outside source repositories")
    if resolved.exists() and (not resolved.is_dir() or any(resolved.iterdir())):
        raise ValueError("choose a new or empty output directory")
    return resolved

def diagnostic_design(name, original):
    design = copy.deepcopy(original)
    if name == "core":
        design["trials"] = 20
    elif name == "statistics":
        design["base"]["trials"] = 100
        design["sample_sizes"] = [10, 30, 100]
        design["seeds"] = design["seeds"][:3]
    elif name == "solver":
        design["base"]["trials"] = 20
        design["benchmark_intervals"] = [10, 30, 60]
        design["accuracy_intervals"] = [1, 10, 60]
        design["accuracy_extra_cases"] = []
        design["timing"].update(repeats=2, warmup_calls=1, min_batch_seconds=.0001, max_loops=4)
    elif name != "historical":
        design["base_true" if name == "robustness" else "base"]["trials"] = 20
    return design

def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False)+"\n", encoding="utf-8", newline="\n")

def run_studies(names, output, *, smoke=False):
    if any(name not in STUDIES for name in names):
        raise ValueError("unknown study")
    output = validate_output(output)
    output.mkdir(parents=True, exist_ok=True)
    with (output / "run-request.json").open("x", encoding="utf-8") as stream:
        json.dump({"studies": names, "mode": "diagnostic_smoke" if smoke else "full_design",
            "smoke_is_not_research_evidence": bool(smoke)}, stream, indent=2)
    runtime = output / "_runtime"
    runtime.mkdir()
    for folder in ("temp", "mpl", "inputs", "logs"):
        (runtime / folder).mkdir()
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.update(PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1", MPLBACKEND="Agg",
        MPLCONFIGDIR=str(runtime / "mpl"), TEMP=str(runtime / "temp"), TMP=str(runtime / "temp"),
        TMPDIR=str(runtime / "temp"), OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1")
    records = []
    for name in names:
        source = default_input(name)
        design = json.loads(source.read_text(encoding="utf-8"))
        if smoke:
            design = diagnostic_design(name, design)
        input_dir = runtime / "inputs" / name
        input_dir.mkdir()
        selected = input_dir / source.name
        write_json(selected, design)
        if name == "historical":
            shutil.copytree(source.parent / "source", input_dir / "source")
        command = [sys.executable, "-m", STUDIES[name][0],
            "--config" if name == "core" else "--design", str(selected), "--output", str(output / name)]
        started = time.perf_counter()
        child = subprocess.run(command, cwd=runtime, env=env, capture_output=True, text=True, encoding="utf-8")
        (runtime / "logs" / (name+".stdout.txt")).write_text(child.stdout, encoding="utf-8")
        (runtime / "logs" / (name+".stderr.txt")).write_text(child.stderr, encoding="utf-8")
        record = {"study": name, "returncode": child.returncode, "elapsed_seconds": time.perf_counter()-started,
            "design_sha256": hashlib.sha256(selected.read_bytes()).hexdigest(),
            "output": name, "mode": "diagnostic_smoke" if smoke else "full_design"}
        records.append(record)
        write_json(output / "run-summary.json", {"ok": all(r["returncode"] == 0 for r in records),
            "mode": record["mode"], "completed": len(records), "requested": len(names), "studies": records})
        print(json.dumps(record), flush=True)
        if child.returncode:
            raise RuntimeError(f"{name} exited {child.returncode}; see _runtime/logs/{name}.stderr.txt")
    return records
