import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from corporate_atlas.settings import SETTINGS, load_settings


class SettingsTests(unittest.TestCase):
    def test_loads_packaged_configuration(self):
        self.assertEqual(SETTINGS.api.port, 8501)
        self.assertEqual(SETTINGS.indexing.batch_delay_seconds, 0)
        self.assertIn("AAPL", SETTINGS.sec.default_tickers)

    def test_rejects_inconsistent_query_limits(self):
        config_path = (
            Path(__file__).parents[1]
            / "src"
            / "python"
            / "corporate_atlas"
            / "config.toml"
        )
        invalid_config = config_path.read_text(encoding="utf-8").replace(
            "default_top_k = 12",
            "default_top_k = 51",
            1,
        )
        with tempfile.TemporaryDirectory() as directory:
            temporary_config = Path(directory) / "config.toml"
            temporary_config.write_text(invalid_config, encoding="utf-8")
            with self.assertRaises(ValidationError):
                load_settings(temporary_config)


if __name__ == "__main__":
    unittest.main()
