# coinjury

**Put every Solana memecoin on trial before it puts your wallet in the ER.**

`coinjury` pulls the memecoins trending *right now*, runs each one through a rug-risk
check, and hands down a verdict — `WATCH` / `COINFLIP` / `AVOID`. Then it can run a
fully transparent **$20 experiment**: let an AI make the calls and log exactly how it
does, on a public scoreboard, over time.

No API keys. DexScreener's public API is keyless, and the analyst runs a local
rule-based judge out of the box — an LLM is optional.

![python](https://img.shields.io/badge/python-3.8%2B-3776AB?style=flat-square&logo=python&logoColor=white)
![api keys](https://img.shields.io/badge/API_keys-none_required-2ea44f?style=flat-square)
![license](https://img.shields.io/badge/license-MIT-black?style=flat-square)

---

## The experiment

> **Can an AI flip $20 in Solana memecoins without getting rugged?**

Most memecoin "AI bots" are black boxes that promise gains. `coinjury` does the opposite:
it starts with $20 of paper money, lets the judge open small positions in the *least-bad*
names it can find, marks them to live prices on every run, and writes the whole thing to
[`SCOREBOARD.md`](SCOREBOARD.md) — wins, losses, and all. The point isn't to get rich.
It's to find out, in the open, whether "safety-first + AI" beats a coinflip. (Spoiler:
memecoins are gambling. This is tuition, not a strategy.)

## What it looks like

```
 coinjury - 6 memecoins on trial (live @ DexScreener)

GIGA           Gigachad Sol
  verdict WATCH       risk   0/100 [--------------------]
  liq $180k   vol24h $900k   fdv $2.1M   age 140h
  No glaring red flags, but memecoins are still a coinflip. 24h +15%. Still risk-only money.

WOLF           Wolf Of Solana
  verdict COINFLIP    risk  40/100 [########------------]
  liq $22k    vol24h $500k   fdv $1.2M   age 40h
  Pure gamble. shallow liquidity (<$30k); volume/liquidity > 20x (wash / pump signature). Size like you'll lose it all.

RUGME          Rug Me Daddy
  verdict AVOID       risk  96/100 [###################-]
  liq $2k     vol24h $90k    fdv $400k   age 20h
  Hard pass. liquidity under $2k (trivially ruggable); pool < 24h old. 24h +120%.
```

## The rug checks

The risk score (0 = calm, 100 = ER visit) is built only from public, keyless data —
the same red flags a careful degen checks by hand, automated and weighted:

- **Honeypot / can't-sell** — near-zero sells against a wall of buys
- **Ruggable liquidity** — thin pools drain in one transaction
- **Fresh-pool landmines** — pools minutes to hours old
- **Wash / pump signature** — volume many multiples of liquidity
- **Thin float** — FDV dwarfing liquidity dumps hard
- **Exit pressure** — sells outpacing buys, violent 1h whipsaws

Safest-first ordering is about *survival odds*, not upside. `coinjury` never tells you
to buy anything.

## Install

```bash
git clone https://github.com/Overdusts/coinjury
cd coinjury
python coinjury.py scan --demo      # try it offline on bundled data, no setup
```

Only dependency for live mode is nothing — it uses the standard library. (`requests`
is listed but optional; the built-in client is keyless.)

## Usage

```bash
python coinjury.py scan                # trial the current trending memecoins (live)
python coinjury.py scan --demo         # run on bundled sample data (offline)
python coinjury.py judge <MINT>        # full rap sheet on one token
python coinjury.py challenge           # run / refresh the $20 paper experiment
python coinjury.py challenge --demo

# options
--limit N        how many to screen (default 12)
--min-liq USD    ignore pools below this liquidity (default 10000)
--ai             richer verdicts via an LLM if ANTHROPIC_API_KEY is set
```

## Optional AI analyst

By default the verdict text is written by a local rule-based judge — zero keys, fully
offline. Set `ANTHROPIC_API_KEY` and pass `--ai` to have a model write a blunter,
funnier take on each token instead. It falls back to the local judge on any error, so
the tool never breaks without it.

## How it works

```
DexScreener (keyless)  ->  rug-risk jury  ->  analyst (local | LLM)  ->  verdict
                                                                          |
                                       $20 paper bankroll  <-------------- challenge
                                                |
                                          SCOREBOARD.md  (committed, auditable)
```

## Not financial advice

This is a research and entertainment tool. It logs how an AI performs; it does not
recommend anything to you. Memecoins are among the riskiest things you can touch —
the overwhelming majority go to zero. Never put in money you can't afford to laugh off.

## License

MIT © Overdusts
