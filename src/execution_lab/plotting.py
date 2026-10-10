"""Static scientific figures; all values come from the experiment bundle."""
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

COLORS = {"twap": "#2864b4", "ac_simplified": "#df7827"}

def render_figures(bundle: dict, output_dir: Path) -> dict[str, Path]:
    c, summary = bundle["config"], bundle["summary"]
    paths = {}
    subtitle = f'{summary["status"]}; {summary["valid_pairs"]}/{summary["total_pairs"]} valid pairs'
    tau = c["duration"] / c["intervals"]
    with plt.rc_context({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False}):
        fig, axes = plt.subplots(1, 2, figsize=(11, 4.2), layout="constrained")
        for name, schedule in bundle["schedules"].items():
            times = np.arange(c["intervals"]) * tau
            axes[0].plot(times, schedule["quantities"], label=name, color=COLORS[name])
            axes[1].step(np.arange(c["intervals"]+1)*tau, schedule["inventory"],
                where="pre", label=name, color=COLORS[name])
            ref = bundle["continuous_references"][name]
            axes[1].step(np.arange(c["intervals"]+1)*tau, ref["inventory"],
                "--", where="pre", color=COLORS[name], alpha=.45, linewidth=1)
        axes[0].set(xlabel="Trade time (minutes)", ylabel="Shares per trade", title="Integer execution plans")
        axes[1].set(xlabel="Time (minutes)", ylabel="Remaining inventory (shares)",
            title="Inventory; dashed = continuous quantities")
        for ax in axes:
            ax.legend()
            ax.grid(alpha=.2)
        fig.suptitle("Execution schedules | "+subtitle)
        target = output_dir/"schedule.png"
        fig.savefig(target, dpi=160)
        plt.close(fig)
        paths[target.name] = target

        fig, axes = plt.subplots(1, 2, figsize=(11, 4.2), layout="constrained")
        for ax, name in zip(axes, COLORS):
            values = np.array(bundle["costs"][name])
            p = summary["strategies"][name]["prediction"]
            ax.hist(values, bins=min(30,max(1,int(np.sqrt(values.size)))), density=True,
                color=COLORS[name], alpha=.55, label="All simulated paths")
            ax.axvline(p["mean"], color=COLORS[name], linestyle="--", label="Analytic mean")
            if p["std"] > 0:
                grid = np.linspace(min(values.min(),p["mean"]-4*p["std"]),
                    max(values.max(),p["mean"]+4*p["std"]),300)
                density = np.exp(-.5*((grid-p["mean"])/p["std"])**2)/(p["std"]*np.sqrt(2*np.pi))
                ax.plot(grid,density,color="#263238",label="Analytic normal density")
            ax.set(title=name, xlabel="Implementation shortfall (currency)", ylabel="Density (1/currency)")
            ax.legend(fontsize=8)
        fig.suptitle("Cost distributions | "+subtitle)
        target = output_dir/"cost-distribution.png"
        fig.savefig(target,dpi=160)
        plt.close(fig)
        paths[target.name] = target

        fig, ax = plt.subplots(figsize=(8,4.5), layout="constrained")
        difference = np.array(bundle["costs"]["ac_simplified"])-np.array(bundle["costs"]["twap"])
        ax.hist(difference,bins=min(30,max(1,int(np.sqrt(difference.size)))),color="#588675",alpha=.65,
            label="All-path paired differences")
        ax.axvline(summary["paired"]["prediction"]["mean"],color="#df7827",linestyle="--",
            label="Analytic mean difference")
        stat = summary["paired"]["empirical"]
        if stat["ci95_mean"] is not None:
            lo, hi = stat["ci95_mean"]
            ax.axvspan(lo,hi,alpha=.25,color="#2864b4",label="95% CI for selected mean" if summary["invalid_pairs"]
                else "95% CI for mean difference")
            ax.axvline(stat["mean"],color="#2864b4")
        ax.set(xlabel="AC minus TWAP shortfall (currency)",ylabel="Pair count",
            title="Paired comparison | "+subtitle)
        ax.legend(fontsize=9)
        ax.grid(alpha=.15)
        target = output_dir/"paired-difference.png"
        fig.savefig(target,dpi=160)
        plt.close(fig)
        paths[target.name] = target
    return paths
