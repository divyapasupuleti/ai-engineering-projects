"""Render a layered architecture diagram (PNG) and a Mermaid equivalent from a project spec."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

KIND_STYLE = {
    "client": ("#E3F2FD", "#1565C0", "Client / caller"),
    "api": ("#E8F5E9", "#2E7D32", "API / contract"),
    "logic": ("#FFF3E0", "#E65100", "Processing logic"),
    "store": ("#F3E5F5", "#6A1B9A", "Storage / index"),
    "llm": ("#FCE4EC", "#AD1457", "Model / LLM"),
    "eval": ("#E0F7FA", "#00838F", "Evals / quality"),
    "ui": ("#FFFDE7", "#F9A825", "Report / UI"),
    "external": ("#ECEFF1", "#455A64", "External system"),
}

BOX_W, BOX_H = 2.6, 1.15
X_GAP, Y_GAP = 3.25, 1.55
FEEDBACK_DIP = 0.9


def _layout(layers: list[list[str]]) -> dict[str, tuple[float, float]]:
    tallest = max(len(l) for l in layers)
    pos = {}
    for col, layer in enumerate(layers):
        offset = (tallest - len(layer)) * Y_GAP / 2
        for row, node in enumerate(layer):
            pos[node] = (col * X_GAP, -(offset + row * Y_GAP))
    return pos


def render_png(spec: dict, out: Path) -> None:
    arch = spec["architecture"]
    layers, nodes, edges = arch["layers"], arch["nodes"], arch["edges"]
    pos = _layout(layers)
    col_of = {n: c for c, layer in enumerate(layers) for n in layer}
    tallest = max(len(l) for l in layers)
    width = max(10.0, len(layers) * X_GAP * 0.92)
    height = max(4.6, tallest * Y_GAP * 0.95 + 2.6)

    fig, ax = plt.subplots(figsize=(width, height), dpi=160)
    ax.set_axis_off()

    for nid, (x, y) in pos.items():
        label, kind = nodes[nid]
        fill, edge, _ = KIND_STYLE[kind]
        ax.add_patch(
            FancyBboxPatch(
                (x - BOX_W / 2, y - BOX_H / 2), BOX_W, BOX_H,
                boxstyle="round,pad=0.04,rounding_size=0.12", fc=fill, ec=edge, lw=1.6, zorder=3,
            )
        )
        ax.text(x, y, label, ha="center", va="center", fontsize=9, color="#1A1A1A", zorder=4, linespacing=1.25)

    for src, dst, label in edges:
        (x1, y1), (x2, y2) = pos[src], pos[dst]
        c1, c2 = col_of[src], col_of[dst]
        if c2 > c1:
            start, end = (x1 + BOX_W / 2, y1), (x2 - BOX_W / 2, y2)
            rad = 0.0 if c2 - c1 == 1 else -0.18
            style = "-"
        elif c2 == c1:
            sign = -1 if y2 < y1 else 1
            start, end = (x1, y1 + sign * BOX_H / 2), (x2, y2 - sign * BOX_H / 2)
            rad, style = 0.0, "-"
        else:
            start, end = (x1, y1 - BOX_H / 2), (x2, y2 - BOX_H / 2)
            rad, style = -min(0.6, 2 * FEEDBACK_DIP / max(1e-6, abs(x2 - x1))), "--"
        ax.add_patch(
            FancyArrowPatch(
                start, end, arrowstyle="-|>", mutation_scale=13, lw=1.3, color="#37474F",
                linestyle=style, connectionstyle=f"arc3,rad={rad}", zorder=2,
            )
        )
        if label:
            mx, my = (start[0] + end[0]) / 2, (start[1] + end[1]) / 2
            if c2 < c1:
                my -= abs(rad) * abs(end[0] - start[0]) / 2 + 0.3
            ax.text(
                mx, my + 0.13, label, ha="center", va="bottom", fontsize=7, color="#263238", zorder=5,
                bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none", alpha=0.9),
            )

    used = sorted({k for _, k in nodes.values()}, key=list(KIND_STYLE).index)
    xs = [p[0] for p in pos.values()]
    ys = [p[1] for p in pos.values()]
    left, right = min(xs) - BOX_W, max(xs) + BOX_W
    bottom, top = min(ys) - BOX_H - 1.3 - FEEDBACK_DIP, max(ys) + BOX_H + 0.6
    ax.set_xlim(left, right)
    ax.set_ylim(bottom, top)
    ax.text((left + right) / 2, top - 0.2, f"Project {spec['number']}: {spec['title']}",
            ha="center", va="top", fontsize=13, weight="bold", color="#0D1B2A")
    lx = left + 0.3
    for kind in used:
        fill, edge, name = KIND_STYLE[kind]
        ax.add_patch(FancyBboxPatch((lx, bottom + 0.25), 0.35, 0.28, boxstyle="round,pad=0.02", fc=fill, ec=edge, lw=1.2))
        ax.text(lx + 0.45, bottom + 0.39, name, va="center", fontsize=7.5, color="#37474F")
        lx += 0.65 + len(name) * 0.095
    ax.text(right - 0.2, bottom + 0.39, "solid = request/data flow   dashed = feedback loop",
            ha="right", va="center", fontsize=7, color="#607D8B", style="italic")
    fig.tight_layout()
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def mermaid(spec: dict) -> str:
    arch = spec["architecture"]
    lines = ["flowchart LR"]
    for nid, (label, kind) in arch["nodes"].items():
        safe = label.replace("\n", "<br/>").replace('"', "'")
        lines.append(f'    {nid}["{safe}"]:::{kind}')
    for src, dst, label in arch["edges"]:
        lines.append(f"    {src} -->|{label}| {dst}" if label else f"    {src} --> {dst}")
    for kind, (fill, edge, _) in KIND_STYLE.items():
        lines.append(f"    classDef {kind} fill:{fill},stroke:{edge},color:#1A1A1A")
    return "\n".join(lines)
