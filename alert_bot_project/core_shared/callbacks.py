from typing import Optional
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.state import StatesGroup, State


class CustomTriggerStates(StatesGroup):
    """
    Група станів кінцевого автомату (FSM) для керування кастомними тригерами користувача.
    """
    waiting_for_keyword = State()  # Очікування введення назви кастомної локації від користувача


class GroupNavCallback(CallbackData, prefix="nav_group"):
    """
    Фабрика колбэків для навігації між регіональними групами дислокацій та пагінації.

    Attributes:
        group (str): Ідентифікатор групи (наприклад, "odesa" або "outside").
        page (int): Поточний номер сторінки для відображення списку.
    """
    group: str
    page: int


class LocationToggleCallback(CallbackData, prefix="loc_toggle"):
    """
    Фабрика колбэків для увімкнення/вимкнення конкретної географічної зони моніторингу.

    Attributes:
        group (str): Регіональна група, до якої належить локація.
        location_key (str): Внутрішній інваріантний ключ зони (наприклад, "cheremushki", "port").
        page (int): Поточна сторінка пагінації, на якій знаходиться користувач.
    """
    group: str
    location_key: str  # ✅ ФИКС: Перейменовано з inv_key для забезпечення зрозумілої семантики
    page: int


class ThreatCategoryCallback(CallbackData, prefix="cat_toggle"):
    """
    Фабрика колбэків для перемикання типів повітряних загроз (Ракети / Мопеди).

    Attributes:
        category (str): Назва категорії загрози з внутрішнього довідника KR_POTVORY.
    """
    category: str


class MutePresetCallback(CallbackData, prefix="mute_set"):
    """
    Фабрика колбэків для активації пресетів режиму тиші (MUTE).

    Attributes:
        preset (str): Строковий ідентифікатор пресету ("1", "2", "4", "morning", "clear").
    """
    preset: str


class CustomActionCallback(CallbackData, prefix="custom_act"):
    """
    Фабрика колбэків для індивідуальних дій з кастомними фразами користувача (наприклад, видалення).

    Attributes:
        action (str): Тип дії, що виконується (наприклад, "delete").
        phrase (Optional[str]): Текст кастомної фрази, якщо дія виконується над конкретним об'єктом.
    """
    action: str
    phrase: Optional[str] = None