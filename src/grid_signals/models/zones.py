from enum import StrEnum


class BiddingZone(StrEnum):
    """Nordic-Baltic bidding zones in scope."""

    EE = "EE"      # Estonia
    LV = "LV"      # Latvia
    LT = "LT"      # Lithuania
    FI = "FI"       # Finland
    SE1 = "SE1"     # Northern Sweden (Luleå)
    SE2 = "SE2"     # Northern-Central Sweden (Sundsvall)
    SE3 = "SE3"     # Central Sweden (Stockholm)
    SE4 = "SE4"     # Southern Sweden (Malmö)
    NO1 = "NO1"     # Southern Norway (Oslo)
    NO2 = "NO2"     # Southwestern Norway (Kristiansand)
    NO3 = "NO3"     # Central Norway (Trondheim)
    NO4 = "NO4"     # Northern Norway (Tromsø)
    NO5 = "NO5"     # Western Norway (Bergen)
    DK1 = "DK1"     # Western Denmark (Jutland)
    DK2 = "DK2"     # Eastern Denmark (Zealand)
