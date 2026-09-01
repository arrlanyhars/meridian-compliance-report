"""
The human checkpoint between "we parsed something out of a PDF" and "this is
trustworthy enough to put in a regulatory report". Extraction is error-prone
by nature (pdf_ingest.py itself hits a row it can't parse cleanly), so
nothing that didn't come from a fully deterministic parse gets to skip a
person looking at it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from meridian.ingestion.chunking import SourceChunk


@dataclass(frozen=True)
class ReviewItem:
    chunk_id: str
    source_doc: str
    page: int | None
    excerpt: str
    reason: str


@dataclass(frozen=True)
class GraphReviewReport:
    total_chunks: int
    needs_review: list[ReviewItem] = field(default_factory=list)

    @property
    def auto_passed(self) -> int:
        return self.total_chunks - len(self.needs_review)

    @property
    def clean(self) -> bool:
        return not self.needs_review


def build_review_report(chunks: list[SourceChunk]) -> GraphReviewReport:
    items: list[ReviewItem] = []
    for chunk in chunks:
        if chunk.auto_passes_review:
            continue
        if chunk.extraction_confidence == 0.0:
            reason = "extraction failed to parse cleanly, see raw_text and verify by hand"
        elif chunk.extraction_method == "regex_prose_parse":
            reason = "extracted from free-form prose, not a structured table, so always reviewed regardless of confidence"
        else:
            reason = f"confidence {chunk.extraction_confidence:.2f} is below the 0.90 auto-pass bar"
        items.append(
            ReviewItem(
                chunk_id=chunk.chunk_id,
                source_doc=chunk.source_doc,
                page=chunk.page,
                excerpt=chunk.raw_text[:160],
                reason=reason,
            )
        )
    return GraphReviewReport(total_chunks=len(chunks), needs_review=items)


def render_review_markdown(report: GraphReviewReport, run_id: str, firm_id: str) -> str:
    lines = [
        f"# Graph review: run `{run_id}` (firm: {firm_id})",
        "",
        f"{report.auto_passed} / {report.total_chunks} extracted facts auto-passed "
        "(deterministic table/CSV parse, confidence >= 0.90, no conflicting chunks).",
        "",
    ]
    if report.needs_review:
        lines.append(f"## {len(report.needs_review)} item(s) need a human to sign off before this graph is trusted")
        lines.append("")
        for item in report.needs_review:
            loc = f"{item.source_doc}" + (f", p.{item.page}" if item.page else "")
            lines.append(f"- **`{item.chunk_id}`** ({loc})")
            lines.append(f"  - reason: {item.reason}")
            lines.append(f"  - excerpt: {item.excerpt!r}")
        lines.append("")
        lines.append(
            "This run proceeded anyway (see the run's console output for how). To require an "
            "explicit human sign-off before proceeding, rerun with `--strict-review`, check the "
            "items above against the source documents, then rerun again with `--approve-graph`."
        )
    else:
        lines.append("Nothing flagged. Every fact came from a deterministic parse at or above the confidence bar.")
    return "\n".join(lines)
