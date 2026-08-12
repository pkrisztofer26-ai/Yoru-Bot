# Yoru Casino Balance Audit — v3.21.0

## Default house-game RTP

| Játék / mód | Default RTP | Megjegyzés |
|---|---:|---|
| Coinflip | 95.00% | 50% win × 1.90 total payout |
| Dice — exact 1–6 | 95.00% | 1/6 × 5.70 |
| Dice — high/low, odd/even | 95.00% | 1/2 × 1.90 |
| Dice — over/under 7 | 95.00% | 15/36 × 2.28 |
| Dice — exactly 7 | 95.00% | 6/36 × 5.70 |
| RPS vs Yoru | 95.00% | 1/3 win × 1.85 + 1/3 tie refund |
| Chicken Fight | 92.00% | 46% win × 2.00 |
| Roulette — even-money | 97.30% | 18/37 × 2.00 |
| Roulette — dozen/column | 97.30% | 12/37 × 3.00 |
| Roulette — single number | 97.30% | 1/37 × 36.00 |
| High / Low | ~96% / decisive step | Dinamikus multiplier: house factor / effective probability; tie ismétli a kört |
| Slots | ~94.88% | 1,000,000 spin Monte Carlo, 20 payline + free spins |
| Lottery | 90% pool payout | Player-funded; 10% economy sink a standard ticket poolnál |

## Blackjack

A Blackjack RTP nem egyetlen fix szám, mert a Hit/Stand/Double/Split/Insurance döntésektől függ. A v3.21.0 audit a payout- és reservation-szabályokat ellenőrizte: normál win 1:1 profit, natural 3:2 profit, push refund, insurance 2:1 profit az insurance stake-re. Statikus payoutból adódó pozitív EV exploitot nem találtunk. A későbbi, pontos strategy-RTP audit külön basic-strategy szimulátort érdemel, ha a blackjack szabályokon változtatunk.

## Monthly Jackpot economy-hatás

A house lossok 2%-a a havi jackpotba kerül, majd legfeljebb 100%-ban visszaosztásra kerül. Ez **nem money source**, hanem a Casino sink egy részének közösségi redisztribúciója. Emiatt az economy-szintű effektív sink kisebb, mint az egyéni RTP-ből számolt house edge. A legkisebb sinket a roulette straight-up adja, de default config mellett ez is negatív EV / nem hoz létre pénzt.

## PvP

Coinflip/Dice/RPS Duel 100%-ban player-to-player escrow: a pot egyik játékostól a másikhoz kerül, tie esetén refund. Nincs house payout és nem tölti a Monthly Jackpotot. Economy-szinten nettó 0 source/sink.

## Következtetés

- Nem találtunk default payout mellett pozitív EV-s statikus exploitot.
- Slots a célzott 92–97% sávban marad.
- Roulette a legplayer-friendlybb house game (~97.30% base RTP).
- Chicken Fight a legnagyobb house edge (~8%).
- A 2% Jackpot hook nem teremt pénzt, csak csökkenti a végleges Casino sinket.
- Új Casino játék csak RTP/EV teszttel kerülhet release-be.
