import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import pytest

def invoke(*args, cwd=None, env=None):
    return subprocess.run([sys.executable, "-m", "execution_lab", *map(str,args)],
        cwd=cwd, env=env, capture_output=True, text=True, timeout=90)

def test_cli_exports_reproducible_strict_bundle_with_spaces(tmp_path):
    out = tmp_path / "study with spaces"
    args = ["--quantity",10,"--intervals",2,"--duration",2,"--volatility",0,
        "--impact",.1,"--trials",4,"--output",out]
    run = invoke(*args)
    assert run.returncode == 0, run.stderr
    required = {"results.json","metrics.csv","manifest.json","study-note.md",
        "schedule.png","cost-distribution.png","paired-difference.png"}
    assert required <= {p.name for p in out.iterdir()}
    data = json.loads((out/"results.json").read_text())
    assert data["schema_version"] == "1.0"
    assert data["model_type"] == "linear_temporary_impact_reference"
    assert data["summary"]["status"] == "valid"
    assert data["summary"]["strategies"]["twap"]["prediction"]["mean"] == 5
    assert data["summary"]["paired"]["empirical"]["ci95_mean"] == [0,0]
    manifest = json.loads((out/"manifest.json").read_text())
    for name, digest in manifest["sha256"].items():
        assert hashlib.sha256((out/name).read_bytes()).hexdigest() == digest
    for name in ['results.json', 'metrics.csv', 'study-note.md', 'manifest.json']:
        assert b'\r\n' not in (out/name).read_bytes(), 'Portable hashes require LF output'
    first = data
    refused = invoke(*args)
    assert refused.returncode == 2
    assert json.loads((out/"results.json").read_text()) == first
    repeated = invoke(*args, "--overwrite")
    assert repeated.returncode == 0
    second = json.loads((out/"results.json").read_text())
    for key in ["config","schedules","prices","fills","costs","summary"]:
        assert first[key] == second[key]
    assert "NaN" not in (out/"results.json").read_text()

@pytest.mark.parametrize("text", ["{bad json", "[]", '{"unknown":1}',
    '{"trials":100000,"intervals":1000}', '{"volatility":NaN}', '{"quantity":true}'])
def test_bad_config_fails_without_output(tmp_path, text):
    config = tmp_path/"bad.json"
    config.write_text(text)
    out = tmp_path/"no allocation"
    run = invoke("--config",config,"--output",out)
    assert run.returncode == 2, run.stderr
    assert not out.exists()

def test_invalid_model_exports_diagnostics(tmp_path):
    out = tmp_path/"invalid"
    run = invoke("--quantity",100,"--intervals",1,"--duration",1,
        "--price",1,"--impact",1,"--volatility",0,"--trials",4,"--output",out)
    assert run.returncode == 2
    data = json.loads((out/"results.json").read_text())
    assert data["summary"]["status"] == "invalid_model"
    assert len(data["invalid_reasons"]) == 4
    assert data["summary"]["paired"]["empirical"]["ci95_mean"] is None

def test_explicit_flags_override_json(tmp_path):
    config = tmp_path/"input.json"
    config.write_text('{"quantity":10,"intervals":2,"duration":2,"volatility":0,"trials":4}')
    out = tmp_path/"override"
    run = invoke("--config",config,"--quantity",12,"--output",out)
    assert run.returncode == 0, run.stderr
    data = json.loads((out/"results.json").read_text())
    assert data["config"]["quantity"] == 12
    assert data["config"]["intervals"] == 2

def test_wheel_runs_from_fresh_directory_without_source_imports(tmp_path):
    root = Path(__file__).resolve().parents[1]
    stage = tmp_path / 'build-source'
    stage.mkdir()
    shutil.copytree(root / 'src', stage / 'src', ignore=shutil.ignore_patterns('__pycache__'))
    for name in ('pyproject.toml', 'README.md'):
        shutil.copy2(root / name, stage / name)
    wheels = tmp_path / 'wheels'
    build = subprocess.run([sys.executable, '-m', 'pip', 'wheel', '--no-deps',
        '--no-build-isolation', '--wheel-dir', str(wheels), str(stage)],
        capture_output=True, text=True, timeout=90)
    assert build.returncode == 0, build.stderr
    wheel = next(wheels.glob('trade_execution_lab-*.whl'))
    target = tmp_path / 'installed'
    install = subprocess.run([sys.executable, '-m', 'pip', 'install', '--no-deps',
        '--target', str(target), str(wheel)], capture_output=True, text=True, timeout=90)
    assert install.returncode == 0, install.stderr
    work = tmp_path / 'fresh working directory'
    work.mkdir()
    env = os.environ.copy()
    env['PYTHONPATH'] = str(target)
    probe = subprocess.run([sys.executable, '-c',
        'import execution_lab; print(execution_lab.__file__)'], cwd=work,
        env=env, capture_output=True, text=True)
    assert str(target).lower() in probe.stdout.lower()
    out = work / 'study'
    result = invoke('--intervals', 2, '--trials', 5, '--output', out, cwd=work, env=env)
    assert result.returncode == 0, result.stderr
    raw = (out/'results.json').read_text()
    data = json.loads(raw)
    assert len(data['provenance']['source_digest_sha256']) == 64
    assert data['provenance']['source_commit'] is None
    assert str(root) not in raw and str(tmp_path) not in raw
    assert ':\\' not in raw and '/Users/' not in raw and '/home/' not in raw

@pytest.mark.parametrize('via_json', [False, True])
def test_huge_integer_returns_usable_cli_error(tmp_path, via_json):
    out = tmp_path / 'must not allocate'
    if via_json:
        config = tmp_path / 'huge.json'
        config.write_text(json.dumps({'quantity': 10**400}))
        args = ['--config', config]
    else:
        args = ['--quantity', '1'+'0'*400]
    result = invoke(*args, '--output', out)
    assert result.returncode == 2
    assert 'quantity' in result.stderr and 'Traceback' not in result.stderr
    assert not out.exists()
