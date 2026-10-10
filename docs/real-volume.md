# Real equity intraday volume pilot

The fixed design uses FirstRate Data SPY/AAPL minute samples from2026-09-21 through2026-10-02, acquired2026-10-09. Retain complete09:30–16:00 ET sessions only; aggregate390 minutes into78 five-minute bins. Reject incomplete/conflicting/invalid sessions rather than inventing missing volume. Each target uses only the preceding five eligible sessions. All predictors share past-ADV order sizes; current-day volume enters evaluation only.

## Run with installed Python

```powershell
D:\Codex\FinTech-Execution-Lab\install\venv\Scripts\python.exe -m execution_volume_validation fetch --input-dir D:\Codex\FinTech-Execution-Lab\volume-input
D:\Codex\FinTech-Execution-Lab\install\venv\Scripts\python.exe -m execution_volume_validation run --input-dir D:\Codex\FinTech-Execution-Lab\volume-input --output D:\Codex\FinTech-Execution-Lab\volume-run
```

The installed `execution-volume-validate` console command is equivalent. Input/output paths must remain outside source. Existing nonempty outputs are rejected. Running generates JSON, derived strategy arrays, five figures, research notes and a report-provenance receipt. `private-diagnostics/full-arrays.npz` contains raw prices/volumes and must stay private; never publish it or vendor CSV/ZIP inputs.

Vendor URLs may rotate. Fetch verifies archive and CSV SHA-256 against the frozen packaged design and fails on different samples. The workflow is reproducible only when the exact inputs remain obtainable under the vendor's terms; the repository does not redistribute them or promise permanent availability. Different inputs require a new named design and separate output.

For a custom design, copy the installed `execution_volume_validation/inputs/design.json` to an external location and use `--design`. Record source hashes and `source_access_date` (YYYY-MM-DD); omitted acquisition metadata is explicitly reported as not recorded. Dates must include every eligible session inside the selected span, so previous-day forecasts cannot silently skip sessions. Report preparation uses the actual generation date.

## Interpretation

Thirty forecasts produce270 planner-case records:264 planned,229 replay-completed. There are only five evaluation calendar dates and ten symbol-days. No-plan cases stay in completion denominators. Replay carries backlog and uses floor(participation rate × observed interval volume), without borrowing missed capacity. Recorded fills are hypothetical retrospective allocations, not actual executions.

Price diagnostics assume observed five-minute Close and constant impact. Residual marking is not execution. Compare planners only on dates where all three of the same predictor/order size produced and completed plans. Complete consolidated volume coverage, live fill availability, spreads/fees/queue and profitability are not established. The introductory input-quality counts cover all accepted sessions in a supplied CSV; a custom selected span may be smaller.

- [English report](../results/real-volume/research-note.md)
- [中文研究解读](../results/real-volume/中文研究解读.md)
- Numerical records: results/real-volume/results.json
- Public arrays: results/real-volume/derived-schedules.npz (planned/fills/remaining only)

Sources: [free samples](https://firstratedata.com/free-intraday-data), [format and research derivative permissions](https://firstratedata.com/about/FAQ), [license](https://firstratedata.com/about/license). Source hashes and acquisition date are retained in provenance/real-volume-sources.json. Raw vendor data/pages are not distributed. Code and research preparation use AI assistance.
