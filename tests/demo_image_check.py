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
        assert any("Final holdout" in caption.value for caption in app.caption)
        for page in ("performance", "methods", "coverage", "overview"):
            app.switch_page(f"pages/{page}.py").run()
            assert not app.exception, page
            assert not app.error, page
        app.selectbox(key="selected_zone").set_value("DE_LU").run()
        for target in ("solar", "load", "price"):
            app.selectbox(key="selected_target").set_value(target).run()
            assert not app.exception, target
            assert any("Final holdout" in caption.value for caption in app.caption), (
                target
            )
        app.selectbox(key="selected_zone").set_value("CH").run()
        assert not app.exception
        assert "no data bundled" in app.info[0].value


if __name__ == "__main__":
    unittest.main()
