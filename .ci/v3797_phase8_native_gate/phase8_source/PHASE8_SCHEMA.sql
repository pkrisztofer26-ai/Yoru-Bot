-- TABLE:crew_relations
CREATE TABLE IF NOT EXISTS crew_relations (
                        guild_id BIGINT UNSIGNED NOT NULL,
                        crew_low_id BIGINT UNSIGNED NOT NULL,
                        crew_high_id BIGINT UNSIGNED NOT NULL,
                        relation_kind VARCHAR(24) NOT NULL DEFAULT 'neutral',
                        pending_kind VARCHAR(24) NULL,
                        pending_from_crew_id BIGINT UNSIGNED NULL,
                        pending_from_user_id BIGINT UNSIGNED NULL,
                        proposal_created_at VARCHAR(64) NULL,
                        relation_started_at VARCHAR(64) NULL,
                        updated_at VARCHAR(64) NOT NULL,
                        PRIMARY KEY (guild_id, crew_low_id, crew_high_id),
                        KEY idx_crew_relations_low (guild_id, crew_low_id, relation_kind),
                        KEY idx_crew_relations_high (guild_id, crew_high_id, relation_kind),
                        KEY idx_crew_relations_pending (guild_id, pending_from_crew_id, pending_kind)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- TABLE:crew_governance_proposals
CREATE TABLE IF NOT EXISTS crew_governance_proposals (
                        proposal_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                        guild_id BIGINT UNSIGNED NOT NULL,
                        crew_id BIGINT UNSIGNED NOT NULL,
                        decision_kind VARCHAR(32) NOT NULL,
                        title VARCHAR(80) NOT NULL,
                        description VARCHAR(500) NOT NULL DEFAULT '',
                        subject_ref VARCHAR(160) NULL,
                        created_by BIGINT UNSIGNED NOT NULL,
                        eligible_count INT UNSIGNED NOT NULL,
                        required_yes INT UNSIGNED NOT NULL,
                        status VARCHAR(24) NOT NULL DEFAULT 'open',
                        active_slot TINYINT UNSIGNED NULL DEFAULT 1,
                        created_at VARCHAR(64) NOT NULL,
                        closes_at VARCHAR(64) NOT NULL,
                        resolved_at VARCHAR(64) NULL,
                        PRIMARY KEY (proposal_id),
                        UNIQUE KEY uq_crew_governance_active (guild_id, crew_id, active_slot),
                        KEY idx_crew_governance_open (guild_id, crew_id, status, closes_at),
                        KEY idx_crew_governance_history (guild_id, crew_id, proposal_id)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- TABLE:crew_governance_votes
CREATE TABLE IF NOT EXISTS crew_governance_votes (
                        proposal_id BIGINT UNSIGNED NOT NULL,
                        guild_id BIGINT UNSIGNED NOT NULL,
                        crew_id BIGINT UNSIGNED NOT NULL,
                        user_id BIGINT UNSIGNED NOT NULL,
                        choice VARCHAR(8) NOT NULL,
                        voted_at VARCHAR(64) NOT NULL,
                        PRIMARY KEY (proposal_id, user_id),
                        KEY idx_crew_governance_votes_crew (guild_id, crew_id, proposal_id),
                        CONSTRAINT fk_crew_governance_vote_proposal FOREIGN KEY (proposal_id)
                            REFERENCES crew_governance_proposals(proposal_id) ON DELETE CASCADE
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- TABLE:crew_governance_executions
CREATE TABLE IF NOT EXISTS crew_governance_executions (
                        proposal_id BIGINT UNSIGNED NOT NULL,
                        guild_id BIGINT UNSIGNED NOT NULL,
                        crew_id BIGINT UNSIGNED NOT NULL,
                        decision_kind VARCHAR(32) NOT NULL,
                        execution_action VARCHAR(32) NOT NULL,
                        subject_ref VARCHAR(160) NOT NULL,
                        status VARCHAR(24) NOT NULL DEFAULT 'pending',
                        authority_ref VARCHAR(160) NULL,
                        detail VARCHAR(500) NOT NULL DEFAULT '',
                        created_at VARCHAR(64) NOT NULL,
                        executed_at VARCHAR(64) NULL,
                        PRIMARY KEY (proposal_id),
                        KEY idx_crew_governance_execution_state (guild_id, crew_id, status, proposal_id),
                        CONSTRAINT fk_crew_governance_execution_proposal FOREIGN KEY (proposal_id)
                            REFERENCES crew_governance_proposals(proposal_id) ON DELETE CASCADE
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- TABLE:crew_internal_projects
CREATE TABLE IF NOT EXISTS crew_internal_projects (
                        project_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                        guild_id BIGINT UNSIGNED NOT NULL,
                        crew_id BIGINT UNSIGNED NOT NULL,
                        governance_proposal_id BIGINT UNSIGNED NOT NULL,
                        project_key VARCHAR(32) NOT NULL,
                        title VARCHAR(80) NOT NULL,
                        description VARCHAR(500) NOT NULL DEFAULT '',
                        budget_amount BIGINT UNSIGNED NOT NULL,
                        target_units INT UNSIGNED NOT NULL,
                        progress_units INT UNSIGNED NOT NULL DEFAULT 0,
                        contributor_count INT UNSIGNED NOT NULL DEFAULT 0,
                        member_snapshot_json LONGTEXT NOT NULL,
                        bank_before BIGINT UNSIGNED NOT NULL,
                        bank_after BIGINT UNSIGNED NOT NULL,
                        status VARCHAR(24) NOT NULL DEFAULT 'active',
                        active_slot TINYINT UNSIGNED NULL DEFAULT 1,
                        started_at VARCHAR(64) NOT NULL,
                        updated_at VARCHAR(64) NOT NULL,
                        completed_at VARCHAR(64) NULL,
                        PRIMARY KEY (project_id),
                        UNIQUE KEY uq_crew_internal_project_governance (governance_proposal_id),
                        UNIQUE KEY uq_crew_internal_project_active (guild_id, crew_id, active_slot),
                        KEY idx_crew_internal_project_status (guild_id, crew_id, status, project_id),
                        KEY idx_crew_internal_project_history (guild_id, crew_id, project_id),
                        CONSTRAINT fk_crew_internal_project_governance FOREIGN KEY (governance_proposal_id)
                            REFERENCES crew_governance_proposals(proposal_id) ON DELETE CASCADE
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- TABLE:crew_hq_state
CREATE TABLE IF NOT EXISTS crew_hq_state (
                        hq_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                        guild_id BIGINT UNSIGNED NOT NULL,
                        crew_id BIGINT UNSIGNED NOT NULL,
                        governance_proposal_id BIGINT UNSIGNED NOT NULL,
                        city_key VARCHAR(40) NOT NULL,
                        budget_amount BIGINT UNSIGNED NOT NULL,
                        bank_before BIGINT UNSIGNED NOT NULL,
                        bank_after BIGINT UNSIGNED NOT NULL,
                        status VARCHAR(24) NOT NULL DEFAULT 'active',
                        active_slot TINYINT UNSIGNED NULL DEFAULT 1,
                        created_at VARCHAR(64) NOT NULL,
                        updated_at VARCHAR(64) NOT NULL,
                        retired_at VARCHAR(64) NULL,
                        PRIMARY KEY (hq_id),
                        UNIQUE KEY uq_crew_hq_governance (governance_proposal_id),
                        UNIQUE KEY uq_crew_hq_active (guild_id, crew_id, active_slot),
                        KEY idx_crew_hq_city (guild_id, city_key, status),
                        CONSTRAINT fk_crew_hq_governance FOREIGN KEY (governance_proposal_id)
                            REFERENCES crew_governance_proposals(proposal_id) ON DELETE CASCADE
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- TABLE:crew_hq_asset_links
CREATE TABLE IF NOT EXISTS crew_hq_asset_links (
                        link_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                        guild_id BIGINT UNSIGNED NOT NULL,
                        crew_id BIGINT UNSIGNED NOT NULL,
                        hq_id BIGINT UNSIGNED NOT NULL,
                        asset_kind VARCHAR(24) NOT NULL,
                        source_owner_id BIGINT UNSIGNED NOT NULL,
                        source_ref VARCHAR(160) NOT NULL,
                        label_snapshot VARCHAR(160) NOT NULL DEFAULT '',
                        linked_by BIGINT UNSIGNED NOT NULL,
                        status VARCHAR(24) NOT NULL DEFAULT 'active',
                        active_slot TINYINT UNSIGNED NULL DEFAULT 1,
                        created_at VARCHAR(64) NOT NULL,
                        updated_at VARCHAR(64) NOT NULL,
                        released_at VARCHAR(64) NULL,
                        PRIMARY KEY (link_id),
                        UNIQUE KEY uq_crew_hq_asset_active (guild_id, crew_id, asset_kind, source_owner_id, source_ref, active_slot),
                        KEY idx_crew_hq_assets_hq (guild_id, crew_id, hq_id, status),
                        CONSTRAINT fk_crew_hq_asset_hq FOREIGN KEY (hq_id)
                            REFERENCES crew_hq_state(hq_id) ON DELETE CASCADE
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- MIGRATION:business_tenders.organization_context_json
ALTER TABLE business_tenders ADD COLUMN organization_context_json LONGTEXT NULL;
