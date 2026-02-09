from enum import StrEnum


class BiddingZone(StrEnum):
    """Nordic-Baltic bidding zones in scope."""

    EE = "EE"      # Estonia
    LV = "LV"      # Latvia
    LT = "LT"      # Lithuania
    FI = "FI"       # Finland
    SE4 = "SE4"     # Southern Sweden
    SE3 = "SE3"     # Central Sweden
    PL = "PL"       # Poland (for LT-PL cross-border flows)
