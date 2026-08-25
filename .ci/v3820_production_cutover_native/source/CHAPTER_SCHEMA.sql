CREATE TABLE IF NOT EXISTS rp_world_chapters (
                    chapter_run_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                    guild_id BIGINT UNSIGNED NOT NULL,
                    chapter_key VARCHAR(64) NOT NULL,
                    status VARCHAR(24) NOT NULL DEFAULT 'active',
                    active_slot TINYINT UNSIGNED NULL,
                    current_stage_key VARCHAR(64) NOT NULL,
                    started_at VARCHAR(64) NOT NULL,
                    stage_started_at VARCHAR(64) NOT NULL,
                    deadline_at VARCHAR(64) NOT NULL,
                    updated_at VARCHAR(64) NOT NULL,
                    resolved_at VARCHAR(64) NULL,
                    ending_key VARCHAR(64) NULL,
                    resolution_snapshot_json LONGTEXT NOT NULL,
                    PRIMARY KEY (chapter_run_id),
                    UNIQUE KEY uq_rp_world_chapter_active (guild_id, active_slot),
                    KEY idx_rp_world_chapter_history (guild_id, chapter_run_id),
                    KEY idx_rp_world_chapter_status (guild_id, status, deadline_at)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
