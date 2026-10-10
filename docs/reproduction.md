# Reproduction guide

Install with tools/bootstrap.py in a new absolute workspace outside the repository; see the root README. Python3.12 and pinned requirements.lock are the supported environment. Bootstrap `--test` runs the full regression suite and eight installation smoke studies against an installed wheel.

The eight unified identifiers are core, sensitivity, robustness, statistics, solver, historical, volume and participation. `python -m execution_research run <id> --output <new absolute directory>` uses that study's packaged full design. `run all` runs all eight. The historical real-volume pilot has its own command described in [real-volume.md](real-volume.md).

`results/` contains saved full-study numerical evidence, not smoke output. New runs may differ in timestamps, source hashes and numerical solver timings. Report text and attribution have been maintained without changing saved financial records. Inspect the individual assumptions and design before interpreting differences.

Generated outputs, virtual environments, build copies, caches and inputs belong outside source. Preserve failed-run logs and use fresh result directories. Source packages include fixed default designs and the existing ECB snapshot under its source notice. FirstRate raw inputs must be acquired independently and must not be redistributed.

Use `tools/check.py --workspace <new absolute directory>` with installed Python to run tests, eight smoke studies and manifest checks. Results manifests hash their present files. The root provenance manifest records current repository bytes; source hashes within old results identify older producing revisions.
