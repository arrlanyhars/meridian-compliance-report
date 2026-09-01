"""
Parses sample_fund_guidelines.pdf into structured facts.

Worth recording why this doesn't use pdfplumber's built-in table detection.
I tried it first, and on this particular PDF it mangles cells badly:
"Singapore Government Securities (SGS" and ") 20%" end up as two separate
cells, "Monitoring Frequency" and "Breach Action" get glued into one column,
and so on. page.extract_text(), on the other hand, comes out clean because
the PDF's underlying text layout is a simple top-to-bottom flow. So this
module works line-by-line against extract_text() with regexes tuned to the
exact rows in this document, instead of fighting extract_tables()'s column
detection. For a fixed, small guidelines document that's a perfectly
reasonable trade. It would not scale to an arbitrary PDF, and that's fine,
this system isn't meant to.

One more quirk worth flagging: this PDF's font encodes "≤" in a way that
extract_text() renders as a plain "£". It's consistent across every
occurrence, so it's handled as a one-line substitution rather than anything
fancier.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import pdfplumber

from meridian.domain import asset_class_slug
from meridian.ingestion.chunking import SourceChunk, make_chunk_id

SOURCE_DOC = "sample_fund_guidelines.pdf"

_LEQ = "≤"  # what "£" actually means in this PDF's extracted text


@dataclass(frozen=True)
class AssetClassFact:
    name: str
    slug: str
    min_pct: Decimal
    max_pct: Decimal
    notes: str
    chunk: SourceChunk


@dataclass(frozen=True)
class RiskMetricFact:
    metric_id: str
    name: str
    limit_display: str
    limit_kind: str  # "range" | "max_value" | "max_percent"
    limit_min: Decimal | None
    limit_max: Decimal | None
    monitoring_frequency: str | None
    breach_action_text: str | None
    owner_role: str | None
    chunk: SourceChunk
    parse_ok: bool
    review_note: str | None = None


@dataclass(frozen=True)
class ProseLimitFact:
    fact_id: str
    value_pct: Decimal
    chunk: SourceChunk


@dataclass(frozen=True)
class GuidelinesExtraction:
    asset_classes: list[AssetClassFact]
    risk_metrics: list[RiskMetricFact]
    single_issuer_cap: ProseLimitFact
    gre_cap: ProseLimitFact
    non_ig_aggregate_cap: ProseLimitFact
    liquidity_floor_normal: ProseLimitFact
    liquidity_floor_stress: ProseLimitFact


def _page_texts(pdf_path: Path) -> list[str]:
    with pdfplumber.open(pdf_path) as pdf:
        pages = [(page.extract_text() or "") for page in pdf.pages]
    return [p.replace("&amp;", "&").replace("£", _LEQ) for p in pages]


_ASSET_CLASS_ROW = re.compile(r"^(?P<name>.+?)\s+(?P<min>\d+)%\s+(?P<max>\d+)%\s+(?P<notes>.+)$")


def _parse_asset_classes(pages: list[str], ingestion_time: str) -> list[AssetClassFact]:
    facts: list[AssetClassFact] = []
    for page_no, text in enumerate(pages, start=1):
        for line in text.splitlines():
            m = _ASSET_CLASS_ROW.match(line.strip())
            if not m:
                continue
            name = m.group("name").strip()
            try:
                slug = asset_class_slug(name)
            except ValueError:
                continue  # not one of the 7 known asset class rows, so skip it, not an error
            chunk = SourceChunk(
                chunk_id=make_chunk_id(SOURCE_DOC, page_no, "allocation", slug),
                source_doc=SOURCE_DOC,
                page=page_no,
                raw_text=line.strip(),
                extraction_method="deterministic_table_parse",
                extraction_confidence=0.98,
                ingestion_time=ingestion_time,
            )
            facts.append(
                AssetClassFact(
                    name=name,
                    slug=slug,
                    min_pct=Decimal(m.group("min")),
                    max_pct=Decimal(m.group("max")),
                    notes=m.group("notes").strip(),
                    chunk=chunk,
                )
            )
    if len(facts) != 7:
        raise ValueError(f"expected 7 asset class rows in {SOURCE_DOC}, parsed {len(facts)}")
    return facts


# Each risk metric row has its own shape in the source table, so each gets
# its own pattern rather than one generic-and-fragile catch-all regex.
_RISK_METRIC_PATTERNS: dict[str, re.Pattern[str]] = {
    "modified_duration": re.compile(
        r"^Modified Duration\s+([\d.]+)\s*–\s*([\d.]+)\s*years\s+(\S+)\s+(.+)$"
    ),
    "portfolio_dv01": re.compile(
        rf"^Portfolio DV01\s+{_LEQ}\s*SGD\s*([\d,]+)\s*per bp\s+(\S+)\s+(.+)$"
    ),
    "value_at_risk": re.compile(
        rf"^Value-at-Risk \(95%, 10-day\)\s+{_LEQ}\s*([\d.]+)%\s*of NAV\s+(\S+)\s+(.+)$"
    ),
    "expected_shortfall": re.compile(
        rf"^Expected Shortfall \(97\.5%\)\s+{_LEQ}\s*([\d.]+)%\s*of NAV\s+(\S+)\s+(.+)$"
    ),
    "interest_rate_sensitivity": re.compile(
        rf"^Interest Rate Sensitivity\s+{_LEQ}\s*±(\d+)%\s*NAV impact for \+/-(\d+)bp\s+(\S+)\s+(.+)$"
    ),
    "tracking_error": re.compile(
        rf"^Tracking Error vs Benchmark\s+{_LEQ}\s*([\d.]+)%\s*annualised\s+(\S+)\s+(.+)$"
    ),
}

_RISK_METRIC_DISPLAY_NAMES = {
    "modified_duration": "Modified Duration",
    "portfolio_dv01": "Portfolio DV01",
    "value_at_risk": "Value-at-Risk (95%, 10-day)",
    "expected_shortfall": "Expected Shortfall (97.5%)",
    "interest_rate_sensitivity": "Interest Rate Sensitivity",
    "tracking_error": "Tracking Error vs Benchmark",
}

_OWNER_KEYWORDS = ("notification", "alert", "review", "reporting", "triggered")


def _infer_owner(breach_action_text: str) -> str:
    lowered = breach_action_text.lower()
    for kw in _OWNER_KEYWORDS:
        idx = lowered.find(kw)
        if idx != -1:
            candidate = breach_action_text[:idx].strip()
            if candidate:
                return candidate
    return breach_action_text.strip()


def _parse_risk_metrics(pages: list[str], ingestion_time: str) -> list[RiskMetricFact]:
    facts: list[RiskMetricFact] = []
    seen: set[str] = set()

    for page_no, text in enumerate(pages, start=1):
        for line in text.splitlines():
            stripped = line.strip()
            for metric_id, pattern in _RISK_METRIC_PATTERNS.items():
                if metric_id in seen or not stripped.startswith(_RISK_METRIC_DISPLAY_NAMES[metric_id]):
                    continue
                seen.add(metric_id)
                m = pattern.match(stripped)
                chunk_base = dict(
                    source_doc=SOURCE_DOC,
                    page=page_no,
                    raw_text=stripped,
                    ingestion_time=ingestion_time,
                )
                if m is None:
                    # This is the one row (Interest Rate Sensitivity, in
                    # practice) where the source text didn't come out clean
                    # enough to parse. A column-overlap artifact in the PDF
                    # merges "200bp" and "Monthly" together. Rather than
                    # guess, this is surfaced as a fact the system could not
                    # confidently resolve, and it is routed to manual review.
                    chunk = SourceChunk(
                        chunk_id=make_chunk_id(SOURCE_DOC, page_no, "risk_metric", metric_id),
                        extraction_method="regex_table_parse_failed",
                        extraction_confidence=0.0,
                        **chunk_base,
                    )
                    facts.append(
                        RiskMetricFact(
                            metric_id=metric_id,
                            name=_RISK_METRIC_DISPLAY_NAMES[metric_id],
                            limit_display="",
                            limit_kind="unknown",
                            limit_min=None,
                            limit_max=None,
                            monitoring_frequency=None,
                            breach_action_text=None,
                            owner_role=None,
                            chunk=chunk,
                            parse_ok=False,
                            review_note=(
                                "Row could not be parsed cleanly from the extracted PDF text "
                                "(monitoring frequency and breach action appear merged together, "
                                "likely a column-overlap artifact). Needs a human to verify the "
                                "limit and breach action directly against the source PDF page "
                                f"{page_no} before this metric is trusted in a report."
                            ),
                        )
                    )
                    break

                chunk = SourceChunk(
                    chunk_id=make_chunk_id(SOURCE_DOC, page_no, "risk_metric", metric_id),
                    extraction_method="deterministic_table_parse",
                    extraction_confidence=0.98,
                    **chunk_base,
                )
                groups = m.groups()

                if metric_id == "modified_duration":
                    limit_min, limit_max, freq, action = groups
                    fact = RiskMetricFact(
                        metric_id=metric_id,
                        name=_RISK_METRIC_DISPLAY_NAMES[metric_id],
                        limit_display=f"{limit_min}–{limit_max} years",
                        limit_kind="range",
                        limit_min=Decimal(limit_min),
                        limit_max=Decimal(limit_max),
                        monitoring_frequency=freq,
                        breach_action_text=action,
                        owner_role=_infer_owner(action),
                        chunk=chunk,
                        parse_ok=True,
                    )
                elif metric_id == "portfolio_dv01":
                    limit_val, freq, action = groups
                    fact = RiskMetricFact(
                        metric_id=metric_id,
                        name=_RISK_METRIC_DISPLAY_NAMES[metric_id],
                        limit_display=f"max SGD {limit_val} / bp",
                        limit_kind="max_value",
                        limit_min=None,
                        limit_max=Decimal(limit_val.replace(",", "")),
                        monitoring_frequency=freq,
                        breach_action_text=action,
                        owner_role=_infer_owner(action),
                        chunk=chunk,
                        parse_ok=True,
                    )
                elif metric_id == "interest_rate_sensitivity":
                    nav_pct, bp, freq, action = groups
                    fact = RiskMetricFact(
                        metric_id=metric_id,
                        name=_RISK_METRIC_DISPLAY_NAMES[metric_id],
                        limit_display=f"max ±{nav_pct}% NAV impact for +/-{bp}bp",
                        limit_kind="max_percent",
                        limit_min=None,
                        limit_max=Decimal(nav_pct),
                        monitoring_frequency=freq,
                        breach_action_text=action,
                        owner_role=_infer_owner(action),
                        chunk=chunk,
                        parse_ok=True,
                    )
                else:  # value_at_risk, expected_shortfall, tracking_error share this shape
                    limit_val, freq, action = groups
                    fact = RiskMetricFact(
                        metric_id=metric_id,
                        name=_RISK_METRIC_DISPLAY_NAMES[metric_id],
                        limit_display=f"max {limit_val}%",
                        limit_kind="max_percent",
                        limit_min=None,
                        limit_max=Decimal(limit_val),
                        monitoring_frequency=freq,
                        breach_action_text=action,
                        owner_role=_infer_owner(action),
                        chunk=chunk,
                        parse_ok=True,
                    )
                facts.append(fact)
                break

    missing = set(_RISK_METRIC_PATTERNS) - seen
    if missing:
        raise ValueError(f"expected risk metric rows not found in {SOURCE_DOC}: {sorted(missing)}")
    return facts


def _sentence_around(blob: str, match_start: int, match_end: int, window: int = 220) -> str:
    """
    Grabs the sentence around a regex match for use as a citation's passage
    summary. Bounded to a fixed window either side rather than scanning the
    whole blob for a ". ". This document has dense, period-heavy numeric
    prose ("97.5%", "2.0 – 6.5 years") but genuine sentence breaks can be
    sparse, so an unbounded backward scan can walk all the way to the start
    of the page before finding one. A local window plus falling back to a
    colon ("Single Issuer Concentration: ...") keeps the citation to the one
    sentence a reader actually needs.
    """
    lo = max(0, match_start - window)
    hi = min(len(blob), match_end + window)
    local = blob[lo:hi]
    local_start = match_start - lo
    local_end = match_end - lo

    boundary_start = 0
    for sep in (". ", ": "):
        idx = local.rfind(sep, 0, local_start)
        if idx != -1:
            boundary_start = max(boundary_start, idx + len(sep))

    idx = local.find(". ", local_end)
    boundary_end = idx + 1 if idx != -1 else len(local)

    return local[boundary_start:boundary_end].strip()


_SINGLE_ISSUER = re.compile(r"more than (\d+)% of NAV")
_GRE_CAP = re.compile(r"capped at (\d+)% per issuer")
_NON_IG_AGGREGATE = re.compile(r"non-investment-grade instruments[^.]*?must not exceed\s+(\d+)% of NAV")
_LIQUIDITY_FLOOR = re.compile(
    r"minimum of (\d+)% of NAV under normal conditions and (\d+)% under stress"
)


def _prose_fact(
    fact_id: str, value: str, page_no: int, blob: str, match: re.Match, ingestion_time: str
) -> ProseLimitFact:
    sentence = _sentence_around(blob, match.start(), match.end())
    chunk = SourceChunk(
        chunk_id=make_chunk_id(SOURCE_DOC, page_no, "prose", fact_id),
        source_doc=SOURCE_DOC,
        page=page_no,
        raw_text=sentence,
        extraction_method="regex_prose_parse",
        extraction_confidence=0.90,
        ingestion_time=ingestion_time,
    )
    return ProseLimitFact(fact_id=fact_id, value_pct=Decimal(value), chunk=chunk)


def _parse_prose_limits(pages: list[str], ingestion_time: str) -> dict[str, ProseLimitFact]:
    results: dict[str, ProseLimitFact] = {}
    for page_no, text in enumerate(pages, start=1):
        blob = " ".join(text.splitlines())

        if "single_issuer_cap" not in results:
            m = _SINGLE_ISSUER.search(blob)
            if m:
                results["single_issuer_cap"] = _prose_fact(
                    "single_issuer_cap", m.group(1), page_no, blob, m, ingestion_time
                )

        if "gre_cap" not in results:
            m = _GRE_CAP.search(blob)
            if m:
                results["gre_cap"] = _prose_fact("gre_cap", m.group(1), page_no, blob, m, ingestion_time)

        if "non_ig_aggregate_cap" not in results:
            m = _NON_IG_AGGREGATE.search(blob)
            if m:
                results["non_ig_aggregate_cap"] = _prose_fact(
                    "non_ig_aggregate_cap", m.group(1), page_no, blob, m, ingestion_time
                )

        if "liquidity_floor" not in results:
            m = _LIQUIDITY_FLOOR.search(blob)
            if m:
                sentence = _sentence_around(blob, m.start(), m.end())
                normal_chunk = SourceChunk(
                    chunk_id=make_chunk_id(SOURCE_DOC, page_no, "prose", "liquidity_floor_normal"),
                    source_doc=SOURCE_DOC,
                    page=page_no,
                    raw_text=sentence,
                    extraction_method="regex_prose_parse",
                    extraction_confidence=0.90,
                    ingestion_time=ingestion_time,
                )
                stress_chunk = SourceChunk(
                    chunk_id=make_chunk_id(SOURCE_DOC, page_no, "prose", "liquidity_floor_stress"),
                    source_doc=SOURCE_DOC,
                    page=page_no,
                    raw_text=sentence,
                    extraction_method="regex_prose_parse",
                    extraction_confidence=0.90,
                    ingestion_time=ingestion_time,
                )
                results["liquidity_floor_normal"] = ProseLimitFact(
                    "liquidity_floor_normal", Decimal(m.group(1)), normal_chunk
                )
                results["liquidity_floor_stress"] = ProseLimitFact(
                    "liquidity_floor_stress", Decimal(m.group(2)), stress_chunk
                )

    required = {
        "single_issuer_cap",
        "gre_cap",
        "non_ig_aggregate_cap",
        "liquidity_floor_normal",
        "liquidity_floor_stress",
    }
    missing = required - results.keys()
    if missing:
        raise ValueError(f"expected prose limits not found in {SOURCE_DOC}: {sorted(missing)}")
    return results


def parse_guidelines(pdf_path: str | Path, ingestion_time: str) -> GuidelinesExtraction:
    pages = _page_texts(Path(pdf_path))
    asset_classes = _parse_asset_classes(pages, ingestion_time)
    risk_metrics = _parse_risk_metrics(pages, ingestion_time)
    prose = _parse_prose_limits(pages, ingestion_time)

    return GuidelinesExtraction(
        asset_classes=asset_classes,
        risk_metrics=risk_metrics,
        single_issuer_cap=prose["single_issuer_cap"],
        gre_cap=prose["gre_cap"],
        non_ig_aggregate_cap=prose["non_ig_aggregate_cap"],
        liquidity_floor_normal=prose["liquidity_floor_normal"],
        liquidity_floor_stress=prose["liquidity_floor_stress"],
    )
