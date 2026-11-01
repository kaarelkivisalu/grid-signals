"""Model explanations alongside the exact feature families used by each recipe."""

from grid_signals.app.snapshot import MODEL_LABELS

REFERENCE_MODELS = {
    "wind_onshore": "physical_power_curve",
    "solar": "smart_persistence",
    "price": "seasonal_naive",
    "load": "load_weekly",
}

# Overview first; exact, evaluated recipes remain in CATALOGUE below.
FORECAST_GUIDES = {
    "wind_onshore": {
        "question": "How much electricity will the onshore turbine fleet generate?",
        "steps": (
            (
                "Inputs",
                "Wind forecasts & turbine fleet",
                "Weather from several models, turbine response and recent generation.",
            ),
            (
                "Model",
                "Physical response + LightGBM",
                "Learn the generation distribution and calibrate it on training-side predictions.",
            ),
            (
                "Output",
                "Generation & uncertainty",
                "Median and prediction ranges, scaled by installed capacity.",
            ),
        ),
        "reference": "Turbine power curves convert forecast wind into generation, with a fitted bias correction.",
        "note": "The wind model learns at hourly resolution; each hour is repeated across four quarter-hours.",
    },
    "solar": {
        "question": "How much electricity will the solar fleet generate during daylight?",
        "steps": (
            (
                "Inputs",
                "Sunlight, weather & panels",
                "Archived irradiance and temperature, solar geometry and panel orientations.",
            ),
            (
                "Model",
                "Physical PV + LightGBM",
                "Learn daylight generation quantiles around a physical panel model.",
            ),
            (
                "Output",
                "Daylight generation & ranges",
                "Calibrated generation ranges; night-time output is zero.",
            ),
        ),
        "reference": "The sunlight-adjusted pattern from 48 hours earlier, applied to the delivery day's clear-sky profile.",
        "note": "Solar predictions use quarter-hour targets. The final evaluation still shows overprediction.",
    },
    "price": {
        "question": "What will the next day's wholesale electricity prices be?",
        "steps": (
            (
                "Inputs",
                "Price history & weekday",
                "Daily price profiles from 1, 2, 3 and 7 days earlier.",
            ),
            (
                "Model",
                "LEAR hourly regressions",
                "One LASSO regression per hour learns recurring price patterns.",
            ),
            (
                "Output",
                "Prices & prediction ranges",
                "Hourly prices repeated on the quarter-hour grid; training errors set the ranges.",
            ),
        ),
        "reference": "The price at the same UTC interval one week earlier, adjusted by a training residual offset.",
        "note": "This LEAR adaptation uses price history and weekday only. Negative prices are retained.",
    },
    "load": {
        "question": "How much electricity will consumers demand?",
        "steps": (
            (
                "Inputs",
                "Demand, temperature & calendar",
                "Past demand, forecast heating/cooling needs, time of day and holidays.",
            ),
            (
                "Model",
                "LightGBM quantiles",
                "Learn 19 demand quantiles from historical demand and archived weather.",
            ),
            (
                "Output",
                "Demand & prediction ranges",
                "Quarter-hour demand with a median and uncertainty ranges.",
            ),
        ),
        "reference": "Demand at the same UTC interval one week earlier, adjusted by a training residual offset.",
        "note": "The German demand case study uses six temperature sites and national holidays; historical observations may be revised.",
    },
}

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
    "Hub-height wind and turbine generation curves, density, shear, gusts, direction, temperature, snow/icing, spatial and model disagreement.",
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
        "Fleet-weighted turbine generation curves driven by archived wind forecasts, with a training-fitted affine bias correction.",
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
    return DISPLAY_NAMES.get(model, MODEL_LABELS.get(model, model))


