# Bitpin-fix integration notes

This folder in the repository is the maintained implementation. The uploaded ZIP was reviewed as a reference; its scanner.py is not copied over the production scanner because it contains an opt-in local-receive-time freshness fallback and uses float arithmetic. Those choices are not accepted for the main arbitrage path.

The existing `arbitrage-ai-mvp/scanner.py` remains the production candidate. This regression test file checks compatible behavior without enabling local-time freshness or live execution.

Safety invariants:
- Public market-data GET requests only.
- Missing Wallex exchange-side timestamp must not become paper-eligible.
- No private trading endpoints, order placement, withdrawals, or transfers.
- No USDT-quoted market is converted to Toman without an independent conversion route.
- Keep scanner feed and execution disabled until separately reviewed.

Run locally:
```bash
cd arbitrage-ai-mvp
python -m pip install -r requirements.txt
PYTHONPATH=. python -m unittest discover -s tests -v
```
