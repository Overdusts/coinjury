#!/usr/bin/env python3
"""
coinjury - put every Solana memecoin on trial before it puts your wallet in the ER.

Screens trending Solana memecoins, runs a rug-risk check on each, hands down an
AI verdict, and can run a transparent $20 paper experiment that logs exactly how
the AI's calls play out over time.

Zero API keys required. DexScreener's public API is keyless; the AI analyst falls
back to a fully local rule-based judge unless you opt into an LLM.

  python coinjury.py scan                 # trial the current trending memecoins
  python coinjury.py scan --demo          # run on bundled sample data (offline)
  python coinjury.py judge <MINT>         # trial one token by mint address
  python coinjury.py challenge            # run/refresh the $20 paper experiment
  python coinjury.py challenge --demo

  --limit N       how many to screen (default 12)
  --min-liq USD   ignore pools below this liquidity (default 10000)
  --ai            use an LLM analyst if ANTHROPIC_API_KEY is set (else local judge)

NOT FINANCIAL ADVICE. This is a research + entertainment tool. It logs how an AI
does; it does not tell you what to buy. Memecoins are ~gambling. Never risk money
you can't laugh about losing.
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

DEX = "https://api.dexscreener.com"
HERE = Path(__file__).resolve().parent
STATE = HERE / "positions.json"
SCOREBOARD = HERE / "SCOREBOARD.md"
SAMPLE = HERE / "sample_data.json"

# ---- tiny ANSI palette (degrades to plain on non-tty / Windows without VT) ----
_TTY = sys.stdout.isatty()
def _c(code, s):
    return f"\033[{code}m{s}\033[0m" if _TTY else s
RED    = lambda s: _c("91", s)
YELLOW = lambda s: _c("93", s)
GREEN  = lambda s: _c("92", s)
DIM    = lambda s: _c("90", s)
BOLD   = lambda s: _c("1",  s)


# --------------------------------------------------------------------------- #
#  Data                                                                       #
# --------------------------------------------------------------------------- #
def _now_ms():
    return int(time.time() * 1000)


def _http_json(url):
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "coinjury/1.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))


def _pair_to_token(p):
    """Flatten a DexScreener pair object into the shape coinjury reasons over."""
    base = p.get("baseToken", {}) or {}
    return {
        "name": base.get("name") or base.get("symbol") or "?",
        "symbol": base.get("symbol") or "?",
        "mint": base.get("address") or "",
        "priceUsd": float(p.get("priceUsd") or 0) or 0.0,
        "liquidityUsd": float((p.get("liquidity") or {}).get("usd") or 0),
        "volume24hUsd": float((p.get("volume") or {}).get("h24") or 0),
        "fdvUsd": float(p.get("fdv") or 0),
        "marketCapUsd": float(p.get("marketCap") or 0),
        "pairCreatedAt": int(p.get("pairCreatedAt") or 0),
        "priceChange": p.get("priceChange") or {},
        "txns24h": (p.get("txns") or {}).get("h24") or {},
        "url": p.get("url") or "",
    }


def fetch_trending(limit, demo=False):
    if demo:
        tokens = json.loads(SAMPLE.read_text(encoding="utf-8"))
        return tokens[:limit]
    # Keyless discovery: DexScreener's "top boosted" tokens are what's being
    # pushed right now - a decent proxy for trending. We then pull each token's
    # best Solana pair for real metrics.
    out = []
    try:
        boosts = _http_json(f"{DEX}/token-boosts/top/v1")
    except Exception as e:
        print(RED(f"! could not reach DexScreener: {e}"))
        return out
    seen = set()
    for b in boosts:
        if b.get("chainId") != "solana":
            continue
        mint = b.get("tokenAddress")
        if not mint or mint in seen:
            continue
        seen.add(mint)
        tok = best_pair(mint)
        if tok:
            out.append(tok)
        if len(out) >= limit:
            break
        time.sleep(0.12)  # be polite to the free API
    return out


def best_pair(mint):
    """Return the deepest-liquidity Solana pair for a mint, flattened."""
    try:
        data = _http_json(f"{DEX}/latest/dex/tokens/{mint}")
    except Exception:
        return None
    pairs = [p for p in (data.get("pairs") or []) if p.get("chainId") == "solana"]
    if not pairs:
        return None
    pairs.sort(key=lambda p: float((p.get("liquidity") or {}).get("usd") or 0), reverse=True)
    return _pair_to_token(pairs[0])


# --------------------------------------------------------------------------- #
#  The rug-risk jury (this is the security core)                              #
# --------------------------------------------------------------------------- #
def hours_since(ms):
    if not ms:
        return 9999
    return max(0.0, (_now_ms() - ms) / 3_600_000)


def rug_risk(t):
    """
    Heuristic 0-100 danger score built only from public, keyless pair data.
    Higher = more likely to hurt. Returns (score, flags) with the most severe
    flag first. These are the same red flags manual degens check by hand.
    """
    fl = []            # (weight, text) so display can lead with the worst
    def add(w, text):
        fl.append((w, text))

    liq = t.get("liquidityUsd", 0)
    vol = t.get("volume24hUsd", 0)
    fdv = t.get("fdvUsd", 0) or t.get("marketCapUsd", 0)
    age = hours_since(t.get("pairCreatedAt", 0))
    pc = t.get("priceChange", {}) or {}
    tx = t.get("txns24h", {}) or {}
    buys = float(tx.get("buys") or 0)
    sells = float(tx.get("sells") or 0)

    # can you even sell? near-zero sells vs many buys smells like a honeypot
    if buys >= 30 and sells <= max(1, buys * 0.12):
        add(25, "almost no sells vs buys (possible honeypot / can't-sell)")
    elif sells > buys * 2 and sells > 40:
        add(8, "sells heavily outpacing buys (holders exiting)")

    # thin liquidity = easy to drain
    if liq < 2_000:      add(40, "liquidity under $2k (trivially ruggable)")
    elif liq < 10_000:   add(25, "thin liquidity (<$10k)")
    elif liq < 30_000:   add(12, "shallow liquidity (<$30k)")
    elif liq < 75_000:   add(5,  "modest liquidity (<$75k)")

    # brand-new pools are landmines
    if age < 1:    add(25, "pool < 1h old (unproven, volatile)")
    elif age < 6:  add(15, "pool < 6h old")
    elif age < 24: add(8,  "pool < 24h old")

    # volume relative to liquidity: wash / pump signature
    if liq > 0:
        vlr = vol / liq
        if vlr > 20:  add(18, "volume/liquidity > 20x (wash / pump signature)")
        elif vlr > 8: add(10, "volume/liquidity > 8x (frothy)")

    # thin float on a big FDV dumps hard
    if liq > 0 and fdv > 0:
        flr = fdv / liq
        if flr > 100:  add(18, "FDV > 100x liquidity (tiny float, easy dump)")
        elif flr > 40: add(10, "FDV > 40x liquidity")

    # violent 1h move
    h1 = abs(float(pc.get("h1") or 0))
    if h1 > 60:   add(12, f"1h move {pc.get('h1')}% (whipsaw)")
    elif h1 > 30: add(6,  f"1h move {pc.get('h1')}%")

    score = max(0, min(100, sum(w for w, _ in fl)))
    flags = [text for _, text in sorted(fl, key=lambda x: -x[0])]
    return score, flags


def verdict_band(risk):
    if risk >= 70:
        return "AVOID", RED
    if risk >= 40:
        return "COINFLIP", YELLOW
    return "WATCH", GREEN


# --------------------------------------------------------------------------- #
#  The analyst                                                                #
# --------------------------------------------------------------------------- #
def local_verdict(t, risk, flags):
    band, _ = verdict_band(risk)
    top = flags[:2]
    reason = "; ".join(top) if top else "no glaring red flags, but memecoins are still a coinflip"
    mom = t.get("priceChange", {}).get("h24")
    mom_s = f" 24h {mom:+.0f}%." if isinstance(mom, (int, float)) else ""
    if band == "AVOID":
        return f"Hard pass. {reason}.{mom_s}"
    if band == "COINFLIP":
        return f"Pure gamble. {reason}.{mom_s} Size like you'll lose it all."
    return f"No glaring red flags, but {reason}.{mom_s} Still risk-only money."


def llm_verdict(t, risk, flags):
    """Optional richer take via Anthropic. Silently falls back on any error."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    model = os.environ.get("COINJURY_MODEL", "claude-haiku-4-5-20251001")
    prompt = (
        "You are a blunt, funny-but-honest Solana memecoin analyst. NOT financial "
        "advice. In 2 sentences max, give a verdict on this token. Be skeptical.\n\n"
        f"symbol: {t['symbol']}\nrisk_score(0-100,higher=worse): {risk}\n"
        f"liquidity_usd: {t.get('liquidityUsd')}\nfdv_usd: {t.get('fdvUsd')}\n"
        f"vol24h_usd: {t.get('volume24hUsd')}\nprice_change: {t.get('priceChange')}\n"
        f"red_flags: {flags}\n"
    )
    try:
        import urllib.request
        body = json.dumps({
            "model": model,
            "max_tokens": 160,
            "messages": [{"role": "user", "content": prompt}],
        }).encode()
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages", data=body,
            headers={
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode())
        return "".join(b.get("text", "") for b in data.get("content", [])).strip() or None
    except Exception:
        return None


