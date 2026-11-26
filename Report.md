European Cross-Commodity Risk Pack Automation

This project builds a daily gas-carbon-power risk pack from public data.

It fetches:
- TTF gas from Yahoo Finance (`TTF=F`)
- German day-ahead power from the Fraunhofer Energy Charts API (`DE-LU`)
- Carbon from Yahoo Finance (`CO2.L`) as a public EUA-linked proxy

It produces:
- Raw source extracts in `outputs/raw/`
- A cleaned aligned dataset in `outputs/clean/market_data_clean.csv`
- Two charts in `outputs/charts/`
- A short daily brief in `outputs/briefs/daily_brief.txt`
- Prompt/output logs for the narrative step in `outputs/logs/`

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

Rules-based brief only:

```bash
python3 daily_eu_power_risk_pack.py
```

With OpenAI narrative generation:

```bash
export OPENAI_API_KEY=your_key_here
python3 daily_eu_power_risk_pack.py --use-openai
```

## Notes

- The power series is averaged from Energy Charts quarter-hourly prices into daily prices.
- The carbon series uses `CO2.L`, which is a public carbon-linked proxy rather than the exact front EUA future.
- Clean spark spread is approximated as:

```text
power - ((TTF / efficiency) + (carbon * emissions_factor) + variable_om)
```

- Default assumptions are:
  - Gas efficiency: `0.50`
  - Emissions factor: `0.37 tCO2/MWh`
  - Variable O&M: `EUR 2/MWh`

## Key outputs

- `outputs/charts/ttf_vs_power.png`
- `outputs/charts/clean_spark_spread.png`
- `outputs/briefs/daily_brief.txt`
- `outputs/logs/openai_brief_log.json` when `--use-openai` is enabled
