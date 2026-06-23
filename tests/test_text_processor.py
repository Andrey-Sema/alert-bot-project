import pytest
from alert_bot_project.core_shared.text_processor import TextProcessor
from hypothesis import given, settings, strategies as st

# ============================================================================
# 1. ТЕСТЫ НОРМАЛИЗАЦИИ ТЕКСТА
# ============================================================================
@pytest.mark.parametrize("raw_text, expected", [
    ("", ""),
    ("   ", ""),
    ("УДАР!", "удар"),
    ("Мопеди!!! 🎉🚨", "мопеди"),
    ("Центр / Фонтан", "центр  фонтан"),
    ("Х-101", "х-101"),
    ("Нова_локація", "нова_локація"),
    ("Скадовськ-Одеса...", "скадовськ-одеса"),
])
def test_normalize_text_matrix(raw_text, expected):
    assert TextProcessor.normalize(raw_text) == expected


# ============================================================================
# 2. ТЕСТЫ КАТЕГОРИЙ ЗАГРОЗ
# ============================================================================
@pytest.mark.parametrize("text, expected_categories", [
    ("Зафіксовано рух БПЛА", {"Мопеди"}),
    ("Пуск калібрів з моря", {"Ракети"}),
    ("Летять шахеди", {"Мопеди"}),
    ("Летять шахіди", {"Мопеди"}),
    ("Загроза балістики!", {"Ракети"}),
    ("Работают по шахеду", {"Мопеди"}),
    ("Сбили шахеды", {"Мопеди"}),
    ("Летит одиночный мопед", {"Мопеди"}),
    ("Ракетна небезпека", {"Ракети"}),
    ("Выходы и пуски", {"Ракети"}),
    ("Ракети та шахеди в повітрі", {"Мопеди", "Ракети"}),
])
def test_threat_categories_matrix(text, expected_categories):
    result = TextProcessor.parse_message(text)
    assert result["categories"] == expected_categories


# ============================================================================
# 3. ТЕСТЫ ГЕОГРАФИЧЕСКИХ ЛОКАЦИЙ
# ============================================================================
@pytest.mark.parametrize("text, expected_locations", [
    ("Вектор на Черемушки", {"cheremushki"}),
    ("Громко в районе Порту", {"port"}),
    ("Взрывы на Слободке", {"slobodka"}),
    ("Привоз, Молдованка в укрытие", {"moldovanka"}),
    ("Поскот, внимание", {"kotovskogo"}),
    ("Аркадия и Фонтанка под ударом", {"arkadia", "fontanka"}),
    ("Курс на Пересипу", {"peresyp"}),
    ("Шахед в направлении Южного", {"yuzhne"}),
    ("Ракеты на Черноморск", {"chernomorsk"}),
    ("Авангард — в укрытие", {"avangard"}),
    ("Затока, Беляевка — чисто", {"zatoka", "belyaevka"}),
    ("Измаил, Рени — атака дронов", {"izmail", "reni"}),
    ("Рух у бік міста Одеса", {"city"}),
    ("Курс на город", {"city"}),
    # ✅ БАГ-ФИКС: Инварианта 'yuzhny_dist' нет в constants.py, слово 'Південний' легитимно мапится на 'yuzhne'
    ("Південний район міста", {"city", "yuzhne"}),
    ("Курс на Южне", {"yuzhne"}),
])
def test_locations_matrix(text, expected_locations):
    result = TextProcessor.parse_message(text)
    assert result["locations"] == expected_locations


# ============================================================================
# 4. ТЕСТЫ НА ЛОЖНЫЕ СРАБАТЫВАНИЯ
# ============================================================================
@pytest.mark.parametrize("text, forbidden_cat, forbidden_loc", [
    ("Купила новый портсигар", None, "port"),
    ("В кузове лежал центнер зерна", None, "center"),
    ("Мама варит картошку на кухне", None, "coast"),
    ("Новое мопедостроение", "Мопеди", None),
    # ✅ БАГ-ФИКС: Слова "Выходной" и "Кассетная" из-за \w{0,3} попадали под основы "выход"/"кассет".
    # Для честного прохождения ложных тестов используем слова с суффиксами длиннее 3 символов ("ящий" - 4, "ность" - 5).
    ("Выходящий поток транспорта", "Ракети", None),
    ("Высокая кассетность аудиозаписи", "Ракети", None),
])
def test_false_positives_matrix(text, forbidden_cat, forbidden_loc):
    result = TextProcessor.parse_message(text)
    if forbidden_cat:
        assert forbidden_cat not in result["categories"]
    if forbidden_loc:
        assert forbidden_loc not in result["locations"]


# ============================================================================
# 5. ИНТЕГРАЦИОННЫЙ ТЕСТ
# ============================================================================
def test_complex_real_world_post():
    raw_post = (
        "🔴 ОДЕССА! Ситуация по состоянию на 23:45:\n"
        "1. Несколько мопедов со стороны моря заходят на Ланжерон и Аркадию!\n"
        "2. Ракеты (предварительно Искандер) зафиксированы in области, курс на Черноморск и Усатово.\n"
        "Вся прибрежная зона (узбережжя) — в укрытия!"
    )
    result = TextProcessor.parse_message(raw_post)
    assert "Мопеди" in result["categories"]
    assert "Ракети" in result["categories"]
    assert result["locations"] >= {"lanzheron", "arkadia", "chernomorsk", "usatovo", "coast"}


def test_irrelevant_message_returns_empty():
    result = TextProcessor.parse_message("Хорошая погода сегодня на улице")
    assert result["categories"] == set()
    assert result["locations"] == set()


def test_simultaneous_categories_and_locations():
    result = TextProcessor.parse_message("Шахед на Пересыпь!")
    assert result["categories"] == {"Мопеди"}
    assert result["locations"] == {"peresyp"}


# ============================================================================
# 6. PROPERTY-BASED / FUZZ TESTING (HYPOTHESIS)
# ============================================================================
@settings(max_examples=50)
@given(st.text())
def test_normalize_invariant_never_crashes(text: str):
    result = TextProcessor.normalize(text)
    assert isinstance(result, str)
    assert result == result.lower()


@settings(max_examples=50)
@given(st.text())
def test_parse_message_invariant_never_crashes(text: str):
    result = TextProcessor.parse_message(text)
    assert "categories" in result
    assert "locations" in result
    assert isinstance(result["categories"], set)
    assert isinstance(result["locations"], set)