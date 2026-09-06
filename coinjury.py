#!/usr/bin/env python3
"""
coinjury - put every Solana memecoin on trial before it puts your wallet in the ER.

Screens trending Solana memecoins, runs a keyless rug-risk check on each, hands
down a verdict, and can run a transparent $20 paper experiment that logs how the
AI's calls play out over time.

Risk is scored in two layers:
  - critical gates (mint/freeze authority live, honeypot, high transfer tax,
    RugCheck "rugged") floor the score at AVOID no matter what else looks good;
  - weighted penalties (liquidity, LP lock, holder/market froth, age) sum on top.

On-chain facts come from public, keyless sources - RugCheck, the Solana JSON-RPC,
and a Jupiter sell-route quote - and every one degrades gracefully, so the tool
still runs offline or when an API is down (it just says what it couldn't check).

  python coinjury.py scan                  # trial the current trending memecoins
  python coinjury.py scan --demo           # bundled sample data, offline, no calls
  python coinjury.py judge <MINT>          # full rap sheet on one token
  python coinjury.py challenge             # run / refresh the $20 paper experiment

  --limit N        how many to screen (default 12)
  --min-liq USD    ignore pools below this liquidity (default 10000)
  --no-enrich      skip on-chain checks (faster, market-data heuristic only)
  --ai             richer verdicts via an LLM if ANTHROPIC_API_KEY is set
  --json           machine-readable output
  --version

NOT FINANCIAL ADVICE. Research and entertainment only. coinjury reads public data,
never touches your keys, and never tells you to buy anything. Memecoins are
gambling; the overwhelming majority go to zero. See DISCLAIMER.md.
"""

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

__version__ = "2.0.0"

HERE = Path(__file__).resolve().parent
STATE = HERE / "positions.json"
SCOREBOARD = HERE / "SCOREBOARD.md"
SAMPLE = HERE / "sample_data.json"

DEX = "https://api.dexscreener.com"
RUGCHECK = "https://api.rugcheck.xyz/v1"
JUP = "https://lite-api.jup.ag"
RPC = "https://api.mainnet-beta.solana.com"
SOL_MINT = "So11111111111111111111111111111111111111112"

# colour only on a real terminal, and honour the NO_COLOR convention
_COLOR = sys.stdout.isatty() and not os.environ.get("NO_COLOR")
def _c(code, s):
    return f"\033[{code}m{s}\033[0m" if _COLOR else s
RED    = lambda s: _c("91", s)
YELLOW = lambda s: _c("93", s)
GREEN  = lambda s: _c("92", s)
DIM    = lambda s: _c("90", s)
BOLD   = lambda s: _c("1",  s)


# --------------------------------------------------------------------------- #
#  HTTP helpers                                                               #
# --------------------------------------------------------------------------- #
def _now_ms():
    return int(time.time() * 1000)

def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None

def _http(url, payload=None, timeout=12):
    """GET, or POST when payload is given. Returns parsed JSON (raises on error)."""
    headers = {"User-Agent": f"coinjury/{__version__}"}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers,
                                 method="POST" if data else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


# --------------------------------------------------------------------------- #
#  Discovery + market data (DexScreener, keyless)                             #
# --------------------------------------------------------------------------- #
def _pair_to_token(p):
    base = p.get("baseToken") or {}
    return {
        "name": base.get("name") or base.get("symbol") or "?",
        "symbol": base.get("symbol") or "?",
        "mint": base.get("address") or "",
        "priceUsd": _f(p.get("priceUsd")) or 0.0,
        "liquidityUsd": _f((p.get("liquidity") or {}).get("usd")) or 0.0,
        "volume24hUsd": _f((p.get("volume") or {}).get("h24")) or 0.0,
        "fdvUsd": _f(p.get("fdv")) or 0.0,
        "marketCapUsd": _f(p.get("marketCap")) or 0.0,
        "pairCreatedAt": int(p.get("pairCreatedAt") or 0),
        "priceChange": p.get("priceChange") or {},
        "txns24h": (p.get("txns") or {}).get("h24") or {},
        "url": p.get("url") or "",
    }

