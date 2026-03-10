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

from core import morrenus_api
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


class FetchManifestDialog(QDialog):
    """
    A dialog for searching and downloading manifests from the Morrenus API.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_window = parent
        self.setWindowTitle("Fetch Manifest from Morrenus API")
        self.setMinimumWidth(600)
        self.setMinimumHeight(500)
        self.task_runner = TaskRunner()
        self._active_image_fetchers = {}  # Keep track of active fetchers to prevent GC

        layout = QVBoxLayout(self)

        # API Status Bar
        self._create_api_status_bar(layout)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search for a game...")
        layout.addWidget(self.search_input)

        self.results_list = QListWidget()
        # Set a larger icon size for the header images (Aspect Ratio approx 2.15)
        # Steam Headers are 460x215. Scaled down to half size: 230x108
        self.results_list.setIconSize(QSize(230, 108))
        self.results_list.setSpacing(5)
        layout.addWidget(self.results_list)

        self.status_label = QLabel("Search for a game to begin")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_label)

        self.search_input.returnPressed.connect(self.on_search)
        self.results_list.itemDoubleClicked.connect(self.on_item_double_clicked)

        logger.debug("FetchManifestDialog initialized.")

        self._request_api_status_update()

    def _create_api_status_bar(self, layout):
        """Create the API status bar with health, username, and usage info."""
        status_container = QHBoxLayout()
        status_container.setContentsMargins(0, 0, 0, 5)
        status_container.setSpacing(0)

        # API Status Container (Status Dot + Text)
        api_status_widget = QWidget()
        api_layout = QHBoxLayout(api_status_widget)
        api_layout.setContentsMargins(0, 0, 0, 0)
        api_layout.setSpacing(8)
        api_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.api_status_dot = QLabel()
        self.api_status_dot.setFixedSize(12, 12)
        # Initial state: gray dot
        self.api_status_dot.setStyleSheet(
            "border-radius: 6px; background-color: #95a5a6;"
        )
        self.api_status_text = QLabel("Checking...")

        api_layout.addWidget(self.api_status_dot)
        api_layout.addWidget(self.api_status_text)
        status_container.addWidget(api_status_widget, 1)

        self.username_label = QLabel("User: --")
        self.username_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        status_container.addWidget(self.username_label, 1)

        self.usage_label = QLabel("Daily: --")
        self.usage_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        status_container.addWidget(self.usage_label, 1)

        status_widget = QWidget()
        status_widget.setLayout(status_container)
        layout.addWidget(status_widget)

    def _request_api_status_update(self):
        """Fetch API status in a background thread and update UI when ready."""
        worker = self.task_runner.run(self._fetch_api_status)
        worker.finished.connect(self._apply_api_status)
        worker.error.connect(self._on_api_status_error)

    def _fetch_api_status(self):
        """Collect API status and user stats off the UI thread."""
        health = morrenus_api.check_health()

        stats = _get_cached_stats()
        if stats is None or stats.get("error"):
            stats = morrenus_api.get_user_stats()
            if "error" not in stats:
                _cache_stats(stats)

        return {"health": health, "stats": stats}

    def _apply_api_status(self, result):
        """Update the API status bar with health and user stats."""
        health = result.get("health", {}) if isinstance(result, dict) else {}
        health_status = health.get("status", "unknown")
        if health_status == "healthy":
            self.api_status_dot.setStyleSheet(
                "border-radius: 6px; background-color: #2ecc71;"
            )
            self.api_status_text.setText("Online")
        else:
            self.api_status_dot.setStyleSheet(
                "border-radius: 6px; background-color: #e74c3c;"
            )
            self.api_status_text.setText("Offline")

        stats = result.get("stats", {}) if isinstance(result, dict) else {}
        if stats.get("error"):
            self.username_label.setText("User: Error")
            self.usage_label.setText("Daily: --")
        else:
            username = stats.get("username", "Unknown")
            self.username_label.setText(f"User: {username}")

            daily_usage = stats.get("daily_usage", 0)
            daily_limit = stats.get("daily_limit", 0)
            self.usage_label.setText(f"Daily: {daily_usage}/{daily_limit}")

    def _on_api_status_error(self, error_info):
        _, error_value, _ = error_info
        logger.error(f"Failed to fetch API status: {error_value}", exc_info=error_info)
        self.api_status_dot.setStyleSheet(
            "border-radius: 6px; background-color: #e74c3c;"
        )
        self.api_status_text.setText("Offline")
        self.username_label.setText("User: Error")
        self.usage_label.setText("Daily: --")

    def on_search(self):
        query = self.search_input.text().strip()
        if not query or len(query) < 2:
            self.status_label.setText("Enter at least 2 characters")
            return

        logger.info(f"Starting Morrenus API search for: '{query}'")
        self.results_list.clear()
        # Clear any old fetchers
        self._stop_active_image_fetchers()

        self.status_label.setText("Searching...")
        self.search_input.setEnabled(False)
        self.results_list.setEnabled(False)

        worker = self.task_runner.run(morrenus_api.search_games, query)
        worker.finished.connect(self.on_search_finished)
        worker.error.connect(self.on_task_error)

    def on_search_finished(self, results):
        self.search_input.setEnabled(True)
        self.results_list.setEnabled(True)

        if results.get("error"):
            error_msg = results.get("error")
            logger.error(f"API search failed: {error_msg}")
            self.status_label.setText(f"Error: {error_msg}")
            QMessageBox.critical(self, "Search Error", error_msg)
            return

        game_results = results.get("results")
        if game_results:
            logger.info(f"Found {len(game_results)} results.")

            blacklist_keywords = [
                "soundtrack",
                "ost",
                "original soundtrack",
                "artbook",
                "graphic novel",
                "demo",
                "server",
                "dedicated server",
                "tool",
                "sdk",
                "3d print model",
            ]

            filtered_count = 0
            for game in game_results:
                try:
                    name_lower = game.get("game_name", "").lower()
                except AttributeError:
                    name_lower = "None"
                is_blacklisted = False
                for keyword in blacklist_keywords:
                    if re.search(rf"\b{re.escape(keyword)}\b", name_lower):
                        is_blacklisted = True
                        break

                if not is_blacklisted:
                    app_id = str(game["game_id"])
                    item_text = f"{game['game_name']} (AppID: {app_id})"
                    item = QListWidgetItem(item_text)
                    item.setData(Qt.ItemDataRole.UserRole, app_id)
                    self.results_list.addItem(item)

                    # Initiate async image fetch for this item
                    self._fetch_item_image(item, app_id)
                else:
                    filtered_count += 1

            self.status_label.setText(
                f"Found {len(game_results)} results ({filtered_count} filtered). Double-click to download"
            )
        else:
            logger.info("No results found.")
            self.status_label.setText("No results found")

    def _fetch_item_image(self, item, app_id):
        url = ImageFetcher.get_header_image_url(app_id)

        fetcher = ImageFetcher(url)
        # Store references to prevent garbage collection
        self._active_image_fetchers[app_id] = fetcher

        # Use a lambda to capture the current item for the callback
        fetcher.finished.connect(
            lambda data, i=item, aid=app_id: self._on_item_image_fetched(data, i, aid)
        )
        fetcher.finished.connect(fetcher.deleteLater)
        fetcher.start()

    def _on_item_image_fetched(self, image_data, item, app_id):
        # Clean up reference
        if app_id in self._active_image_fetchers:
            del self._active_image_fetchers[app_id]

        if image_data:
            pixmap = QPixmap()
            pixmap.loadFromData(image_data)
            if not pixmap.isNull():
                item.setIcon(QIcon(pixmap))
        # If it failed, it just won't have an icon, which is fine as a fallback.

    def on_item_double_clicked(self, item):
        app_id = item.data(Qt.ItemDataRole.UserRole)
        if not app_id:
            return

        logger.info(f"User selected AppID {app_id} for download.")
        self.status_label.setText(f"Downloading manifest for App ID {app_id}...")
        self.search_input.setEnabled(False)
        self.results_list.setEnabled(False)

        worker = self.task_runner.run(morrenus_api.download_manifest, app_id)
        worker.finished.connect(self.on_download_finished)
        worker.error.connect(self.on_task_error)

    def on_download_finished(self, result):
        temp_zip_path, error_message = result

        if error_message:
            logger.error(f"Manifest download failed: {error_message}")
            QMessageBox.critical(self, "Download Failed", error_message)
            self.search_input.setEnabled(True)
            self.results_list.setEnabled(True)
            self.status_label.setText("Download failed. Ready to search")
            return

        if temp_zip_path:
            logger.info(f"Manifest downloaded successfully to {temp_zip_path}")
            self.status_label.setText("Download complete! Adding to queue")
            if self.parent_window:
                self.parent_window.job_queue.add_job(temp_zip_path)
            self.accept()

    def on_task_error(self, error_info):
        _, error_value, _ = error_info
        logger.error(f"A worker task failed: {error_value}", exc_info=error_info)
        QMessageBox.critical(
            self, "Error", f"An unexpected error occurred: {error_value}"
        )
        self.search_input.setEnabled(True)
        self.results_list.setEnabled(True)
        self.status_label.setText("An error occurred. Ready to search")

    def closeEvent(self, a0):
        # Ensure all image fetchers are cleaned up when dialog closes
        self._stop_active_image_fetchers()

        # Clean up task_runner thread if running using safe stop method
        if self.task_runner:
            try:
                self.task_runner.stop()
            except RuntimeError:
                # Thread may have already been deleted by Qt
                logger.debug("TaskRunner thread was already deleted, skipping cleanup.")
                pass

        super().closeEvent(a0)

    def _stop_active_image_fetchers(self):
        for fetcher in list(self._active_image_fetchers.values()):
            try:
                fetcher.stop()
            except RuntimeError:
                logger.debug(
                    "Image fetcher was already deleted, skipping cleanup."
                )
                pass
        self._active_image_fetchers.clear()
