import pytest

from scripts.financials import prepare


def sample():
    data = dict(entity="Example Company", period="2030-01", metrics={
        "revenue": {"value": "1250.00", "source": "fictional ledger: revenue"},
        "expenses": {"value": "850.00", "source": "fictional ledger: expenses"},
        "net_income": {"value": "400.00", "source": "fictional ledger: net income"},
    })
    config = dict(entity="Example Company", inputs=[
        {"metric": "revenue", "sheet": "Summary", "cell": "B1"},
        {"metric": "expenses", "sheet": "Summary", "cell": "B2"},
    ], equations=[{"name": "Net income", "terms": {"revenue": 1, "expenses": -1}, "expected": "net_income", "tolerance": "0.01"}])
    return data, config


def test_source_totals_reconcile_before_writes():
    data, config = sample()
    updates, checks = prepare(data, config)
    assert [u["value"] for u in updates] == [1250, 850]
    assert checks[0]["status"] == "passed"
    data["metrics"]["net_income"]["value"] = "401.00"
    with pytest.raises(ValueError):
        prepare(data, config)


def test_missing_provenance_and_new_nonzero_metric_rejected():
    data, config = sample()
    data["metrics"]["unmapped"] = {"value": "5", "source": "fictional ledger"}
    with pytest.raises(ValueError):
        prepare(data, config)
    del data["metrics"]["unmapped"]
    data["metrics"]["revenue"]["source"] = ""
    with pytest.raises(ValueError):
        prepare(data, config)


def test_mismatched_entity_rejected():
    data, config = sample()
    config["entity"] = "Other Company"
    with pytest.raises(ValueError):
        prepare(data, config)
