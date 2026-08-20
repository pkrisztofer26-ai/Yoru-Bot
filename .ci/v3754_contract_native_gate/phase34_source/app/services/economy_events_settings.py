from __future__ import annotations
from .economy_events_settings_projection_support import *
from .economy_events_settings_projection_mixin_01 import EconomyEventsSettingsServiceProjectionMixin01
from .economy_events_settings_projection_mixin_02 import EconomyEventsSettingsServiceProjectionMixin02

class EconomyEventsSettingsService(EconomyEventsSettingsServiceProjectionMixin01, EconomyEventsSettingsServiceProjectionMixin02):
    """Per-guild Economy + Events configuration using the existing guild_state table.

    No schema migration is required; missing keys always fall back to Yoru's
    existing v3.10.1 balance/config values so upgrading does not change behaviour.
    """
    ECONOMY_CHANNELS_KEY = 'economy_allowed_channel_ids'
    ECONOMY_CATEGORIES_KEY = 'economy_allowed_category_ids'
