"""Tests for Prefect flow definitions.

Catches issues like TYPE_CHECKING-only imports that break Pydantic
parameter validation at runtime.
"""

import pytest

from grid_signals.flows import initial_seed, morning_pipeline, weather_update

ALL_FLOWS = [morning_pipeline, weather_update, initial_seed]


@pytest.mark.parametrize("flow_fn", ALL_FLOWS, ids=lambda f: f.name)
def test_flow_parameter_models_resolve(flow_fn):
    """Prefect builds a Pydantic model for each flow's parameters.

    If a type annotation (e.g. Path) is only available under
    TYPE_CHECKING, Pydantic raises PydanticUserError at runtime.
    Calling validate_parameters with defaults exercises that path.
    """
    flow_fn.validate_parameters({})