def best_pair(mint):
    """Deepest-liquidity Solana pair for a mint, flattened; None if not found."""
    try:
        data = _http(f"{DEX}/latest/dex/tokens/{mint}")
    except Exception:
        return None
    pairs = [p for p in (data.get("pairs") or []) if p.get("chainId") == "solana"]
    if not pairs:
        return None
    pairs.sort(key=lambda p: _f((p.get("liquidity") or {}).get("usd")) or 0, reverse=True)
    return _pair_to_token(pairs[0])

def fetch_trending(limit, demo=False):
    if demo:
        return json.loads(SAMPLE.read_text(encoding="utf-8"))[:limit]
    try:
        boosts = _http(f"{DEX}/token-boosts/top/v1")
    except Exception as e:
        print(RED(f"! could not reach DexScreener: {e}"))
        return []
    out, seen = [], set()
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
        time.sleep(0.12)
    return out


# --------------------------------------------------------------------------- #
#  On-chain enrichment (keyless, best-effort, never fatal)                    #
# --------------------------------------------------------------------------- #
def _rugcheck(mint):
    j = _http(f"{RUGCHECK}/tokens/{mint}/report", timeout=12)
    lp_pcts = [m["lp"].get("lpLockedPct") for m in (j.get("markets") or []) if m.get("lp")]
    lp_pcts = [x for x in lp_pcts if isinstance(x, (int, float))]
    danger = [r.get("name") for r in (j.get("risks") or [])
              if r.get("level") == "danger" and r.get("name")]
    return {
        "mintAuth": j.get("mintAuthority"),
        "freezeAuth": j.get("freezeAuthority"),
        "rugged": bool(j.get("rugged")),
        "lpLockedPct": max(lp_pcts) if lp_pcts else None,
        "transferFeePct": _f((j.get("transferFee") or {}).get("pct")),
        "rcScore": j.get("score_normalised"),
        "dangerRisks": danger,
    }

def _rpc_authorities(mint):
    j = _http(RPC, payload={"jsonrpc": "2.0", "id": 1, "method": "getAccountInfo",
                            "params": [mint, {"encoding": "jsonParsed"}]}, timeout=12)
    data = (((j.get("result") or {}).get("value") or {}).get("data") or {})
    info = (data.get("parsed") or {}).get("info") or {}
    return {"mintAuth": info.get("mintAuthority"),
            "freezeAuth": info.get("freezeAuthority"),
            "program": data.get("program")}

def _jupiter_sellable(mint):
    """True/False if a sell route to SOL exists; None if we couldn't tell."""
    url = (f"{JUP}/swap/v1/quote?inputMint={mint}&outputMint={SOL_MINT}"
           f"&amount=1000000&slippageBps=200")
    try:
        j = _http(url, timeout=10)
        return (int(j.get("outAmount") or 0) > 0), _f(j.get("priceImpactPct"))
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", "replace").lower()
        except Exception:
            body = ""
        if "route" in body:          # explicit "no route" = unsellable
            return False, None
        return None, None
    except Exception:
        return None, None

def enrich(mint):
    """Merge keyless on-chain facts. Returns a dict (with 'src' list) or None."""
    if not mint:
        return None
    info = {"src": []}
    try:
        info.update(_rugcheck(mint)); info["src"].append("rugcheck")
    except Exception:
        pass
    try:
        rpc = _rpc_authorities(mint)
        info["src"].append("rpc")
        # RPC is ground truth for authorities; flag if RugCheck disagreed
        if rpc.get("mintAuth") and not info.get("mintAuth"):
            info["authMismatch"] = True
        if rpc.get("freezeAuth") and not info.get("freezeAuth"):
            info["authMismatch"] = True
        info["mintAuth"] = rpc.get("mintAuth", info.get("mintAuth"))
        info["freezeAuth"] = rpc.get("freezeAuth", info.get("freezeAuth"))
        info["program"] = rpc.get("program")
    except Exception:
        pass
    sellable, impact = _jupiter_sellable(mint)
    if sellable is not None:
        info["src"].append("jupiter")
    info["sellable"] = sellable
    info["priceImpactPct"] = impact
    return info if info["src"] else None


