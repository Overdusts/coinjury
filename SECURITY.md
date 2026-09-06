# Security & Privacy

## Threat model — what coinjury does and doesn't touch
- **Read-only.** coinjury only *reads* public data. It never sends transactions.
- **Never handles keys.** It does not ask for, store, or transmit private keys,
  seed phrases, or wallet connections. It cannot move funds. There is nothing for
  it to drain.
- **No telemetry.** It collects no analytics and phones no home server.
- **Zero required dependencies.** It runs on the Python standard library, so there
  is no third-party package supply chain to compromise.

## What leaves your machine (live mode only)
In live mode coinjury makes outbound requests to public APIs to fetch data —
DexScreener, RugCheck, Jupiter, and a Solana RPC endpoint. It sends only token
**mint addresses** (public information). Those services have their own terms and
privacy policies. Demo mode (`--demo`) makes no network calls at all.

## Optional AI
With `--ai` and an `ANTHROPIC_API_KEY` set in your environment, coinjury sends a
token's public metrics (symbol, risk score, red flags) to the Anthropic API for a
natural-language verdict. The key is read from the environment only — it is never
logged, printed, or committed. Keep it in a `.env` (which is git-ignored) or your
shell environment.

## Reporting a vulnerability
Please open a private security advisory on the GitHub repository, or a regular
issue for non-sensitive reports. Do not include secrets in public issues.
