"""Fetch licensed samples locally, or run the frozen pilot."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import urllib.request
import zipfile
from .study import run_study,save_study


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("action",choices=("fetch","run"));p.add_argument("--input-dir",type=Path,required=True)
    p.add_argument("--output",type=Path);p.add_argument("--design",type=Path,default=Path(__file__).parent/"inputs"/"design.json")
    args=p.parse_args();design=json.loads(args.design.read_text(encoding="utf-8"))
    if args.action=="fetch":
        args.input_dir.mkdir(parents=True,exist_ok=True)
        for symbol in design["symbols"]:
            source=design["sources"][symbol]
            request=urllib.request.Request(source["url"],headers={"User-Agent":"Mozilla/5.0","Referer":"https://firstratedata.com/free-intraday-data"})
            data=urllib.request.urlopen(request,timeout=60).read()
            if hashlib.sha256(data).hexdigest()!=source["archive_sha256"]:raise ValueError(f"{symbol}: vendor sample rotated; frozen archive hash mismatch. Do not silently use it as the original study.")
            with zipfile.ZipFile(io.BytesIO(data)) as z:csv=z.read(source["csv_member"])
            if hashlib.sha256(csv).hexdigest()!=source["csv_sha256"]:raise ValueError("CSV hash mismatch")
            name=source["csv_member"]
            if Path(name).name!=name or "/" in name or "\\" in name:raise ValueError("unsafe source filename")
            (args.input_dir/name).write_bytes(csv)
            print(f"{symbol}: local licensed input verified; do not redistribute")
    else:
        if args.output is None:p.error("run requires --output")
        if args.output.exists() and (not args.output.is_dir() or any(args.output.iterdir())):p.error("output must be new or empty")
        result,private,public=run_study(args.input_dir,design);save_study(result,private,public,args.output)
        from .reporting import write_report
        write_report(result,private,public,args.output)
        print(json.dumps({"records":len(result["records"]),"forecasts":len(result["forecasts"]),"planned":result["planned_record_count"],"completed":result["completed_record_count"],"evaluation_symbol_days":result["evaluation_symbol_days"]}))

if __name__=="__main__":main()
