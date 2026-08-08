#!/usr/bin/env python3
"""Paper figures. Fig 1: review discrimination — the calibrated ROC with every
adversarial-framing detector plotted as an operating point on/off the curve.
Fig 2: perception without conviction — likelihood scores on bad vs control
diffs, bad points keyed by whether the findings identified the actual defect.

Outputs paper/figures/*.{pdf,png}.
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt

matplotlib.rcParams.update({
    "font.family": "sans-serif",
    "font.size": 9,
    "axes.edgecolor": "#c3c2b7",
    "axes.linewidth": 0.8,
    "axes.labelcolor": "#0b0b0b",
    "text.color": "#0b0b0b",
    "xtick.color": "#52514e",
    "ytick.color": "#52514e",
    "figure.facecolor": "#fcfcfb",
    "axes.facecolor": "#fcfcfb",
    "savefig.facecolor": "#fcfcfb",
})
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
GRAY = "#52514e"

ROOT = Path(__file__).resolve().parent.parent
FIG = ROOT / "paper" / "figures"
FIG.mkdir(parents=True, exist_ok=True)


def likelihoods(path: str) -> list[int]:
    d = json.loads((ROOT / path).read_text())
    return [r["likelihood"] for r in d["records"]
            if r["status"] == "ok" and r["likelihood"] is not None]


def fig1_roc() -> None:
    bad = likelihoods("eval/results/calib-full.json")
    good = likelihoods("eval/results/calib-full-control.json")
    ts = sorted({*bad, *good, 0, 101})
    pts = sorted(
        ((sum(x >= t for x in good) / len(good), sum(x >= t for x in bad) / len(bad))
         for t in ts),
    )
    auc = sum((1.0 if x > y else 0.5 if x == y else 0.0) for x in bad for y in good) / (len(bad) * len(good))

    fig, ax = plt.subplots(figsize=(4.2, 3.6))
    ax.plot([0, 1], [0, 1], color="#c3c2b7", lw=0.8, ls="--", zorder=1)
    ax.plot(*zip(*pts), color=BLUE, lw=2, zorder=2,
            label=f"calibrated GPT-5.1, 664/428 (AUC {auc:.2f})")

    # adversarial-framing operating points (measured, Section 6)
    ops = [
        ("Bandit SAST", 0.088, 0.024, GRAY, "o"),
        ("GPT-5.1 adversarial", 0.31, 0.51, ORANGE, "o"),
        ("Gemini adversarial", 0.54, 0.80, ORANGE, "s"),
        ("union (either flags)", 0.54, 0.89, AQUA, "^"),
        ("intersection (both)", 0.31, 0.42, AQUA, "v"),
    ]
    for name, fpr, tpr, color, marker in ops:
        ax.scatter([fpr], [tpr], s=42, color=color, marker=marker, zorder=3,
                   edgecolors="#fcfcfb", linewidths=1.2)
    offsets = {"Bandit SAST": (6, -2), "GPT-5.1 adversarial": (7, -3),
               "Gemini adversarial": (7, -8), "union (either flags)": (-8, -3),
               "intersection (both)": (7, -3)}
    for name, fpr, tpr, color, _ in ops:
        dx, dy = offsets[name]
        ax.annotate(name, (fpr, tpr), textcoords="offset points",
                    xytext=(dx, dy), fontsize=7.5,
                    ha="left" if dx > 0 else "right", color="#0b0b0b")

    ax.set_xlabel("false-positive rate (presumed-good controls)")
    ax.set_ylabel("sensitivity (known-bad changes)")
    ax.set_xlim(-0.02, 1.02)
    ax.set_ylim(-0.02, 1.02)
    ax.legend(loc="upper left", fontsize=7.5, frameon=False)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(FIG / "roc.pdf")
    fig.savefig(FIG / "roc.png", dpi=220)
    plt.close(fig)


def fig2_conviction() -> None:
    calib = json.loads((ROOT / "eval/results/calib-full.json").read_text())
    validity = json.loads((ROOT / "eval/results/validity-full.json").read_text())
    verdict = {r["sha"]: r["verdict"] for r in validity["records"]}
    good = likelihoods("eval/results/calib-full-control.json")

    groups = {"identifies": [], "incidental": [], "silent": []}
    for r in calib["records"]:
        if r["status"] != "ok" or r["likelihood"] is None:
            continue
        v = verdict.get(r["sha"])
        key = v if v in ("identifies", "incidental") else "silent"
        groups[key].append(r["likelihood"])

    import random
    rng = random.Random(7)

    fig, ax = plt.subplots(figsize=(4.2, 3.2))
    cols = [
        ("control\n(good, n=%d)" % len(good), good, GRAY, "o"),
        ("bad, no findings\n(n=%d)" % len(groups["silent"]), groups["silent"], GRAY, "o"),
        ("bad, findings\nincidental (n=%d)" % len(groups["incidental"]),
         groups["incidental"], ORANGE, "o"),
        ("bad, findings name\nthe defect (n=%d)" % len(groups["identifies"]),
         groups["identifies"], BLUE, "o"),
    ]
    for i, (label, vals, color, marker) in enumerate(cols):
        xs = [i + rng.uniform(-0.22, 0.22) for _ in vals]
        ax.scatter(xs, vals, s=9, color=color, marker=marker, alpha=0.5,
                   edgecolors="none", zorder=3)

    ax.axhline(40, color="#d03b3b", lw=1.2, ls="--", zorder=2)
    ax.set_xlim(-0.6, 2.45)
    ax.annotate("best-J gating\nthreshold (40)", (-0.55, 43), fontsize=7.5,
                color="#d03b3b", ha="left", va="bottom")
    below = sum(v < 40 for v in groups["identifies"])
    ax.annotate(
        f"{below}/{len(groups['identifies'])} correctly-perceived\ndefects scored below the threshold",
        (0.62, 88), fontsize=7.5, ha="center", color="#0b0b0b",
    )

    ax.set_xticks(range(len(cols)))
    ax.set_xticklabels([c[0] for c in cols], fontsize=7)
    ax.set_ylabel("reviewer defect likelihood (0–100)")
    ax.set_ylim(-3, 118)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(FIG / "conviction.pdf")
    fig.savefig(FIG / "conviction.png", dpi=220)
    plt.close(fig)


if __name__ == "__main__":
    fig1_roc()
    fig2_conviction()
    print("figures ->", FIG)
