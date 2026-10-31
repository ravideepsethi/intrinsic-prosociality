"""Keep historical outcome exceptions explicit, with independent count gates."""


def known_outcome_checks(config, audits):
    policy = config.get("known_outcomes", {})
    checks = []
    for family in sorted({a["family"] for a in audits}):
        selected = [a for a in audits if a["family"] == family]
        spec = policy.get(family, {"field": "chooser_loss_rows", "expected": 0})
        field = spec["field"]
        actual = sum(a["counts"][field] for a in selected)
        expected = spec["expected"]
        checks.append(dict(family=family, check="known_"+field, actual=actual,
                           expected=expected, passed=actual == expected))
        if "monthly" in spec:
            for audit in selected:
                month = audit["month"]
                actual = audit["counts"][field]
                expected = spec["monthly"].get(month, 0)
                checks.append(dict(family=family, month=month, check="known_monthly_"+field,
                                   actual=actual, expected=expected, passed=actual == expected))
    return checks