# Short labels for browsing; the full recipes and exact feature families stay above.
DISPLAY_NAMES = {
    "hourly_repeated": "Wind model · LightGBM",
    "interpolated_weather": "Wind model · interpolated weather",
    "physical_power_curve": "Physical wind reference",
    "solar_quantile": "Solar model · LightGBM",
    "solar_physical": "Physical solar reference",
    "smart_persistence": "Solar persistence · 48 hours",
    "clear_sky_climatology": "Clear-sky climatology",
    "lear_hourly": "LEAR · price history",
    "seasonal_naive": "Weekly price reference",
    "lightgbm_point": "Price model · median LightGBM",
    "lightgbm_quantile": "Price model · quantile LightGBM",
    "load_quantile_gbm": "Demand model · quantile LightGBM",
    "load_point_gbm": "Demand model · median LightGBM",
    "load_ridge": "Demand model · ridge regression",
    "load_weekly": "Weekly demand reference",
}

# Forecast-time inputs and fitting data are deliberately separate.
MODEL_DATA = {
    "hourly_repeated": (
        "Archived weather: IFS, GFS, ICON, Nordic MEPS; mapped SE3 turbines; ENTSO-E generation and capacity.",
        "Wind at turbine height, direction, gusts, air density, icing indicators, fleet response, weather disagreement, generation 48/72/168 hours earlier, calendar cycles.",
        "Past generation as a fraction of installed capacity; rolling training with a seven-day embargo. Calibration uses training-side predictions.",
    ),
    "interpolated_weather": (
        "Same weather archives, SE3 turbine fleet and generation history as the wind model.",
        "The wind model's feature families, with weather interpolated to quarter-hour times.",
        "The same hourly training and calibration recipe; development comparison only.",
    ),
    "physical_power_curve": (
        "Archived wind forecasts, mapped SE3 turbines, installed capacity and historical generation.",
        "Wind at turbine height and each turbine's wind-speed-to-generation curve, weighted across the fleet. No learned generation-lag features.",
        "Historical generation fits an affine bias correction and residual uncertainty around physical output.",
    ),
    "solar_quantile": (
        "Archived ECMWF IFS irradiance, temperature and snow at six German sites; ENTSO-E solar generation and annual capacity.",
        "Physical PV output, clear-sky output, irradiance, temperature, snow flag, sun elevation, forecast lead time and calendar cycles.",
        "Past daylight generation divided by installed capacity; rolling training with a seven-day embargo and training-side quantile calibration.",
    ),
    "solar_physical": (
        "Archived IFS irradiance and temperature; site locations, panel-orientation assumptions, solar geometry and annual capacity.",
        "PVWatts conversion from irradiance and temperature to electricity generation; clear-sky profile sets the daily shape.",
        "Past solar generation fits a derating factor and training-residual uncertainty. Night output is zero.",
    ),
    "smart_persistence": (
        "ENTSO-E solar generation history, installed capacity and calculated clear-sky irradiance.",
        "The observed clear-sky index 48 hours earlier, applied to the delivery day's clear-sky profile. No forecast weather.",
        "Historical residuals set uncertainty. The forecast rule itself reuses the lagged observation.",
    ),
    "clear_sky_climatology": (
        "Historical solar generation and calculated clear-sky profiles.",
        "The historical clear-sky-index distribution and delivery-day solar geometry. No weather forecast.",
        "Training-side climatology; development-only reference.",
    ),
    "lear_hourly": (
        "ENTSO-E day-ahead electricity-price history for Germany-Luxembourg.",
        "Four complete daily price profiles: 1, 2, 3 and 7 days earlier; weekday indicators. No weather, demand or renewable-generation inputs.",
        "24 hourly LASSO regressions. The last 30 training days supply out-of-sample residuals for uncertainty.",
    ),
    "seasonal_naive": (
        "ENTSO-E day-ahead electricity-price history.",
        "Observed price 168 hours earlier on the UTC clock. No forecast weather or generation.",
        "Training residuals provide an offset and uncertainty around the weekly lag.",
    ),
    "lightgbm_point": (
        "ENTSO-E day-ahead electricity-price history.",
        "24/48/72/168-hour price lags, complete daily price profiles from 1/2/3/7 days earlier, weekday, market quarter and month.",
        "Past prices fit median LightGBM; held-out training residuals supply uncertainty. No weather or demand inputs in this baseline.",
    ),
    "lightgbm_quantile": (
        "ENTSO-E day-ahead electricity-price history.",
        "The same price lags, daily profiles and calendar features as median LightGBM. No weather or demand inputs.",
        "Past prices fit 19 direct quantile models. Final-evaluation intervals substantially under-cover.",
    ),
    "load_weekly": (
        "ENTSO-E total electricity-demand observations.",
        "Observed demand 168 hours earlier on the UTC clock.",
        "Training residuals provide an offset and uncertainty around weekly persistence.",
    ),
}
for _model in ("load_ridge", "load_point_gbm", "load_quantile_gbm"):
    MODEL_DATA[_model] = (
        "ENTSO-E electricity-demand history; archived ECMWF IFS temperatures at six German sites; calendar and national holidays.",
        "Demand 72/168 hours earlier, temperature, heating below 15°C, cooling above 22°C, local quarter-hour, weekday, annual/daily cycles and holidays.",
        "Past demand fits the selected regression. Ridge and median LightGBM use the last 30 training days for residual uncertainty; quantile LightGBM predicts 19 quantiles directly.",
    )


