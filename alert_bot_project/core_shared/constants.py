# Target time zones and pagination configurations
KYIV_TZ = "Europe/Kyiv"
DISLOCS_PER_PAGE = 8
MAX_CUSTOM_TRIGGERS = 5

# Odesa municipal locations mapping with bilingual regex patterns
ODESA_LOCS = {
    "city": {"emoji": "🏙️", "display": "Місто (Загально)", "patterns": ["город", "місто", "одеса", "одесі"]},
    "center": {"emoji": "⚡", "display": "Центр", "patterns": ["центр"]},
    "cheremushki": {"emoji": "🏢", "display": "Черемушки", "patterns": ["черемушки", "черьомушки"]},
    "port": {"emoji": "⚓", "display": "Порт", "patterns": ["порт"]},
    "moldovanka": {"emoji": "🚏", "display": "Молдованка", "patterns": ["молдаванка", "молдовка", "молдаванці"]},
    "bugaevka": {"emoji": "🚂", "display": "Бугаєвка", "patterns": ["бугаевка", "бугаївка", "бугаївці"]},
    "slobodka": {"emoji": "🏘️", "display": "Слобідка", "patterns": ["слободка", "слобідка", "слобідці"]},
    "tairovo": {"emoji": "🌆", "display": "Таїрове", "patterns": ["таирово", "таїров"]},
    "sovignon": {"emoji": "🏖️", "display": "Совіньйон", "patterns": ["совиньон", "совіньйон"]},
    "lanzheron": {"emoji": "🌊", "display": "Ланжерон", "patterns": ["ланжерон"]},
    "kotovskogo": {"emoji": "🏚️", "display": "Селище Котовського", "patterns": ["поселок", "поскот", "котовского", "котовського"]},
    "yuzhny_dist": {"emoji": "🌞", "display": "Південний район", "patterns": ["южный", "південний"]},
    "fontanka": {"emoji": "⛲", "display": "Фонтанка", "patterns": ["фонтанка"]},
    "peresyp": {"emoji": "🌉", "display": "Пересип", "patterns": ["пересыпь", "пересип"]},
    "arkadia": {"emoji": "🌴", "display": "Аркадія", "patterns": ["аркадия", "аркадія"]},
    "coast": {"emoji": "🌊", "display": "Узбережжя", "patterns": ["берег", "побережье", "узбережжя"]}
}

# Regional / Suburb locations mapping with bilingual regex patterns
OUTSIDE_LOCS = {
    "usatovo": {"emoji": "🌾", "display": "Усатове", "patterns": ["усатово", "усатове"]},
    "yuzhne": {"emoji": "🌻", "display": "Южне", "patterns": ["южное", "южне", "южного"]},
    "belyaevka": {"emoji": "🌾", "display": "Біляївка", "patterns": ["беляевк", "біляївк"]},
    "ovidiopol": {"emoji": "🌅", "display": "Овідіополь", "patterns": ["овидиополь", "овідіополь"]},
    "chernomorsk": {"emoji": "⚓", "display": "Чорноморськ", "patterns": ["черноморс", "чорноморськ"]},
    "chernomorka": {"emoji": "🌊", "display": "Чорноморка", "patterns": ["черноморк", "чорноморка"]},
    "novi_belyari": {"emoji": "🌳", "display": "Нові Білярі", "patterns": ["новые беляр", "ніві біляр", "нові біляр"]},
    "reni": {"emoji": "🛳️", "display": "Рені", "patterns": ["рени", "рені"]},
    "izmail": {"emoji": "🚢", "display": "Ізмаїл", "patterns": ["измаил", "ізмаїл"]},
    "tatarbunary": {"emoji": "🏞️", "display": "Татарбунари", "patterns": ["татарбунар"]},
    "berezovka": {"emoji": "🌳", "display": "Березівка", "patterns": ["березовк", "березівк"]},
    "vilkovo": {"emoji": "🚤", "display": "Вилкове", "patterns": ["вилково", "вилкове"]},
    "avangard": {"emoji": "🎯", "display": "Авангард", "patterns": ["авангард"]},
    "limanka": {"emoji": "🏞️", "display": "Лиманка", "patterns": ["лиманк"]},
    "zatoka": {"emoji": "🏖️", "display": "Затока", "patterns": ["заток"]},
    "belgorod": {"emoji": "🏰", "display": "Білгород-Дністровський", "patterns": ["белгород", "білгород"]},
    "teplodar": {"emoji": "🔥", "display": "Теплодар", "patterns": ["теплодар"]},
    "dobroslav": {"emoji": "🌄", "display": "Доброслав", "patterns": ["доброслав"]},
    "tuzly": {"emoji": "🌊", "display": "Тузли", "patterns": ["тузлы", "тузли"]}
}

# Threat classifications mapped to multi-language structural lexical tokens
KR_POTVORY = {
    "Мопеди": [
        "мопед", "дрон", "шахед", "табун", "бпла", "літачок", "атака", "шахід"
    ],
    "Ракети": [
        "ракета", "балумба", "балістика", "балистика", "іскандер", "искандер", "касета", "кассета", "вихід", "выход", "пуск", "х101", "калібр", "калибр"
    ]
}

# Notification structural text templates (Clean Ukrainian UI)
ALERT_FIRST = "🚨 <b>Увага! Загроза у вашому напрямку!</b> Негайно прямуйте до укриття!"
ALERT_SECOND = "🔔 <b>[2/3] Загроза все ще актуальна!</b> Повідомлення дублюється для вашої безпеки."
ALERT_THIRD = "🔔 <b>[3/3] Будь ласка, підтвердіть отримання</b> та перебування в безпечному місці!"

# Notification step delay configuration (seconds)
ALERT_DELAY_1 = 5
ALERT_DELAY_2 = 60