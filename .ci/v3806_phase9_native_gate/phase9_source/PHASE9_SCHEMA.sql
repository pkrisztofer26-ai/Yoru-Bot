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
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

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
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- TABLE:asset_trophy_showcase
CREATE TABLE IF NOT EXISTS asset_trophy_showcase (
                    guild_id BIGINT UNSIGNED NOT NULL,
                    user_id BIGINT UNSIGNED NOT NULL,
                    slot_index TINYINT UNSIGNED NOT NULL,
                    asset_instance_id BIGINT UNSIGNED NOT NULL,
                    created_at VARCHAR(64) NOT NULL,
                    updated_at VARCHAR(64) NOT NULL,
                    PRIMARY KEY (guild_id, user_id, slot_index),
                    UNIQUE KEY uq_asset_trophy_user_instance (guild_id, user_id, asset_instance_id),
                    CONSTRAINT fk_asset_trophy_instance
                        FOREIGN KEY (asset_instance_id) REFERENCES asset_instances(asset_instance_id)
                        ON UPDATE CASCADE ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

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
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

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
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