def analyze(t, use_ai=False):
    risk, flags = rug_risk(t)
    take = (llm_verdict(t, risk, flags) if use_ai else None) or local_verdict(t, risk, flags)
    return risk, flags, take


# --------------------------------------------------------------------------- #
#  Rendering                                                                  #
# --------------------------------------------------------------------------- #
def fmt_usd(n):
    if n >= 1_000_000: return f"${n/1_000_000:.1f}M"
    if n >= 1_000:     return f"${n/1_000:.0f}k"
    return f"${n:.0f}"


def print_card(t, risk, flags, take):
    band, color = verdict_band(risk)
    head = f"{BOLD(t['symbol']):<14} {DIM(t['name'][:26])}"
    bar = color("#" * (risk // 5) + "-" * (20 - risk // 5))
    print(head)
    print(f"  verdict {color(BOLD(band)):<10}  risk {color(f'{risk:>3}/100')} [{bar}]")
    print(f"  liq {fmt_usd(t.get('liquidityUsd',0)):<7} vol24h {fmt_usd(t.get('volume24hUsd',0)):<7} "
          f"fdv {fmt_usd(t.get('fdvUsd',0)):<7} age {hours_since(t.get('pairCreatedAt',0)):.0f}h")
    print(f"  {DIM(take)}")
    if t.get("url"):
        print(f"  {DIM(t['url'])}")
    print()


def cmd_scan(args):
    toks = fetch_trending(args.limit, demo=args.demo)
    toks = [t for t in toks if t.get("liquidityUsd", 0) >= args.min_liq]
    if not toks:
        print(YELLOW("nothing passed the filter (try --demo, or lower --min-liq)"))
        return
    graded = []
    for t in toks:
        risk, flags, take = analyze(t, use_ai=args.ai)
        graded.append((risk, t, flags, take))
    graded.sort(key=lambda x: x[0])  # safest first
    print(BOLD(f"\n coinjury - {len(graded)} memecoins on trial "
               f"({'demo data' if args.demo else 'live @ DexScreener'})\n"))
    for risk, t, flags, take in graded:
        print_card(t, risk, flags, take)
    print(DIM(" not financial advice. safest-first ordering is about survival odds, not upside.\n"))


def cmd_judge(args):
    t = (json.loads(SAMPLE.read_text(encoding="utf-8"))[0] if args.demo
         else best_pair(args.mint))
    if not t:
        print(RED("no Solana pair found for that mint."))
        return
    risk, flags, take = analyze(t, use_ai=args.ai)
    print()
    print_card(t, risk, flags, take)
    if flags:
        print(DIM("  full rap sheet:"))
        for f in flags:
            print(f"   - {f}")
        print()


# --------------------------------------------------------------------------- #
#  The $20 paper experiment                                                   #
# --------------------------------------------------------------------------- #
START_CASH = 20.0
BET = 4.0        # $ per paper position
MAX_POS = 5


def load_state():
    if STATE.exists():
        return json.loads(STATE.read_text(encoding="utf-8"))
    return {"startedAt": datetime.now(timezone.utc).isoformat(),
            "startCash": START_CASH, "cash": START_CASH,
            "positions": [], "log": []}


def save_state(s):
    STATE.write_text(json.dumps(s, indent=2), encoding="utf-8")


def cmd_challenge(args):
    s = load_state()
    toks = fetch_trending(args.limit, demo=args.demo)
    prices = {t["mint"]: t for t in toks}
    ts = datetime.now(timezone.utc).isoformat()

    # 1) mark open positions to market, close the ones whose risk turned ugly
    still_open = []
    for pos in s["positions"]:
        cur = prices.get(pos["mint"])
        px = cur["priceUsd"] if cur else pos["entry"]
        pos["last"] = px
        risk = rug_risk(cur)[0] if cur else 100
        turned = cur and (px <= pos["entry"] * 0.6 or risk >= 70)
        if turned:
            val = pos["amount"] * (px / pos["entry"]) if pos["entry"] else 0
            s["cash"] += val
            s["log"].append({"t": ts, "action": "SELL", "sym": pos["sym"],
                             "pnl": round(val - pos["amount"], 2)})
        else:
            still_open.append(pos)
    s["positions"] = still_open

    # 2) the AI opens new paper positions in the least-bad names it can afford
    held = {p["mint"] for p in s["positions"]}
    ranked = sorted(((rug_risk(t)[0], t) for t in toks), key=lambda x: x[0])
    for risk, t in ranked:
        if len(s["positions"]) >= MAX_POS or s["cash"] < BET:
            break
        h24 = float((t.get("priceChange") or {}).get("h24") or 0)
        if t["mint"] in held or risk >= 40 or t["priceUsd"] <= 0 or h24 <= -25:
            continue  # skip held, risky, priceless, or already dumping names
        s["cash"] -= BET
        s["positions"].append({"sym": t["symbol"], "mint": t["mint"],
                               "entry": t["priceUsd"], "last": t["priceUsd"],
                               "amount": BET, "openedAt": ts})
        s["log"].append({"t": ts, "action": "BUY", "sym": t["symbol"], "risk": risk})

    save_state(s)
    write_scoreboard(s)
    equity = s["cash"] + sum(p["amount"] * (p["last"] / p["entry"]) for p in s["positions"] if p["entry"])
    pct = (equity / s["startCash"] - 1) * 100
    col = GREEN if pct >= 0 else RED
    print(BOLD("\n coinjury - the $20 experiment\n"))
    print(f"  equity {col(f'${equity:.2f}')}  ({col(f'{pct:+.1f}%')} vs ${s['startCash']:.0f})   "
          f"cash ${s['cash']:.2f}   open {len(s['positions'])}")
    print(DIM(f"  scoreboard written to {SCOREBOARD.name} - not financial advice\n"))


def write_scoreboard(s):
    equity = s["cash"] + sum(p["amount"] * (p["last"] / p["entry"]) for p in s["positions"] if p["entry"])
    pct = (equity / s["startCash"] - 1) * 100
    lines = [
        "# coinjury - the $20 experiment",
        "",
        f"> Can an AI flip **$20** in Solana memecoins without getting rugged? "
        f"Every call below is logged automatically. **Not financial advice.**",
        "",
        f"**Equity:** ${equity:.2f} ({pct:+.1f}% vs ${s['startCash']:.0f}) &nbsp;|&nbsp; "
        f"**Cash:** ${s['cash']:.2f} &nbsp;|&nbsp; **Open:** {len(s['positions'])} &nbsp;|&nbsp; "
        f"started {s['startedAt'][:10]}",
        "",
        "### Open positions",
        "",
        "| token | entry | last | value | pnl |",
        "|---|---|---|---|---|",
    ]
    if s["positions"]:
        for p in s["positions"]:
            val = p["amount"] * (p["last"] / p["entry"]) if p["entry"] else 0
            lines.append(f"| {p['sym']} | ${p['entry']:.6f} | ${p['last']:.6f} | "
                         f"${val:.2f} | {val - p['amount']:+.2f} |")
    else:
        lines.append("| _flat - all in cash_ | | | | |")
    lines += ["", "### Recent calls", ""]
    for e in s["log"][-12:][::-1]:
        extra = f"pnl {e['pnl']:+.2f}" if "pnl" in e else f"risk {e.get('risk','?')}"
        lines.append(f"- `{e['t'][:16]}` **{e['action']}** {e['sym']} ({extra})")
    lines += ["", "---", "_Generated by coinjury. Paper trading. Memecoins are gambling._"]
    SCOREBOARD.write_text("\n".join(lines) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- #
def main():
    p = argparse.ArgumentParser(prog="coinjury", description="put memecoins on trial")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("scan", "challenge"):
        sp = sub.add_parser(name)
        sp.add_argument("--limit", type=int, default=12)
        sp.add_argument("--min-liq", type=float, default=10_000)
        sp.add_argument("--demo", action="store_true")
        sp.add_argument("--ai", action="store_true")
    jp = sub.add_parser("judge")
    jp.add_argument("mint", nargs="?", default="")
    jp.add_argument("--demo", action="store_true")
    jp.add_argument("--ai", action="store_true")

    args = p.parse_args()
    if args.cmd == "scan":
        cmd_scan(args)
    elif args.cmd == "judge":
        cmd_judge(args)
    elif args.cmd == "challenge":
        cmd_challenge(args)


if __name__ == "__main__":
    main()
