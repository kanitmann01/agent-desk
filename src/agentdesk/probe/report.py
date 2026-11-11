"""Report rendering: gate results and a verdict into markdown and stdout text.

Pure string building, no I/O; the CLI writes the markdown to disk and
prints the summary.
"""

from agentdesk.probe.core import GateResult, Verdict
from agentdesk.probe.verdict import verdict_line

_REPORT_HEADER = """# Agent Desk environment probe report

- Generated: {generated}
- Python: {python}
- Platform: {platform}
- User: {user}
- Workdir: {workdir}
"""


def _gate_heading(result: GateResult) -> str:
    return f"## Gate {result.number}: {result.title} ({result.key})"


def _gate_section(result: GateResult) -> str:
    lines = [_gate_heading(result), "", f"Status: {result.status}", "", "Evidence:"]
    lines.extend(f"- {item}" for item in result.evidence)
    if result.note:
        lines.extend(["", f"Note: {result.note}"])
    return "\n".join(lines)


def render_report(results, verdict: Verdict, context) -> str:
    """Full markdown report; its final non-empty line is the verdict line."""
    ordered = sorted(results, key=lambda r: r.number)
    parts = [_REPORT_HEADER.format(**context), "## Summary", ""]
    parts.extend(f"- Gate {r.number} ({r.key}): {r.status}" for r in ordered)
    parts.extend(["", "## Verdict", "", verdict.name])
    parts.extend(f"Note: {note}" for note in verdict.notes)
    parts.append("")
    for index, result in enumerate(ordered):
        if index:
            parts.append("")
        parts.append(_gate_section(result))
    parts.append("")
    parts.append(verdict_line(verdict))
    return "\n".join(parts) + "\n"


def render_summary(results, verdict: Verdict) -> str:
    """Short stdout summary; its final line is the verdict line."""
    ordered = sorted(results, key=lambda r: r.number)
    lines = ["Agent Desk environment probe"]
    lines.extend(f"Gate {r.number}: {r.title} ({r.key}): {r.status}" for r in ordered)
    lines.extend(f"Note: {note}" for note in verdict.notes)
    lines.append(verdict_line(verdict))
    return "\n".join(lines)