def input_rows(model: str) -> list[tuple[str, str]]:
    """Short source-to-feature mapping for the default model view."""
    if model in {"hourly_repeated", "interpolated_weather"}:
        rows = [
            (
                "Weather archives · IFS, GFS, ICON, MEPS",
                "Wind speed, direction, gusts, density, icing and model disagreement",
            ),
            ("SE3 turbine registry", "Turbine response and fleet-weighted weather"),
            (
                "ENTSO-E generation & capacity",
                "Generation 48, 72 and 168 hours earlier; capacity-factor targets",
            ),
            ("Calendar", "Daily and annual cycles"),
        ]
    elif model == "physical_power_curve":
        rows = [
            (
                "Wind forecasts & SE3 turbines",
                "Wind-speed-to-generation response across the fleet",
            ),
            (
                "Generation history & capacity",
                "Bias correction, output scaling and residual uncertainty",
            ),
        ]
    elif model in {"solar_quantile", "solar_physical"}:
        rows = [
            (
                "ECMWF IFS weather archive",
                "Irradiance and temperature at six German sites",
            ),
            (
                "Solar geometry & panel assumptions",
                "Clear-sky profile and physical PV output",
            ),
            (
                "ENTSO-E generation & capacity",
                "Historical output and installed-capacity scaling",
            ),
        ]
        if model == "solar_quantile":
            rows.append(
                (
                    "Snow, calendar & forecast timing",
                    "Snow flag, sun elevation, lead time and daily/annual cycles",
                )
            )
    elif model in {"smart_persistence", "clear_sky_climatology"}:
        rows = [
            (
                "Solar generation history",
                "Clear-sky index 48 hours earlier"
                if model == "smart_persistence"
                else "Historical clear-sky-index distribution",
            ),
            (
                "Solar geometry & installed capacity",
                "Delivery-day clear-sky profile and output scaling",
            ),
        ]
    elif model == "lear_hourly":
        rows = [
            (
                "ENTSO-E price history",
                "Daily price profiles from 1, 2, 3 and 7 days earlier",
            ),
            ("Calendar", "Weekday indicators"),
            ("Training errors", "Last 30 training days set the prediction range"),
        ]
    elif model in {"seasonal_naive", "load_weekly"}:
        rows = [
            (
                "ENTSO-E price history"
                if model == "seasonal_naive"
                else "ENTSO-E demand history",
                "Observed value 168 hours earlier",
            ),
            ("Training errors", "Offset and uncertainty around the weekly reference"),
        ]
    elif model in {"lightgbm_point", "lightgbm_quantile"}:
        rows = [
            (
                "ENTSO-E price history",
                "24/48/72/168-hour lags and daily profiles from 1/2/3/7 days earlier",
            ),
            ("Calendar", "Weekday, market quarter and month"),
        ]
    else:
        rows = [
            ("ENTSO-E demand history", "Demand 72 and 168 hours earlier"),
            (
                "ECMWF IFS temperature archive",
                "Temperature, heating and cooling at six German sites",
            ),
            (
                "Calendar",
                "Quarter-hour, weekday, daily/annual cycles and national holidays",
            ),
        ]
    return rows
