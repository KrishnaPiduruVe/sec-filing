"""Central application paths, independent of the caller's working directory."""
import os
from pathlib import Path

from corporate_atlas.settings import SETTINGS

# The src layout resolves to the checkout root. Packaged deployments can set
# ATLAS_PROJECT_ROOT explicitly to the directory containing their .env file.
PROJECT_ROOT = Path(os.getenv('ATLAS_PROJECT_ROOT', Path(__file__).resolve().parents[3])).expanduser().resolve()
_configured_data_dir = os.getenv('ATLAS_DATA_DIR', SETTINGS.paths.data_dir)
_data = Path(_configured_data_dir).expanduser()
DATA_ROOT = (_data if _data.is_absolute() else PROJECT_ROOT / _data).resolve()
ENV_FILE = PROJECT_ROOT / '.env'
