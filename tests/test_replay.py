"""The replay viewer, checked the same way as everything else here: against the real graph and figures."""

from meridian.compute.engine import compute_figure_set
from meridian.replay.viewer import explain_figure


def test_replay_names_the_config_rule_that_produced_a_config_dependent_figure(meridian_graph, firm_b_config):
    figures = compute_figure_set(meridian_graph, firm_b_config)
    figure = figures.by_id("aggregate_non_ig_exposure")

    explanation = explain_figure(figure, firm_b_config)

    assert "non_ig_aggregate.include_fallen_angels = True" in explanation.config_rules
    assert explanation.graph_path == figure.graph_path
    assert explanation.source_doc == "sample_fund_guidelines.pdf"


def test_replay_shows_no_firm_specific_rule_for_a_figure_no_config_touches(meridian_graph, firm_a_config):
    figures = compute_figure_set(meridian_graph, firm_a_config)
    figure = figures.by_id("liquid_assets_ratio")

    explanation = explain_figure(figure, firm_a_config)

    # only the universal formatting rule applies; liquidity isn't config-dependent
    assert explanation.config_rules == ("formatting.utilization_style = percent_1dp",)


def test_replay_reports_delta_against_the_answer_key(meridian_graph, firm_a_config):
    figures = compute_figure_set(meridian_graph, firm_a_config)
    figure = figures.by_id("allocation_sgs")

    explanation = explain_figure(figure, firm_a_config, answer_key_value="35.0%")

    assert explanation.delta_vs_answer_key == "0 (exact match)"


def test_replay_reports_the_delta_between_firm_a_and_firm_b(meridian_graph, firm_a_config, firm_b_config):
    figures_a = compute_figure_set(meridian_graph, firm_a_config)
    figures_b = compute_figure_set(meridian_graph, firm_b_config)

    fig_a = figures_a.by_id("largest_gre_issuer")
    fig_b = figures_b.by_id("largest_gre_issuer")

    explanation = explain_figure(fig_b, firm_b_config, firm_a_figure=fig_a)

    assert "7.0% (OK)" in explanation.delta_vs_firm_a
    assert "13.0% (BREACH)" in explanation.delta_vs_firm_a


def test_replay_reports_unchanged_when_a_figure_matches_firm_a(meridian_graph, firm_a_config, firm_b_config):
    figures_a = compute_figure_set(meridian_graph, firm_a_config)
    figures_b = compute_figure_set(meridian_graph, firm_b_config)

    fig_a = figures_a.by_id("liquid_assets_ratio")
    fig_b = figures_b.by_id("liquid_assets_ratio")

    explanation = explain_figure(fig_b, firm_b_config, firm_a_figure=fig_a)

    assert explanation.delta_vs_firm_a == "unchanged from Firm A"
