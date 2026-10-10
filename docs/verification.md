# Local release verification

Release0.3.1 was checked on2026-10-11 with Windows/Python3.12.10 in an isolated environment without system-site-packages.

- External-staging wheel build, pinned dependency installation, pip check and doctor: passed.
- Full regression suite against the installed wheel:188 tests passed.
- Eight installed diagnostic study runs: passed; all eight output manifests verified.
- Installed real-volume pilot:30 forecasts,270 case records,264 plans and229 completed retrospective replays. Numerical records equal the saved evidence;792 public strategy arrays match exactly.
- Installed Python source and packaged design files:54 byte-for-byte matches.
- All65 saved CSV, NPZ and PNG files retained from the existing numerical evidence are unchanged. Report attribution and documentation are maintained separately from financial calculations.

These are local checks. Hosted results are available separately in GitHub Actions. Smoke runs test installation and do not replace full research. The real-volume pilot has only five evaluation dates and does not establish live fills, complete market-volume coverage or profitability.

Byte-preserving Git attributes keep source digests, frozen inputs and result manifests stable across checkouts. Current repository checksums are recorded in provenance/repository-manifest.json. Study manifests describe distributed files; hashes embedded in prior results identify their producing revision.
