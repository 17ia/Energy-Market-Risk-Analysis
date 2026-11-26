from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import pandas as pd
import requests
import yfinance as yf

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - optional dependency at runtime
    OpenAI = None


ENERGY_CHARTS_URL = "https://api.energy-charts.info/price"
DEFAULT_LOOKBACK_DAYS = 120
DEFAULT_POWER_ZONE = "DE-LU"
DEFAULT_TTF_TICKER = "TTF=F"
DEFAULT_CARBON_TICKER = "CO2.L"


@dataclass
class MarketConfig:
    start_date: str
    end_date: str
    power_zone: str
    ttf_ticker: str
    carbon_ticker: str
    gas_efficiency: float
    emissions_factor: float
    variable_om: float
    output_dir: Path
    use_openai: bool
    openai_model: str


def parse_args() -> MarketConfig:
    today = datetime.now(UTC).date()
    default_start = today - timedelta(days=DEFAULT_LOOKBACK_DAYS)
    parser = argparse.ArgumentParser(
        description="Build a daily European gas-carbon-power risk pack."
    )
    parser.add_argument("--start-date", default=default_start.isoformat())
    parser.add_argument("--end-date", default=today.isoformat())
    parser.add_argument("--power-zone", default=DEFAULT_POWER_ZONE)
    parser.add_argument("--ttf-ticker", default=DEFAULT_TTF_TICKER)
    parser.add_argument("--carbon-ticker", default=DEFAULT_CARBON_TICKER)
    parser.add_argument("--gas-efficiency", type=float, default=0.50)
    parser.add_argument("--emissions-factor", type=float, default=0.37)
    parser.add_argument("--variable-om", type=float, default=2.0)
    parser.add_argument("--output-dir", default="outputs")
    parser.add_argument("--use-openai", action="store_true")
    parser.add_argument("--openai-model", default="gpt-5")
    args = parser.parse_args()

    return MarketConfig(
        start_date=args.start_date,
        end_date=args.end_date,
        power_zone=args.power_zone,
        ttf_ticker=args.ttf_ticker,
        carbon_ticker=args.carbon_ticker,
        gas_efficiency=args.gas_efficiency,
        emissions_factor=args.emissions_factor,
        variable_om=args.variable_om,
        output_dir=Path(args.output_dir),
        use_openai=args.use_openai,
        openai_model=args.openai_model,
    )


def ensure_directories(output_dir: Path) -> dict[str, Path]:
    paths = {
        "base": output_dir,
        "raw": output_dir / "raw",
        "clean": output_dir / "clean",
        "charts": output_dir / "charts",
        "briefs": output_dir / "briefs",
        "logs": output_dir / "logs",
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    return paths


def date_to_unix_seconds(date_str: str, hour: int = 0, minute: int = 0) -> int:
    dt = datetime.fromisoformat(date_str).replace(tzinfo=UTC, hour=hour, minute=minute)
    return int(dt.timestamp())


def fetch_power_prices(config: MarketConfig) -> pd.DataFrame:
    params = {
        "bzn": config.power_zone,
        "start": date_to_unix_seconds(config.start_date),
        "end": date_to_unix_seconds(config.end_date, hour=23, minute=59),
    }
    response = requests.get(ENERGY_CHARTS_URL, params=params, timeout=60)
    response.raise_for_status()
    payload = response.json()

    if "unix_seconds" not in payload or "price" not in payload:
        raise ValueError("Unexpected power price payload from Energy Charts API.")

    frame = pd.DataFrame(
        {
            "timestamp_utc": pd.to_datetime(payload["unix_seconds"], unit="s", utc=True),
            "power_price_eur_mwh": payload["price"],
        }
    )
    frame["date"] = frame["timestamp_utc"].dt.date
    daily = (
        frame.groupby("date", as_index=False)["power_price_eur_mwh"]
        .mean()
        .sort_values("date")
    )
    daily["date"] = pd.to_datetime(daily["date"])
    return daily


def fetch_yahoo_series(ticker: str, start_date: str, end_date: str, column_name: str) -> pd.DataFrame:
    end_plus_one = (datetime.fromisoformat(end_date).date() + timedelta(days=1)).isoformat()
    data = yf.download(
        tickers=ticker,
        start=start_date,
        end=end_plus_one,
        progress=False,
        auto_adjust=False,
        threads=False,
    )
    if data.empty:
        raise ValueError(f"No data returned for ticker {ticker}.")

    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)

    if "Adj Close" in data.columns:
        series = data["Adj Close"]
    else:
        series = data["Close"]

    frame = series.rename(column_name).reset_index()
    frame.columns = ["date", column_name]
    frame["date"] = pd.to_datetime(frame["date"], utc=True).dt.tz_localize(None).dt.normalize()
    return frame.sort_values("date")


