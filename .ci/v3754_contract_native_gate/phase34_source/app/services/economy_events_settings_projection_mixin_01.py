from __future__ import annotations
from .economy_events_settings_projection_support import *

class EconomyEventsSettingsServiceProjectionMixin01:

    def __init__(self, db: Database) -> None:
        self.db = db
        self.guild_state_repository = GuildStateRepository(db.path)
        self.state = ServerSettingsService(db)

    async def _get_int_default(self, guild_id: int, key: str, default: int) -> int:
        value = await self.state.get_int(guild_id, key)
        return int(default if value is None else value)

    async def _get_float_default(self, guild_id: int, key: str, default: float) -> float:
        raw = await self.guild_state_repository.get(guild_id, key)
        if raw is None or not str(raw).strip():
            return float(default)
        try:
            return float(raw)
        except (TypeError, ValueError):
            return float(default)

    async def _set_float(self, guild_id: int, key: str, value: float) -> None:
        await self.guild_state_repository.set(guild_id, key, f'{float(value):g}')

    async def get_economy_enabled(self, guild_id: int) -> bool:
        return await self.state.get_bool(guild_id, 'economy_enabled', True)

    async def set_economy_enabled(self, guild_id: int, enabled: bool) -> None:
        await self.state.set_bool(guild_id, 'economy_enabled', enabled)

    async def require_feature(self, guild_id: int, feature: str) -> None:
        """Validate economy + feature availability with one batched state read.

        This path is used by gamble-room commands that intentionally bypass the
        configured economy channel allowlist. Keeping it batched avoids two
        sequential DB reads on a cold guild-state cache.
        """
        if feature not in ECONOMY_FEATURE_DEFAULTS:
            raise ValueError(f'Ismeretlen economy feature: {feature}')
        keys = ['economy_enabled', 'economy_currency_symbol']
        feature_key = f'economy_feature_{feature}'
        if feature != 'economy':
            keys.append(feature_key)
        values = await self.guild_state_repository.get_many(guild_id, keys)
        currency_raw = values.get('economy_currency_symbol')
        set_currency_symbol((currency_raw or '$').strip()[:12] or '$')
        economy_raw = values.get('economy_enabled')
        economy_enabled = True if economy_raw is None or not economy_raw.strip() else economy_raw == '1'
        if not economy_enabled:
            raise ValueError('A szerver economy rendszere jelenleg ki van kapcsolva.')
        if feature != 'economy':
            raw = values.get(feature_key)
            default = ECONOMY_FEATURE_DEFAULTS[feature]
            enabled = default if raw is None or not raw.strip() else raw == '1'
            if not enabled:
                label = ECONOMY_FEATURE_LABELS.get(feature, feature)
                raise ValueError(f'Ez a funkció jelenleg ki van kapcsolva a szerveren: **{label}**.')

    async def require_access(self, guild_id: int, feature: str, channel_id: int | None, category_id: int | None=None) -> None:
        """Validate feature + channel access from one batched guild-state read.

        Economy commands are among Yoru's hottest slash/prefix paths. The old
        guard performed several sequential guild_state round trips on a cold
        cache. This preserves the exact defaults/errors while fetching the
        complete access policy in one repository call.
        """
        if feature not in ECONOMY_FEATURE_DEFAULTS:
            raise ValueError(f'Ismeretlen economy feature: {feature}')
        feature_key = f'economy_feature_{feature}'
        keys = ['economy_enabled', 'economy_currency_symbol', self.ECONOMY_CHANNELS_KEY, self.ECONOMY_CATEGORIES_KEY, 'economy_channel_id']
        if feature != 'economy':
            keys.append(feature_key)
        values = await self.guild_state_repository.get_many(guild_id, keys)
        currency_raw = values.get('economy_currency_symbol')
        set_currency_symbol((currency_raw or '$').strip()[:12] or '$')
        economy_raw = values.get('economy_enabled')
        economy_enabled = True if economy_raw is None or not economy_raw.strip() else economy_raw == '1'
        if not economy_enabled:
            raise ValueError('A szerver economy rendszere jelenleg ki van kapcsolva.')
        if feature != 'economy':
            raw = values.get(feature_key)
            default = ECONOMY_FEATURE_DEFAULTS[feature]
            enabled = default if raw is None or not raw.strip() else raw == '1'
            if not enabled:
                label = ECONOMY_FEATURE_LABELS.get(feature, feature)
                raise ValueError(f'Ez a funkció jelenleg ki van kapcsolva a szerveren: **{label}**.')

        def decode_ids(raw: str | None) -> list[int]:
            if raw is None or not raw.strip():
                return []
            try:
                data = json.loads(raw)
            except (TypeError, ValueError, json.JSONDecodeError):
                return []
            return self._clean_id_list(data if isinstance(data, list) else [])
        if self.ECONOMY_CHANNELS_KEY in values:
            channels = decode_ids(values.get(self.ECONOMY_CHANNELS_KEY))
        else:
            legacy_raw = values.get('economy_channel_id')
            try:
                legacy = int(legacy_raw) if legacy_raw and legacy_raw.strip() else 0
            except ValueError:
                legacy = 0
            channels = [legacy] if legacy > 0 else []
        categories = decode_ids(values.get(self.ECONOMY_CATEGORIES_KEY)) if self.ECONOMY_CATEGORIES_KEY in values else []
        if not channels and (not categories):
            return
        if channel_id is not None and int(channel_id) in channels:
            return
        if category_id is not None and int(category_id) in categories:
            return
        allowed = [*(f'<#{cid}>' for cid in channels), *(f'<#{cid}> (kategória)' for cid in categories)]
        where = ', '.join(allowed[:12])
        if len(allowed) > 12:
            where += f' +{len(allowed) - 12} további'
        raise EconomyAccessLocationError(f'A gazdasági parancsokat csak az engedélyezett helyeken használhatod: {where}')

    @staticmethod
    def _clean_id_list(values: list) -> list[int]:
        cleaned: list[int] = []
        for raw in values:
            try:
                value = int(raw)
            except (TypeError, ValueError):
                continue
            if value > 0 and value not in cleaned:
                cleaned.append(value)
        return cleaned[:100]

    async def get_economy_channel_ids(self, guild_id: int) -> list[int]:
        """Return the allowlisted economy channels.

        v3.11.0 only stored a single ``economy_channel_id``. If the new list has
        never been configured, transparently expose that legacy channel as the
        first allowlisted channel. An explicitly stored empty list means
        unrestricted usage and does not fall back to the old key.
        """
        raw = await self.guild_state_repository.get(guild_id, self.ECONOMY_CHANNELS_KEY)
        if raw is not None and raw.strip():
            return self._clean_id_list(await self.state.get_list(guild_id, self.ECONOMY_CHANNELS_KEY))
        if raw is not None:
            return []
        legacy = await self.state.get_int(guild_id, 'economy_channel_id')
        return [legacy] if legacy else []

    async def get_economy_category_ids(self, guild_id: int) -> list[int]:
        raw = await self.guild_state_repository.get(guild_id, self.ECONOMY_CATEGORIES_KEY)
        if raw is None:
            return []
        return self._clean_id_list(await self.state.get_list(guild_id, self.ECONOMY_CATEGORIES_KEY))

    async def set_economy_channel_ids(self, guild_id: int, channel_ids: list[int]) -> None:
        values = self._clean_id_list(channel_ids)
        await self.state.set_list(guild_id, self.ECONOMY_CHANNELS_KEY, values)
        await self.state.set_int(guild_id, 'economy_channel_id', values[0] if values else None)

    async def set_economy_category_ids(self, guild_id: int, category_ids: list[int]) -> None:
        await self.state.set_list(guild_id, self.ECONOMY_CATEGORIES_KEY, self._clean_id_list(category_ids))

    async def clear_economy_locations(self, guild_id: int) -> None:
        await self.set_economy_channel_ids(guild_id, [])
        await self.set_economy_category_ids(guild_id, [])

    async def prepare_currency(self, guild_id: int) -> str:
        symbol = await self.get_currency_symbol(guild_id)
        set_currency_symbol(symbol)
        return symbol

    async def get_currency_symbol(self, guild_id: int) -> str:
        value = (await self.state.get_text(guild_id, 'economy_currency_symbol', '$')).strip()
        return value[:12] or '$'

    async def get_cooldown(self, guild_id: int, feature: str) -> timedelta:
        if feature not in COOLDOWN_DEFAULTS:
            raise ValueError(f'Ismeretlen várakozási idő: {feature}')
        default_seconds = max(1, int(COOLDOWN_DEFAULTS[feature].total_seconds()))
        seconds = await self._get_int_default(guild_id, f'economy_cooldown_{feature}_seconds', default_seconds)
        return timedelta(seconds=max(1, min(seconds, 365 * 24 * 3600)))

    async def set_cooldown_seconds(self, guild_id: int, feature: str, seconds: int | None) -> None:
        if feature not in COOLDOWN_DEFAULTS:
            raise ValueError(f'Ismeretlen várakozási idő: {feature}')
        if seconds is None:
            await self.state.set_int(guild_id, f'economy_cooldown_{feature}_seconds', None)
            return
        if seconds < 1 or seconds > 365 * 24 * 3600:
            raise ValueError('A várakozási idő 1 másodperc és 365 nap között lehet.')
        await self.state.set_int(guild_id, f'economy_cooldown_{feature}_seconds', int(seconds))

    async def reset_all_cooldowns(self, guild_id: int) -> None:
        for feature in COOLDOWN_DEFAULTS:
            await self.set_cooldown_seconds(guild_id, feature, None)

    async def get_reward_range(self, guild_id: int, key: str) -> tuple[int, int]:
        if key not in REWARD_DEFAULTS:
            raise ValueError(f'Ismeretlen jutalomtartomány: {key}')
        default_min, default_max = REWARD_DEFAULTS[key]
        minimum = await self._get_int_default(guild_id, f'economy_reward_{key}_min', default_min)
        maximum = await self._get_int_default(guild_id, f'economy_reward_{key}_max', default_max)
        if minimum < 0 or maximum < minimum:
            return (default_min, default_max)
        return (minimum, maximum)
