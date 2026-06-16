# Target time zones and pagination configurations
KYIV_TZ = "Europe/Kyiv"
DISLOCS_PER_PAGE = 8
MAX_CUSTOM_TRIGGERS = 5

# Odesa municipal locations mapping with root stems for suffix matching
ODESA_LOCS = {
    "city": {"emoji": "🏙️", "display": "Місто (Загально)", "patterns": ["город", "міст", "одеськ", "одес"]},
    "center": {"emoji": "⚡", "display": "Центр", "patterns": ["центр"]},
    "cheremushki": {"emoji": "🏢", "display": "Черемушки", "patterns": ["черемушк", "черьомушк"]},
    "port": {"emoji": "⚓", "display": "Порт", "patterns": ["порт"]},
    "moldovanka": {"emoji": "🚏", "display": "Молдованка", "patterns": ["молдаванк", "молдовк", "молдаванц"]},
    "bugaevka": {"emoji": "🚂", "display": "Бугаєвка", "patterns": ["бугаевк", "бугаївк", "бугаївц"]},
    "slobodka": {"emoji": "🏘️", "display": "Слобідка", "patterns": ["слободк", "слобідк", "слобідц"]},
    "tairovo": {"emoji": "🌆", "display": "Таїрове", "patterns": ["таиров", "таїров"]},
    "sovignon": {"emoji": "🏖️", "display": "Совіньйон", "patterns": ["совиньон", "совіньйон"]},
    "lanzheron": {"emoji": "🌊", "display": "Ланжерон", "patterns": ["ланжерон"]},
    "kotovskogo": {"emoji": "🏚️", "display": "Селище Котовського", "patterns": ["поселок", "поскот", "котовск", "котовськ"]},
    "yuzhny_dist": {"emoji": "🌞", "display": "Південний район", "patterns": ["південн"]}, # Убрали 'южн', чтобы не путать с г. Южне
    "fontanka": {"emoji": "⛲", "display": "Фонтанка", "patterns": ["фонтанк"]},
    "peresyp": {"emoji": "🌉", "display": "Пересип", "patterns": ["пересып", "пересип"]},
    "arkadia": {"emoji": "🌴", "display": "Аркадія", "patterns": ["аркади", "аркаді"]},
    "coast": {"emoji": "🌊", "display": "Узбережжя", "patterns": ["берег", "побереж", "узбереж"]}
}

# Regional / Suburb locations mapping with root stems
OUTSIDE_LOCS = {
    "usatovo": {"emoji": "🌾", "display": "Усатове", "patterns": ["усатов"]},
    "yuzhne": {"emoji": "🌻", "display": "Южне", "patterns": ["южн"]}, # Оставили 'южн' только здесь
    "belyaevka": {"emoji": "🌾", "display": "Біляївка", "patterns": ["беляевк", "біляївк"]},
    "ovidiopol": {"emoji": "🌅", "display": "Овідіополь", "patterns": ["овидиопол", "овідіопол"]},
    "chernomorsk": {"emoji": "⚓", "display": "Чорноморськ", "patterns": ["черноморс", "чорноморс"]},
    "chernomorka": {"emoji": "🌊", "display": "Чорноморка", "patterns": ["черноморк", "чорноморк"]},
    "novi_belyari": {"emoji": "🌳", "display": "Нові Білярі", "patterns": ["новые беляр", "нові біляр", "нові біляр"]},
    "reni": {"emoji": "🛳️", "display": "Рені", "patterns": ["рен"]},
    "izmail": {"emoji": "🚢", "display": "Ізмаїл", "patterns": ["измаил", "ізмаїл"]},
    "tatarbunary": {"emoji": "🏞️", "display": "Татарбунари", "patterns": ["татарбунар"]},
    "berezovka": {"emoji": "🌳", "display": "Березівка", "patterns": ["березовк", "березівк"]},
    "vilkovo": {"emoji": "🚤", "display": "Вилкове", "patterns": ["вилков"]},
    "avangard": {"emoji": "🎯", "display": "Авангард", "patterns": ["авангард"]},
    "limanka": {"emoji": "🏞️", "display": "Лиманка", "patterns": ["лиманк"]},
    "zatoka": {"emoji": "🏖️", "display": "Затока", "patterns": ["заток"]},
    "belgorod": {"emoji": "🏰", "display": "Білгород-Дністровський", "patterns": ["белгород", "білгород"]},
    "teplodar": {"emoji": "🔥", "display": "Теплодар", "patterns": ["теплодар"]},
    "dobroslav": {"emoji": "🌄", "display": "Доброслав", "patterns": ["доброслав"]},
    "tuzly": {"emoji": "🌊", "display": "Тузли", "patterns": ["тузл"]}
}

KR_POTVORY = {
    "Мопеди": ["мопед", "дрон", "шахед", "табун", "бпла", "літачок", "атака", "шахід"],
    "Ракети": ["ракета", "балумба", "балістик", "балистик", "іскандер", "искандер", "касет", "кассет", "вихід", "выход", "пуск", "х101", "калібр", "калибр"]
}

ALERT_FIRST = "🚨 <b>Увага! Загроза у вашому напрямку!</b> Негайно прямуйте до укриття!"
ALERT_SECOND = "🔔 <b>[2/3] Загроза все ще актуальна!</b> Повідомлення дублюється для вашої безпеки."
ALERT_THIRD = "🔔 <b>[3/3] Будь ласка, підтвердіть отримання</b> та перебування в безпечному місці!"

ALERT_DELAY_1 = 5
ALERT_DELAY_2 = 60