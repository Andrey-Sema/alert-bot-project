import re
from typing import Set, Dict, Any
from alert_bot_project.core_shared.constants import ODESA_LOCS, OUTSIDE_LOCS, KR_POTVORY

CLEAN_PATTERN = re.compile(r"[^\w\s-]")

# Изменили \w{0,5} на \w{0,2}. Теперь ложных захватов не будет.
COMPILED_CATEGORIES = {
    category: re.compile(rf"(?<![\w])({'|'.join(re.escape(word) for word in keywords)})\w{{0,2}}(?![\w])")
    for category, keywords in KR_POTVORY.items()
}

COMPILED_LOCATIONS = {
    loc_key: re.compile(rf"(?<![\w])({'|'.join(re.escape(p) for p in data['patterns'])})\w{{0,2}}(?![\w])")
    for loc_key, data in {**ODESA_LOCS, **OUTSIDE_LOCS}.items()
}


class TextProcessor:
    @staticmethod
    def normalize(text: str) -> str:
        if not text:
            return ""
        return CLEAN_PATTERN.sub("", text.lower())

    @classmethod
    def parse_message(cls, raw_text: str) -> Dict[str, Any]:
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