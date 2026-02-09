"""ENTSO-E client factory, zone mapping, and border definitions."""

import os

from entsoe import EntsoePandasClient

from grid_signals.models.zones import BiddingZone

# entsoe-py uses underscored codes for Swedish zones; rest map 1:1.
ZONE_TO_ENTSOE: dict[BiddingZone, str] = {
    BiddingZone.EE: "EE",
    BiddingZone.LV: "LV",
    BiddingZone.LT: "LT",
    BiddingZone.FI: "FI",
    BiddingZone.SE4: "SE_4",
    BiddingZone.SE3: "SE_3",
    BiddingZone.PL: "PL",
}

# Cross-border interconnectors in the Nordic-Baltic region.
BORDERS: list[tuple[BiddingZone, BiddingZone]] = [
    (BiddingZone.EE, BiddingZone.FI),
    (BiddingZone.EE, BiddingZone.LV),
    (BiddingZone.LV, BiddingZone.LT),
    (BiddingZone.LT, BiddingZone.SE4),
    (BiddingZone.FI, BiddingZone.SE3),
    (BiddingZone.SE3, BiddingZone.SE4),
    (BiddingZone.LT, BiddingZone.PL),
]


def get_entsoe_client() -> EntsoePandasClient:
    """Create an EntsoePandasClient from the ENTSOE_API_KEY env var."""
    api_key = os.environ["ENTSOE_API_KEY"]
    return EntsoePandasClient(api_key=api_key, retry_count=3, retry_delay=10)
