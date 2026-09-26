import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from alert_bot_project.core_shared.constants import KR_POTVORY, ODESA_LOCS, OUTSIDE_LOCS

CLEAN_PATTERN = re.compile(r"[^\w\s-]")
CLEAR_PATTERN = re.compile(r"\b(?:відбій|отбой|тривогу скасовано|тревога отменена)\b", re.IGNORECASE)
NEGATION_PATTERN = re.compile(
    r"\b(?:не\s+(?:виявлено|зафіксовано|підтверджено|обнаружено|зафиксировано)|"
    r"нет\s+(?:угрозы|ракет|бпла)|загрози\s+немає)\b",
    re.IGNORECASE,
)
RESOLVED_PATTERN = re.compile(r"\b(?:минул\w*|більше\s+не|больше\s+не|чисто)\b", re.IGNORECASE)
CLAUSE_SPLIT_PATTERN = re.compile(r"[,.;!?\n]+|\b(?:але|однак|но)\b", re.IGNORECASE)


def _compile_word_boundary_pattern(keywords: Iterable[str]) -> re.Pattern[str]:
    """Складає та прекомпілює регулярний вираз із межами слів для захисту від помилкових спрацьовувань."""
    escaped_words = "|".join(re.escape(word) for word in keywords)
    # ✅ ФИКС: Увеличен лимит суффикса до \w{0,3} для гибкого захвата падежей и окончаний
    return re.compile(rf"(?<![\w])({escaped_words})\w{{0,3}}(?![\w])")


COMPILED_CATEGORIES = {category: _compile_word_boundary_pattern(keywords) for category, keywords in KR_POTVORY.items()}

COMPILED_LOCATIONS = {
    loc_key: _compile_word_boundary_pattern(data["patterns"])
    for loc_key, data in {**ODESA_LOCS, **OUTSIDE_LOCS}.items()
}


@dataclass(frozen=True)
class SignalAnalysis:
    status: str
    positive_text: str
    clear_locations: frozenset[str]
    global_clear: bool


class TextProcessor:
    @classmethod
    def analyze_signal(cls, raw_text: str) -> SignalAnalysis:
        """Keep clear, negated and actionable clauses separate for routing."""
        clear_locations: set[str] = set()
        global_clear = False
        saw_negation = False
        saw_active = False
        positive_clauses: list[str] = []
        for raw_clause in CLAUSE_SPLIT_PATTERN.split(raw_text):
            clause = cls.normalize(raw_clause)
            if not clause:
                continue
            if CLEAR_PATTERN.search(clause) or RESOLVED_PATTERN.search(clause):
                locations = cls.parse_message(raw_clause)["locations"]
                if locations:
                    clear_locations.update(locations)
                else:
                    global_clear = True
                continue
            if NEGATION_PATTERN.search(clause):
                saw_negation = True
                continue
            positive_clauses.append(raw_clause)
            if any(pattern.search(clause) for pattern in COMPILED_CATEGORIES.values()):
                saw_active = True
        if saw_active:
            status = "active"
        elif global_clear or clear_locations:
            status = "clear"
        elif saw_negation:
            status = "negated"
        else:
            status = "unknown"
        return SignalAnalysis(status, " ".join(positive_clauses), frozenset(clear_locations), global_clear)

    @classmethod
    def classify_status(cls, raw_text: str) -> str:
        return cls.analyze_signal(raw_text).status

    @staticmethod
    def normalize(text: str) -> str:
        """Очищає текст від спецсимволів, зводить до нижнього регістру та прибирає зайві пробіли."""
        if not text:
            return ""
        return CLEAN_PATTERN.sub("", text.lower()).strip()

    @classmethod
    def parse_message(cls, raw_text: str) -> dict[str, Any]:
        """Аналізує повідомлення на наявність категорій загроз та збігів із тригерними локаціями."""
        normalized_text = cls.normalize(raw_text)
        matched_categories: set[str] = set()
        matched_locations: set[str] = set()

        if not normalized_text:
            return {"categories": matched_categories, "locations": matched_locations}

        for cat_name, pattern in COMPILED_CATEGORIES.items():
            if pattern.search(normalized_text):
                matched_categories.add(cat_name)

        for loc_key, pattern in COMPILED_LOCATIONS.items():
            if pattern.search(normalized_text):
                matched_locations.add(loc_key)

        return {"categories": matched_categories, "locations": matched_locations}
