"""The human-review gate: the auto-pass/needs-review split has to be mechanical, not vibes."""

from meridian.ingestion.review_gate import build_review_report


def test_prose_facts_always_need_review_even_though_they_parsed_fine(meridian_graph):
    report = build_review_report(meridian_graph.all_chunks())
    prose_chunk_ids = {
        c.chunk_id for c in meridian_graph.all_chunks() if c.extraction_method == "regex_prose_parse"
    }
    flagged_ids = {item.chunk_id for item in report.needs_review}
    assert prose_chunk_ids and prose_chunk_ids <= flagged_ids


def test_the_one_failed_table_row_is_flagged_with_zero_confidence(meridian_graph):
    report = build_review_report(meridian_graph.all_chunks())
    failed = [item for item in report.needs_review if "interest_rate_sensitivity" in item.chunk_id]
    assert len(failed) == 1
    assert "failed to parse" in failed[0].reason.lower()


def test_deterministic_table_and_csv_rows_auto_pass(meridian_graph):
    report = build_review_report(meridian_graph.all_chunks())
    flagged_ids = {item.chunk_id for item in report.needs_review}
    clean_table_row = next(
        c for c in meridian_graph.all_chunks()
        if c.extraction_method == "deterministic_table_parse" and c.extraction_confidence >= 0.90
    )
    assert clean_table_row.chunk_id not in flagged_ids
