# FinTech Execution Lab

A reproducible Python research toolkit for trading execution: temporary-impact costs, inventory risk, numerical optimization, Monte Carlo inference, volume benchmarks and participation constraints.

The package contains the core model, seven simulation/calibration extensions and a chronological SPY/AAPL intraday-volume pilot. It is research software under simplified assumptions. Historical replay is a capacity diagnostic, not actual fills or evidence of profitability.

## Install and verify

Windows and Python3.12 are the verified environment. Run from the repository root using a new absolute workspace outside the repository:

```powershell
python tools/bootstrap.py --workspace D:\Codex\FinTech-Execution-Lab\install --test
```

Bootstrap builds a wheel in external staging, creates an isolated environment, installs pinned dependencies, runs all tests and smoke-checks the original eight studies. Initial dependency installation needs internet; use `--wheelhouse` for an existing offline wheel directory. Generated files stay outside source.

```powershell
D:\Codex\FinTech-Execution-Lab\install\venv\Scripts\python.exe -m execution_research list
D:\Codex\FinTech-Execution-Lab\install\venv\Scripts\python.exe -m execution_research doctor
D:\Codex\FinTech-Execution-Lab\install\venv\Scripts\python.exe -m execution_research run all --output D:\Codex\FinTech-Execution-Lab\full-run
```

Installed commands are `execution-lab`, `execution-lab-research` and `execution-volume-validate`. Smoke runs are installation diagnostics; full research uses the packaged fixed designs. Use new output directories to preserve prior results.

## Research and evidence

- [Research map](docs/research-map.md)
- [Reproduction guide](docs/reproduction.md)
- [Model assumptions](docs/original-core/model.md)
- [Historical data notice](docs/studies/historical/DATA-NOTICE.md)
- [Real intraday volume: methods and reproduction](docs/real-volume.md)
- [Frozen real-volume research report](results/real-volume/research-note.md)

The historical volume pilot uses five prior complete sessions to predict each of five evaluation dates, three predictors, three order sizes and three planners. It contains30 forecasts and270 scenario records, with264 plans and229 completed retrospective replays. Repeated scenarios share market dates and are not independent observations. Raw FirstRate Data inputs and private price/volume arrays are excluded. Vendor sample URLs may rotate; frozen hashes reject changed inputs.

Saved numerical studies are frozen evidence. Report wording and metadata are maintained separately from financial calculations; source hashes inside prior results identify the producing revision. Current manifests describe the distributed files. Simulation volume profiles remain synthetic; daily ECB references are not executable quotes. Prices, impact, spread, queue and fill assumptions limit real-market interpretation. A continuous-relaxation bound does not prove integer global optimality.

Distribution version0.3.1; model kernel interface version0.1.0. Tests cover financial accounting, analytical moments, numerical solutions, chronology, integer quotas, feasibility, residual marking and output safety. See [verification](docs/verification.md) for the release check record. GitHub Actions configuration runs the same external build/install/check workflow.

## Attribution and data

Implementation and research preparation use AI assistance. Financial references and data attribution are retained in their study notes. Data are governed by their source conditions; source notices do not grant a project-code license. No code license is asserted by this repository.
