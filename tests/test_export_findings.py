"""Unit tests for the findings export and the analysis header parser (no database needed)."""

import pytest

import export_findings
import refresh_views


def test_export_refuses_to_publish_a_small_cell():
    with pytest.raises(SystemExit, match="small cell"):
        export_findings.check_no_small_cells("v", ["patients"], [(7,)])


def test_export_allows_zero_suppressed_and_row_labels():
    # 0 is allowed; None is a suppressed cell; sort_order/period are labels, not counts.
    export_findings.check_no_small_cells("v", ["sort_order", "period", "patients"],
                                         [(1, 3, 0), (2, 4, None), (3, 5, 11)])


def test_suppressed_values_are_labelled_in_the_published_table():
    assert export_findings.fmt(None) == "*suppressed*"
    assert export_findings.fmt(1234) == "1,234"


def test_every_analysis_file_has_a_complete_header():
    for a in refresh_views.list_analyses():
        assert set(a.header) == set(refresh_views.HEADER_FIELDS), a.path.name


def test_header_parser_rejects_a_missing_field():
    with pytest.raises(ValueError, match="Limitations"):
        refresh_views.parse_header("-- Title: t\n-- Question: q\n-- Method: m\n"
                                   "-- Assumptions: a\nSELECT 1")
