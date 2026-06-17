import re
from typing import Set, Dict, Any, Iterable
from alert_bot_project.core_shared.constants import ODESA_LOCS, OUTSIDE_LOCS, KR_POTVORY

CLEAN_PATTERN = re.compile(r"[^\w\s-]")


def _compile_word_boundary_pattern(keywords: Iterable[str]) -> re.Pattern:
    """Складає та прекомпілює регулярний вираз із межами слів для захисту від помилкових спрацьовувань."""
    escaped_words = "|".join(re.escape(word) for word in keywords)
    # ✅ ФИКС: Увеличен лимит суффикса до \w{0,3} для гибкого захвата падежей и окончаний
    return re.compile(rf"(?<![\w])({escaped_words})\w{{0,3}}(?![\w])")


COMPILED_CATEGORIES = {
    category: _compile_word_boundary_pattern(keywords)
    for category, keywords in KR_POTVORY.items()
}

COMPILED_LOCATIONS = {
    loc_key: _compile_word_boundary_pattern(data['patterns'])
    for loc_key, data in {**ODESA_LOCS, **OUTSIDE_LOCS}.items()
}


class TextProcessor:
    @staticmethod
    def normalize(text: str) -> str:
        """Очищає текст від спецсимволів, зводить до нижнього регістру та прибирає зайві пробіли."""
        if not text:
            return ""
        return CLEAN_PATTERN.sub("", text.lower()).strip()

    @classmethod
    def parse_message(cls, raw_text: str) -> Dict[str, Any]:
        """Аналізує повідомлення на наявність категорій загроз та збігів із тригерними локаціями."""
        normalized_text = cls.normalize(raw_text)
        matched_categories: Set[str] = set()
        matched_locations: Set[str] = set()

        if not normalized_text:
            return {"categories": matched_categories, "locations": matched_locations}

        for cat_name, pattern in COMPILED_CATEGORIES.items():
            if pattern.search(normalized_text):
                matched_categories.add(cat_name)

        for loc_key, pattern in COMPILED_LOCATIONS.items():
            if pattern.search(normalized_text):
                matched_locations.add(loc_key)

        return {
            "categories": matched_categories,
            "locations": matched_locations
        }