from utils.paths import Paths
import logging

logger = logging.getLogger(__name__)
version_file = Paths.resource("version")
app_version = "unknown version"

if version_file.exists():
    try:
        with open(str(version_file), "r", encoding="utf-8") as f:
            app_version = f.read().strip() or "unknown version"
    except Exception as e:
        logger.warning(f"Failed to read version file: {e}")
else:
    logger.warning("Version file not found, using unknown version")