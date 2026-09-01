"""
Constraint 3, the verified half: proves the firewall actually catches a
fabricated number, using a stub LLM client so this doesn't depend on a real
API key or a live model's behavior being predictable.
"""

from meridian.compute.engine import compute_figure_set
from meridian.narrative.firewall import check
from meridian.narrative.generator import generate_narrative
from meridian.narrative.llm_client import LLMClient


class _FixedTextClient(LLMClient):
    model_name = "stub"

    def __init__(self, text: str) -> None:
        self._text = text

    def generate(self, prompt: str) -> str:
        return self._text


def test_narrative_using_only_reported_numbers_passes(meridian_graph, firm_a_config):
    figures = compute_figure_set(meridian_graph, firm_a_config)
    narrative = "The fund breaches its cash floor at 4.0% against a minimum of 5%."
    report = check(narrative, figures)
    assert report.passed
    assert report.violations == ()


def test_narrative_with_a_fabricated_number_is_caught(meridian_graph, firm_a_config):
    figures = compute_figure_set(meridian_graph, firm_a_config)
    narrative = "Estimated portfolio VaR came in at 3.2% this quarter."
    report = check(narrative, figures)
    assert not report.passed
    assert "3.2" in report.violations


def test_generator_ends_in_firewall_failed_when_the_model_keeps_fabricating(meridian_graph, firm_a_config):
    figures = compute_figure_set(meridian_graph, firm_a_config)
    client = _FixedTextClient("Estimated VaR is 3.2% this quarter, which analysts consider elevated.")
    result = generate_narrative(client, figures)
    assert result.status == "FIREWALL_FAILED"
    assert result.text is None  # never emits the unverified text
    assert result.attempts == 2  # retried once before giving up


def test_generator_returns_ok_when_the_model_behaves(meridian_graph, firm_a_config):
    figures = compute_figure_set(meridian_graph, firm_a_config)
    client = _FixedTextClient("The largest single corporate issuer sits exactly at its 8.0% cap, with no headroom left.")
    result = generate_narrative(client, figures)
    assert result.status == "OK"
    assert result.text is not None


def test_no_client_configured_skips_gracefully(meridian_graph, firm_a_config):
    figures = compute_figure_set(meridian_graph, firm_a_config)
    result = generate_narrative(None, figures)
    assert result.status == "SKIPPED_NO_API_KEY"
