"""Rename weather_forecasts location names from bare country codes to descriptive names."""

import duckdb

DB_PATH = "data/grid_signals.duckdb"

RENAMES = {
    "EE": "EE_tallinn",
    "LT": "LT_kaunas",
    "LV": "LV_riga",
}


def main() -> None:
    con = duckdb.connect(DB_PATH)
    for old, new in RENAMES.items():
        result = con.execute(
            "UPDATE weather_forecasts SET location_name = ? WHERE location_name = ?",
            [new, old],
        )
        print(f"Renamed '{old}' → '{new}': {result.fetchone()[0]} rows updated")
    con.close()


if __name__ == "__main__":
    main()
