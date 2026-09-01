from __future__ import annotations

import csv
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from meridian.domain import asset_class_slug
from meridian.ingestion.chunking import SourceChunk, make_chunk_id

SOURCE_DOC = "sample_holdings.csv"


@dataclass(frozen=True)
class PositionRecord:
    instrument_id: str
    instrument_name: str
    asset_class_slug: str
    issuer_name: str
    issuer_type: str
    parent_issuer: str | None
    credit_rating: str
    downgraded_from: str | None
    market_value_sgd: Decimal
    modified_duration: Decimal
    chunk: SourceChunk


def load_holdings(csv_path: str | Path, ingestion_time: str) -> list[PositionRecord]:
    csv_path = Path(csv_path)
    records: list[PositionRecord] = []

    with csv_path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for row_index, row in enumerate(reader, start=2):  # header is row 1
            raw_text = ",".join(f"{k}={v}" for k, v in row.items())
            chunk = SourceChunk(
                chunk_id=make_chunk_id(SOURCE_DOC, None, "csv_row", str(row_index)),
                source_doc=SOURCE_DOC,
                page=None,
                raw_text=raw_text,
                extraction_method="deterministic_csv_row",
                extraction_confidence=1.0,
                ingestion_time=ingestion_time,
            )
            parent_issuer = row["parent_issuer"].strip() or None
            downgraded_from = row["downgraded_from"].strip() or None

            records.append(
                PositionRecord(
                    instrument_id=row["instrument_id"].strip(),
                    instrument_name=row["instrument_name"].strip(),
                    asset_class_slug=asset_class_slug(row["asset_class"].strip()),
                    issuer_name=row["issuer_name"].strip(),
                    issuer_type=row["issuer_type"].strip(),
                    parent_issuer=parent_issuer,
                    credit_rating=row["credit_rating"].strip(),
                    downgraded_from=downgraded_from,
                    market_value_sgd=Decimal(row["market_value_sgd"].strip()),
                    modified_duration=Decimal(row["modified_duration"].strip()),
                    chunk=chunk,
                )
            )

    # Stable order matters for anything downstream that sums or iterates over
    # positions. See compute/rounding.py for why summation order needs to
    # be fixed rather than "whatever csv.DictReader happened to hand back".
    records.sort(key=lambda r: r.instrument_id)
    return records
