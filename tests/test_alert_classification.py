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