def clean_and_merge(
    power_df: pd.DataFrame,
    ttf_df: pd.DataFrame,
    carbon_df: pd.DataFrame,
    config: MarketConfig,
) -> pd.DataFrame:
    merged = power_df.merge(ttf_df, on="date", how="outer").merge(carbon_df, on="date", how="outer")
    merged = merged.sort_values("date").reset_index(drop=True)

    # Public sources use different calendars. Fill short gaps so we can compute
    # day-over-day and week-over-week metrics on a daily aligned panel.
    for column in ["power_price_eur_mwh", "ttf_price_eur_mwh", "carbon_price_eur_t"]:
        merged[column] = merged[column].interpolate(limit_direction="both")

    merged["implied_power_price_eur_mwh"] = (
        merged["ttf_price_eur_mwh"] / config.gas_efficiency
        + merged["carbon_price_eur_t"] * config.emissions_factor
        + config.variable_om
    )
    merged["clean_spark_spread_eur_mwh"] = (
        merged["power_price_eur_mwh"] - merged["implied_power_price_eur_mwh"]
    )
    merged["ttf_wow_pct"] = merged["ttf_price_eur_mwh"].pct_change(5) * 100
    merged["power_wow_pct"] = merged["power_price_eur_mwh"].pct_change(5) * 100
    merged["carbon_wow_pct"] = merged["carbon_price_eur_t"].pct_change(5) * 100
    merged["ttf_power_20d_corr"] = (
        merged["ttf_price_eur_mwh"].rolling(20).corr(merged["power_price_eur_mwh"])
    )
    merged["gas_to_power_beta_20d"] = (
        merged["power_price_eur_mwh"].diff().rolling(20).cov(merged["ttf_price_eur_mwh"].diff())
        / merged["ttf_price_eur_mwh"].diff().rolling(20).var()
    )
    merged["carbon_cost_component_eur_mwh"] = (
        merged["carbon_price_eur_t"] * config.emissions_factor
    )
    return merged


def save_raw_data(
    paths: dict[str, Path],
    power_df: pd.DataFrame,
    ttf_df: pd.DataFrame,
    carbon_df: pd.DataFrame,
) -> None:
    power_df.to_csv(paths["raw"] / "power_prices_raw.csv", index=False)
    ttf_df.to_csv(paths["raw"] / "ttf_raw.csv", index=False)
    carbon_df.to_csv(paths["raw"] / "carbon_raw.csv", index=False)


def generate_charts(df: pd.DataFrame, paths: dict[str, Path]) -> dict[str, Path]:
    latest_date = df["date"].max().strftime("%Y-%m-%d")
    chart_paths = {
        "ttf_vs_power": paths["charts"] / "ttf_vs_power.png",
        "css": paths["charts"] / "clean_spark_spread.png",
    }

    plt.style.use("seaborn-v0_8-whitegrid")

    fig, ax1 = plt.subplots(figsize=(12, 6))
    ax1.plot(df["date"], df["ttf_price_eur_mwh"], color="#1f77b4", linewidth=2, label="TTF")
    ax1.set_ylabel("TTF Gas (EUR/MWh)", color="#1f77b4")
    ax1.tick_params(axis="y", labelcolor="#1f77b4")

    ax2 = ax1.twinx()
    ax2.plot(
        df["date"],
        df["power_price_eur_mwh"],
        color="#d62728",
        linewidth=2,
        label="Power",
    )
    ax2.set_ylabel("Power Price (EUR/MWh)", color="#d62728")
    ax2.tick_params(axis="y", labelcolor="#d62728")

    ax1.set_title(f"TTF vs Power Price ({latest_date})")
    ax1.set_xlabel("Date")
    fig.tight_layout()
    fig.savefig(chart_paths["ttf_vs_power"], dpi=180, bbox_inches="tight")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(12, 6))
    ax.plot(
        df["date"],
        df["clean_spark_spread_eur_mwh"],
        color="#2a9d8f",
        linewidth=2,
    )
    ax.axhline(0, color="#444444", linestyle="--", linewidth=1)
    ax.set_title(f"Clean Spark Spread ({latest_date})")
    ax.set_xlabel("Date")
    ax.set_ylabel("EUR/MWh")
    fig.tight_layout()
    fig.savefig(chart_paths["css"], dpi=180, bbox_inches="tight")
    plt.close(fig)

    return chart_paths


