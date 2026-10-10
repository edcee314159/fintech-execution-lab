"""Validated local experiment command."""
import argparse
from dataclasses import fields
import json
from pathlib import Path
from .config import ExecutionConfig
from .schedule import make_twap, make_ac
from .simulation import run_paired
from .metrics import summarize
from .export import build_bundle, export_bundle

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare TWAP and simplified AC under a temporary-impact reference model.")
    parser.add_argument("--config", type=Path, help="JSON configuration; explicit flags take precedence")
    parser.add_argument("--output", type=Path, default=Path("artifacts/default"))
    parser.add_argument("--overwrite", action="store_true", help="Overwrite known study files in the output directory")
    integers = {"quantity", "intervals", "trials", "seed"}
    for field in fields(ExecutionConfig):
        parser.add_argument("--"+field.name.replace("_","-"), dest=field.name,
            type=int if field.name in integers else float, default=None)
    args = parser.parse_args(argv)
    try:
        data = {}
        if args.config is not None:
            data = json.loads(args.config.read_text(encoding="utf-8-sig"))
            if not isinstance(data,dict):
                raise ValueError("configuration must be a JSON object")
        data.update({field.name:getattr(args,field.name) for field in fields(ExecutionConfig)
            if getattr(args,field.name) is not None})
        config = ExecutionConfig.from_dict(data)
        if args.output.exists() and not args.overwrite:
            raise ValueError("output already exists; choose another directory or use --overwrite")
        if args.output.exists() and not args.output.is_dir():
            raise ValueError("output must be a directory")
        experiment = run_paired(config, {"twap":make_twap(config),"ac_simplified":make_ac(config)})
        summary = summarize(experiment)
        export_bundle(build_bundle(experiment,summary),args.output)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    print(f'Study status: {summary["status"]}; {summary["valid_pairs"]}/{summary["total_pairs"]} valid pairs. '
        "Results, figures and study note exported.")
    return 0 if summary["status"] == "valid" else 2
