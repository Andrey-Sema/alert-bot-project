# Target time zones and pagination configurations
KYIV_TZ = "Europe/Kyiv"
DISLOCS_PER_PAGE = 8
MAX_CUSTOM_TRIGGERS = 5

# Odesa municipal locations mapping with root stems for suffix matching
ODESA_LOCS = {
    "city": {"emoji": "🏙️", "display": "Місто (Загально)", "patterns": ["город", "міст", "одеськ", "одес"]},
    "center": {"emoji": "⚡", "display": "Центр", "patterns": ["центр"]},
    "cheremushki": {"emoji": "🏢", "display": "Черемушки", "patterns": ["черемушк", "черьомушк"]},
    "port": {"emoji": "⚓", "display": "Порт", "patterns": ["port", "порт"]},  # Добавлен английский вариант на всякий случай
    "moldovanka": {"emoji": "🚏", "display": "Молдованка", "patterns": ["молдаванк", "молдованк", "молдовк", "молдаванц"]},
    "bugaevka": {"emoji": "🚂", "display": "Бугаєвка", "patterns": ["бугаевк", "бугаївк", "бугаївц"]},
    "slobodka": {"emoji": "🏘️", "display": "Слобідка", "patterns": ["слободк", "слобідк", "слобідц"]},
    "tairovo": {"emoji": "🌆", "display": "Таїрове", "patterns": ["таиров", "таїров"]},
    "sovignon": {"emoji": "🏖️", "display": "Совіньйон", "patterns": ["совиньон", "совіньйон"]},
    "lanzheron": {"emoji": "🌊", "display": "Ланжерон", "patterns": ["ланжерон"]},
    "kotovskogo": {"emoji": "🏚️", "display": "Селище Котовського", "patterns": ["поселок", "поскот", "котовск", "котовськ"]},
    "yuzhny_dist": {"emoji": "🌞", "display": "Південний район", "patterns": ["південн"]},
    "fontanka": {"emoji": "⛲", "display": "Фонтанка", "patterns": ["фонтанк"]},
    "peresyp": {"emoji": "🌉", "display": "Пересип", "patterns": ["пересып", "пересип"]},
    "arkadia": {"emoji": "🌴", "display": "Аркадія", "patterns": ["аркади", "аркаді"]},
    "coast": {"emoji": "🌊", "display": "Узбережжя", "patterns": ["берег", "побереж", "узбереж"]}
}

# Regional / Suburb locations mapping with root stems
OUTSIDE_LOCS = {
    "usatovo": {"emoji": "🌾", "display": "Усатове", "patterns": ["усатов"]},
    "yuzhne": {"emoji": "🌻", "display": "Южне", "patterns": ["южн", "южно"]},
    "belyaevka": {"emoji": "🌾", "display": "Біляївка", "patterns": ["беляевк", "біляївк"]},
    "ovidiopol": {"emoji": "🌅", "display": "Овідіополь", "patterns": ["овидиопол", "овідіопол"]},
    "chernomorsk": {"emoji": "⚓", "display": "Чорноморськ", "patterns": ["черноморс", "чорноморс"]},
    "chernomorka": {"emoji": "🌊", "display": "Чорноморка", "patterns": ["черноморк", "чорноморк"]},
    "novi_belyari": {"emoji": "🌳", "display": "Нові Білярі", "patterns": ["новые беляр", "нові біляр", "нові біляри"]},
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

# ✅ ВНЕДРЕНИЕ: Новые тактические синонимы и сленг с поддержкой суффиксов
KR_POTVORY = {
    "Мопеди": [
        "мопед", "дрон", "шахед", "табун", "бпла", "літачок", "атака", "шахід",
        "шлюхед",       # Матчит: шлюхед, шлюхеды, шлюхеда
        "шлюх",         # Матчит: шлюхи, шлюха, шлюху
        "турбодизел",   # Матчит: турбодизель, турбодизели
        "турбодизельн", # Матчит: турбодизельные, турбодизельный (хвост "ые"/"ый" входит в лимит \w{0,2})
        "реактивыч",    # Матчит: реактивыч, реактивычи
        "реактив",      # Матчит: реактив, реактивы
        "реактивн"      # Матчит: реактивный, реактивные, реактивного
    ],
    "Ракети": [
        "ракет", "балумба", "балістик", "балистик", "іскандер", "искандер", "касет", "кассет",
        "вихід", "выход", "пуск", "х101", "калібр", "калибр",
        "х22", "х-22",  # Ракеты Х-22 (оба варианта написания)
        "циркон",       # Циркон
        "цыркон"        # Цыркон (через "ы" от безграмотных админов)
    ]
}

ALERT_FIRST = "🚨 <b>Увага! Загроза у вашому напрямку!</b> Негайно прямуйте до укриття!"
ALERT_SECOND = "🔔 <b>[2/3] Загроза все ще актуальна!</b> Повідомлення дублюється для вашої безпеки."
ALERT_THIRD = "🔔 <b>[3/3] Будь ласка, підтвердіть отримання</b> та перебування в безпечному місці!"

ALERT_DELAY_1 = 5
ALERT_DELAY_2 = 60