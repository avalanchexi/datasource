# A+H Dual Listed 2026 Extractor

This is a standalone utility and does not depend on the Stage1/2/3 pipeline.

## What it does

1. Builds A+H list with strategy:
   - Primary: TuShare `stk_ah_comparison`
   - Fallback: WebSearch scrape from AASTOCKS A/H page
   - Final fallback: TuShare `stock_basic + hk_basic` normalized name matching
2. Pulls 2026 data:
   - A-share daily bars (`daily`)
   - H-share daily bars (`hk_daily`)
   - A-share money flow (`moneyflow`)
3. Pulls 2026 northbound/southbound market flow (`moneyflow_hsgt`).
4. Writes CSV/JSON/Markdown outputs.

## Files generated

- `dual_listed_companies.csv`
- `ah_2026_daily_data.csv`
- `ah_2026_summary.csv`
- `hsgt_2026_flow_daily.csv`
- `hsgt_2026_flow_summary.json`
- `dual_list_source_meta.json`
- `ah_2026_report.md`

## Usage

```bash
python3 standalone/ah_dual_listed_2026/fetch_ah_dual_listed_2026.py \
  --output-dir standalone/ah_dual_listed_2026/output \
  --list-source auto \
  --start-date 20260101 \
  --end-date 20261231
```

`--list-source` options:
- `auto` (default): `stk_ah` -> `websearch` -> `name_match`
- `stk_ah`: only TuShare `stk_ah_comparison`
- `websearch`: only scrape AASTOCKS list
- `name_match`: only normalized name matching (`stock_basic + hk_basic`)

If token is in environment:

```bash
export TUSHARE_TOKEN=your_token_here
python3 standalone/ah_dual_listed_2026/fetch_ah_dual_listed_2026.py
```

Or pass token explicitly:

```bash
python3 standalone/ah_dual_listed_2026/fetch_ah_dual_listed_2026.py \
  --token your_token_here
```

## Notes

- `a_net_flow_amount_2026_wan` unit is ten-thousand CNY (`wan`), based on TuShare `moneyflow.net_mf_amount`.
- `hsgt_2026_flow_summary.json` converts `north_money/south_money` to yi CNY by dividing by `10000`.
- Markdown report is `ah_2026_report.md`.
- If an endpoint is unavailable under current TuShare permission, corresponding rows may be empty.
