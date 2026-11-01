"""The decision example must respect energy and power constraints, including DST."""

import numpy as np
import pytest

from grid_signals.forecast.pipelines.decision_study import dispatch


@pytest.mark.parametrize("intervals", [92, 96, 100])
def test_dispatch_preserves_energy_and_power_with_negative_prices(intervals):
    prices = np.linspace(-100, 200, intervals)
    energy = dispatch(prices)
    assert energy.sum() == pytest.approx(1)
    assert (energy / 0.25).max() == pytest.approx(0.5)
    assert energy[:8].sum() == pytest.approx(1)
    assert energy @ prices <= prices.mean()
    assert np.array_equal(energy, dispatch(prices))


def test_unknown_prices_cannot_produce_a_dispatch():
    with pytest.raises(ValueError, match="finite"):
        dispatch(np.array([float("nan")] * 96))
