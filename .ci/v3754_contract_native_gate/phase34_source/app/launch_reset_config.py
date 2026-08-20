from __future__ import annotations

"""Canonical launch-reset manifest for Yoru.

The manifest is intentionally explicit.  A destructive launch reset must never
silently start deleting a newly introduced table just because it happens to have
``guild_id``.  New persistent tables must be classified as RESET or PRESERVE and
release QA fails when the runtime schema contains an unclassified Yoru table.
"""

RESET_CONFIRM_PHRASE = "VEGLEGES INDULASI RESET"
BACKUP_DIR = "backups/launch_reset"
BACKUP_LATEST_KEY = "launch_reset_latest_backup"
LAST_RUN_KEY = "launch_reset_last_run"

# Tables whose rows are gameplay/test progression and are reset for the target guild.
# Child-only tables without guild_id are handled separately by the service.
RESET_GUILD_TABLES: tuple[str, ...] = (
    # transient anti-farm/game runtime
    "activity_message_hashes",
    # betting / casino / live games
    "betting_draft_legs",
    "horse_bets",
    "live_game_sessions",
    "casino_ledger",
    "casino_sessions",
    "casino_monthly_user_contrib",
    "casino_monthly_jackpot",
    "casino_jackpot_history",
    "lottery_entries",
    "lottery_history",
    "market_daily",
    "player_market_trades",
    "player_market_listings",
    "pvp_duels",
    "player_notifications",
    # unified contract economy (children before parent)
    "contract_event_claims",
    "contract_telemetry",
    "business_delivery_history",
    "contract_source_state",
    "contract_reward_budgets",
    "contract_history",
    "contract_events",
    "contract_objectives",
    "item_transfer_history",
    "contracts",
    # business
    "business_transactions",
    "business_offers",
    "business_workers",
    "business_licenses",
    # heist
    "heist_vehicle_choices",
    "heist_runs",
    "heist_lobby_members",
    "heist_lobbies",
    "heist_gear",
    "heist_cooldowns",
    # organizations
    "crew_member_custom_ranks",
    "crew_custom_ranks",
    "crew_perks",
    "crew_invites",
    "crew_members",
    "crew_wars",
    "crews",
    # scenario engine / jobs / career economy layer
    "player_scenario_history",
    "scenario_runs",
    "scenario_shuffle_bags",
    "job_sessions",
    "job_mastery",
    "job_history",
    # housing / vehicles / training / career / character
    "housing_garage",
    "vehicle_state",
    "character_travel_history",
    "vehicle_market_offers",
    "character_vehicles",
    "housing_storage",
    "housing_properties",
    "housing_state",
    "training_sessions",
    "character_qualifications",
    "career_employment",
    "career_history",
    "character_police_state",
    "player_opportunity_history",
    "character_relationship_state",
    "character_memory_state",
    "character_history",
    "character_creation_drafts",
    # world state
    "rp_world_story_history",
    "rp_world_story_state",
    "rp_world_state",
    # player economy/profile
    "achievements",
    "user_badges",
    "user_badge_showcase",
    "inventory",
    "user_statistics",
    "transactions",
    # catalogs that are regenerated after reset
    "business_properties",
    # parents last
    "characters",
    "users",
    "betting_tickets",
    "betting_matches",
    "horse_races",
    "poker_tables",
)

# Tables that are community/server infrastructure and survive the RP launch reset.
PRESERVE_TABLES: tuple[str, ...] = (
    "activity_users",
    "guild_state",
    "shop_items",
    "server_shop_items",
    "server_shop_purchases",
    "server_shop_claims",
    "temporary_role_grants",
    "moderation_warnings",
    "moderation_cases",
    "automod_rules",
    "automod_exemptions",
    "automod_domains",
    "automod_words",
    "role_panels",
    "role_panel_items",
    "verification_panels",
    "member_role_snapshots",
    "player_notification_preferences",
    "community_suggestions",
    "community_suggestion_votes",
    "community_polls",
    "community_poll_votes",
    "community_giveaways",
    "community_giveaway_entries",
    "community_afk",
    "community_starboard_posts",
    "community_stickies",
    "server_architect_panels",
    "server_architect_snapshots",
    "server_temp_channels",
    "ticket_panels",
    "ticket_panel_types",
    "tickets",
    "ticket_members",
)


# Optional legacy tables that may still exist on upgraded production databases.
# They are classified explicitly but are NOT required on a clean/fresh schema.
LEGACY_RESET_GUILD_TABLES: tuple[str, ...] = (
    "active_boosters",
    "crew_faction_progress",
    "crew_member_faction",
    "crew_objectives",
    "guild_effects",
    "quest_assignments",
    "role_income",
    "user_prestige",
)

