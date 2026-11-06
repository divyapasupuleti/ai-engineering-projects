#!/usr/bin/env python3
"""Write the repository README index from every project's project_spec.py.

    python tools/build_index.py
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def load(project: Path) -> dict:
    spec = importlib.util.spec_from_file_location(f"spec_{project.name}", project / "project_spec.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.SPEC


def main() -> None:
    projects = sorted(p for p in REPO.glob("[0-9][0-9]-*") if (p / "project_spec.py").exists())
    specs = [(p, load(p)) for p in projects]
    lines = [
        "# AI Engineering Projects", "",
        "Fifteen production-style AI engineering projects, each runnable offline with the Python standard library.",
        "Every project folder contains code, tests, a README, an architecture diagram, a project explanation "
        "(Markdown + Word) and a presentation deck generated from one spec.", "",
        "| # | Project | Topic | Headline result | Folder |", "|---|---|---|---|---|",
    ]
    for p, s in specs:
        lines.append(f"| {s['number']} | **{s['title']}** | {s['topic']} | {s['resume_bullet']} | [`{p.name}`]({p.name}/) |")
    lines += [
        "", "## Each project folder", "",
        "| File | Contents |", "|---|---|",
        "| `README.md` | Goals, architecture, how to run, sample output |",
        "| `docs/ARCHITECTURE.png` | Layered architecture diagram (Mermaid source in the explanation doc) |",
        "| `docs/PROJECT_EXPLANATION.md` / `.docx` | Problem, goals, components, flow, decisions, evaluation, interview talking points |",
        "| `docs/PRESENTATION.pptx` | 11-slide deck with speaker notes |",
        "| `project_spec.py` | Single source for all of the above |",
        "| `tests/` | Unit tests (`python -m unittest discover -s tests`) |",
        "", "## Quick start", "", "```bash",
        "python run_all_tests.py                     # all project test suites",
        "cd 01-support-knowledge-copilot && python evaluate.py",
        "```", "",
        "Regenerate docs (needs `pip install -r tools/requirements.txt`):", "", "```bash",
        "MPLCONFIGDIR=/tmp/mpl python tools/build_docs.py        # all projects",
        "python tools/build_docs.py 07 12                         # selected projects",
        "python tools/build_index.py                              # this README",
        "```", "",
        "## Shared code", "",
        "`common/` holds small helpers used across projects: hashed embeddings, tokenisation, a model pricing "
        "registry, a tracer, JSONL I/O and percentiles. Simulated models and providers are deterministic so every "
        "metric in the docs is reproducible; each project's docs say where a real provider plugs in.", "",
        "## Projects", "",
    ]
    for p, s in specs:
        lines += [f"### {s['number']}. {s['title']}", "", s["tagline"], "",
                  *[f"- **{g}**: {c}" for g, c in s["goals"]], "",
                  f"Run: `cd {p.name} && {s['run'][0]}` · [Explanation]({p.name}/docs/PROJECT_EXPLANATION.md) · "
                  f"[Slides]({p.name}/docs/PRESENTATION.pptx) · [Diagram]({p.name}/docs/ARCHITECTURE.png)", ""]
    (REPO / "README.md").write_text("\n".join(lines))
    print(f"wrote README.md with {len(specs)} projects")


if __name__ == "__main__":
    main()
