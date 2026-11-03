"""Reconcile normalized, source-backed metrics before constructing workbook updates."""
from decimal import Decimal

from scripts.delivery import validate_period


def number(value):
    amount = Decimal(str(value))
    if not amount.is_finite():
        raise ValueError("Financial values must be finite")
    return amount


def prepare(data, config):
    validate_period(data["period"])
    if not data.get("entity") or data["entity"] != config["entity"]:
        raise ValueError("Entity mismatch")
    values = {}
    for metric, entry in data["metrics"].items():
        if not isinstance(entry.get("source"), str) or not entry["source"].strip():
            raise ValueError("Every metric needs a source reference")
        values[metric] = number(entry["value"])
    used = {entry["metric"] for entry in config["inputs"]}
    checks = []
    if not config.get("equations"):
        raise ValueError("Define independent reconciliation equations")
    for equation in config["equations"]:
        terms = equation["terms"]
        used.update(terms)
        used.add(equation["expected"])
        tolerance = number(equation.get("tolerance", "0"))
        if tolerance < 0 or not terms:
            raise ValueError("Nonnegative tolerance and at least one term are required")
        calculated = sum((values[key] * number(weight) for key, weight in terms.items()), Decimal(0))
        expected = values[equation["expected"]]
        if abs(calculated - expected) > tolerance:
            raise ValueError("Source reconciliation failed: " + equation["name"])
        checks.append(dict(name=equation["name"], status="passed", calculated=str(calculated), expected=str(expected)))
    if any(value != 0 and key not in used for key, value in values.items()):
        raise ValueError("Unmapped nonzero metric requires review")
    updates = [dict(sheet=entry["sheet"], cell=entry["cell"], value=float(values[entry["metric"]])) for entry in config["inputs"]]
    if len({(entry["sheet"], entry["cell"]) for entry in updates}) != len(updates):
        raise ValueError("Duplicate input destination")
    return updates, checks
