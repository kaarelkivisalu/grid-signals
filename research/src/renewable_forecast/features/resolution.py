"""Interpolate weather within a single forecast vintage, before applying physics."""

import numpy as np
import pandas as pd


def validate(value: str) -> pd.Timedelta:
    """Only the two evaluated product resolutions are supported."""
    step = pd.Timedelta(value)
    if step not in {pd.Timedelta("1h"), pd.Timedelta("15min")}:
        raise ValueError("resolution must be 1h or 15min")
    return step


def interpolate(frame: pd.DataFrame, resolution: str = "15min") -> pd.DataFrame:
    """Piecewise linear weather interpolation; no extrapolation or gap filling.

    Each model/run/point/height is independent. Missing endpoints remain missing and
    gaps longer than an hour are never bridged. Directions follow the shortest arc.
    Linear interpolation is monotone between samples and cannot create negative wind.
    """
    step = validate(resolution)
    if step == pd.Timedelta("1h") or frame.empty:
        return frame.copy()
    keys = [c for c in ("model", "run_time", "point_id", "height_m") if c in frame]
    groups = frame.groupby(keys, sort=False, dropna=False) if keys else [((), frame)]
    frames = []
    for key, sample in groups:
        group = sample.sort_values("valid_time").set_index("valid_time")
        if group.index.has_duplicates:
            raise ValueError("duplicate weather timestamps within a vintage")
        grid = pd.date_range(group.index.min(), group.index.max(), freq=step)
        x = group.index.asi8
        target = grid.asi8
        left = np.searchsorted(x, target, side="right") - 1
        right = np.minimum(left + 1, len(x) - 1)
        exact = target == x[left]
        gap = x[right] - x[left]
        usable = exact | ((gap > 0) & (gap <= pd.Timedelta("1h").value))
        out = pd.DataFrame({"valid_time": grid})
        for column in group.columns.difference(keys):
            values = group[column].to_numpy(dtype=float)
            if "direction" in column:
                difference = (values[right] - values[left] + 180) % 360 - 180
                fraction = np.divide(
                    target - x[left], gap, out=np.zeros(len(grid)), where=gap > 0
                )
                interpolated = (values[left] + fraction * difference) % 360
            else:
                interpolated = np.interp(target, x, values)
            interpolated[exact] = values[left[exact]]
            out[column] = np.where(usable, interpolated, np.nan)
        for column, value in zip(
            keys, key if isinstance(key, tuple) else (key,), strict=True
        ):
            out[column] = value
        frames.append(out)
    return pd.concat(frames, ignore_index=True)
