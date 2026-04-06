"""ENTSO-E client factory, zone mapping, and border definitions."""

from entsoe import EntsoePandasClient

from grid_signals.config import get_entsoe_api_key
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

# Cross-border interconnectors between zones we track (one pair per physical
# link — BORDERS expands to both directions for flow ingestion).
_INTERNAL_LINKS: list[tuple[str, str]] = [
    # Baltic
    ("EE", "FI"),
    ("EE", "LV"),
    ("LV", "LT"),
    # Baltic-Nordics
    ("LT", "SE_4"),
    ("FI", "SE_3"),
    # Sweden internal
    ("SE_1", "SE_2"),
    ("SE_2", "SE_3"),
    ("SE_3", "SE_4"),
    # Norway internal
    ("NO_1", "NO_2"),
    ("NO_1", "NO_3"),
    ("NO_1", "NO_5"),
    ("NO_2", "NO_5"),
    ("NO_3", "NO_4"),
    ("NO_3", "NO_5"),
    # Norway-Sweden/Finland
    ("NO_1", "SE_3"),
    ("NO_3", "SE_2"),
    ("NO_4", "SE_1"),
    ("NO_4", "SE_2"),
    ("NO_4", "FI"),
    ("FI", "SE_1"),
    # Denmark
    ("DK_1", "DK_2"),
    ("DK_1", "NO_2"),
    ("DK_1", "SE_3"),
    ("DK_2", "SE_4"),
]

# Interconnectors to zones outside our scope (one of our zones ↔ external zone).
_EXTERNAL_LINKS: list[tuple[str, str]] = [
    ("DK_1", "DE_LU"),
    ("DK_1", "GB"),
    ("DK_1", "NL"),
    ("DK_2", "DE_LU"),
    ("LT", "PL"),
    ("NO_2", "DE_LU"),
    ("NO_2", "GB"),
    ("NO_2", "NL"),
    ("SE_4", "DE_LU"),
    ("SE_4", "PL"),
]

# Both directions for each link — ENTSO-E reports A→B and B→A separately.
BORDERS: list[tuple[str, str]] = [
    pair for a, b in _INTERNAL_LINKS + _EXTERNAL_LINKS for pair in ((a, b), (b, a))
]


def get_entsoe_client() -> EntsoePandasClient:
    """Create an EntsoePandasClient from the ENTSOE_API_KEY env var."""
    api_key = get_entsoe_api_key()
    return EntsoePandasClient(
        api_key=api_key, retry_count=3, retry_delay=10, timeout=60
    )
