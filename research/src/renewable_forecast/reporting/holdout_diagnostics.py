"""Post-evaluation diagnostics of unchanged frozen renewable predictions."""

import numpy as np
import pandas as pd
import scoringrules as sr

from renewable_forecast import paths
from renewable_forecast.evaluation import metrics, splits
from renewable_forecast.pipelines import holdout


def write() -> None:
    levels = np.arange(0.05, 1, 0.05).round(2)
    columns = [f"q{q:.2f}" for q in levels]
    lines = [
        "# Final renewable diagnostics",
        "",
        "Post-evaluation analysis of fixed predictions, without changing any model. Bias is actual minus forecast; negative means overprediction. Solar uses daylight rows.",
        "",
    ]
    for fuel, reference in [
        ("wind_onshore", "physical_power_curve"),
        ("solar", "solar_physical"),
    ]:
        frame = pd.concat(
            [
                pd.read_parquet(path)
                for path in sorted(holdout.OUTPUT.glob(f"{fuel}_*.parquet"))
            ],
            ignore_index=True,
        )
        chosen = frame[(frame.forecaster == "quantile") & frame.daylight].sort_values(
            "valid_time"
        )
        baseline = frame[(frame.forecaster == reference) & frame.daylight].sort_values(
            "valid_time"
        )
        if chosen.valid_time.tolist() != baseline.valid_time.tolist():
            raise ValueError("diagnostic rows must match")
        loss = sr.crps_quantile(
            chosen.cf.to_numpy(), chosen[columns].to_numpy(), levels
        )
        base_loss = sr.crps_quantile(
            baseline.cf.to_numpy(), baseline[columns].to_numpy(), levels
        )
        low, high = splits.bootstrap_ci(
            pd.Series(loss - base_loss), chosen.delivery_day
        )
        missing = pd.date_range(
            holdout.START, holdout.END, inclusive="left"
        ).difference(pd.DatetimeIndex(chosen.delivery_day.unique()))
        lines += [
            f"## {fuel}",
            "",
            f"Paired day-block 95% bootstrap interval for CRPS difference versus {reference}: **{low * 100:.3f} to {high * 100:.3f} percentage points of capacity**. Negative favours the quantile model.",
            "",
            "Missing complete delivery days: "
            + (
                ", ".join(str(day.date()) for day in missing)
                if len(missing)
                else "none"
            )
            + ".",
            "",
            "| Month | Days | nMAE | Bias | 80% coverage |",
            "|---|---|---|---|---|",
        ]
        for month, group in chosen.groupby(chosen.delivery_day.dt.to_period("M")):
            result = metrics.summarise(
                group.cf.to_numpy(), group[columns].to_numpy(), levels
            )
            lines.append(
                f"| {month} | {group.delivery_day.nunique()} | {result['nmae']:.2%} | {result['nbias']:+.2%} | {result['coverage_80']:.1%} |"
            )
        lines += [""]
    lines += [
        "Aggregate interval coverage is close to nominal while monthly coverage and bias vary. The solar median overpredicts on average: fleet assumptions and weather/model bias are hypotheses to investigate, not established causes.",
        "",
        "Any corrective experiment needs a new declared development/forward window. These final outcomes cannot become another tuning set.",
        "",
    ]
    (paths.REPORTS / "holdout_diagnostics.md").write_text("\n".join(lines))


if __name__ == "__main__":
    write()
