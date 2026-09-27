"""Data minimisation: the ONLY data the LLM ever receives. This is the primary privacy control.

The payload is built from an explicit allowlist: for each aggregate view, exactly which columns
may be sent. Anything not listed, including any column added to a view later, is dropped until
someone deliberately adds it here. Inputs are already aggregates with small cells suppressed.
Dates are reduced to year-month.
"""

from datetime import date, datetime
from decimal import Decimal

# view -> columns allowed to leave the system. All are aggregate labels, counts or rates.
ALLOWED_COLUMNS = {
    "population_overview": ["dimension", "category", "patients", "suppressed"],
    "chronic_disease_prevalence": ["condition", "age_band", "gender", "patients_with_condition",
                                   "living_patients", "prevalence_pct", "suppressed"],
    "readmissions_30day": ["dimension", "category", "index_stays", "readmissions",
                           "readmission_rate_pct", "suppressed"],
    "ed_visits_per_1000": ["period", "period_start", "period_end", "ed_visits",
                           "active_patients", "visits_per_1000", "suppressed"],
    "ed_frequent_users": ["ed_users", "frequent_users", "frequent_user_pct", "ed_visits",
                          "frequent_user_visits", "frequent_user_visit_pct", "suppressed"],
    "cost_by_class_payer": ["encounter_class", "payer", "payer_type", "encounters",
                            "total_claim_cost", "payer_coverage", "patient_out_of_pocket",
                            "coverage_pct", "suppressed"],
    "top_conditions_by_cost": ["cost_rank", "condition", "encounters", "patients",
                               "total_claim_cost", "patient_out_of_pocket", "suppressed"],
    "care_gaps": ["measure", "eligible_patients", "patients_with_gap", "gap_pct", "suppressed"],
    "polypharmacy": ["age_band", "eligible_patients", "patients_with_polypharmacy",
                     "polypharmacy_pct", "suppressed"],
    "flu_vaccination": ["age_band", "eligible_patients", "vaccinated_patients",
                        "vaccination_pct", "suppressed"],
}
MAX_ROWS_PER_TABLE = 80   # keeps the prompt small; the largest view has 72 rows


def _value(v):
    if isinstance(v, datetime | date):
        return f"{v.year}-{v.month:02d}"   # year-month only
    if isinstance(v, Decimal):
        return float(v)
    return v


def build_payload(analysis: dict) -> dict:
    """The minimised, aggregate-only view of one analysis that may be sent to the LLM."""
    tables = []
    for table in analysis["tables"]:
        allowed = ALLOWED_COLUMNS.get(table["name"])
        if allowed is None:
            continue   # a view nobody has reviewed is never sent
        columns = [c for c in table["columns"] if c in allowed]
        rows = [[_value(row[c]) for c in columns] for row in table["rows"][:MAX_ROWS_PER_TABLE]]
        tables.append({"name": table["name"], "title": table["title"],
                       "columns": columns, "rows": rows})
    ref = analysis.get("reference_date")
    return {
        "analysis": analysis["id"],
        "title": analysis["title"],
        "question": analysis["question"],
        "limitations": analysis["limitations"],
        "data_through": _value(ref) if ref else None,
        "notes": "null means suppressed: the true value involves 1-10 patients or events.",
        "tables": tables,
    }


def numbers_in(payload: dict) -> frozenset:
    """Every number in the payload's rows: what the model is allowed to cite."""
    found = set()
    for table in payload["tables"]:
        for row in table["rows"]:
            found.update(v for v in row if isinstance(v, int | float) and not isinstance(v, bool))
    return frozenset(found)
