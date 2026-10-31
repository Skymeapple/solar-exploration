"""Figures for the Mars sample return study: python scripts/plot_sample_return.py

Needs matplotlib (not a package dependency). Writes results/sample_return/figures.png.
"""

import math
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from sample_return.ascent import MAV, design_mav, monte_carlo_ascent  # noqa: E402
from sample_return.bodies import MARS  # noqa: E402
from sample_return.entry import MSR_EEV, STARDUST, EntryConditions, simulate_entry  # noqa: E402
from sample_return.targets import compare_targets  # noqa: E402

S1, S2, S3 = "#2a78d6", "#eb6834", "#1baf7a"
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e4e3df"


def style(ax, title, xlabel, ylabel):
    ax.set_title(title, loc="left", fontsize=11, color=INK)
    ax.set_xlabel(xlabel, color=MUTED, fontsize=9)
    ax.set_ylabel(ylabel, color=MUTED, fontsize=9)
    ax.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(colors=MUTED, labelsize=8)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(GRID)


def main(out="results/sample_return/figures.png"):
    fig, axes = plt.subplots(2, 2, figsize=(11, 8), facecolor="#fcfcfb")
    mav, asc = design_mav(MAV(payload=16.0))
    tr = asc.trajectory
    r = np.hypot(tr[:, 1], tr[:, 2])
    theta = np.unwrap(np.arctan2(tr[:, 2], tr[:, 1]))
    ax = axes[0, 0]
    ax.plot(theta * MARS.radius / 1e3, (r - MARS.radius) / 1e3, color=S1, linewidth=2)
    style(ax, "MAV ascent to the 380 km orbit", "Downrange (km)", "Altitude (km)")

    ax = axes[0, 1]
    for ev, cond, col, lab in [
        (MSR_EEV, EntryConditions(11_980.0, -10.5), S1, "MSR-class EEV, 12.0 km/s"),
        (STARDUST, EntryConditions(12_900.0, -8.2), S2, "Stardust, 12.9 km/s"),
    ]:
        e = simulate_entry(ev, cond, keep_trajectory=True)
        t, V, h = e.trajectory[:, 0], e.trajectory[:, 1], e.trajectory[:, 3]
        from sample_return.entry import K_SUTTON_GRAVES_EARTH, density_us76

        q = K_SUTTON_GRAVES_EARTH * np.sqrt(np.array([density_us76(x) for x in h]) / ev.nose_radius) * V**3 / 1e4
        m = t < 120
        ax.plot(t[m], q[m], color=col, linewidth=2, label=lab)
        i = int(np.argmax(q))
        ax.annotate(f"{q[i]:.0f}", (t[i], q[i]), textcoords="offset points", xytext=(6, 4), fontsize=8, color=INK)
    ax.legend(frameon=False, fontsize=8)
    style(ax, "Stagnation-point convective heating", "Time from 125 km (s)", "Heat flux (W/cm²)")

    ax = axes[1, 0]
    for sig, col, lab in [(0.005, S2, "Baseline (Isp 0.5 %)"), (0.0025, S1, "Mitigated (Isp 0.25 %)")]:
        mc = monte_carlo_ascent(mav, n=300, min_periapsis=200e3, isp_sigma=sig)
        ax.hist(mc.periapsis_alt / 1e3, bins=np.arange(150, 420, 10), color=col, histtype="step", linewidth=2,
                label=f"{lab}: {mc.success_fraction * 100:.1f} % ≥ 200 km")
    ax.axvline(200, color=MUTED, linestyle="--", linewidth=1)
    ax.legend(frameon=False, fontsize=8, loc="upper left")
    style(ax, "Orbiting-sample periapsis, 300-run Monte Carlo", "Periapsis altitude (km)", "Runs")

    ax = axes[1, 1]
    rows = compare_targets()
    names = [t.name for t in rows]
    vals = [t.peak_heat_W_cm2 for t in rows]
    bars = ax.barh(names, vals, color=S1, height=0.6)
    for b, t in zip(bars, rows):
        ax.text(b.get_width() + 15, b.get_y() + b.get_height() / 2, f"{t.peak_heat_W_cm2:.0f} at {t.entry_speed:.1f} km/s",
                va="center", fontsize=8, color=INK)
    ax.invert_yaxis()
    ax.set_xlim(0, max(vals) * 1.45)
    style(ax, "Same EEV, peak heating by sample source", "Peak heat flux (W/cm²)", "")
    fig.tight_layout()
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=140, facecolor=fig.get_facecolor())
    print("wrote", out)


if __name__ == "__main__":
    main()
