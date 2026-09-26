"""Regression corpus for alert/clear classification."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from alert_bot_project.core_shared.text_processor import TextProcessor


@pytest.mark.parametrize(
    ("post", "expected"),
    [
        ("Ракети на центр", "active"),
        ("Бпла на Пересип", "active"),
        ("Відбій тривоги, ракетна небезпека минула", "clear"),
        ("Отбой тревоги. Ракеты больше не угрожают", "clear"),
        ("Не виявлено ракет на центр", "negated"),
        ("Нет угрозы БПЛА", "negated"),
        ("Не виявлено ракет, але БПЛА на центр", "active"),
        ("Звичайний допис без загрози", "unknown"),
    ],
)
def test_labelled_status_corpus(post: str, expected: str) -> None:
    assert TextProcessor.classify_status(post) == expected


@given(st.sampled_from(["Відбій", "Отбой", "тривогу скасовано"]), st.sampled_from(["Ракети", "Бпла"]))
def test_clear_never_becomes_active_when_category_is_mentioned(clear: str, category: str) -> None:
    assert TextProcessor.classify_status(f"{clear} тривоги: {category} на центр") == "clear"


@pytest.mark.parametrize(
    ("post", "expected_location"),
    [
        ("Відбій для центру. Ракети летять на Пересип", "peresyp"),
        ("Отбой для центра! Ракеты летят на Пересыпь", "peresyp"),
    ],
)
def test_new_threat_after_scoped_clear_remains_actionable(post: str, expected_location: str) -> None:
    signal = TextProcessor.analyze_signal(post)
    assert signal.status == "active"
    assert signal.clear_locations == frozenset({"center"})
    assert signal.global_clear is False
    assert TextProcessor.parse_message(signal.positive_text)["locations"] == {expected_location}


@given(
    st.sampled_from(["Не виявлено ракет на центр", "Не обнаружено ракет на центр"]),
    st.sampled_from(["БПЛА на Пересип", "Шахеди на Пересип"]),
)
def test_negated_clause_cannot_supply_active_recipients(negated: str, active: str) -> None:
    signal = TextProcessor.analyze_signal(f"{negated}, але {active}")
    assert signal.status == "active"
    assert TextProcessor.parse_message(signal.positive_text) == {
        "categories": {"Мопеди"},
        "locations": {"peresyp"},
    }
