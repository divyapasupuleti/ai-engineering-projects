#!/usr/bin/env python3
"""Generate README, architecture diagram, explanation doc (MD + DOCX) and PPTX for each project.

    python tools/build_docs.py            # all projects
    python tools/build_docs.py 01 07      # selected projects

Needs matplotlib, python-docx, python-pptx (see tools/requirements.txt).
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt, RGBColor
from pptx import Presentation
from pptx.dml.color import RGBColor as PRGB
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN
from pptx.util import Emu
from pptx.util import Inches as PIn
from pptx.util import Pt as PPt

sys.path.insert(0, str(Path(__file__).resolve().parent))
from diagram import KIND_STYLE, mermaid, render_png  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
NAVY = (0x0D, 0x1B, 0x2A)
ACCENT = (0x1E, 0x88, 0xE5)
MAX_SAMPLE_LINES = 40


def load_spec(project: Path) -> dict:
    mod_spec = importlib.util.spec_from_file_location(f"spec_{project.name}", project / "project_spec.py")
    mod = importlib.util.module_from_spec(mod_spec)
    mod_spec.loader.exec_module(mod)
    return mod.SPEC


def run_demo(project: Path, spec: dict) -> str:
    cmd = [sys.executable if a in ("python", "python3") else a for a in spec["demo"]]
    proc = subprocess.run(cmd, cwd=project, capture_output=True, text=True, timeout=300)
    out = (proc.stdout + (proc.stderr if proc.returncode not in (0, 1) else "")).strip()
    lines = out.splitlines()
    if len(lines) > MAX_SAMPLE_LINES:
        lines = lines[:MAX_SAMPLE_LINES] + [f"... ({len(lines) - MAX_SAMPLE_LINES} more lines)"]
    return "\n".join(lines)


# ---------------------------------------------------------------- markdown


def md_table(headers: list[str], rows: list[tuple]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    out += ["| " + " | ".join(str(c).replace("|", "\\|") for c in r) + " |" for r in rows]
    return "\n".join(out)


def explanation_md(spec: dict, sample: str) -> str:
    s = spec
    parts = [
        f"# Project {s['number']}: {s['title']}",
        "",
        f"**Primary topic:** {s['topic']} · **Secondary:** {', '.join(s['secondary'])}",
        "",
        f"> {s['tagline']}",
        "",
        "## 1. Problem",
        s["problem"],
        "",
        "### Why it matters",
        *[f"- {w}" for w in s["why_it_matters"]],
        "",
        "## 2. Goals and success criteria",
        md_table(["Goal", "Success criterion"], s["goals"]),
        "",
        "### Non-goals",
        *[f"- {n}" for n in s["non_goals"]],
        "",
        "## 3. Architecture",
        "![Architecture](ARCHITECTURE.png)",
        "",
        "```mermaid",
        mermaid(s),
        "```",
        "",
        "### Components",
        md_table(["Component", "File", "Responsibility"], s["components"]),
        "",
        "## 4. Request / data flow",
        *[f"{i}. {step}" for i, step in enumerate(s["flow"], 1)],
        "",
        "## 5. Key design decisions",
        md_table(["Decision", "Why", "Trade-off"], s["decisions"]),
        "",
        "## 6. Evaluation and metrics",
        *[f"- {e}" for e in s["evaluation"]],
        "",
        "## 7. How to run",
        "```bash",
        *s["run"],
        "```",
        "",
        "### Sample output",
        f"`{' '.join(s['demo'])}`",
        "",
        "```text",
        sample,
        "```",
        "",
        "## 8. Project structure",
        md_table(["Path", "Purpose"], s["structure"]),
        "",
        "## 9. Interview talking points",
        *[f"- {t}" for t in s["talking_points"]],
        "",
        "## 10. Production roadmap",
        *[f"- {p}" for p in s["production_next"]],
        "",
        "## 11. Resume bullet",
        f"> {s['resume_bullet']}",
        "",
    ]
    return "\n".join(parts)


def readme_md(spec: dict, sample: str) -> str:
    s = spec
    return "\n".join(
        [
            f"# Project {s['number']}: {s['title']}",
            "",
            f"`{s['topic']}` " + " ".join(f"`{x}`" for x in s["secondary"]),
            "",
            s["tagline"],
            "",
            "## Goals",
            md_table(["Goal", "Success criterion"], s["goals"]),
            "",
            "## Architecture",
            "![Architecture](docs/ARCHITECTURE.png)",
            "",
            "<details><summary>Mermaid source</summary>",
            "",
            "```mermaid",
            mermaid(s),
            "```",
            "</details>",
            "",
            "## Quick start",
            "No third-party packages needed (Python 3.10+).",
            "",
            "```bash",
            *s["run"],
            "```",
            "",
            "## Sample output",
            "```text",
            sample,
            "```",
            "",
            "## Files",
            md_table(["Path", "Purpose"], s["structure"]),
            "",
            "## Documentation",
            "- [docs/PROJECT_EXPLANATION.md](docs/PROJECT_EXPLANATION.md) · [docs/PROJECT_EXPLANATION.docx](docs/PROJECT_EXPLANATION.docx): full explanation",
            "- [docs/PRESENTATION.pptx](docs/PRESENTATION.pptx): slide deck for walkthroughs and interviews",
            "",
        ]
    )


# ---------------------------------------------------------------- docx


def _docx_table(doc: Document, headers: list[str], rows: list[tuple]) -> None:
    table = doc.add_table(rows=1, cols=len(headers))
    table.style = "Light Grid Accent 1"
    for i, h in enumerate(headers):
        cell = table.rows[0].cells[i]
        cell.text = h
        cell.paragraphs[0].runs[0].bold = True
    for r in rows:
        cells = table.add_row().cells
        for i, v in enumerate(r):
            cells[i].text = str(v)
    for row in table.rows:
        for cell in row.cells:
            for p in cell.paragraphs:
                for run in p.runs:
                    run.font.size = Pt(9.5)
    doc.add_paragraph()


def _code(doc: Document, text: str) -> None:
    for line in text.splitlines() or [""]:
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(0)
        run = p.add_run(line or " ")
        run.font.name = "Consolas"
        run.font.size = Pt(8.5)
        run.font.color.rgb = RGBColor(0x26, 0x32, 0x38)
    doc.add_paragraph()


def explanation_docx(spec: dict, sample: str, png: Path, out: Path) -> None:
    s = spec
    doc = Document()
    styles = doc.styles
    styles["Normal"].font.name = "Calibri"
    styles["Normal"].font.size = Pt(10.5)

    title = doc.add_heading(f"Project {s['number']}: {s['title']}", level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.LEFT
    meta = doc.add_paragraph()
    meta.add_run("Primary topic: ").bold = True
    meta.add_run(s["topic"] + "    ")
    meta.add_run("Secondary: ").bold = True
    meta.add_run(", ".join(s["secondary"]))
    tag = doc.add_paragraph(s["tagline"])
    tag.runs[0].italic = True

    doc.add_heading("1. Problem", level=1)
    doc.add_paragraph(s["problem"])
    doc.add_heading("Why it matters", level=2)
    for w in s["why_it_matters"]:
        doc.add_paragraph(w, style="List Bullet")

    doc.add_heading("2. Goals and success criteria", level=1)
    _docx_table(doc, ["Goal", "Success criterion"], s["goals"])
    doc.add_heading("Non-goals", level=2)
    for n in s["non_goals"]:
        doc.add_paragraph(n, style="List Bullet")

    doc.add_heading("3. Architecture", level=1)
    doc.add_picture(str(png), width=Inches(6.6))
    cap = doc.add_paragraph("Figure 1. Architecture: solid arrows are the request/data path, dashed arrows are feedback loops.")
    cap.runs[0].italic = True
    cap.runs[0].font.size = Pt(9)
    doc.add_heading("Components", level=2)
    _docx_table(doc, ["Component", "File", "Responsibility"], s["components"])

    doc.add_heading("4. Request / data flow", level=1)
    for step in s["flow"]:
        doc.add_paragraph(step, style="List Number")

    doc.add_heading("5. Key design decisions", level=1)
    _docx_table(doc, ["Decision", "Why", "Trade-off"], s["decisions"])

    doc.add_heading("6. Evaluation and metrics", level=1)
    for e in s["evaluation"]:
        doc.add_paragraph(e, style="List Bullet")

    doc.add_heading("7. How to run", level=1)
    _code(doc, "\n".join(s["run"]))
    doc.add_heading("Sample output", level=2)
    doc.add_paragraph(f"Command: {' '.join(s['demo'])}")
    _code(doc, sample)

    doc.add_heading("8. Project structure", level=1)
    _docx_table(doc, ["Path", "Purpose"], s["structure"])

    doc.add_heading("9. Interview talking points", level=1)
    for t in s["talking_points"]:
        doc.add_paragraph(t, style="List Bullet")

    doc.add_heading("10. Production roadmap", level=1)
    for p in s["production_next"]:
        doc.add_paragraph(p, style="List Bullet")

    doc.add_heading("11. Resume bullet", level=1)
    rb = doc.add_paragraph(s["resume_bullet"])
    rb.runs[0].italic = True
    doc.save(str(out))


# ---------------------------------------------------------------- pptx

SLIDE_W, SLIDE_H = PIn(13.333), PIn(7.5)


def _bar(slide, title: str, subtitle: str | None = None) -> None:
    bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, SLIDE_W, PIn(1.05))
    bar.fill.solid()
    bar.fill.fore_color.rgb = PRGB(*NAVY)
    bar.line.fill.background()
    tf = bar.text_frame
    tf.margin_left = PIn(0.5)
    p = tf.paragraphs[0]
    p.text = title
    p.font.size = PPt(28)
    p.font.bold = True
    p.font.color.rgb = PRGB(0xFF, 0xFF, 0xFF)
    p.alignment = PP_ALIGN.LEFT
    accent = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, PIn(1.05), SLIDE_W, PIn(0.06))
    accent.fill.solid()
    accent.fill.fore_color.rgb = PRGB(*ACCENT)
    accent.line.fill.background()
    if subtitle:
        box = slide.shapes.add_textbox(PIn(0.5), PIn(1.2), PIn(12.3), PIn(0.5))
        q = box.text_frame.paragraphs[0]
        q.text = subtitle
        q.font.size = PPt(15)
        q.font.italic = True
        q.font.color.rgb = PRGB(0x45, 0x5A, 0x64)


def _bullets(slide, items: list[str], top: float = 1.85, size: int = 18, left: float = 0.6, width: float = 12.1) -> None:
    box = slide.shapes.add_textbox(PIn(left), PIn(top), PIn(width), SLIDE_H - PIn(top) - PIn(0.4))
    tf = box.text_frame
    tf.word_wrap = True
    for i, item in enumerate(items):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = f"•  {item}"
        p.font.size = PPt(size)
        p.font.color.rgb = PRGB(0x1A, 0x1A, 0x1A)
        p.space_after = PPt(10)


def _table(slide, headers: list[str], rows: list[tuple], top: float = 1.85, col_widths: list[float] | None = None, size: int = 13) -> None:
    n_rows = len(rows) + 1
    height = PIn(min(5.2, 0.5 * n_rows))
    shape = slide.shapes.add_table(n_rows, len(headers), PIn(0.5), PIn(top), PIn(12.3), height)
    table = shape.table
    widths = col_widths or [12.3 / len(headers)] * len(headers)
    for i, w in enumerate(widths):
        table.columns[i].width = PIn(w)
    for i, h in enumerate(headers):
        cell = table.cell(0, i)
        cell.text = h
        para = cell.text_frame.paragraphs[0]
        para.font.bold = True
        para.font.size = PPt(size + 1)
        para.font.color.rgb = PRGB(0xFF, 0xFF, 0xFF)
        cell.fill.solid()
        cell.fill.fore_color.rgb = PRGB(*NAVY)
    for r, row in enumerate(rows, 1):
        for c, v in enumerate(row):
            cell = table.cell(r, c)
            cell.text = str(v)
            cell.text_frame.paragraphs[0].font.size = PPt(size)


def _notes(slide, text: str) -> None:
    slide.notes_slide.notes_text_frame.text = text


def presentation(spec: dict, sample: str, png: Path, out: Path) -> None:
    s = spec
    prs = Presentation()
    prs.slide_width, prs.slide_height = SLIDE_W, SLIDE_H
    blank = prs.slide_layouts[6]

    # 1 title
    slide = prs.slides.add_slide(blank)
    bg = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, SLIDE_W, SLIDE_H)
    bg.fill.solid()
    bg.fill.fore_color.rgb = PRGB(*NAVY)
    bg.line.fill.background()
    box = slide.shapes.add_textbox(PIn(0.8), PIn(2.0), PIn(11.7), PIn(3.5))
    tf = box.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = f"PROJECT {s['number']:02d}  ·  {s['topic'].upper()}"
    p.font.size = PPt(16)
    p.font.bold = True
    p.font.color.rgb = PRGB(*ACCENT)
    p = tf.add_paragraph()
    p.text = s["title"]
    p.font.size = PPt(40)
    p.font.bold = True
    p.font.color.rgb = PRGB(0xFF, 0xFF, 0xFF)
    p = tf.add_paragraph()
    p.text = s["tagline"]
    p.font.size = PPt(18)
    p.font.color.rgb = PRGB(0xCF, 0xD8, 0xDC)
    p.space_before = PPt(18)
    p = tf.add_paragraph()
    p.text = "Topics: " + ", ".join([s["topic"], *s["secondary"]])
    p.font.size = PPt(14)
    p.font.color.rgb = PRGB(0x90, 0xA4, 0xAE)
    p.space_before = PPt(24)
    _notes(slide, s["tagline"])

    # 2 problem
    slide = prs.slides.add_slide(blank)
    _bar(slide, "The problem", s["problem"][:220] + ("…" if len(s["problem"]) > 220 else ""))
    _bullets(slide, s["why_it_matters"], top=2.3)
    _notes(slide, s["problem"])

    # 3 goals
    slide = prs.slides.add_slide(blank)
    _bar(slide, "Goals & success criteria")
    _table(slide, ["Goal", "Success criterion"], s["goals"], col_widths=[5.4, 6.9])
    _notes(slide, "Non-goals: " + " ".join(s["non_goals"]))

    # 4 architecture
    slide = prs.slides.add_slide(blank)
    _bar(slide, "Architecture")
    from PIL import Image

    with Image.open(png) as im:
        w, h = im.size
    max_w, max_h = 12.5, 5.95
    scale = min(max_w / (w / 160), max_h / (h / 160))
    pw, ph = w / 160 * scale, h / 160 * scale
    slide.shapes.add_picture(str(png), PIn((13.333 - pw) / 2), PIn(1.3 + (max_h - ph) / 2), PIn(pw), PIn(ph))
    _notes(slide, "Components: " + "; ".join(f"{c[0]} ({c[1]}): {c[2]}" for c in s["components"]))

    # 5 components
    slide = prs.slides.add_slide(blank)
    _bar(slide, "Components")
    _table(slide, ["Component", "File", "Responsibility"], s["components"], col_widths=[2.6, 2.6, 7.1], size=12)

    # 6 flow
    slide = prs.slides.add_slide(blank)
    _bar(slide, "How a request flows")
    _bullets(slide, [f"{i}. {step}" for i, step in enumerate(s["flow"], 1)], size=15)

    # 7 decisions
    slide = prs.slides.add_slide(blank)
    _bar(slide, "Key design decisions & trade-offs")
    _table(slide, ["Decision", "Why", "Trade-off"], s["decisions"], col_widths=[3.4, 4.6, 4.3], size=11)

    # 8 evaluation
    slide = prs.slides.add_slide(blank)
    _bar(slide, "Evaluation & metrics")
    _bullets(slide, s["evaluation"], size=17)

    # 9 demo output
    slide = prs.slides.add_slide(blank)
    _bar(slide, "Demo run", "$ " + " ".join(s["demo"]))
    lines = sample.splitlines()[:22]
    box = slide.shapes.add_textbox(PIn(0.5), PIn(1.8), PIn(12.3), PIn(5.4))
    box.fill.solid()
    box.fill.fore_color.rgb = PRGB(0xF5, 0xF7, 0xFA)
    tf = box.text_frame
    tf.word_wrap = True
    for i, line in enumerate(lines or ["(no output)"]):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = line[:150]
        p.font.name = "Consolas"
        p.font.size = PPt(10.5)
    _notes(slide, sample)

    # 10 talking points
    slide = prs.slides.add_slide(blank)
    _bar(slide, "Interview talking points")
    _bullets(slide, s["talking_points"], size=17)

    # 11 roadmap + resume
    slide = prs.slides.add_slide(blank)
    _bar(slide, "Production roadmap")
    _bullets(slide, s["production_next"], size=16, top=1.6)
    box = slide.shapes.add_textbox(PIn(0.6), PIn(5.9), PIn(12.1), PIn(1.2))
    box.fill.solid()
    box.fill.fore_color.rgb = PRGB(0xE3, 0xF2, 0xFD)
    tf = box.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = "Resume bullet: " + s["resume_bullet"]
    p.font.size = PPt(13)
    p.font.italic = True

    prs.save(str(out))


# ---------------------------------------------------------------- driver


def build(project: Path) -> None:
    spec = load_spec(project)
    docs = project / "docs"
    docs.mkdir(exist_ok=True)
    png = docs / "ARCHITECTURE.png"
    render_png(spec, png)
    sample = run_demo(project, spec)
    (docs / "PROJECT_EXPLANATION.md").write_text(explanation_md(spec, sample), encoding="utf-8")
    explanation_docx(spec, sample, png, docs / "PROJECT_EXPLANATION.docx")
    presentation(spec, sample, png, docs / "PRESENTATION.pptx")
    (project / "README.md").write_text(readme_md(spec, sample), encoding="utf-8")
    print(f"built {project.name}: README.md, docs/ARCHITECTURE.png, PROJECT_EXPLANATION.md/.docx, PRESENTATION.pptx")


def main() -> None:
    wanted = set(sys.argv[1:])
    projects = sorted(p for p in REPO.iterdir() if (p / "project_spec.py").exists())
    if wanted:
        projects = [p for p in projects if p.name[:2] in wanted]
    for p in projects:
        build(p)


if __name__ == "__main__":
    main()
