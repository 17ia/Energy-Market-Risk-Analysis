# European Energy Market Risk Analysis

## Project Overview

A Python-based quantitative analytics project monitoring the relationship between European natural gas, carbon and electricity prices.

The project combines market data collection, data processing, quantitative modelling and automated reporting to produce an energy market risk pack.

## Key Features

- **Market Data Collection:** Retrieves electricity prices from the Energy-Charts API and gas and carbon-linked price data from Yahoo Finance.
- **Data Processing:** Cleans, aligns and merges market datasets.
- **Quantitative Analysis:** Calculates clean spark spreads, implied power generation costs, price changes, rolling correlations and gas-to-power beta.
- **Data Visualisation:** Generates market charts using Matplotlib.
- **Automated Reporting:** Produces daily market commentary and structured JSON metrics.
- **AI Integration:** Optional OpenAI API integration for market commentary.

## Technologies

- Python
- Pandas
- Matplotlib
- Requests
- yfinance
- OpenAI API (optional)

## Project Structure

```text
energy-market-risk-analysis/
│
├── Main Code.py
├── Report.md
├── README.md
│
└── outputs/
    ├── raw/
    ├── clean/
    ├── charts/
    ├── briefs/
    ├── logs/
    └── manifest.json
```

## Analytical Framework

| Metric | Description |
|---|---|
| TTF Price | European natural gas price |
| Power Price | German electricity price |
| Carbon Price | Carbon-linked price proxy |
| Implied Power Price | Estimated gas-fired generation cost |
| Clean Spark Spread | Electricity price less implied generation cost |
| Rolling Correlation | 20-day TTF and power price correlation |
| Gas-to-Power Beta | 20-day sensitivity of power price changes to gas price changes |

## Project Outputs

### TTF Gas vs Electricity Prices

![TTF vs Power](outputs/charts/ttf_vs_power.png)

### Clean Spark Spread

![Clean Spark Spread](outputs/charts/clean_spark_spread.png)

### Market Data

- [Clean market dataset](outputs/clean/market_data_clean.csv)
- [Quantitative metrics snapshot](outputs/clean/metrics_snapshot.json)
- [Daily market brief](outputs/briefs/daily_brief.txt)
- [Detailed project report](Report.md)

## Installation and Usage

Install the required packages:

```bash
pip install pandas matplotlib requests yfinance
```

For optional AI-generated commentary:

```bash
pip install openai
```

Run the analysis:

```bash
python "Main Code.py"
```

To enable OpenAI commentary:

```bash
export OPENAI_API_KEY="your-api-key"
python "Main Code.py" --use-openai
```

## Data Sources

- Energy-Charts API
- Yahoo Finance

## Methodology and Assumptions

The model estimates gas-fired generation costs using gas efficiency, carbon emissions intensity and variable operating costs.

The carbon price series uses a Yahoo Finance carbon-linked market proxy. It should not be interpreted as a direct representation of all European carbon allowance markets.

## Disclaimer

This project is for educational and analytical purposes only. Data availability, source methodologies and modelling assumptions may affect results. It does not constitute investment advice.