def safe_float(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)


def build_metrics(df: pd.DataFrame, config: MarketConfig) -> dict[str, Any]:
    latest = df.iloc[-1]
    previous = df.iloc[-2] if len(df) > 1 else latest

    metrics = {
        "as_of_date": latest["date"].strftime("%Y-%m-%d"),
        "power_zone": config.power_zone,
        "ttf_ticker": config.ttf_ticker,
        "carbon_ticker": config.carbon_ticker,
        "latest": {
            "ttf_price_eur_mwh": safe_float(latest["ttf_price_eur_mwh"]),
            "power_price_eur_mwh": safe_float(latest["power_price_eur_mwh"]),
            "carbon_price_eur_t": safe_float(latest["carbon_price_eur_t"]),
            "implied_power_price_eur_mwh": safe_float(latest["implied_power_price_eur_mwh"]),
            "clean_spark_spread_eur_mwh": safe_float(latest["clean_spark_spread_eur_mwh"]),
            "carbon_cost_component_eur_mwh": safe_float(latest["carbon_cost_component_eur_mwh"]),
        },
        "changes": {
            "ttf_day_change_pct": safe_float(
                (latest["ttf_price_eur_mwh"] / previous["ttf_price_eur_mwh"] - 1) * 100
            ),
            "power_day_change_pct": safe_float(
                (latest["power_price_eur_mwh"] / previous["power_price_eur_mwh"] - 1) * 100
            ),
            "carbon_day_change_pct": safe_float(
                (latest["carbon_price_eur_t"] / previous["carbon_price_eur_t"] - 1) * 100
            ),
            "ttf_week_change_pct": safe_float(latest["ttf_wow_pct"]),
            "power_week_change_pct": safe_float(latest["power_wow_pct"]),
            "carbon_week_change_pct": safe_float(latest["carbon_wow_pct"]),
        },
        "signals": {
            "ttf_power_20d_corr": safe_float(latest["ttf_power_20d_corr"]),
            "gas_to_power_beta_20d": safe_float(latest["gas_to_power_beta_20d"]),
            "power_vs_implied_gap_eur_mwh": safe_float(
                latest["power_price_eur_mwh"] - latest["implied_power_price_eur_mwh"]
            ),
        },
        "assumptions": {
            "gas_efficiency": config.gas_efficiency,
            "emissions_factor_tco2_per_mwh": config.emissions_factor,
            "variable_om_eur_mwh": config.variable_om,
            "carbon_proxy_note": (
                "Uses Yahoo Finance ticker "
                f"{config.carbon_ticker} as a public carbon-linked proxy."
            ),
        },
    }
    return metrics


def format_pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:+.1f}%"


def format_eur(value: float | None) -> str:
    return "n/a" if value is None else f"EUR {value:,.1f}"


def build_template_brief(metrics: dict[str, Any]) -> str:
    latest = metrics["latest"]
    changes = metrics["changes"]
    signals = metrics["signals"]

    css = latest["clean_spark_spread_eur_mwh"]
    gap = signals["power_vs_implied_gap_eur_mwh"]
    css_bias = "margin compression" if css is not None and css < 0 else "positive generation margin"
    gap_bias = "below" if gap is not None and gap < 0 else "above"

    return "\n".join(
        [
            f"Daily brief for {metrics['as_of_date']} ({metrics['power_zone']})",
            "",
            (
                f"TTF closed at {format_eur(latest['ttf_price_eur_mwh'])}/MWh "
                f"({format_pct(changes['ttf_week_change_pct'])} week-on-week), while "
                f"power printed {format_eur(latest['power_price_eur_mwh'])}/MWh and "
                f"carbon was {format_eur(latest['carbon_price_eur_t'])}/t."
            ),
            (
                f"Implied gas-fired marginal power cost is {format_eur(latest['implied_power_price_eur_mwh'])}/MWh, "
                f"putting observed power {gap_bias} implied cost by {format_eur(abs(gap) if gap is not None else None)}/MWh."
            ),
            (
                f"Clean spark spread is {format_eur(css)}/MWh, which points to {css_bias}. "
                f"The 20-day TTF-power correlation is {signals['ttf_power_20d_corr']:.2f} and "
                f"the rolling gas-to-power beta is {signals['gas_to_power_beta_20d']:.2f}."
                if signals["ttf_power_20d_corr"] is not None and signals["gas_to_power_beta_20d"] is not None
                else "Rolling gas-power linkage metrics are not yet available for the full lookback window."
            ),
            (
                "Risk view: front-end power remains most exposed to gas repricing, while the back end should stay better "
                "anchored by the carbon component unless carbon or structural generation costs materially re-rate."
            ),
        ]
    )


