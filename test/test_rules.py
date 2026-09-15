import pytest

from codereview.report import Category, Severity
from codereview.rules import RULES, Rule, get


def test_registry_has_expected_number_of_rules():
    assert len(RULES) == 23


def test_rule_ids_unique():
    assert len({r.code for r in RULES.values()}) == len(RULES)


def test_get_returns_rule():
    rule = get("PY001")
    assert isinstance(rule, Rule)
    assert rule.code == "PY001"


def test_get_unknown_raises():
    with pytest.raises(KeyError):
        get("NOPE")


def test_all_rules_have_valid_category_and_message():
    for rule in RULES.values():
        assert isinstance(rule.category, Category)
        assert isinstance(rule.severity, Severity)
        assert rule.message.strip()


def test_rule_is_frozen():
    rule = Rule("X", "n", Category.PYTHONIC, Severity.INFO, "title", "msg")
    with pytest.raises(Exception):
        rule.code = "Y"


def test_pythonic_and_design_both_present():
    cats = {r.category for r in RULES.values()}
    assert Category.PYTHONIC in cats
    assert Category.DESIGN in cats