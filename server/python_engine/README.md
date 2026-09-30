# GROWISEINVEST V27

Complete sector-aware institutional equity research terminal.

## Start
Use `START_GROWISEINVEST.bat` on Windows, or run:

```powershell
python self_test.py
python GROWISEINVEST.py
```

Enter a ticker once, then use the module number. `20` is the flagship Security Master. `90` is Equity Research Intelligence. `100` is Fair Value. `98` runs production diagnostics.

## Production structure
- `GROWISEINVEST.py` - canonical terminal
- `engine/` - analytical models
- `institutional_pack.py` - Word/Excel research pack
- `tests/` - regression checks
- `docs/` - current documentation and historical notes
- `reports/` - generated report workspace
- `config/` - reserved configuration workspace

## Core controls
- No fabricated market prices
- Provider failures degrade to controlled N/A/REVIEW states
- DCF and accounting controls remain gated by model validation
- Live Market is credential-gated and fail-closed
- Human investment decision remains separate from automated research output