def build_openai_prompt(metrics: dict[str, Any]) -> dict[str, str]:
    system_prompt = (
        "You are an energy market analyst. Produce a concise daily brief grounded only in the supplied metrics. "
        "Do not invent data. Keep the tone professional and decision-useful. Include: summary, curve read-through, "
        "and risk implications. If a metric is missing, say it is unavailable."
    )
    user_prompt = (
        "Write a short daily brief for a European cross-commodity gas-carbon-power pack. "
        "Use the metrics JSON below as the only source of truth.\n\n"
        f"{json.dumps(metrics, indent=2)}"
    )
    return {"system": system_prompt, "user": user_prompt}


def run_openai_brief(
    metrics: dict[str, Any],
    config: MarketConfig,
    paths: dict[str, Path],
) -> tuple[str, str]:
    if OpenAI is None:
        raise RuntimeError("openai package is not installed. Add it via requirements.txt.")
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is not set.")

    prompt = build_openai_prompt(metrics)
    client = OpenAI()
    response = client.responses.create(
        model=config.openai_model,
        instructions=prompt["system"],
        input=prompt["user"],
    )
    output_text = response.output_text
    log_payload = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "model": config.openai_model,
        "prompt": prompt,
        "response_id": getattr(response, "id", None),
        "output_text": output_text,
    }
    log_path = paths["logs"] / "openai_brief_log.json"
    log_path.write_text(json.dumps(log_payload, indent=2), encoding="utf-8")
    return output_text, str(log_path)


def write_outputs(
    df: pd.DataFrame,
    brief_text: str,
    chart_paths: dict[str, Path],
    paths: dict[str, Path],
    metrics: dict[str, Any],
    ai_log_path: str | None,
) -> None:
    df.to_csv(paths["clean"] / "market_data_clean.csv", index=False)
    (paths["briefs"] / "daily_brief.txt").write_text(brief_text, encoding="utf-8")
    (paths["clean"] / "metrics_snapshot.json").write_text(
        json.dumps(metrics, indent=2), encoding="utf-8"
    )

    manifest = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "clean_dataset": str(paths["clean"] / "market_data_clean.csv"),
        "brief": str(paths["briefs"] / "daily_brief.txt"),
        "metrics_snapshot": str(paths["clean"] / "metrics_snapshot.json"),
        "charts": {name: str(path) for name, path in chart_paths.items()},
        "openai_log": ai_log_path,
    }
    (paths["base"] / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def main() -> None:
    config = parse_args()
    paths = ensure_directories(config.output_dir)

    power_df = fetch_power_prices(config)
    ttf_df = fetch_yahoo_series(
        ticker=config.ttf_ticker,
        start_date=config.start_date,
        end_date=config.end_date,
        column_name="ttf_price_eur_mwh",
    )
    carbon_df = fetch_yahoo_series(
        ticker=config.carbon_ticker,
        start_date=config.start_date,
        end_date=config.end_date,
        column_name="carbon_price_eur_t",
    )

    save_raw_data(paths, power_df, ttf_df, carbon_df)
    merged = clean_and_merge(power_df, ttf_df, carbon_df, config)
    metrics = build_metrics(merged, config)
    chart_paths = generate_charts(merged, paths)

    ai_log_path = None
    if config.use_openai:
        brief_text, ai_log_path = run_openai_brief(metrics, config, paths)
    else:
        prompt = build_openai_prompt(metrics)
        ai_log_path = str(paths["logs"] / "template_brief_log.json")
        (paths["logs"] / "template_brief_log.json").write_text(
            json.dumps(
                {
                    "timestamp_utc": datetime.now(UTC).isoformat(),
                    "prompt": prompt,
                    "output_text": "Template narrative used because --use-openai was not enabled.",
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        brief_text = build_template_brief(metrics)

    write_outputs(merged, brief_text, chart_paths, paths, metrics, ai_log_path)
    print(f"Created clean dataset: {paths['clean'] / 'market_data_clean.csv'}")
    print(f"Created brief: {paths['briefs'] / 'daily_brief.txt'}")
    print(f"Created chart: {chart_paths['ttf_vs_power']}")
    print(f"Created chart: {chart_paths['css']}")
    print(f"Created manifest: {paths['base'] / 'manifest.json'}")


if __name__ == "__main__":
    main()
