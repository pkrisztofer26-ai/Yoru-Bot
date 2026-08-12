# Yoru Interactive Jobs — v3.22.0 Balance Audit

## Goal
Interactive Jobs are free, active early-game content. They must pay enough to be worth actively playing while not making the existing cooldown-based Economy commands irrelevant.

## Safety rules
- No job requires or reserves a gambling bet.
- No AFK payout: a shift only pays after all required player interactions are completed.
- Timeout/cancel/restart recovery releases the session with no unfinished payout.
- Settlement is atomic and idempotency-protected by session status.
- Only one active Interactive Job is allowed per player/guild.
- Rewards support balances above 1B; no fixed money cap is assumed.
- Guild reward multiplier is configurable from 50–200%; default is 100%.
- Job Mastery income bonus is intentionally capped at +10%.
- Existing Prestige/Frakció income bonuses are applied through the normal EconomyService pipeline.

## Default payout calibration
These figures are before guild reward multiplier, Mastery and Prestige/Frakció bonuses.

### Raktáros
Formula: `145k + 42k × correct + 8k × best combo` over 5 rounds.

- random 25% answer accuracy: ~206k average
- 50% accuracy: ~266k average
- 75% accuracy: ~328k average
- perfect shift: 395k

The reward therefore scales with actual performance rather than an RNG-only roll.

### Borsodi Lopkodás
5×5 board, exactly 3 hidden patrol cells, up to 7 unique searches. A patrol ends the run and leaves 70% of accumulated run loot; it never removes pre-existing wallet money.

Monte-Carlo calibration with random unrevealed picks:
- patrol encountered before/at pick 7: ~65%
- average payout: ~250k
- median: ~205k

The loot table intentionally has high variance and rare crate hits, but no paid entry fee.

### Futár / Taxi
Each shift has 4 route decisions. Default strategy simulations:
- safe route every trip: ~276k average; high average performance
- long route every trip: ~366k average; medium risk
- risky route every trip: ~440k average; much lower average performance / more bad events

Higher nominal payout is paired with worse performance reliability, which also affects the final rating/Mastery result.

## Economy comparison
The legacy Work command remains the quick cooldown-based option. Interactive Jobs require multiple clicks/decisions and no unfinished shift pays, so their target reward is deliberately above a single ordinary quick-work outcome while staying below late-game Biznisz/Heist scale.

Live Economy Analytics should be used for future tuning. No automatic rebalance should be made from simulated values alone once real server usage data exists.
