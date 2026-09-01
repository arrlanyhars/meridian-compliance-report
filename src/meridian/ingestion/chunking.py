"""
A SourceChunk is the unit citations point at: one row of a table, one
paragraph of prose, one CSV row. Every fact pulled out during ingestion has
to name the chunk it came from, and every chunk has to be re-findable in the
original document (page number + a short summary of what's on it).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceChunk:
    chunk_id: str
    source_doc: str
    page: int | None
    raw_text: str
    extraction_method: str
    extraction_confidence: float
    ingestion_time: str

    @property
    def auto_passes_review(self) -> bool:
        """
        The gate a chunk's derived facts must clear before compute trusts them.

        Deterministic parses (a table row, a CSV row) are structurally hard to
        get subtly wrong. Either the row matches the expected shape or it
        doesn't parse at all. Prose extracted by regex is the opposite: it can
        match confidently on the wrong sentence and nobody would notice until
        an auditor asks. So prose always goes to a human, full stop, and table/
        CSV rows only skip review if they parsed cleanly.
        """
        if self.extraction_method not in ("deterministic_table_parse", "deterministic_csv_row"):
            return False
        return self.extraction_confidence >= 0.90


def make_chunk_id(source_doc: str, page: int | None, kind: str, key: str) -> str:
    page_part = f"p{page}" if page is not None else "p-"
    return f"{source_doc}:{page_part}:{kind}:{key}"
