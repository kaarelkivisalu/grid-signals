"""Guards on the report figures.

The reports embed figures by relative path. A stale or mistyped path renders as a broken
image in every viewer and silently costs the reader the evidence for a claim, so the
paths are asserted rather than eyeballed.
"""

import re

import pytest

from renewable_forecast import paths
from renewable_forecast.reporting import figures

IMAGE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
MARKDOWN = (
    sorted(paths.ROOT.glob("*.md"))
    + sorted(paths.REPORTS.glob("*.md"))
    + sorted(paths.DOCS.glob("*.md"))
)


@pytest.mark.parametrize("document", MARKDOWN, ids=lambda p: p.name)
def test_every_embedded_figure_resolves(document):
    missing = [
        target
        for target in IMAGE.findall(document.read_text())
        if not target.startswith(("http://", "https://"))
        and not (document.parent / target).exists()
    ]
    assert not missing, f"{document.name} embeds missing figures: {missing}"


def test_colours_cover_every_forecaster_drawn():
    assert set(figures.ORDER) <= set(figures.COLOURS)


def test_reference_forecaster_is_never_treated_as_a_bar():
    # A69 is served at its latest revision, so it must stay in ORDER for drawing but
    # be excluded wherever the report ranks models against each other.
    assert figures.REFERENCE in figures.ORDER
