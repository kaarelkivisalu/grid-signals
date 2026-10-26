"""Exercise the built web image with networking disabled and no service keys.

Run inside Docker using: docker run --rm -i --network none --entrypoint python
grid-signals-demo:local < tests/demo_image_check.py
"""

import hashlib
import importlib.util
import json
import os
import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = Path("/app/src/grid_signals/app")


class DemoReleaseTests(unittest.TestCase):
    def test_image_contains_only_current_results_and_web_dependencies(self):
        assert os.getuid() != 0
        assert not (Path("/app") / ".env").exists()
        for key in ("ENTSOE_API_KEY", "ANTHROPIC_API_KEY", "DATABASE_URL"):
            assert key not in os.environ
        for module in ("psycopg", "anthropic", "prefect", "lightgbm", "mlflow"):
            assert importlib.util.find_spec(module) is None
        assert {path.name for path in APP.parent.iterdir()} == {"__init__.py", "app"}
        assert {path.name for path in (APP / "pages").glob("*.py")} == {
            "overview.py",
            "wind.py",
            "solar.py",
            "price.py",
            "load.py",
            "performance.py",
            "coverage.py",
            "methods.py",
        }
        root = APP / "assets/explorer"
        index = json.loads((root / "manifest.json").read_text())
        files = {
            info[key]
            for info in index["zones"].values()
            for key in ("forecast_file", "observation_file")
            if info[key]
        }
        assert {path.name for path in root.glob("*.parquet")} == files
        for name in files:
            digest = hashlib.sha256((root / name).read_bytes()).hexdigest()[:16]
            assert name.endswith(f"-{digest}.parquet")

    def test_forecasts_evidence_methods_and_missing_data_work_offline(self):
        app = AppTest.from_file(str(APP / "main.py"), default_timeout=30).run()
        assert not app.exception
        assert app.session_state["selected_zone"] == "SE3"
        assert app.session_state["selected_target"] == "wind_onshore"
        assert not app.sidebar.selectbox
        assert not app.sidebar.date_input
        assert any("2026-09-19" in caption.value for caption in app.caption)
        for page in (
            "wind",
            "solar",
            "price",
            "load",
            "performance",
            "methods",
            "coverage",
            "overview",
        ):
            app.switch_page(f"pages/{page}.py").run()
            assert not app.exception, page
            assert not app.error, page
        app.switch_page("pages/wind.py").run()
        assert app.button(key="market_wind_onshore_NO1").disabled
        assert not app.button(key="market_wind_onshore_SE3").disabled
        app.switch_page("pages/solar.py").run()
        assert app.session_state["selected_zone"] == "DE_LU"
        assert app.button(key="market_solar_SE3").disabled
        assert not app.button(key="market_solar_DE_LU").disabled


if __name__ == "__main__":
    unittest.main()