# The short-lived premium reward table is retained as migration/history safety.
# Current Community Shop data lives in server_shop_purchases/server_shop_claims.
LEGACY_PRESERVE_TABLES: tuple[str, ...] = (
    "premium_reward_claims",
)

# These have no guild_id and must be selected/deleted through a guild-scoped parent.
CHILD_TABLES: tuple[str, ...] = (
    "betting_ticket_legs",
    "poker_players",
)

# Opt-in destructive extension.  This is deliberately separate from the default
# reset because Community XP is Discord-community progression, not RP character
# progression.
OPTIONAL_COMMUNITY_XP_TABLES: tuple[str, ...] = ("activity_users",)

# Runtime guild_state values that represent generated gameplay state rather than
# configuration.  Configuration/channel bindings are intentionally preserved.
RUNTIME_GUILD_STATE_KEYS: tuple[str, ...] = (
    "world_news_last_cycle_id",
    "betting_results_thread_day",
    "betting_results_thread_id",
)

# These tables are deleted by the launch reset, but a clean running bot may
# immediately regenerate fresh, non-player baseline rows after the reset.
# They are still RESET targets so old test/runtime history is destroyed first.
POST_RESET_GENERATED_TABLES: tuple[str, ...] = (
    "business_properties",
    "rp_world_state",
    "rp_world_story_state",
    "rp_world_story_history",
    "betting_matches",
    "horse_races",
)

# Current known runtime schema.  QA compares this with discovered tables so a new
# table cannot accidentally bypass classification.
# Required active schema tables.  Missing one of these is a real schema error.
REQUIRED_TABLES: frozenset[str] = frozenset(
    RESET_GUILD_TABLES
    + PRESERVE_TABLES
    + CHILD_TABLES
)

# Full classification set also includes optional legacy artifacts.
KNOWN_TABLES: frozenset[str] = frozenset(
    tuple(REQUIRED_TABLES)
    + LEGACY_RESET_GUILD_TABLES
    + LEGACY_PRESERVE_TABLES
)

# Critical arbitrary-precision economy columns.  On MySQL/MariaDB these must be
# DECIMAL(65,0); SQLite is accepted as INTEGER for local/dev compatibility.
CRITICAL_MONEY_COLUMNS: dict[str, tuple[str, ...]] = {
    "users": ("wallet", "bank", "rob_profit", "gambling_profit", "money_earned", "money_lost", "investment_profit"),
    "transactions": ("amount",),
    "user_statistics": ("value",),
    "shop_items": ("price",),
    "market_daily": ("price",),
    "lottery_history": ("payout",),
    "casino_sessions": ("bet", "payout", "profit", "wallet_after"),
    "casino_ledger": ("amount", "balance_after"),
    "casino_monthly_jackpot": ("pool", "total_house_loss", "total_contributed"),
    "casino_monthly_user_contrib": ("contributed", "house_loss"),
    "casino_jackpot_history": ("pool", "payout", "total_house_loss", "total_contributed"),
    "betting_tickets": ("stake_unit", "total_stake", "potential_payout", "payout"),
    "horse_bets": ("stake", "payout"),
    "pvp_duels": ("stake",),
    "poker_tables": ("buy_in",),
    "poker_players": ("reserved", "payout"),
    "live_game_sessions": ("stake", "reward"),
    "job_history": ("reward",),
    "job_mastery": ("total_earned",),
    "job_sessions": ("reward",),
    "business_properties": ("base_price", "base_hourly_revenue", "hourly_upkeep"),
    "business_workers": ("wage_per_hour",),
    "business_offers": ("amount",),
    "contracts": ("reward_amount", "escrow_wallet_amount", "escrow_bank_amount"),
    "business_transactions": ("amount",),
    "crews": ("bank", "total_contributed"),
    "crew_members": ("contributed",),
    "crew_wars": ("target", "challenger_score", "target_score"),
    "heist_runs": ("reward_pool", "total_reward"),
    "player_market_listings": ("unit_price",),
    "player_market_trades": ("unit_price", "gross", "tax", "net"),
    "server_shop_items": ("price",),
    "server_shop_purchases": ("price",),
    # Additive RP tables use explicit backend-aware DECIMAL DDL.
    "housing_properties": ("purchase_price", "maintenance_debt", "sale_price"),
    "character_vehicles": ("purchase_price", "estimated_value"),
    "vehicle_market_offers": ("price",),
    "character_travel_history": ("cost",),
}
