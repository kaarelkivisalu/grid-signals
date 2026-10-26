"""Model explanations alongside the exact feature families used by each recipe."""

from grid_signals.app.snapshot import MODEL_LABELS

PRICE_FEATURES = (
    "Observed price lags: 24, 48, 72 and 168 hours (UTC; unavailable auction prices masked).",
    "24-hour price profiles from 1, 2, 3 and 7 delivery days earlier; weekday indicators, market quarter and month.",
)
LOAD_FEATURES = (
    "Observed total-load lags at 72 and 168 hours, assuming a conservative 24-hour reporting delay.",
    "ECMWF IFS 0.25° archived temperature at six equally weighted German sites; heating below 15°C and cooling above 22°C.",
    "96 local quarter indicators, seven weekdays, daily/annual sine-cosine terms and nationwide German holidays.",
)
SOLAR_FEATURES = (
    "Pinned ECMWF IFS 0.25° previous-run irradiance, 2 m temperature and snow depth at six German sites.",
    "Fleet-weighted physical_cf, clear_sky_cf, ghi, temperature_2m, snow_flag, maximum solar_elevation, lead hour and daily/annual calendar cycles.",
    "Irradiance interpolated by clear-sky index at interval midpoint; the following hourly endpoint must also predate issue.",
)
WIND_FEATURES = (
    "ECMWF IFS, GFS and ICON previous runs; run-addressed Nordic MEPS and IFS; eight fleet-weighted SE3 clusters.",
    "Hub-height wind/power curves, density, shear, gusts, direction, temperature, snow/icing, spatial and model disagreement.",
    "Capacity-factor lags at 48, 72 and 168 h; daily/annual cycles; archived weather trajectory shifts ±1/±3 h and 6 h rolling summaries.",
)

