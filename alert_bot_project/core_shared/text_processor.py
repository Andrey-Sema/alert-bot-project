import re
from typing import Set, Dict, Any
from alert_bot_project.core_shared.constants import ODESA_LOCS, OUTSIDE_LOCS, KR_POTVORY

CLEAN_PATTERN = re.compile(r"[^\w\s-]")

# Precompile integrated lookup regex strings for multi-language category tracking
COMPILED_CATEGORIES = {
    category: re.compile(rf"(?<![\w])({'|'.join(re.escape(word) for word in keywords)})(?![\w])")
    for category, keywords in KR_POTVORY.items()
}

# Precompile and map bilingual text patterns directly to invariant database location keys
COMPILED_LOCATIONS = {
    loc_key: re.compile(rf"(?<![\w])({'|'.join(re.escape(p) for p in data['patterns'])})(?![\w])")
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
        """
        Parses incoming text feeds against combined Russian and Ukrainian patterns,
        returning static invariant tracking keys to downstream services.
        """
        normalized_text = cls.normalize(raw_text)
        matched_categories: Set[str] = set()
        matched_locations: Set[str] = set()

        if not normalized_text:
            return {"categories": matched_categories, "locations": matched_locations}

        # Scan text against compiled category rules
        for cat_name, pattern in COMPILED_CATEGORIES.items():
            if pattern.search(normalized_text):
                matched_categories.add(cat_name)

        # Scan text against bilingual location variations mapped to exact invariant keys
        for loc_key, pattern in COMPILED_LOCATIONS.items():
            if pattern.search(normalized_text):
                matched_locations.add(loc_key)

        return {
            "categories": matched_categories,
            "locations": matched_locations
        }