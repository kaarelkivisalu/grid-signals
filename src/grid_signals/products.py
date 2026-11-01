"""Shared forecast products and provider codes; membership is not coverage."""

from dataclasses import dataclass

from grid_signals.markets import BY_CODE

ENTSOE_CODES = {
    code: code[:2] + "_" + code[2:]
    if code[:2] in {"SE", "NO", "DK"} and code[2:].isdigit()
    else code
    for code in BY_CODE
}
ENTSOE_CODES["SE"] = "SE"  # Installed capacity is published nationally.


@dataclass(frozen=True)
class Product:
    zone: str
    target: str
    unit: str
    adapter: str
    fleet: str
    resolution: str = "15min"
    cutoff_hour_utc: int = 9
    deadline_minute_utc: int = 30
    # Preserve the evaluated CET/CEST delivery-day convention for these products.
    delivery_timezone: str = "Europe/Berlin"


PRODUCTS = {
    "se3-wind": Product("SE3", "wind_onshore", "MW", "renewable", "vindbrukskollen"),
    "de-solar": Product("DE_LU", "solar", "MW", "renewable", "six_site_solar"),
    "de-load": Product("DE_LU", "total_load", "MW", "load", "national_load"),
    "de-price": Product("DE_LU", "spot_price", "EUR/MWh", "price", "price_history"),
}


def renewable_product(zone: str, fuel: str) -> Product:
    for product in PRODUCTS.values():
        if product.adapter == "renewable" and (product.zone, product.target) == (
            zone,
            fuel,
        ):
            return product
    message = f"No evaluated renewable product for {zone} {fuel}"
    raise ValueError(message)
