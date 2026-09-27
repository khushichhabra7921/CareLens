"""Step 1: the AWS Budget with email alerts. Created before any other resource. Idempotent.

Important: the budget measures cost BEFORE credits (IncludeCredit = false). With the default
(credits included), a Free plan account's net cost is always $0, so the alerts would never fire.

Run:  py -3.12 infra/budget.py
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from awscli import aws  # noqa: E402
from config import (  # noqa: E402
    BUDGET_ALERTS_USD,
    BUDGET_EMAIL,
    BUDGET_LIMIT_USD,
    BUDGET_NAME,
    TAGS,
)


def account_id() -> str:
    return aws("sts", "get-caller-identity")["Account"]


def budget_definition() -> dict:
    return {
        "BudgetName": BUDGET_NAME,
        "BudgetLimit": {"Amount": str(BUDGET_LIMIT_USD), "Unit": "USD"},
        "TimeUnit": "MONTHLY",
        "BudgetType": "COST",
        "CostTypes": {
            "IncludeCredit": False,      # see module docstring: measure real usage
            "IncludeRefund": False,
            "IncludeTax": True, "IncludeSubscription": True, "IncludeSupport": True,
            "IncludeOtherSubscription": True, "IncludeRecurring": True, "IncludeUpfront": True,
            "IncludeDiscount": True, "UseBlended": False, "UseAmortized": False,
        },
    }


def notifications() -> list[dict]:
    return [{
        "Notification": {"NotificationType": "ACTUAL", "ComparisonOperator": "GREATER_THAN",
                         "Threshold": amount, "ThresholdType": "ABSOLUTE_VALUE"},
        "Subscribers": [{"SubscriptionType": "EMAIL", "Address": BUDGET_EMAIL}],
    } for amount in BUDGET_ALERTS_USD]


def ensure_budget() -> None:
    account = account_id()
    existing = aws("budgets", "describe-budgets", "--account-id", account,
                   region="us-east-1") or {}
    if any(b["BudgetName"] == BUDGET_NAME for b in existing.get("Budgets", [])):
        print(f"Budget '{BUDGET_NAME}' already exists.")
        return
    with tempfile.TemporaryDirectory() as tmp:
        budget_file = Path(tmp) / "budget.json"
        notes_file = Path(tmp) / "notifications.json"
        budget_file.write_text(json.dumps(budget_definition()), encoding="utf-8")
        notes_file.write_text(json.dumps(notifications()), encoding="utf-8")
        aws("budgets", "create-budget", "--account-id", account,
            "--budget", f"file://{budget_file}",
            "--notifications-with-subscribers", f"file://{notes_file}",
            "--resource-tags", *[f"Key={k},Value={v}" for k, v in TAGS.items()],
            region="us-east-1")
    print(f"Created budget '{BUDGET_NAME}': ${BUDGET_LIMIT_USD}/month, alerts at "
          f"{', '.join(f'${a}' for a in BUDGET_ALERTS_USD)} to {BUDGET_EMAIL}.")


def show_budget() -> None:
    account = account_id()
    b = aws("budgets", "describe-budget", "--account-id", account, "--budget-name", BUDGET_NAME,
            region="us-east-1")["Budget"]
    notes = aws("budgets", "describe-notifications-for-budget", "--account-id", account,
                "--budget-name", BUDGET_NAME, region="us-east-1")["Notifications"]
    print(f"  limit: {b['BudgetLimit']['Amount']} {b['BudgetLimit']['Unit']} / {b['TimeUnit']}, "
          f"credits included: {b['CostTypes']['IncludeCredit']}")
    for n in notes:
        print(f"  alert: {n['NotificationType']} {n['ComparisonOperator']} {n['Threshold']} "
              f"({n['ThresholdType']})")


if __name__ == "__main__":
    ensure_budget()
    show_budget()
