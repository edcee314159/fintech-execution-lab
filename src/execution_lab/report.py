"""Generate a research note from measured data, without manually entered claims."""
def _number(value):
    return "unavailable" if value is None else f"{value:,.6g}"

def render_note(bundle: dict) -> str:
    s, c, p = bundle["summary"], bundle["config"], bundle["provenance"]
    lines = ["# Trade Execution Cost & Risk Lab — Study Note", "",
        "## Research question", "",
        "How does risk-sensitive front-loading change temporary-impact cost and price exposure relative to TWAP?",
        "This experiment uses a simplified Almgren–Chriss-style discrete reference, a custom O(N) Thomas solver, "
        "and integer approximations. It does not simulate a live order book.", "",
        "## Reproducible setup", "",
        f'Software {p["software_version"]}; schema {bundle["schema_version"]}; model {bundle["model_type"]}.',
        f'Seed: {c["seed"]}; status: **{s["status"]}**; valid pairs: **{s["valid_pairs"]}/{s["total_pairs"]}**.',
        f'Invalid pairs: {s["invalid_pairs"]}. They are preserved and never replaced.',
        "", "| Parameter | Value |", "|---|---:|"]
    for key,value in c.items():
        lines.append(f"| {key} | {value} |")
    lines.extend(["", "Both strategies sell on the same synthetic reference-price paths. "
        "Every scheduled trade fills at the start of its interval. Integer and continuous plans are separately exported.",
        "", "## Results for actual integer schedules", "",
        "| Strategy | Analytic mean | Analytic variance | Analytic J | Sample mean | 95% CI for mean | Sample variance |",
        "|---|---:|---:|---:|---:|---|---:|"])
    for name,row in s["strategies"].items():
        prediction, observed = row["prediction"],row["empirical"]
        ci = observed["ci95_mean"]
        interval = "unavailable" if ci is None else f"[{_number(ci[0])}, {_number(ci[1])}]"
        lines.append(f'| {name} | {_number(prediction["mean"])} | {_number(prediction["variance"])} | '
            f'{_number(prediction["objective"])} | {_number(observed["mean"])} | {interval} | {_number(observed["variance"])} |')
    pair = s["paired"]
    ci = pair["empirical"]["ci95_mean"]
    lines.extend(["", "Mean shortfall and its interval are in currency; variances are in currency squared.",
        "Confidence intervals use Student-t with sample variance (ddof=1). They measure simulation mean uncertainty.",
        f'Paired AC-minus-TWAP: analytic mean {_number(pair["prediction"]["mean"])}, '
        f'analytic variance {_number(pair["prediction"]["variance"])}; '
        f'sample mean {_number(pair["empirical"]["mean"])}; '
        + ("95% interval unavailable." if ci is None else f'95% interval [{_number(ci[0])}, {_number(ci[1])}].'),
        "", s["interpretation"], "",
        "If any path is invalid, the table uses conditional selected valid samples, not unconditional inference. "
        "The raw all-path algebraic diagnostics remain in results.json. If fewer than two pairs are valid, inferential metrics are unavailable.",
        "", "![Schedules](schedule.png)", "", "![Costs](cost-distribution.png)", "",
        "![Paired differences](paired-difference.png)", "", "## Assumptions and limits", "",
        "Prices follow zero-drift arithmetic Brownian motion. Only linear temporary impact is present. "
        "No permanent impact, fees, bid–ask spread, queue priority, partial fills or liquidity constraints are represented. "
        "Negative costs can arise from favourable price innovations; nonpositive prices flag model invalidity.",
        "Parameters are illustrative, not fitted to market data. The continuous reference minimizes the chosen cost–risk objective; "
        "integerization is a feasible approximation and not an exact integer optimum. No real-market superiority is established.",
        "", "## Verification and provenance", "",
        "The test suite checks hand calculations, an independent constrained SciPy optimizer, "
        "paired accounting, degenerate and invalid cases, and fixed-seed Monte Carlo moment consistency.",
        f'Core source SHA-256: {p["source_digest_sha256"]}.',
        f'Source commit: {p["source_commit"] or "unavailable in installed context"}; core modified: {p["source_modified"]}.',
        "Costs use the stable impact-minus-inventory-exposure identity with preserved raw price innovations. "
        "Rounded displayed prices can lose very small changes at large price levels. "
        "The bundle retains price_innovations and a conservative roundoff check against notional minus proceeds.",
        "manifest.json hashes the actual output files. Numeric reproducibility requires the pinned environment.",
        "", "## Attribution", "",
        "This research software was developed with AI assistance."
        "", ""])
    return "\n".join(lines)
