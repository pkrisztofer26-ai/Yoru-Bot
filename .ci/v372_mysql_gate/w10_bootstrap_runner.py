from __future__ import annotations

import asyncio
import os

from mysql.connector.aio import connect as mysql_async_connect


USERS_DDL = """CREATE TABLE IF NOT EXISTS `users` (
  `guild_id` BIGINT UNSIGNED NOT NULL,
  `user_id` BIGINT UNSIGNED NOT NULL,
  `wallet` DECIMAL(65,0) NOT NULL DEFAULT 0,
  `bank` DECIMAL(65,0) NOT NULL DEFAULT 0,
  `created_at` VARCHAR(64) NOT NULL,
  `last_daily` VARCHAR(64),
  `last_work` VARCHAR(64),
  `last_crime` VARCHAR(64),
  `last_rob` VARCHAR(64),
  `last_role_income` VARCHAR(64),
  `work_count` BIGINT NOT NULL DEFAULT 0,
  `crime_success` BIGINT NOT NULL DEFAULT 0,
  `crime_failed` BIGINT NOT NULL DEFAULT 0,
  `rob_success` BIGINT NOT NULL DEFAULT 0,
  `rob_failed` BIGINT NOT NULL DEFAULT 0,
  `rob_profit` DECIMAL(65,0) NOT NULL DEFAULT 0,
  `gambling_profit` DECIMAL(65,0) NOT NULL DEFAULT 0,
  `game_wins` BIGINT NOT NULL DEFAULT 0,
  `last_beg` VARCHAR(64),
  `last_search` VARCHAR(64),
  `daily_streak` BIGINT NOT NULL DEFAULT 0,
  `best_daily_streak` BIGINT NOT NULL DEFAULT 0,
  `daily_count` BIGINT NOT NULL DEFAULT 0,
  `beg_count` BIGINT NOT NULL DEFAULT 0,
  `search_count` BIGINT NOT NULL DEFAULT 0,
  `money_earned` DECIMAL(65,0) NOT NULL DEFAULT 0,
  `money_lost` DECIMAL(65,0) NOT NULL DEFAULT 0,
  `jail_until` LONGTEXT,
  `last_weekly` VARCHAR(64),
  `last_monthly` VARCHAR(64),
  `last_interest` VARCHAR(64),
  `weekly_count` BIGINT NOT NULL DEFAULT 0,
  `monthly_count` BIGINT NOT NULL DEFAULT 0,
  `scratch_count` BIGINT NOT NULL DEFAULT 0,
  `chicken_wins` BIGINT NOT NULL DEFAULT 0,
  `xp_points` BIGINT NOT NULL DEFAULT 0,
  `selected_title` VARCHAR(1024) NOT NULL DEFAULT 'Kezdő',
  `investment_profit` DECIMAL(65,0) NOT NULL DEFAULT 0,
  `last_invest` VARCHAR(64),
  `jackpot_wins` BIGINT NOT NULL DEFAULT 0,
  `lottery_wins` BIGINT NOT NULL DEFAULT 0,
  `last_slut` VARCHAR(64),
  `last_withdraw` VARCHAR(64),
  PRIMARY KEY (`guild_id`, `user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"""


async def bootstrap_db1_users() -> None:
    conn = await mysql_async_connect(
        host=os.environ["MYSQL_HOST"],
        port=int(os.environ.get("MYSQL_PORT", "3306")),
        user=os.environ["MYSQL_USER"],
        password=os.environ["MYSQL_PASSWORD"],
        database=os.environ["MYSQL_DATABASE"],
        autocommit=False,
        charset="utf8mb4",
        connection_timeout=10,
        use_pure=True,
        ssl_disabled=True,
    )
    try:
        cur = await conn.cursor()
        try:
            await cur.execute(USERS_DDL)
            await conn.commit()
        finally:
            await cur.close()
    finally:
        await conn.close()


def main() -> int:
    asyncio.run(bootstrap_db1_users())
    import w10_transaction_contracts
    return w10_transaction_contracts.main()


if __name__ == "__main__":
    raise SystemExit(main())
