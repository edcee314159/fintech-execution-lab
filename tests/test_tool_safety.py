import importlib,os,shutil,subprocess,sys
from pathlib import Path
import pytest

def test_standalone_checker_does_not_cache_adjacent_source(tmp_path):
    root=Path(__file__).resolve().parents[1]
    tools=tmp_path/"source/tools";tools.mkdir(parents=True)
    for name in ("bootstrap.py","check.py"):shutil.copy2(root/"tools"/name,tools/name)
    env=os.environ.copy()
    env.pop("PYTHONDONTWRITEBYTECODE",None);env.pop("PYTHONPATH",None)
    result=subprocess.run([sys.executable,str(tools/"check.py"),"--workspace","relative"],
        cwd=tmp_path,env=env,capture_output=True,text=True)
    assert result.returncode==2
    assert not list(tools.rglob("*.pyc"))

def test_installed_cli_rejects_source_descendant(tmp_path,monkeypatch):
    runner=importlib.import_module("execution_research.runner")
    monkeypatch.setattr(runner,"__file__",str(tmp_path/"installed/site-packages/execution_research/runner.py"))
    source=tmp_path/"research-source";source.mkdir()
    (source/"pyproject.toml").write_text("[project]\nname = 'research'\n")
    target=source/"outputs"/"never-created"
    with pytest.raises(ValueError,match="source"):runner.validate_output(target)
    assert not target.exists()
