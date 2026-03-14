import logging
import re

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from utils.image_fetcher import ImageFetcher
from utils.task_runner import TaskRunner

logger = logging.getLogger(__name__)

# Cache for API stats to avoid excessive requests
_api_stats_cache = {"data": None, "timestamp": 0}
_API_STATS_CACHE_DURATION = 60  # seconds


def _get_cached_stats():
    """Returns cached stats if still valid, otherwise None."""
    import time

    if _api_stats_cache["data"] is not None:
        if time.time() - _api_stats_cache["timestamp"] < _API_STATS_CACHE_DURATION:
            return _api_stats_cache["data"]
    return None


def _cache_stats(data):
    """Store stats in cache."""
    import time

    _api_stats_cache["data"] = data
    _api_stats_cache["timestamp"] = time.time()



