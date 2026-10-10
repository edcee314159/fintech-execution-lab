
import importlib,json,subprocess,sys
from pathlib import Path
import pytest

NAMES=("core","sensitivity","robustness","statistics","solver","historical","volume","participation")

def test_registry_packages_all_default_inputs():
    from execution_research.registry import STUDIES, default_input
    assert tuple(STUDIES)==NAMES
    for name in NAMES:
        path=default_input(name)
        assert path.is_file()
        assert isinstance(json.loads(path.read_text(encoding="utf-8")),dict)
    historical=default_input("historical").parent/"source"
    assert (historical/"eurofxref-hist.zip").stat().st_size>600000
    assert (historical/"source-metadata.json").is_file()

def test_report_namespaces_and_shared_dependency():
    a=importlib.import_module("execution_research.studies.historical.study_reporting")
    b=importlib.import_module("execution_research.studies.volume.study_reporting")
    assert a is not b and a.__file__!=b.__file__
    from execution_research.studies.participation import participation
    from execution_research.studies.volume import volume_benchmark
    assert participation.normalize_volume is volume_benchmark.normalize_volume

def test_cli_list_and_doctor_from_external_directory(tmp_path):
    for command in ("list","doctor"):
        run=subprocess.run([sys.executable,"-m","execution_research",command],cwd=tmp_path,capture_output=True,text=True)
        assert run.returncode==0,run.stderr
        data=json.loads(run.stdout)
        if command=="list":assert tuple(x["name"] for x in data)==NAMES
        else:
            assert data["ok"]
            assert data["core_source_sha256"]=="0eab9ba5bf9201a7d456430c02a5a293236473c4f9c7f046e94043ef58ab36c1"

def test_output_rejected_before_mutation(tmp_path):
    from execution_research.runner import validate_output
    occupied=tmp_path/"occupied";occupied.mkdir()
    sentinel=occupied/"keep.txt";sentinel.write_text("keep")
    with pytest.raises(ValueError,match="empty"):validate_output(occupied)
    assert sentinel.read_text()=="keep"
    with pytest.raises(ValueError,match="absolute"):validate_output(Path("relative"))
    with pytest.raises(ValueError,match="source|installation"):
        validate_output(Path(importlib.import_module("execution_research").__file__).parent/"forbidden")

def test_smoke_design_is_separate_and_does_not_mutate_default():
    from execution_research.runner import diagnostic_design
    from execution_research.registry import default_input
    original=json.loads(default_input("statistics").read_text(encoding="utf-8"))
    snapshot=json.dumps(original,sort_keys=True)
    reduced=diagnostic_design("statistics",original)
    assert json.dumps(original,sort_keys=True)==snapshot
    assert reduced["base"]["trials"]==100
    assert reduced["sample_sizes"][-1]==100
    assert len(reduced["seeds"])==3

def test_unknown_study_creates_nothing(tmp_path):
    out=tmp_path/"absent"
    run=subprocess.run([sys.executable,"-m","execution_research","run","unknown","--output",str(out)],cwd=tmp_path,capture_output=True,text=True)
    assert run.returncode==2
    assert not out.exists()
