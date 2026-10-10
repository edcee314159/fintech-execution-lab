"""Build/install from external staging; never generate build files in source."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import venv

def external_empty(path, source):
    path = Path(path)
    if not path.is_absolute():
        raise ValueError("workspace must be absolute")
    path = path.resolve()
    if path == source or source in path.parents:
        raise ValueError("workspace must be outside source")
    if path.exists() and (not path.is_dir() or any(path.iterdir())):
        raise ValueError("workspace must be new or empty")
    return path

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--wheelhouse", type=Path)
    parser.add_argument("--test", action="store_true")
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[1]
    try:
        if sys.version_info[:2] != (3, 12):
            raise ValueError("Python 3.12 required")
        workspace = external_empty(args.workspace, source)
        wheelhouse = args.wheelhouse.resolve() if args.wheelhouse else None
        if wheelhouse and not wheelhouse.is_dir():
            raise ValueError("wheelhouse must exist")
    except ValueError as exc:
        parser.error(str(exc))
    workspace.mkdir(parents=True, exist_ok=True)
    for folder in ("temp", "pip-cache", "mpl", "wheels"):
        (workspace / folder).mkdir()
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.update(PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1", PIP_DISABLE_PIP_VERSION_CHECK="1",
        PIP_CACHE_DIR=str(workspace/"pip-cache"), TEMP=str(workspace/"temp"), TMP=str(workspace/"temp"),
        TMPDIR=str(workspace/"temp"), MPLCONFIGDIR=str(workspace/"mpl"), MPLBACKEND="Agg",
        OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1")
    # venv's ensurepip inherits the parent environment.
    os.environ.update({k:env[k] for k in ("TEMP","TMP","TMPDIR","PYTHONDONTWRITEBYTECODE","PIP_CACHE_DIR")})
    venv.EnvBuilder(with_pip=True, system_site_packages=False).create(workspace/"venv")
    python = workspace/"venv"/("Scripts/python.exe" if os.name=="nt" else "bin/python")
    def run(*command):
        subprocess.run([str(python), *map(str,command)], cwd=workspace, env=env, check=True)
    offline = ["--no-index", "--find-links", str(wheelhouse)] if wheelhouse else []
    run("-m", "pip", "install", "--no-compile", *offline, "-r", source/"requirements.lock")
    stage = workspace/"build-source"
    stage.mkdir()
    shutil.copytree(source/"src", stage/"src", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in ("pyproject.toml", "README.md"):
        shutil.copy2(source/name, stage/name)
    run("-m", "pip", "wheel", "--no-deps", "--no-build-isolation", "--wheel-dir", workspace/"wheels", stage)
    wheels = list((workspace/"wheels").glob("trade_execution_lab-*.whl"))
    if len(wheels)!=1:
        raise RuntimeError("expected exactly one project wheel")
    run("-m", "pip", "install", "--no-compile", "--no-deps", wheels[0])
    run("-m", "pip", "check")
    run("-m", "execution_research", "doctor")
    if args.test:
        run(source/"tools/check.py", "--workspace", workspace/"verification")
    (workspace/"installation.json").write_text(json.dumps({"python": str(python), "wheel": str(wheels[0]),
        "system_site_packages":False, "tests_requested":args.test},indent=2)+"\n",encoding="utf-8")
    print("Installed Python:", python)

if __name__ == "__main__":
    main()
