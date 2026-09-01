"""
Constraint 5: switching firms is a config change, nothing else. This test
computes both firms off the exact same graph object. If the fix for a
future bug ever involved a `if firm_id == ...` branch inside compute/,
this is the test that would need faking to still pass, which is the point.
"""

from meridian.compute.engine import compute_figure_set

EXPECTED_DELTAS = {
    "Aggregate non-IG exposure": {"firm_a": ("15.0%", "OK"), "firm_b": ("21.0%", "BREACH")},
    "Largest GRE issuer": {"firm_a": ("7.0%", "OK"), "firm_b": ("13.0%", "BREACH")},
}


def test_only_the_three_stated_conventions_change_between_firms(meridian_graph, firm_a_config, firm_b_config):
    figures_a = compute_figure_set(meridian_graph, firm_a_config)
    figures_b = compute_figure_set(meridian_graph, firm_b_config)

    changed_metrics = set()
    for fig_a, fig_b in zip(figures_a.figures, figures_b.figures):
        assert fig_a.metric == fig_b.metric
        if (fig_a.value_display, fig_a.status) != (fig_b.value_display, fig_b.status):
            changed_metrics.add(fig_a.metric)

    assert changed_metrics == set(EXPECTED_DELTAS)


def test_the_two_deltas_match_firm_b_brief_exactly(meridian_graph, firm_a_config, firm_b_config):
    figures_a = compute_figure_set(meridian_graph, firm_a_config)
    figures_b = compute_figure_set(meridian_graph, firm_b_config)

    for metric, expected in EXPECTED_DELTAS.items():
        fig_a = next(f for f in figures_a.figures if f.metric == metric)
        fig_b = next(f for f in figures_b.figures if f.metric == metric)
        assert (fig_a.value_display, fig_a.status) == expected["firm_a"]
        assert (fig_b.value_display, fig_b.status) == expected["firm_b"]


def test_firm_b_utilization_is_truncated_basis_points(meridian_graph, firm_b_config):
    figures_b = compute_figure_set(meridian_graph, firm_b_config)
    sgs = next(f for f in figures_b.figures if f.metric == "Singapore Government Securities")
    assert sgs.utilization_display == "5833 bps"  # 58.333...% truncated, per firm_B_brief.md's own example
