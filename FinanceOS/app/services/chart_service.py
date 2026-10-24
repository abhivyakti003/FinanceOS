"""Charts for the PDF report, rendered to PNG bytes in memory.

Nothing is written to disk, so two users generating reports at the same
time can never see each other's charts.
"""

import io

import matplotlib

matplotlib.use("Agg")  # no GUI needed; required on servers
import matplotlib.pyplot as plt  # noqa: E402

PALETTE = ["#1f4e79", "#2e86ab", "#57a773", "#f2a541", "#c8553d", "#8e6c8a", "#5c6b73", "#b5b682"]


def _to_png(fig) -> bytes:
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    return buffer.getvalue()


def category_chart(categories: list[str], amounts: list[float]) -> bytes | None:
    if not amounts:
        return None
    fig, ax = plt.subplots(figsize=(6.5, 3.6))
    y = list(reversed(categories[:8]))
    x = list(reversed(amounts[:8]))
    ax.barh(y, x, color=PALETTE[0])
    ax.set_xlabel("Rs.")
    ax.spines[["top", "right"]].set_visible(False)
    ax.set_title("Spending by category")
    return _to_png(fig)


def monthly_chart(labels: list[str], income: list[float], spending: list[float]) -> bytes | None:
    if not labels:
        return None
    fig, ax = plt.subplots(figsize=(6.5, 3.2))
    idx = range(len(labels))
    width = 0.4
    ax.bar([i - width / 2 for i in idx], income, width, label="Income", color=PALETTE[2])
    ax.bar([i + width / 2 for i in idx], spending, width, label="Spending", color=PALETTE[4])
    ax.set_xticks(list(idx))
    ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False)
    ax.set_title("Income and spending by month")
    return _to_png(fig)


def budget_chart(categories: list[str], percents: list[float]) -> bytes | None:
    if not categories:
        return None
    fig, ax = plt.subplots(figsize=(6.5, 0.5 + 0.45 * len(categories)))
    colors = [PALETTE[4] if p > 100 else PALETTE[3] if p > 80 else PALETTE[2] for p in percents]
    ax.barh(categories, [min(p, 150) for p in percents], color=colors)
    ax.axvline(100, color="#333", linewidth=1, linestyle="--")
    ax.set_xlabel("% of monthly budget used")
    ax.spines[["top", "right"]].set_visible(False)
    return _to_png(fig)
