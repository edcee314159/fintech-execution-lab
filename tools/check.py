"""Installed-wheel regression and eight diagnostic entry points from external cwd."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

# Protect the source-adjacent helper import even for standalone invocations.
sys.dont_write_bytecode = True

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace",required=True,type=Path)
    args=parser.parse_args()
    source=Path(__file__).resolve().parents[1]
    from bootstrap import external_empty
    try:work=external_empty(args.workspace,source)
    except ValueError as exc:parser.error(str(exc))
    work.mkdir(parents=True,exist_ok=True)
    for name in ("temp","mpl"): (work/name).mkdir()
    env=os.environ.copy();env.pop("PYTHONPATH",None)
    env.update(PYTHONUTF8="1",PYTHONDONTWRITEBYTECODE="1",TEMP=str(work/"temp"),TMP=str(work/"temp"),
        TMPDIR=str(work/"temp"),MPLCONFIGDIR=str(work/"mpl"),MPLBACKEND="Agg",
        OPENBLAS_NUM_THREADS="1",OMP_NUM_THREADS="1",MKL_NUM_THREADS="1")
    report={"ok":False,"checks":[]}
    def run(label,args):
        child=subprocess.run([sys.executable,*map(str,args)],cwd=work,env=env,capture_output=True,text=True,encoding="utf-8")
        (work/(label+".stdout.txt")).write_text(child.stdout,encoding="utf-8")
        (work/(label+".stderr.txt")).write_text(child.stderr,encoding="utf-8")
        report["checks"].append({"name":label,"returncode":child.returncode})
        print(label,child.returncode,flush=True)
        if child.returncode:raise RuntimeError(label+" failed; see logs in "+str(work))
    try:
        import execution_lab,execution_research
        for mod in (execution_lab,execution_research):
            location=Path(mod.__file__).resolve()
            if source==location or source in location.parents:raise RuntimeError("check requires an installed wheel, not source imports")
        run("pip-check",["-m","pip","check"])
        run("doctor",["-m","execution_research","doctor"])
        run("pytest",["-m","pytest",source/"tests","--rootdir",source,"--confcutdir",source,
            "-q","-p","no:cacheprovider","--basetemp",work/"pytest-tmp"])
        run("smoke",["-m","execution_research","smoke","all","--output",work/"smoke"])
        verified=0
        for manifest in (work/"smoke").glob("*/manifest.json"):
            for name,digest in json.loads(manifest.read_text(encoding="utf-8"))["sha256"].items():
                if hashlib.sha256((manifest.parent/name).read_bytes()).hexdigest()!=digest:raise RuntimeError("manifest mismatch: "+name)
            verified+=1
        if verified!=8:raise RuntimeError("expected all eight output manifests")
        report.update(ok=True,verified_smoke_manifests=verified,python=sys.version,installed_package=str(Path(execution_research.__file__).parent))
    finally:
        (work/"verification.json").write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(report,indent=2))

if __name__=="__main__":main()