# --------------------------------------------------------------------------- #
#  Scoring - two layers                                                       #
# --------------------------------------------------------------------------- #
def hours_since(ms):
    return 9999.0 if not ms else max(0.0, (_now_ms() - ms) / 3_600_000)

def base_flags(t):
    """Market-data heuristics from public pair data -> list of (weight, text)."""
    fl = []
    liq = t.get("liquidityUsd", 0)
    vol = t.get("volume24hUsd", 0)
    fdv = t.get("fdvUsd", 0) or t.get("marketCapUsd", 0)
    age = hours_since(t.get("pairCreatedAt", 0))
    pc = t.get("priceChange") or {}
    tx = t.get("txns24h") or {}
    buys, sells = _f(tx.get("buys")) or 0, _f(tx.get("sells")) or 0

    if buys >= 30 and sells <= max(1, buys * 0.12):
        fl.append((25, "almost no sells vs buys (possible honeypot / can't-sell)"))
    elif sells > buys * 2 and sells > 40:
        fl.append((8, "sells heavily outpacing buys (holders exiting)"))

    if liq < 2_000:    fl.append((40, "liquidity under $2k (trivially ruggable)"))
    elif liq < 10_000: fl.append((25, "thin liquidity (<$10k)"))
    elif liq < 30_000: fl.append((12, "shallow liquidity (<$30k)"))
    elif liq < 75_000: fl.append((5,  "modest liquidity (<$75k)"))

    if age < 1:    fl.append((25, "pool < 1h old (unproven, volatile)"))
    elif age < 6:  fl.append((15, "pool < 6h old"))
    elif age < 24: fl.append((8,  "pool < 24h old"))

    if liq > 0:
        vlr = vol / liq
        if vlr > 20:  fl.append((18, "volume/liquidity > 20x (wash / pump signature)"))
        elif vlr > 8: fl.append((10, "volume/liquidity > 8x (frothy)"))
    if liq > 0 and fdv > 0:
        flr = fdv / liq
        if flr > 100:  fl.append((18, "FDV > 100x liquidity (tiny float, easy dump)"))
        elif flr > 40: fl.append((10, "FDV > 40x liquidity"))

    h1 = abs(_f(pc.get("h1")) or 0)
    if h1 > 60:   fl.append((12, f"1h move {pc.get('h1')}% (whipsaw)"))
    elif h1 > 30: fl.append((6,  f"1h move {pc.get('h1')}%"))
    return fl

def onchain_flags(info):
    """On-chain signals -> (list of (weight, text), gate_tripped)."""
    fl, gate = [], False
    if info.get("mintAuth"):
        fl.append((25, "mint authority active (dev can infinite-mint)")); gate = True
    if info.get("freezeAuth"):
        fl.append((20, "freeze authority active (dev can freeze your tokens)")); gate = True
    if info.get("rugged"):
        fl.append((40, "RugCheck flags this token as already rugged")); gate = True
    tf = info.get("transferFeePct")
    if isinstance(tf, (int, float)) and tf > 0:
        if tf > 10:
            fl.append((min(int(tf), 40), f"transfer tax {tf:g}% (soft honeypot)")); gate = True
        else:
            fl.append((int(tf * 1.5), f"transfer tax {tf:g}%"))
    lp = info.get("lpLockedPct")
    if isinstance(lp, (int, float)):
        if lp < 50:   fl.append((20, f"only {lp:.0f}% of LP locked/burned (ruggable)"))
        elif lp < 90: fl.append((8,  f"{lp:.0f}% of LP locked"))
    if info.get("sellable") is False:
        fl.append((40, "no sell route to SOL (possible honeypot)"))
    if info.get("authMismatch"):
        fl.append((10, "on-chain authority disagrees with RugCheck (stale data?)"))
    for name in (info.get("dangerRisks") or [])[:2]:
        low = name.lower()
        if "authorit" in low or "liquidit" in low or "lp" in low:
            continue  # already counted above
        fl.append((8, f"RugCheck: {name}"))
    return fl, gate

def score_of(fl):
    return max(0, min(100, sum(w for w, _ in fl)))

