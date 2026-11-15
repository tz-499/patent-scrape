"""Render the weekly Markdown digest."""
from __future__ import annotations


def _clip(text: str, n: int = 420) -> str:
    return text if len(text) <= n else text[:n].rsplit(" ", 1)[0] + "..."


def render(run_date: str, ranked: dict[str, list[dict]], stats: dict) -> str:
    lines = [
        f"# Patent digest - {run_date}",
        "",
        f"Files: {', '.join(stats['files']) or 'none'}  ",
        f"Scanned {stats['scanned']:,} documents, {stats['candidates']:,} passed the CPC/keyword filter.",
        "",
    ]
    for topic, matches in ranked.items():
        lines += [f"## {topic} ({len(matches)})", ""]
        if not matches:
            lines += ["_No matches this week._", ""]
            continue
        for m in matches:
            kind = "Grant" if m["doc_type"] == "grant" else "Application"
            assignee = ", ".join(m["assignees"][:2]) or "unassigned"
            lines.append(f"### [{m['title']}]({m['url']})")
            lines.append(
                f"`{m['pub_number']}` | {kind} | {assignee} | published {m['pub_date']} "
                f"| filed {m['filing_date'] or '?'} | score {m['score']:.2f}"
            )
            lines.append("")
            llm = m.get("llm")
            if llm:
                lines.append(f"{llm['summary']} (relevance {llm['relevance']}/5)")
                if llm["why_it_matters"]:
                    lines.append(f"\n**Why it matters:** {llm['why_it_matters']}")
            else:
                lines.append(_clip(m["abstract"]) or "_No abstract._")
            lines.append(f"\nCPC: {', '.join(m['cpc'][:5])}")
            if m.get("also_published_as"):
                lines.append(f"  \nAlso published as: {', '.join(m['also_published_as'])}")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"
