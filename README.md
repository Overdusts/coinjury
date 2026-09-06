# coinjury

**Put every Solana memecoin on trial before it puts your wallet in the ER.**

`coinjury` pulls the memecoins trending *right now*, runs each one through real
on-chain rug checks, and hands down a verdict — `WATCH` / `COINFLIP` / `AVOID`.
Then it can run a transparent **$20 experiment**: let an AI make the calls and log
exactly how it does, on a public scoreboard, over time.

No API keys required. Every data source is keyless, and if one is down the tool
degrades gracefully instead of breaking.

![python](https://img.shields.io/badge/python-3.8%2B-3776AB?style=flat-square&logo=python&logoColor=white)
![api keys](https://img.shields.io/badge/API_keys-none_required-2ea44f?style=flat-square)
![tests](https://img.shields.io/badge/tests-passing-2ea44f?style=flat-square)
![license](https://img.shields.io/badge/license-MIT-black?style=flat-square)

> **Not financial advice.** coinjury reads public data, never touches your keys, and
> never tells you to buy anything. Memecoins are gambling — most go to zero. See
> [DISCLAIMER.md](DISCLAIMER.md).

---

## The experiment

> **Can an AI flip $20 in Solana memecoins without getting rugged?**

Most memecoin "AI bots" are black boxes that promise gains. `coinjury` does the
opposite: it starts with $20 of paper money, lets the judge open small positions in
the *least-bad* names it can find, marks them to live prices, and commits the whole
thing to [`SCOREBOARD.md`](SCOREBOARD.md) — wins, losses, and all — on a daily
schedule. The point isn't to get rich. It's to find out, in the open, whether
safety-first + AI beats a coinflip. (Spoiler: memecoins are gambling. This is
tuition, not a strategy.)

## What it looks like

```
Bonk           Bonk
  verdict WATCH       risk  18/100 [###-----------------]
  liq $333k   vol24h $762k   fdv $304.4M  age 32429h
  No glaring killers, but FDV > 100x liquidity (tiny float, easy dump). 24h +5%. Still risk-only money.
  on-chain checked: rugcheck + rpc + jupiter | rugcheck 7/100

RUGME          Rug Me Daddy
  verdict AVOID       risk  96/100 [###################-]
  liq $2k     vol24h $90k    fdv $400k    age 20h
  Hard pass. mint authority active (dev can infinite-mint); liquidity under $2k. 24h +120%.
```

## How the score works — two layers

**Critical gates** floor the score at `AVOID` no matter how good everything else
looks. Any one of these and the token fails:

- **mint authority still active** — dev can infinite-mint and dilute you to zero
- **freeze authority still active** — dev can freeze your tokens so you can't sell
- **no sell route** — you can buy but can't sell (honeypot)
- **transfer tax > 10%** — a soft honeypot
- **RugCheck marks it already rugged**

**Weighted penalties** then sum on top: LP not burned/locked, ruggable liquidity,
holder/market froth (volume ≫ liquidity, tiny float), violent price swings, and
brand-new pools.

Signals come from **public, keyless** sources and cross-check each other:

| source | gives |
|---|---|
| **Solana JSON-RPC** | mint / freeze authority — ground truth, read straight from chain |
| **RugCheck** | LP-locked %, transfer tax, "rugged" flag, holder/insider risks, composite |
| **Jupiter** | a real sell-route quote — can you actually get out? |
| **DexScreener** | liquidity, FDV, volume, age (discovery + market data) |

When two sources disagree (e.g. RugCheck says renounced but the chain says active),
coinjury trusts the chain and flags the mismatch. Safest-first ordering is about
*survival odds*, not upside — and the tool never tells you to buy.

## Install

```bash
git clone https://github.com/Overdusts/coinjury
cd coinjury
python coinjury.py scan --demo      # try it offline on bundled data, no setup
```

No dependencies to install — coinjury runs on the Python standard library.

## Usage

```bash
python coinjury.py scan                # trial the current trending memecoins (live)
python coinjury.py scan --demo         # bundled sample data, offline, no calls
python coinjury.py judge <MINT>        # full rap sheet on one token
python coinjury.py challenge           # run / refresh the $20 paper experiment

# options
--limit N        how many to screen (default 12)
--min-liq USD    ignore pools below this liquidity (default 10000)
--no-enrich      skip on-chain checks (faster, market-data heuristic only)
--ai             richer verdicts via an LLM if ANTHROPIC_API_KEY is set
--json           machine-readable output
--version
```

## Optional AI analyst

By default the verdict text is written by a local rule-based judge — zero keys,
fully offline. Set `ANTHROPIC_API_KEY` and pass `--ai` to have a model write a
blunter take instead. It falls back to the local judge on any error, so the tool
never breaks without it.

## Tests

```bash
python -m unittest discover -s tests -v
```

Offline unit tests cover the scoring gates, penalties, verdict bands, graceful
degradation, and the full demo pipeline.

## What coinjury can't see

Be honest with yourself about the limits. coinjury cannot detect off-chain team
intent, a slow rug (a dev who dumps next week), a coordinated social pump, a future
CEX listing, or a brand-new scam pattern its rules don't encode yet. It measures
*on-chain and market survival odds* at one moment — not the future, and not upside.

## Privacy

coinjury collects nothing about you: no analytics, no telemetry, no account. It
runs entirely on your machine. In live mode it sends token **mint addresses**
(public info) to the public APIs above to fetch data; `--demo` makes no network
calls at all. With `--ai`, token metrics are sent to Anthropic. See
[SECURITY.md](SECURITY.md).

## Not financial advice

This is a research and entertainment tool. It logs how an AI performs; it does not
recommend anything to you. Memecoins are among the riskiest things you can touch —
the overwhelming majority go to zero. Never put in money you can't afford to lose.
Full terms in [DISCLAIMER.md](DISCLAIMER.md).

## License

MIT © Overdusts