def verdict_band(risk):
    if risk >= 70:
        return "AVOID", RED
    if risk >= 40:
        return "COINFLIP", YELLOW
    return "WATCH", GREEN

def assess(t, info=None):
    """Combine heuristics + on-chain facts. Returns (risk, band, flags[])."""
    fl = base_flags(t)
    gate = False
    if info:
        onc, gate = onchain_flags(info)
        fl += onc
    risk = score_of(fl)
    if gate:
        risk = max(risk, 75)
    band, _ = verdict_band(risk)
    flags = [txt for _, txt in sorted(fl, key=lambda x: -x[0])]
    return risk, band, flags


# --------------------------------------------------------------------------- #
#  Analyst (local rule-based; optional LLM)                                   #
# --------------------------------------------------------------------------- #
def local_verdict(t, risk, band, flags):
    mom = _f((t.get("priceChange") or {}).get("h24"))
    mom_s = f" 24h {mom:+.0f}%." if mom is not None else ""
    if not flags:
        return f"Nothing obviously wrong on the checks I ran.{mom_s} Still a coinflip - risk-only money."
    reason = "; ".join(flags[:2])
    if band == "AVOID":
        return f"Hard pass. {reason}.{mom_s}"
    if band == "COINFLIP":
        return f"Pure gamble. {reason}.{mom_s} Size like you'll lose it all."
    return f"No glaring killers, but {reason}.{mom_s} Still risk-only money."

def llm_verdict(t, risk, flags):
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    model = os.environ.get("COINJURY_MODEL", "claude-haiku-4-5-20251001")
    prompt = ("You are a blunt, funny-but-honest Solana memecoin analyst. NOT "
              "financial advice. In 2 sentences max, give a skeptical verdict.\n\n"
              f"symbol: {t['symbol']}\nrisk(0-100,worse=higher): {risk}\n"
              f"liquidity_usd: {t.get('liquidityUsd')}\nred_flags: {flags}\n")
    try:
        body = json.dumps({"model": model, "max_tokens": 160,
                           "messages": [{"role": "user", "content": prompt}]}).encode()
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages", data=body,
            headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode())
        return "".join(b.get("text", "") for b in data.get("content", [])).strip() or None
    except Exception:
        return None

def verdict_text(t, risk, band, flags, use_ai):
    return (llm_verdict(t, risk, flags) if use_ai else None) or \
           local_verdict(t, risk, band, flags)


# --------------------------------------------------------------------------- #
#  Rendering                                                                  #
# --------------------------------------------------------------------------- #
def fmt_usd(n):
    n = n or 0
    if n >= 1_000_000: return f"${n/1_000_000:.1f}M"
    if n >= 1_000:     return f"${n/1_000:.0f}k"
    return f"${n:.0f}"

