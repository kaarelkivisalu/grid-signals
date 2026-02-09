"""ENTSO-E fuel type name → normalized slug mapping."""

FUEL_TYPE_MAP: dict[str, str] = {
    "Biomass": "biomass",
    "Fossil Brown coal/Lignite": "lignite",
    "Fossil Coal-derived gas": "coal_gas",
    "Fossil Gas": "gas",
    "Fossil Hard coal": "hard_coal",
    "Fossil Oil": "oil",
    "Fossil Oil shale": "oil_shale",
    "Fossil Peat": "peat",
    "Geothermal": "geothermal",
    "Hydro Pumped Storage": "hydro_pumped",
    "Hydro Run-of-river and poundage": "hydro_run_of_river",
    "Hydro Water Reservoir": "hydro_reservoir",
    "Marine": "marine",
    "Nuclear": "nuclear",
    "Other": "other",
    "Other renewable": "other_renewable",
    "Solar": "solar",
    "Waste": "waste",
    "Wind Offshore": "wind_offshore",
    "Wind Onshore": "wind_onshore",
}


def normalize_fuel_type(raw: str) -> str:
    """Map an ENTSO-E fuel type name to a normalized slug.

    Returns the raw name lowercased with spaces replaced by underscores
    if no explicit mapping exists.
    """
    return FUEL_TYPE_MAP.get(raw, raw.lower().replace(" ", "_"))
