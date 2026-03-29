"""ENTSO-E client factory, zone mapping, and border definitions."""

import os

from entsoe import EntsoePandasClient

from grid_signals.models.zones import BiddingZone

# entsoe-py uses underscored codes for Swedish/Norwegian/Danish zones; rest map 1:1.
ZONE_TO_ENTSOE: dict[BiddingZone, str] = {
    BiddingZone.EE: "EE",
    BiddingZone.LV: "LV",
    BiddingZone.LT: "LT",
    BiddingZone.FI: "FI",
    BiddingZone.SE1: "SE_1",
    BiddingZone.SE2: "SE_2",
    BiddingZone.SE3: "SE_3",
    BiddingZone.SE4: "SE_4",
    BiddingZone.NO1: "NO_1",
    BiddingZone.NO2: "NO_2",
    BiddingZone.NO3: "NO_3",
    BiddingZone.NO4: "NO_4",
    BiddingZone.NO5: "NO_5",
    BiddingZone.DK1: "DK_1",
    BiddingZone.DK2: "DK_2",
}

# Cross-border interconnectors in the Nordic-Baltic region (one pair per
# physical link — BORDER_PAIRS expands to both directions for flow ingestion).
_BORDER_LINKS: list[tuple[BiddingZone, BiddingZone]] = [
    # Baltic
    (BiddingZone.EE, BiddingZone.FI),
    (BiddingZone.EE, BiddingZone.LV),
    (BiddingZone.LV, BiddingZone.LT),
    # Baltic–Nordics
    (BiddingZone.LT, BiddingZone.SE4),
    (BiddingZone.FI, BiddingZone.SE3),
    # Sweden internal
    (BiddingZone.SE1, BiddingZone.SE2),
    (BiddingZone.SE2, BiddingZone.SE3),
    (BiddingZone.SE3, BiddingZone.SE4),
    # Norway internal
    (BiddingZone.NO1, BiddingZone.NO2),
    (BiddingZone.NO1, BiddingZone.NO3),
    (BiddingZone.NO1, BiddingZone.NO5),
    (BiddingZone.NO2, BiddingZone.NO5),
    (BiddingZone.NO3, BiddingZone.NO4),
    (BiddingZone.NO3, BiddingZone.NO5),
    # Norway–Sweden/Finland
    (BiddingZone.NO1, BiddingZone.SE3),
    (BiddingZone.NO3, BiddingZone.SE2),
    (BiddingZone.NO4, BiddingZone.SE1),
    (BiddingZone.NO4, BiddingZone.SE2),
    (BiddingZone.NO4, BiddingZone.FI),
    (BiddingZone.FI, BiddingZone.SE1),
    # Denmark
    (BiddingZone.DK1, BiddingZone.DK2),
    (BiddingZone.DK1, BiddingZone.NO2),
    (BiddingZone.DK1, BiddingZone.SE3),
    (BiddingZone.DK2, BiddingZone.SE4),
]

# Both directions for each link — ENTSO-E reports A→B and B→A separately.
BORDERS: list[tuple[BiddingZone, BiddingZone]] = [
    pair for a, b in _BORDER_LINKS for pair in ((a, b), (b, a))
]


def get_entsoe_client() -> EntsoePandasClient:
    """Create an EntsoePandasClient from the ENTSOE_API_KEY env var."""
    api_key = os.environ["ENTSOE_API_KEY"]
    return EntsoePandasClient(api_key=api_key, retry_count=3, retry_delay=10)
