from typing import Optional
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.state import StatesGroup, State


class CustomTriggerStates(StatesGroup):
    """FSM states tracking custom phrase user registration flows."""
    waiting_for_keyword = State()


class GroupNavCallback(CallbackData, prefix="nav_group"):
    group: str
    page: int


class LocationToggleCallback(CallbackData, prefix="loc_toggle"):
    group: str
    inv_key: str
    page: int


class ThreatCategoryCallback(CallbackData, prefix="cat_toggle"):
    category: str


class MutePresetCallback(CallbackData, prefix="mute_set"):
    preset: str


class CustomActionCallback(CallbackData, prefix="custom_act"):
    action: str
    phrase: Optional[str] = None