def print_card(t, risk, band, flags, take, info):
    color = {"AVOID": RED, "COINFLIP": YELLOW, "WATCH": GREEN}[band]
    bar = color("#" * (risk // 5) + "-" * (20 - risk // 5))
    print(f"{BOLD(t['symbol']):<14} {DIM(t['name'][:26])}")
    print(f"  verdict {color(BOLD(band)):<10}  risk {color(f'{risk:>3}/100')} [{bar}]")
    print(f"  liq {fmt_usd(t.get('liquidityUsd')):<7} vol24h {fmt_usd(t.get('volume24hUsd')):<7} "
          f"fdv {fmt_usd(t.get('fdvUsd')):<7} age {hours_since(t.get('pairCreatedAt',0)):.0f}h")
    print(f"  {DIM(take)}")
    if info and info.get("src"):
        checked = " + ".join(info["src"])
        rc = info.get("rcScore")
        extra = f" | rugcheck {rc}/100" if isinstance(rc, (int, float)) else ""
        print(f"  {DIM('on-chain checked: ' + checked + extra)}")
    elif info is None:
        print(f"  {DIM('on-chain checks unavailable (market-data heuristic only)')}")
    if t.get("url"):
        print(f"  {DIM(t['url'])}")
    print()

def to_record(t, risk, band, flags, take, info):
    return {"symbol": t.get("symbol"), "mint": t.get("mint"), "risk": risk,
            "verdict": band, "reasons": flags, "take": take,
            "liquidityUsd": t.get("liquidityUsd"), "fdvUsd": t.get("fdvUsd"),
            "checked": (info or {}).get("src", []), "url": t.get("url")}


# --------------------------------------------------------------------------- #
#  Commands                                                                   #
# --------------------------------------------------------------------------- #
def _enrich_for(t, args):
    if args.demo or args.no_enrich:
        return None
    return enrich(t.get("mint"))

def cmd_scan(args):
    toks = [t for t in fetch_trending(args.limit, demo=args.demo)
            if t.get("liquidityUsd", 0) >= args.min_liq]
    if not toks:
        print(YELLOW("nothing passed the filter (try --demo, or lower --min-liq)"))
        return
    graded = []
    for t in toks:
        info = _enrich_for(t, args)
        risk, band, flags = assess(t, info)
        take = verdict_text(t, risk, band, flags, args.ai)
        graded.append((risk, t, band, flags, take, info))
    graded.sort(key=lambda x: x[0])
    if args.json:
        print(json.dumps([to_record(t, r, b, f, tk, i)
                          for r, t, b, f, tk, i in graded], indent=2))
        return
    print(BOLD(f"\n coinjury {__version__} - {len(graded)} memecoins on trial "
               f"({'demo data' if args.demo else 'live'})\n"))
    for risk, t, band, flags, take, info in graded:
        print_card(t, risk, band, flags, take, info)
    print(DIM(" not financial advice. safest-first ordering is about survival odds, not upside.\n"))

def cmd_judge(args):
    if args.demo:
        t = json.loads(SAMPLE.read_text(encoding="utf-8"))[0]
    elif not args.mint:
        print(RED("usage: coinjury judge <MINT>  (or --demo)"))
        return
    else:
        t = best_pair(args.mint)
    if not t:
        print(RED("no Solana pair found for that mint."))
        return
    info = _enrich_for(t, args)
    risk, band, flags = assess(t, info)
    take = verdict_text(t, risk, band, flags, args.ai)
    if args.json:
        print(json.dumps(to_record(t, risk, band, flags, take, info), indent=2))
        return
    print()
    print_card(t, risk, band, flags, take, info)
    if flags:
        print(DIM("  full rap sheet:"))
        for f in flags:
            print(f"   - {f}")
        print()


# --------------------------------------------------------------------------- #
#  The $20 paper experiment                                                   #
# --------------------------------------------------------------------------- #
START_CASH, BET, MAX_POS = 20.0, 4.0, 5

def rank_by_risk(toks, graded):
    """Tokens safest-first. Keyed sort so equal-risk ties never compare dicts."""
    return sorted(toks, key=lambda t: graded.get(t["mint"], 100))

def load_state():
    if STATE.exists():
        return json.loads(STATE.read_text(encoding="utf-8"))
    return {"startedAt": datetime.now(timezone.utc).isoformat(),
            "startCash": START_CASH, "cash": START_CASH, "positions": [], "log": []}

def _equity(s):
    return s["cash"] + sum(p["amount"] * (p["last"] / p["entry"])
                           for p in s["positions"] if p["entry"])

def cmd_challenge(args):
    s = load_state()
    toks = fetch_trending(args.limit, demo=args.demo)
    priced = {t["mint"]: t for t in toks}
    graded = {}
    for t in toks:
        info = _enrich_for(t, args)
        graded[t["mint"]] = assess(t, info)[0]
    ts = datetime.now(timezone.utc).isoformat()

    kept = []
    for pos in s["positions"]:
        cur = priced.get(pos["mint"])
        px = cur["priceUsd"] if cur else pos["entry"]
        pos["last"] = px
        risk = graded.get(pos["mint"], 100)
        if cur and (px <= pos["entry"] * 0.6 or risk >= 70):
            val = pos["amount"] * (px / pos["entry"]) if pos["entry"] else 0
            s["cash"] += val
            s["log"].append({"t": ts, "action": "SELL", "sym": pos["sym"],
                             "pnl": round(val - pos["amount"], 2)})
        else:
            kept.append(pos)
    s["positions"] = kept

    held = {p["mint"] for p in s["positions"]}
    for t in rank_by_risk(toks, graded):
        risk = graded.get(t["mint"], 100)
        if len(s["positions"]) >= MAX_POS or s["cash"] < BET:
            break
        h24 = _f((t.get("priceChange") or {}).get("h24")) or 0
        if t["mint"] in held or risk >= 40 or t["priceUsd"] <= 0 or h24 <= -25:
            continue
        s["cash"] -= BET
        s["positions"].append({"sym": t["symbol"], "mint": t["mint"],
                               "entry": t["priceUsd"], "last": t["priceUsd"],
                               "amount": BET, "openedAt": ts})
        s["log"].append({"t": ts, "action": "BUY", "sym": t["symbol"], "risk": risk})

    STATE.write_text(json.dumps(s, indent=2), encoding="utf-8")
    write_scoreboard(s)
    eq = _equity(s)
    pct = (eq / s["startCash"] - 1) * 100
    col = GREEN if pct >= 0 else RED
    print(BOLD("\n coinjury - the $20 experiment\n"))
    print(f"  equity {col(f'${eq:.2f}')}  ({col(f'{pct:+.1f}%')} vs ${s['startCash']:.0f})   "
          f"cash ${s['cash']:.2f}   open {len(s['positions'])}")
    print(DIM(f"  scoreboard -> {SCOREBOARD.name} - not financial advice\n"))

def write_scoreboard(s):
    eq = _equity(s)
    pct = (eq / s["startCash"] - 1) * 100
    L = ["# coinjury - the $20 experiment", "",
         "> Can an AI flip **$20** in Solana memecoins without getting rugged? "
         "Every call is logged automatically. **Not financial advice.**", "",
         f"**Equity:** ${eq:.2f} ({pct:+.1f}% vs ${s['startCash']:.0f}) &nbsp;|&nbsp; "
         f"**Cash:** ${s['cash']:.2f} &nbsp;|&nbsp; **Open:** {len(s['positions'])} &nbsp;|&nbsp; "
         f"started {s['startedAt'][:10]}", "",
         "### Open positions", "", "| token | entry | last | value | pnl |",
         "|---|---|---|---|---|"]
    if s["positions"]:
        for p in s["positions"]:
            val = p["amount"] * (p["last"] / p["entry"]) if p["entry"] else 0
            L.append(f"| {p['sym']} | ${p['entry']:.6f} | ${p['last']:.6f} | "
                     f"${val:.2f} | {val - p['amount']:+.2f} |")
    else:
        L.append("| _flat - all in cash_ | | | | |")
    L += ["", "### Recent calls", ""]
    for e in s["log"][-12:][::-1]:
        extra = f"pnl {e['pnl']:+.2f}" if "pnl" in e else f"risk {e.get('risk','?')}"
        L.append(f"- `{e['t'][:16]}` **{e['action']}** {e['sym']} ({extra})")
    L += ["", "---", "_Generated by coinjury. Paper trading. Memecoins are gambling._"]
    SCOREBOARD.write_text("\n".join(L) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- #
def build_parser():
    p = argparse.ArgumentParser(prog="coinjury", description="put memecoins on trial")
    p.add_argument("--version", action="version", version=f"coinjury {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)
    def common(sp):
        sp.add_argument("--limit", type=int, default=12)
        sp.add_argument("--min-liq", type=float, default=10_000)
        sp.add_argument("--demo", action="store_true")
        sp.add_argument("--no-enrich", action="store_true")
        sp.add_argument("--ai", action="store_true")
        sp.add_argument("--json", action="store_true")
    common(sub.add_parser("scan"))
    common(sub.add_parser("challenge"))
    jp = sub.add_parser("judge"); common(jp); jp.add_argument("mint", nargs="?", default="")
    return p

def main(argv=None):
    args = build_parser().parse_args(argv)
    {"scan": cmd_scan, "judge": cmd_judge, "challenge": cmd_challenge}[args.cmd](args)

if __name__ == "__main__":
    main()
