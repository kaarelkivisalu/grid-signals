from enum import StrEnum


class BiddingZone(StrEnum):
    """Nordic-Baltic bidding zones in scope."""

    EE = "EE"      # Estonia
    LV = "LV"      # Latvia
    LT = "LT"      # Lithuania
    FI = "FI"       # Finland
    SE4 = "SE4"     # Southern Sweden
    SE3 = "SE3"     # Central Sweden
    NO1 = "NO1"     # Southern Norway (Oslo)
    NO2 = "NO2"     # Southwestern Norway (Kristiansand)
    NO3 = "NO3"     # Central Norway (Trondheim)
    NO4 = "NO4"     # Northern Norway (Tromsø)
    NO5 = "NO5"     # Western Norway (Bergen)
    DK1 = "DK1"     # Western Denmark (Jutland)
    DK2 = "DK2"     # Eastern Denmark (Zealand)
