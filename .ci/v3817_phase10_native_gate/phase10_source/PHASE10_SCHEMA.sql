-- TABLE:characters
CREATE TABLE characters (
  guild_id BIGINT UNSIGNED NOT NULL,
  user_id BIGINT UNSIGNED NOT NULL,
  status VARCHAR(24) NOT NULL DEFAULT 'active',
  PRIMARY KEY(guild_id,user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci

-- TABLE:users
CREATE TABLE users (
  guild_id BIGINT UNSIGNED NOT NULL,
  user_id BIGINT UNSIGNED NOT NULL,
  wallet DECIMAL(65,0) NOT NULL DEFAULT 0,
  bank DECIMAL(65,0) NOT NULL DEFAULT 0,
  money_lost DECIMAL(65,0) NOT NULL DEFAULT 0,
  money_earned DECIMAL(65,0) NOT NULL DEFAULT 0,
  selected_title VARCHAR(64) NOT NULL DEFAULT 'Kezdő',
  PRIMARY KEY (guild_id,user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci

-- TABLE:user_statistics
CREATE TABLE user_statistics (
  guild_id BIGINT UNSIGNED NOT NULL,
  user_id BIGINT UNSIGNED NOT NULL,
  stat_name VARCHAR(128) NOT NULL,
  value DECIMAL(65,0) NOT NULL DEFAULT 0,
  updated_at VARCHAR(64) NOT NULL,
  PRIMARY KEY(guild_id,user_id,stat_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci

-- TABLE:transactions
CREATE TABLE transactions (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  guild_id BIGINT UNSIGNED NOT NULL,
  user_id BIGINT UNSIGNED NOT NULL,
  amount DECIMAL(65,0) NOT NULL,
  reason VARCHAR(191) NOT NULL,
  created_at VARCHAR(64) NOT NULL,
  PRIMARY KEY(id),
  KEY idx_transactions_reason(guild_id,user_id,reason)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci

-- TABLE:shop_items
CREATE TABLE shop_items (
  item_id VARCHAR(80) NOT NULL,
  name VARCHAR(120) NOT NULL,
  description VARCHAR(255) NOT NULL DEFAULT '',
  price DECIMAL(65,0) NOT NULL DEFAULT 0,
  emoji VARCHAR(32) NOT NULL DEFAULT '',
  active TINYINT UNSIGNED NOT NULL DEFAULT 1,
  PRIMARY KEY(item_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci

-- TABLE:inventory
CREATE TABLE inventory (
  guild_id BIGINT UNSIGNED NOT NULL,
  user_id BIGINT UNSIGNED NOT NULL,
  item_id VARCHAR(80) NOT NULL,
  quantity BIGINT NOT NULL DEFAULT 0,
  PRIMARY KEY(guild_id,user_id,item_id),
  CONSTRAINT fk_phase10_inventory_item FOREIGN KEY(item_id) REFERENCES shop_items(item_id) ON UPDATE CASCADE ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci

-- TABLE:market_daily
CREATE TABLE market_daily (
  guild_id BIGINT UNSIGNED NOT NULL,
  item_id VARCHAR(80) NOT NULL,
  market_date VARCHAR(16) NOT NULL,
  price DECIMAL(65,0) NOT NULL,
  stock BIGINT NOT NULL,
  starting_stock BIGINT NOT NULL,
  PRIMARY KEY(guild_id,item_id,market_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci

-- TABLE:business_transactions
CREATE TABLE business_transactions (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  guild_id BIGINT UNSIGNED NOT NULL,
  property_id BIGINT UNSIGNED NOT NULL,
  user_id BIGINT UNSIGNED NOT NULL,
  amount DECIMAL(65,0) NOT NULL,
  kind VARCHAR(64) NOT NULL,
  created_at VARCHAR(64) NOT NULL,
  PRIMARY KEY(id), KEY idx_phase10_business_progress(guild_id,user_id,created_at,kind)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci

-- TABLE:crew_internal_projects
CREATE TABLE crew_internal_projects (
  project_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  guild_id BIGINT UNSIGNED NOT NULL,
  status VARCHAR(24) NOT NULL,
  member_snapshot_json TEXT NOT NULL,
  completed_at VARCHAR(64) NULL,
  PRIMARY KEY(project_id), KEY idx_phase10_org_progress(guild_id,status,completed_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci

-- TABLE:heist_runs
CREATE TABLE heist_runs (
  run_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  guild_id BIGINT UNSIGNED NOT NULL,
  target_key VARCHAR(80) NOT NULL,
  success TINYINT UNSIGNED NOT NULL DEFAULT 0,
  member_snapshot TEXT NOT NULL,
  resolved_at VARCHAR(64) NULL,
  PRIMARY KEY(run_id), KEY idx_phase10_heist_history(guild_id,target_key,success,resolved_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci

-- TABLE:achievements
CREATE TABLE achievements (
  guild_id BIGINT UNSIGNED NOT NULL,user_id BIGINT UNSIGNED NOT NULL,achievement_id VARCHAR(120) NOT NULL,unlocked_at VARCHAR(64) NOT NULL,
  PRIMARY KEY(guild_id,user_id,achievement_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci

-- TABLE:user_badges
CREATE TABLE user_badges (
  guild_id BIGINT UNSIGNED NOT NULL,user_id BIGINT UNSIGNED NOT NULL,badge_id VARCHAR(120) NOT NULL,unlocked_at VARCHAR(64) NOT NULL,
  PRIMARY KEY(guild_id,user_id,badge_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci

-- TABLE:asset_instances
CREATE TABLE IF NOT EXISTS asset_instances (
                    asset_instance_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                    guild_id BIGINT UNSIGNED NOT NULL,
                    asset_type VARCHAR(24) NOT NULL,
                    source_ref VARCHAR(128) NOT NULL,
                    reference_key VARCHAR(128) NOT NULL,
                    rarity VARCHAR(24) NOT NULL DEFAULT 'standard',
                    origin_key VARCHAR(128) NOT NULL,
                    special_flags_json LONGTEXT NOT NULL,
                    created_at VARCHAR(64) NOT NULL,
                    updated_at VARCHAR(64) NOT NULL,
                    PRIMARY KEY (asset_instance_id),
                    UNIQUE KEY uq_asset_source (guild_id, asset_type, source_ref),
                    KEY idx_asset_type_rarity (guild_id, asset_type, rarity, created_at)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci

-- TABLE:asset_ownership_history
CREATE TABLE IF NOT EXISTS asset_ownership_history (
                    ownership_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                    instance_id BIGINT UNSIGNED NOT NULL,
                    guild_id BIGINT UNSIGNED NOT NULL,
                    owner_type VARCHAR(24) NOT NULL,
                    owner_id BIGINT UNSIGNED NULL,
                    acquisition_type VARCHAR(64) NOT NULL,
                    acquisition_ref VARCHAR(191) NULL,
                    acquired_at VARCHAR(64) NOT NULL,
                    released_at VARCHAR(64) NULL,
                    release_type VARCHAR(64) NULL,
                    release_ref VARCHAR(191) NULL,
                    active_slot TINYINT UNSIGNED NULL DEFAULT 1,
                    event_key VARCHAR(191) NOT NULL,
                    created_at VARCHAR(64) NOT NULL,
                    updated_at VARCHAR(64) NOT NULL,
                    PRIMARY KEY (ownership_id),
                    UNIQUE KEY uq_asset_ownership_event (instance_id, event_key),
                    UNIQUE KEY uq_asset_active_owner (instance_id, active_slot),
                    KEY idx_asset_owner_active (guild_id, owner_type, owner_id, active_slot, acquired_at),
                    CONSTRAINT fk_asset_ownership_instance
                        FOREIGN KEY (instance_id) REFERENCES asset_instances(asset_instance_id)
                        ON UPDATE CASCADE ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci

-- TABLE:asset_auction_listings
CREATE TABLE IF NOT EXISTS asset_auction_listings (
                    auction_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                    guild_id BIGINT UNSIGNED NOT NULL,
                    asset_instance_id BIGINT UNSIGNED NOT NULL,
                    seller_id BIGINT UNSIGNED NOT NULL,
                    start_price DECIMAL(65,0) NOT NULL,
                    min_increment DECIMAL(65,0) NOT NULL,
                    fee_bp INT NOT NULL DEFAULT 500,
                    status VARCHAR(24) NOT NULL DEFAULT 'active',
                    active_slot TINYINT UNSIGNED NULL DEFAULT 1,
                    current_bid_id BIGINT UNSIGNED NULL,
                    current_bid_amount DECIMAL(65,0) NULL,
                    created_at VARCHAR(64) NOT NULL,
                    expires_at VARCHAR(64) NOT NULL,
                    resolved_at VARCHAR(64) NULL,
                    winner_id BIGINT UNSIGNED NULL,
                    final_price DECIMAL(65,0) NULL,
                    seller_net DECIMAL(65,0) NULL,
                    settlement_ref VARCHAR(191) NULL,
                    PRIMARY KEY (auction_id),
                    UNIQUE KEY uq_asset_auction_active (asset_instance_id, active_slot),
                    KEY idx_asset_auction_active (guild_id, status, expires_at, auction_id),
                    KEY idx_asset_auction_seller (guild_id, seller_id, status, auction_id),
                    CONSTRAINT fk_asset_auction_instance
                        FOREIGN KEY (asset_instance_id) REFERENCES asset_instances(asset_instance_id)
                        ON UPDATE CASCADE ON DELETE RESTRICT
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci

-- TABLE:asset_auction_bids
CREATE TABLE IF NOT EXISTS asset_auction_bids (
                    bid_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                    auction_id BIGINT UNSIGNED NOT NULL,
                    guild_id BIGINT UNSIGNED NOT NULL,
                    bidder_id BIGINT UNSIGNED NOT NULL,
                    amount DECIMAL(65,0) NOT NULL,
                    wallet_reserved DECIMAL(65,0) NOT NULL DEFAULT 0,
                    bank_reserved DECIMAL(65,0) NOT NULL DEFAULT 0,
                    status VARCHAR(24) NOT NULL DEFAULT 'leading',
                    request_ref VARCHAR(191) NOT NULL,
                    created_at VARCHAR(64) NOT NULL,
                    resolved_at VARCHAR(64) NULL,
                    PRIMARY KEY (bid_id),
                    UNIQUE KEY uq_asset_auction_bid_request (auction_id, request_ref),
                    KEY idx_asset_auction_bidder (guild_id, bidder_id, status, auction_id),
                    KEY idx_asset_auction_bids (auction_id, amount, bid_id),
                    CONSTRAINT fk_asset_auction_bid_listing
                        FOREIGN KEY (auction_id) REFERENCES asset_auction_listings(auction_id)
                        ON UPDATE CASCADE ON DELETE RESTRICT
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci

-- TABLE:holding_mega_projects
CREATE TABLE IF NOT EXISTS holding_mega_projects (
                    project_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                    guild_id BIGINT UNSIGNED NOT NULL,
                    owner_user_id BIGINT UNSIGNED NOT NULL,
                    project_key VARCHAR(64) NOT NULL,
                    title VARCHAR(120) NOT NULL,
                    commitment_amount DECIMAL(65,0) NOT NULL,
                    funded_wallet_amount DECIMAL(65,0) NOT NULL,
                    funded_bank_amount DECIMAL(65,0) NOT NULL,
                    target_units INT UNSIGNED NOT NULL,
                    progress_units INT UNSIGNED NOT NULL DEFAULT 0,
                    contract_units INT UNSIGNED NOT NULL DEFAULT 0,
                    business_units INT UNSIGNED NOT NULL DEFAULT 0,
                    community_units INT UNSIGNED NOT NULL DEFAULT 0,
                    organization_units INT UNSIGNED NOT NULL DEFAULT 0,
                    stage_snapshot VARCHAR(16) NOT NULL,
                    business_count_snapshot INT UNSIGNED NOT NULL,
                    business_city_count_snapshot INT UNSIGNED NOT NULL,
                    status VARCHAR(24) NOT NULL DEFAULT 'active',
                    active_slot TINYINT UNSIGNED NULL,
                    started_at VARCHAR(64) NOT NULL,
                    updated_at VARCHAR(64) NOT NULL,
                    completed_at VARCHAR(64) NULL,
                    PRIMARY KEY (project_id),
                    UNIQUE KEY uq_holding_mega_project_once (guild_id, owner_user_id, project_key),
                    UNIQUE KEY uq_holding_mega_project_active (guild_id, owner_user_id, active_slot),
                    KEY idx_holding_mega_project_status (guild_id, owner_user_id, status, project_id),
                    KEY idx_holding_mega_project_history (guild_id, owner_user_id, project_id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci

-- TABLE:contracts
CREATE TABLE IF NOT EXISTS contracts (
                    contract_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                    guild_id BIGINT UNSIGNED NOT NULL,
                    source_type VARCHAR(24) NOT NULL,
                    source_ref VARCHAR(64) NOT NULL DEFAULT '',
                    creator_id BIGINT UNSIGNED NULL,
                    assignee_id BIGINT UNSIGNED NULL,
                    title VARCHAR(120) NOT NULL,
                    reward_amount DECIMAL(65,0) NOT NULL,
                    escrow_state VARCHAR(16) NOT NULL DEFAULT 'held',
                    escrow_wallet_amount DECIMAL(65,0) NOT NULL DEFAULT 0,
                    escrow_bank_amount DECIMAL(65,0) NOT NULL DEFAULT 0,
                    status VARCHAR(16) NOT NULL DEFAULT 'open',
                    created_at VARCHAR(64) NOT NULL,
                    expires_at VARCHAR(64) NOT NULL,
                    accepted_at VARCHAR(64) NULL,
                    resolved_at VARCHAR(64) NULL,
                    PRIMARY KEY (contract_id),
                    KEY idx_contracts_active (guild_id,status,expires_at),
                    KEY idx_contracts_assignee (guild_id,assignee_id,status,contract_id),
                    KEY idx_contracts_creator (guild_id,creator_id,status,contract_id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci

-- TABLE:player_opportunity_history
CREATE TABLE IF NOT EXISTS player_opportunity_history (
                    event_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                    guild_id BIGINT UNSIGNED NOT NULL,
                    user_id BIGINT UNSIGNED NOT NULL,
                    opportunity_key VARCHAR(96) NOT NULL,
                    source_family VARCHAR(32) NOT NULL,
                    action_key VARCHAR(96) NULL,
                    cycle_id VARCHAR(32) NULL,
                    event_type VARCHAR(24) NOT NULL,
                    created_at VARCHAR(64) NOT NULL,
                    PRIMARY KEY (event_id),
                    KEY idx_player_opportunity_user (guild_id,user_id,event_id),
                    KEY idx_player_opportunity_key (guild_id,user_id,opportunity_key,event_type,event_id),
                    CONSTRAINT fk_player_opportunity_character
                        FOREIGN KEY (guild_id,user_id)
                        REFERENCES characters (guild_id,user_id)
                        ON UPDATE CASCADE ON DELETE RESTRICT
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci

-- TABLE:rp_world_community_projects
CREATE TABLE IF NOT EXISTS rp_world_community_projects (
                    project_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                    guild_id BIGINT UNSIGNED NOT NULL,
                    project_key VARCHAR(64) NOT NULL,
                    city_key VARCHAR(32) NULL,
                    source_cycle_id VARCHAR(32) NOT NULL,
                    status VARCHAR(24) NOT NULL,
                    target_units INT UNSIGNED NOT NULL,
                    min_participants SMALLINT UNSIGNED NOT NULL,
                    actor_cap_units SMALLINT UNSIGNED NOT NULL,
                    contributed_units INT UNSIGNED NOT NULL DEFAULT 0,
                    participant_count INT UNSIGNED NOT NULL DEFAULT 0,
                    started_at VARCHAR(64) NOT NULL,
                    deadline_at VARCHAR(64) NOT NULL,
                    completed_at VARCHAR(64) NULL,
                    updated_at VARCHAR(64) NOT NULL,
                    PRIMARY KEY (project_id),
                    UNIQUE KEY uq_rp_world_project_cycle (guild_id, source_cycle_id),
                    KEY idx_rp_world_project_active (guild_id, status, deadline_at)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci

-- TABLE:rp_world_community_project_contributions
CREATE TABLE IF NOT EXISTS rp_world_community_project_contributions (
                    contribution_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                    project_id BIGINT UNSIGNED NOT NULL,
                    guild_id BIGINT UNSIGNED NOT NULL,
                    source_ref VARCHAR(192) NOT NULL,
                    actor_user_id BIGINT UNSIGNED NOT NULL,
                    domain VARCHAR(32) NOT NULL,
                    city_key VARCHAR(32) NULL,
                    crew_id BIGINT UNSIGNED NULL,
                    business_property_id BIGINT UNSIGNED NULL,
                    units SMALLINT UNSIGNED NOT NULL,
                    recorded_at VARCHAR(64) NOT NULL,
                    PRIMARY KEY (contribution_id),
                    UNIQUE KEY uq_rp_world_project_source (project_id, source_ref),
                    KEY idx_rp_world_project_actor (project_id, actor_user_id),
                    KEY idx_rp_world_project_guild (guild_id, recorded_at),
                    CONSTRAINT fk_rp_world_project_contribution
                        FOREIGN KEY (project_id) REFERENCES rp_world_community_projects(project_id)
                        ON UPDATE CASCADE ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
