# Arbitrage AI paper worker

This worker is analysis/simulation only. It reads public Wallex and Nobitex order books and writes observations to Supabase. It does not submit exchange orders, access balances, withdraw, or transfer funds.

## GitHub Actions secrets

Configure these repository Actions secrets before enabling the scheduled workflow:

- `SUPABASE_URL`: project URL.
- `SUPABASE_SERVICE_ROLE_KEY`: Supabase service-role key. Keep it in Actions secrets only; never place it in Streamlit, frontend code, or committed files.
- `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`: optional alerts.

## Worker environment

Optional variables and defaults:

- `CAPITAL_TOMAN=2000000`
- `FEE_WALLEX_PCT=0.25`
- `FEE_NOBITEX_PCT=0.25`
- `SLIPPAGE_PCT=0.20`
- `TRANSFER_COST_PCT=0.30`
- `MIN_NET_PROFIT_PCT=0.25`
- `MIN_EXECUTABLE_TOMAN=100000`
- `MAX_BOOK_AGE_SECONDS=90`
- `VALIDATION_HORIZONS=60,300,900`
- `PAPER_VALIDATION_COOLDOWN_SECONDS=1800`
- `RUN_SECONDS=270`
- `SCAN_INTERVAL_SECONDS=30`

Fee variables ending in `_PCT` are percentages; the worker converts them to decimal fractions for the scanner.

## Supabase setup

Run `supabase/migrations/20261118_worker_pipeline.sql` in the Supabase SQL Editor. The worker uses the service role key. The dashboard should use only the anon key and read-only access. The `arb_state` table has no anon/authenticated read policy.

## Run locally

From this directory:

```bash
python -m pip install -r requirements-worker.txt
python tests/test_pipeline.py
python worker.py
```

Local execution requires the two Supabase environment variables. The end-to-end tests use fake order books and an in-memory database and need no credentials.
