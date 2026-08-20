from __future__ import annotations
__all__ = ['COOLDOWN_DEFAULTS', 'Database', 'ECONOMY_FEATURE_DEFAULTS', 'ECONOMY_FEATURE_LABELS', 'EconomyAccessLocationError', 'EventRuntimeConfig', 'GuildStateRepository', 'REWARD_DEFAULTS', 'ServerSettingsService', 'dataclass', 'eco', 'json', 'set_currency_symbol', 'timedelta']
from dataclasses import dataclass
import json
from datetime import timedelta
from app import economy_config as eco
from app.database import Database
from app.repositories.guild_state import GuildStateRepository
from app.services.server_settings import ServerSettingsService
from app.ui import set_currency_symbol
ECONOMY_FEATURE_DEFAULTS: dict[str, bool] = {'economy': True, 'daily': True, 'weekly': True, 'monthly': True, 'work': True, 'crime': True, 'search': True, 'beg': True, 'rob': True, 'slut': True, 'bank': True, 'interest': True, 'gambling': True}
COOLDOWN_DEFAULTS: dict[str, timedelta] = {'daily': eco.DAILY_COOLDOWN, 'weekly': eco.WEEKLY_COOLDOWN, 'monthly': eco.MONTHLY_COOLDOWN, 'work': eco.WORK_COOLDOWN, 'crime': eco.CRIME_COOLDOWN, 'search': eco.SEARCH_COOLDOWN, 'beg': eco.BEG_COOLDOWN, 'rob': eco.ROB_COOLDOWN, 'slut': eco.SLUT_COOLDOWN, 'interest': eco.INTEREST_COOLDOWN}
REWARD_DEFAULTS: dict[str, tuple[int, int]] = {'weekly': eco.WEEKLY_REWARD, 'work': eco.WORK_REWARD, 'crime_reward': eco.CRIME_REWARD, 'crime_fine': eco.CRIME_FINE, 'slut_reward': eco.SLUT_REWARD, 'slut_fine': eco.SLUT_FINE}
ECONOMY_FEATURE_LABELS: dict[str, str] = {'economy': 'Gazdaság', 'daily': 'Napi lehetőség', 'weekly': 'Heti összegzés', 'monthly': 'Havi kiemelés', 'work': 'Alkalmi munka', 'crime': 'Bűnözés', 'search': 'Keresés', 'beg': 'Kéregetés', 'rob': 'Rablás', 'slut': 'Utcai lehetőség', 'bank': 'Bank', 'interest': 'Automatikus kamat', 'gambling': 'Kaszinó'}

class EconomyAccessLocationError(ValueError):
    """The economy feature is enabled, but this channel/category is not allowed."""

@dataclass(frozen=True, slots=True)
class EventRuntimeConfig:
    auto_enabled: bool
    safe_enabled: bool
    bomb_enabled: bool
    manual_enabled: bool
    channel_id: int | None
    min_hours: float
    max_hours: float
    join_seconds: int
    safe_min_reward: int
    safe_max_reward: int
    bomb_min_entry: int
    bomb_max_entry: int
    bomb_round_seconds: int
    activity_messages: int
    activity_window_minutes: int
    activity_min_users: int
    activity_user_cooldown_seconds: int
    safe_chance: float