# Recipe, inputs, uncertainty, resolution, caveats. Recipes are frozen research code.
CATALOGUE = {
    "lear_hourly": (
        "24 separate hourly LASSO regressions (AIC selection), robust median/MAD arcsinh scaling and training-only imputation.",
        (
            "Four complete prior daily price profiles (1, 2, 3, 7 days) and weekday indicators. No weather, load or renewable inputs.",
        ),
        "Out-of-sample residual quantiles from the last 30 training days, then refit on all eligible training data.",
        "Hourly forecasts repeated on the quarter-hour grid.",
        "Price-only LEAR adaptation, not the full exogenous LEAR recipe. Negative prices are retained.",
    ),
    "seasonal_naive": (
        "Same interval one week earlier, with a training residual offset.",
        ("Observed day-ahead price at a 168-hour lag.",),
        "Empirical training residual quantiles (median may differ from the raw lag).",
        "Quarter-hour lag on the UTC clock.",
        "DST changes can shift the corresponding local trading time.",
    ),
    "lightgbm_point": (
        "Fixed LightGBM median regression: 300 trees, 15 leaves, learning rate 0.05.",
        PRICE_FEATURES,
        "Held-out training residual distribution, separate from the scored delivery days.",
        "Native quarter-hour targets after October 2025.",
        "Price-only baseline. The separate load-input experiment is development evidence only.",
    ),
    "lightgbm_quantile": (
        "19 independent LightGBM quantile regressions, 0.05 to 0.95; sorted to prevent crossing.",
        PRICE_FEATURES,
        "Direct conditional quantiles.",
        "Native quarter-hour targets.",
        "Under-covers substantially on final evaluation; retained as an experimental reference.",
    ),
    "load_weekly": (
        "Weekly total-load persistence with a training residual offset.",
        ("Observed load at a 168-hour UTC lag.",),
        "Empirical training residual quantiles.",
        "Native quarter-hour targets.",
        "Holidays and DST can break the weekly pattern; historical actuals may be revised.",
    ),
    "load_ridge": (
        "Ridge regression (alpha 10), training-median imputation and standard scaling.",
        LOAD_FEATURES,
        "Residual distribution calibrated on the last 30 training days.",
        "Native quarter-hour targets.",
        "Regional and Luxembourg-only holidays are omitted. Historical load revisions are not point-in-time vintages.",
    ),
    "load_point_gbm": (
        "LightGBM median regression with fixed tree settings.",
        LOAD_FEATURES,
        "Residual distribution calibrated on the last 30 training days.",
        "Native quarter-hour targets.",
        "Temperature uses an equal-area site approximation rather than population-weighted exposure.",
    ),
    "load_quantile_gbm": (
        "19 LightGBM quantile regressions (300 trees, 15 leaves, minimum child 80); crossing correction.",
        LOAD_FEATURES,
        "Direct conditional quantiles.",
        "Native quarter-hour targets.",
        "Development intervals under-cover; final evaluation is a separate 44-day window. Actual-lag revisions remain assumed.",
    ),
    "hourly_repeated": (
        "19 LightGBM quantile models with physical monotonicity constraints and cross-fit quantile calibration.",
        WIND_FEATURES,
        "Calibrated conditional capacity-factor quantiles, converted with dated installed capacity.",
        "Hourly-trained distributions repeated four times; no demonstrated native quarter-hour skill.",
        "Mapped and dated SE3 turbine registry; availability, icing and capacity drift remain open. Historical weather publication age is approximated conservatively.",
    ),
    "interpolated_weather": (
        "The same hourly-trained wind model, evaluated using interpolated weather at quarter-hour steps.",
        WIND_FEATURES,
        "Same quantile and cross-fit calibration recipe as repeated-hour wind.",
        "Interpolated weather; no native quarter-hour retraining.",
        "No statistically resolved development CRPS gain over repeating hours. Development comparison only.",
    ),
    "physical_power_curve": (
        "Fleet-weighted turbine power curves driven by archived wind forecasts, with a training-fitted affine bias correction.",
        (
            "Mapped SE3 fleet, hub-height weather and physical turbine response. No learned generation-lag model.",
        ),
        "Training residual distribution around physical output.",
        "Hourly physical response repeated on the scoring grid.",
        "Does not model turbine outages or curtailment explicitly.",
    ),
    "solar_quantile": (
        "19 daylight LightGBM quantile models around a physical PV representation, with cross-fit calibration.",
        SOLAR_FEATURES,
        "Calibrated capacity-factor quantiles; deterministic zero during night.",
        "Native quarter-hour target and midpoint solar physics.",
        "Six-site fleet proxy: 50% south at 30°, 25% east and 25% west at 20°. Annual capacity vintages are assumed; final solar overprediction remains unresolved.",
    ),
    "solar_physical": (
        "PVWatts physical PV model with fixed losses/orientations and a training-fitted derating factor.",
        (
            "Archived IFS irradiance/temperature, solar geometry, six equal-area sites and annual installed capacity.",
        ),
        "Held-out training residual quantiles scaled by the clear-sky profile, with night forced to zero.",
        "Quarter-hour solar geometry and irradiance reconstruction.",
        "Static fleet proxy; no operational availability information.",
    ),
    "smart_persistence": (
        "Re-use the observed clear-sky index from 48 hours earlier, applied to today's clear-sky profile.",
        (
            "Lagged solar generation, clear-sky irradiance/geometry and capacity. No future weather input.",
        ),
        "Training residual quantiles.",
        "Quarter-hour profile with night forced to zero.",
        "Poor when cloud conditions change quickly; daylight scoring only.",
    ),
    "clear_sky_climatology": (
        "Training climatology of the clear-sky index applied to solar geometry.",
        (
            "Historical clear-sky-index distribution and calendar/clear-sky profile; no forecast weather.",
        ),
        "Empirical training distribution.",
        "Quarter-hour geometry.",
        "Development-only reference; not evaluated in the final solar release.",
    ),
}


def model_name(model: str) -> str:
    return MODEL_LABELS.get(model, model)
