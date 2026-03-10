import logging
import os
import platform
import sys
import subprocess
from pathlib import Path
from functools import partial
from weakref import ref as weakref

from PyQt6.QtCore import QSize, Qt, QTimer
from PyQt6.QtGui import QIntValidator
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core import morrenus_api
from core.steam_helpers import slssteam_api_send
from utils.helpers import get_base_path
from utils.image_fetcher import ImageFetcher
from utils.yaml_config_manager import (
    add_fake_app_id,
    get_fake_app_ids,
    get_user_config_path,
    is_slssteam_config_management_enabled,
    is_slssteam_mode_enabled,
    remove_fake_app_id,
)

logger = logging.getLogger(__name__)


class GameItemWidget(QWidget):
    """Custom widget for displaying a game item in the library"""

    def __init__(self, game_data, size_str, accent_color):
        super().__init__()
        self.game_data = game_data
        self.accent_color = accent_color

        layout = QVBoxLayout(self)

        # Game name (top)
        name_label = QLabel(game_data.get("game_name", "Unknown"))
        name_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(name_label)

        # Size (middle)
        size_label = QLabel(f"Size: {size_str}")
        layout.addWidget(size_label)

        # Update status (bottom, always visible with four states)
        update_status = game_data.get("update_status", "cannot_determine")
        status_label = QLabel()

        if update_status == "update_available":
            status_label.setText("New version available")
            status_label.setStyleSheet(f"color: {self.accent_color};")
        elif update_status == "up_to_date":
            status_label.setText("Up to date")
            status_label.setStyleSheet(f"color: {self.accent_color};")
        elif update_status == "checking":
            status_label.setText("Checking for updates...")
            status_label.setStyleSheet(f"color: {self.accent_color};")
        elif update_status == "cannot_determine":
            status_label.setText("Unable to check updates")
            status_label.setStyleSheet(f"color: {self.accent_color};")

        layout.addWidget(status_label)

    def sizeHint(self):
        """Return size hint that matches the icon height"""
        return QSize(230, 108)


class GameLibraryDialog(QDialog):
    """Dialog to display and manage the game library"""

    def __init__(self, main_window):
        super().__init__(main_window)
        self.main_window = main_window
        self.game_manager = main_window.game_manager
        self.settings = main_window.settings
        self.accent_color = self.settings.value("accent_color", "#C06C84")
        # Store active fetchers by app_id to prevent duplicates and allow cleanup
        self._active_fetchers = {}  # app_id -> ImageFetcher
        self._image_cache = {}  # Cache for downloaded images

        self.setWindowTitle("Game Library")
        self.setMinimumWidth(800)
        self.setMinimumHeight(800)

        layout = QVBoxLayout(self)

        # Scan button
        self.scan_button = QPushButton("Scan Libraries")
        self.scan_button.clicked.connect(self._scan_for_games)
        layout.addWidget(self.scan_button)

        # Sort options
        sort_layout = QHBoxLayout()
        sort_label = QLabel("Sort by:")
        sort_layout.addWidget(sort_label)

        self.sort_combo = QComboBox()
        self.sort_combo.addItem("Recently Installed", "recently_installed")
        self.sort_combo.addItem("Name (A-Z)", "name_asc")
        self.sort_combo.addItem("Name (Z-A)", "name_desc")
        self.sort_combo.addItem("Size (Smallest)", "size_asc")
        self.sort_combo.addItem("Size (Largest)", "size_desc")
        self.sort_combo.addItem("AppID", "appid")
        self.sort_combo.currentIndexChanged.connect(self._on_sort_changed)
        sort_layout.addWidget(self.sort_combo)
        sort_layout.addStretch()

        layout.addLayout(sort_layout)

        # Games list
        self.games_list = QListWidget()
        self.games_list.setIconSize(QSize(230, 108))
        self.games_list.setSpacing(5)
        self.games_list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        scrollbar = self.games_list.verticalScrollBar()
        if scrollbar is not None:
            scrollbar.setSingleStep(10)
        layout.addWidget(self.games_list)

        # Bottom info
        self.info_label = QLabel("Found 0 games installed by ACCELA")
        layout.addWidget(self.info_label)

        self._connect_signals()

        # Game library is now scanned at app startup
        # Just refresh the existing list (which should already be populated)
        self._refresh_game_list()

    def _connect_signals(self):
        # Use UniqueConnection to prevent signal accumulation when dialog is opened multiple times
        self.game_manager.scan_complete.connect(
            self._on_scan_complete, Qt.ConnectionType.UniqueConnection
        )
        self.game_manager.library_updated.connect(
            self._refresh_game_list, Qt.ConnectionType.UniqueConnection
        )
        self.game_manager.game_update_status_changed.connect(
            self._on_game_update_status_changed, Qt.ConnectionType.UniqueConnection
        )
        self.games_list.itemSelectionChanged.connect(self._on_item_selected)
        self._dialog_open = False  # Track if dialog is already open
        self._refreshing = False  # Track if list is being refreshed
        self._closing = False  # Track if dialog is being closed
        self._scanning = False  # Track if scan is in progress
        self._checking_updates = False  # Track if update checking is in progress
        self._current_shortcuts_task = None  # Track current shortcuts task
        self._current_shortcuts_runner = None  # Track current shortcuts task runner

    def _scan_for_games(self):
        """Scan Steam libraries for ACCELA-installed games"""
        # Prevent multiple simultaneous scans
        if self._scanning:
            logger.warning("Scan already in progress, ignoring request")
            return

        self._scanning = True
        self.scan_button.setEnabled(False)
        self.info_label.setText("Scanning Steam libraries...")
        self._refreshing = True  # Set refreshing flag during scan
        self.games_list.clear()

        self.game_manager.scan_steam_libraries_async()

        # Result will be handled in _on_scan_complete via signal

    def _on_scan_complete(self, count):
        """Handle scan completion"""
        self.scan_button.setEnabled(True)

        if count > 0:
            self._checking_updates = True
            # Start a timer to check if update checking is done
            QTimer.singleShot(100, self._check_if_updates_complete)
        else:
            self.info_label.setText(f"Scan complete: Found {count} game(s) installed by ACCELA")
            self._scanning = False

        # Note: _refreshing flag is cleared in _refresh_game_list

    def _on_sort_changed(self):
        """Handle sort option change"""
        self._refresh_game_list()

    def _sort_games(self, games):
        """Sort games based on selected option"""
        sort_option = self.sort_combo.currentData()

        def get_key(game):
            if sort_option == "name_asc":
                return game.get("game_name", "").lower()
            elif sort_option == "name_desc":
                return game.get("game_name", "").lower()
            elif sort_option == "size_asc":
                return game.get("size_on_disk", 0)
            elif sort_option == "size_desc":
                return game.get("size_on_disk", 0)
            elif sort_option == "appid":
                try:
                    return int(game.get("appid", 0))
                except (ValueError, TypeError):
                    return 0
            elif sort_option == "recently_installed":
                depot_path = game.get("depot_downloader_path", "")
                if depot_path and os.path.exists(depot_path):
                    try:
                        return os.path.getmtime(depot_path)
                    except (OSError, PermissionError):
                        return 0
                return 0
            return game.get("game_name", "").lower()

        def sort_reverse():
            if sort_option in ("name_desc", "size_desc", "recently_installed"):
                return True
            return False

        return sorted(games, key=get_key, reverse=sort_reverse())

    def _check_if_updates_complete(self):
        """Check if all games have been checked for updates"""
        if not self._checking_updates:
            return

        # Count how many games still show "checking" or have no appid
        checking_count = 0
        total_games = 0

        for i in range(self.games_list.count()):
            item = self.games_list.item(i)
            if item:
                game_data = item.data(Qt.ItemDataRole.UserRole)
                if game_data:
                    total_games += 1
                    status = game_data.get("update_status")
                    if status == "checking":
                        checking_count += 1

        # If no games show "checking", update checking is complete
        if total_games > 0 and checking_count == 0:
            self._checking_updates = False
            self._scanning = False
            # Refresh to show total size info
            self._refresh_game_list()
        else:
            # Check again later
            QTimer.singleShot(500, self._check_if_updates_complete)

    def _on_game_update_status_changed(self, appid, update_status):
        # Defensive check: don't process if dialog is closing or not visible
        if self._closing or not self.isVisible():
            return

        for i in range(self.games_list.count()):
            item = self.games_list.item(i)
            if item:
                game_data = item.data(Qt.ItemDataRole.UserRole)
                if game_data and game_data.get("appid") == appid:
                    # Update the game's status
                    game_data["update_status"] = update_status

                    # Recreate the widget with the new status
                    # Instead of clearing and re-adding all items, just update this one
                    size_str = self._format_size(game_data.get("size_on_disk", 0))
                    game_widget = GameItemWidget(game_data, size_str, self.accent_color)

                    # Set the updated widget
                    self.games_list.setItemWidget(item, game_widget)

                    # Keep the data updated
                    item.setData(Qt.ItemDataRole.UserRole, game_data)

                    logger.debug(f"Updated UI for game {appid}: {update_status}")
                    break

    def _format_size(self, size_bytes):
        """Format size in bytes to human-readable format"""
        if size_bytes == 0:
            return "0 B"
        size_names = ["B", "KB", "MB", "GB", "TB"]
        import math

        i = int(math.floor(math.log(size_bytes, 1024)))
        p = math.pow(1024, i)
        s = round(size_bytes / p, 2)
        return f"{s} {size_names[i]}"

    def _fetch_item_image(self, item, app_id):
        """Asynchronously fetch header image for a game item using Qt's network API"""
        logger.debug(f"Starting image fetch for game {app_id}")
        url = ImageFetcher.get_header_image_url(app_id)

        # Don't start duplicate fetches
        if app_id in self._active_fetchers:
            return

        # Create fetcher (uses QNetworkAccessManager internally - no threads!)
        fetcher = ImageFetcher(url)
        fetcher.setProperty("app_id", app_id)
        
        # Store reference to prevent garbage collection and allow cleanup
        self._active_fetchers[app_id] = fetcher

        # Connect signal - no need for QueuedConnection since it's already on main thread
        fetcher.finished.connect(self._on_item_image_fetched)
        fetcher.finished.connect(lambda _, aid=app_id: self._cleanup_fetcher(aid))
        
        # Start the async fetch
        fetcher.start()

    def _cleanup_fetcher(self, app_id):
        """Remove fetcher from active dict after it completes"""
        fetcher = self._active_fetchers.pop(app_id, None)
        if fetcher:
            fetcher.deleteLater()

    def _on_item_image_fetched(self, image_data):
        """Handle fetched image data"""
        # Defensive check: don't process if dialog is closing or not visible
        if self._closing or not self.isVisible():
            return

        sender = self.sender()
        if sender is None:
            return

        # Read the app_id from Qt dynamic properties
        app_id = sender.property("app_id")
        if app_id is None:
            return

        # Cache the image data
        if image_data:
            self._image_cache[app_id] = image_data

        # If we got valid image data, find the current item by app_id and set the icon
        if image_data:
            pixmap = QPixmap()
            pixmap.loadFromData(image_data)
            if not pixmap.isNull():
                # Find the item with matching app_id (safer than storing item reference)
                item = self._find_item_by_appid(app_id)
                if item is None:
                    logger.debug(f"Item for game {app_id} not found in list, skipping icon set")
                    return

                try:
                    # Resize to smaller dimensions (half size)
                    resized_pixmap = pixmap.scaled(
                        230,
                        108,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                    item.setIcon(QIcon(resized_pixmap))
                    logger.debug(f"Successfully set icon for game {app_id}")
                except RuntimeError as e:
                    # Item was deleted, ignore
                    logger.debug(
                        f"Item for game {app_id} was deleted, skipping icon set"
                    )
                except Exception as e:
                    logger.warning(f"Error setting icon for game {app_id}: {e}")
        else:
            logger.debug(f"No image data received for game {app_id}, attempting to refresh from API")
            # Trigger a database refresh for this appid to fetch fresh metadata
            # Use QTimer to avoid blocking the UI
            QTimer.singleShot(0, lambda aid=app_id: self._trigger_header_refresh(aid))

    def _trigger_header_refresh(self, app_id):
        """
        Trigger a background refresh of the header image URL from the Steam API.
        This is called when an image fetch fails, to update the database with fresh data.
        Uses a background thread to avoid blocking the UI.
        """
        from concurrent.futures import ThreadPoolExecutor
        
        # Use a thread pool to fetch the header URL without blocking
        def fetch_and_update():
            try:
                from utils.image_fetcher import ImageFetcher
                
                # Fetch the correct URL from Steam API
                api_url = ImageFetcher._fetch_header_from_web_api(app_id)
                if api_url:
                    return api_url
            except Exception as e:
                logger.warning(f"Failed to fetch header URL for appid {app_id}: {e}")
            return None
        
        def on_fetch_complete(future):
            try:
                api_url = future.result()
                if api_url and not self._closing:
                    # Update database and re-fetch image (must be done on main thread)
                    QTimer.singleShot(0, lambda: self._apply_header_refresh(app_id, api_url))
            except Exception as e:
                logger.warning(f"Header refresh failed for appid {app_id}: {e}")
        
        # Submit to thread pool
        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(fetch_and_update)
        future.add_done_callback(on_fetch_complete)
        executor.shutdown(wait=False)
    
    def _apply_header_refresh(self, app_id, api_url):
        """Apply the refreshed header URL on the main thread."""
        if self._closing or not self.isVisible():
            return
            
        try:
            from managers.db_manager import DatabaseManager
            
            # Update the database with fresh URL
            db = DatabaseManager()
            db.upsert_app_info(app_id, {"header_url": api_url})
            logger.info(f"Refreshed database entry for appid {app_id}")
            
            # Re-fetch the image with the updated URL
            item = self._find_item_by_appid(app_id)
            if item and app_id not in self._active_fetchers:
                fetcher = ImageFetcher(api_url)
                fetcher.setProperty("app_id", app_id)
                fetcher.setProperty("is_retry", True)
                self._active_fetchers[app_id] = fetcher
                fetcher.finished.connect(self._on_retry_image_fetched)
                fetcher.finished.connect(lambda _, aid=app_id: self._cleanup_fetcher(aid))
                fetcher.start()
        except Exception as e:
            logger.warning(f"Failed to apply header refresh for appid {app_id}: {e}")

    def _on_retry_image_fetched(self, image_data):
        """
        Handle fetched image data from a retry attempt.
        This is separate from _on_item_image_fetched to prevent infinite retry loops.
        """
        if self._closing or not self.isVisible():
            return

        sender = self.sender()
        if sender is None:
            return

        app_id = sender.property("app_id")
        if app_id is None:
            return

        if image_data:
            self._image_cache[app_id] = image_data
            pixmap = QPixmap()
            pixmap.loadFromData(image_data)
            if not pixmap.isNull():
                item = self._find_item_by_appid(app_id)
                if item:
                    try:
                        resized_pixmap = pixmap.scaled(
                            230, 108,
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation,
                        )
                        item.setIcon(QIcon(resized_pixmap))
                        logger.info(f"Successfully set icon for game {app_id} after retry")
                    except Exception as e:
                        logger.warning(f"Error setting icon for game {app_id} on retry: {e}")
        else:
            logger.warning(f"Image retry also failed for game {app_id}")

    def _find_item_by_appid(self, app_id):
        """Find a QListWidgetItem by its app_id in the game data. Returns None if not found."""
        for i in range(self.games_list.count()):
            item = self.games_list.item(i)
            if item:
                game_data = item.data(Qt.ItemDataRole.UserRole)
                if game_data and game_data.get("appid") == app_id:
                    return item
        return None

    def _refresh_game_list(self):
        """Refresh the games list display"""
        # Don't refresh if dialog is closing
        if self._closing:
            return

        # Set refreshing flag to prevent dialogs from opening during refresh
        self._refreshing = True

        # Stop any active fetchers
        for app_id, fetcher in list(self._active_fetchers.items()):
            fetcher.stop()
        self._active_fetchers.clear()

        # Now clear the list safely
        self.games_list.clear()

        games = self.game_manager.get_all_games()

        # Sort games based on selected option
        games = self._sort_games(games)

        # Calculate total size
        total_size = 0

        logger.debug(f"Refreshing game list with {len(games)} games")

        for game in games:
            size_bytes = game.get("size_on_disk", 0)
            total_size += size_bytes

            # Format size for display
            size_str = self._format_size(size_bytes)

            # Create custom widget for game item
            game_widget = GameItemWidget(game, size_str, self.accent_color)

            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, game)
            item.setSizeHint(QSize(230, 108))
            self.games_list.addItem(item)
            self.games_list.setItemWidget(item, game_widget)

            # Fetch and set header image (check cache first)
            app_id = game.get("appid", "0")
            logger.debug(f"Game: {game.get('game_name', 'Unknown')}, AppID: {app_id}")
            if app_id and app_id != "0":
                # Check if we have cached image data
                if app_id in self._image_cache:
                    # Use cached image data
                    pixmap = QPixmap()
                    pixmap.loadFromData(self._image_cache[app_id])
                    if not pixmap.isNull():
                        resized_pixmap = pixmap.scaled(
                            230,
                            108,
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation,
                        )
                        item.setIcon(QIcon(resized_pixmap))
                        logger.debug(f"Using cached image for game {app_id}")
                    else:
                        # Cache is invalid, re-fetch
                        self._fetch_item_image(item, app_id)
                else:
                    # No cache, fetch the image
                    self._fetch_item_image(item, app_id)
            else:
                logger.debug("Skipping image fetch for game without valid AppID")

        count = len(games)
        total_size_str = self._format_size(total_size)
        self.info_label.setText(
            f"Found {count} game(s) installed by ACCELA - Total Size: {total_size_str}"
        )

        # Clear refreshing flag after refresh is complete
        self._refreshing = False

    def _on_item_selected(self):
        """Handle game selection with debouncing to prevent multiple dialogs"""
        # If a dialog is already open or list is refreshing, don't open another one
        if self._dialog_open or self._refreshing:
            return

        current_item = self.games_list.currentItem()
        if not current_item:
            return

        game_data = current_item.data(Qt.ItemDataRole.UserRole)
        if not game_data:
            return

        # Use QTimer.singleShot to debounce rapid selection changes
        # and prevent multiple dialogs from opening
        # Use weakref to safely handle case where dialog is destroyed before timer fires
        weak_self = weakref(self)

        def _safe_show_dialog():
            dialog = weak_self()
            if dialog and not dialog._closing:
                dialog._show_game_details_dialog(game_data)

        def _safe_reset_flag():
            dialog = weak_self()
            if dialog and not dialog._closing:
                dialog._set_dialog_open(False)

        QTimer.singleShot(100, _safe_show_dialog)
        self._dialog_open = True

        # Reset the flag after a short delay to allow the dialog to open
        QTimer.singleShot(500, _safe_reset_flag)

    def _set_dialog_open(self, state):
        """Set the dialog open state"""
        self._dialog_open = state

    def _is_goldberg_applied(self, game_dir: str) -> bool:
        """Return True if any .valve backup files exist in the game directory tree."""
        if not game_dir or game_dir == "N/A" or not os.path.exists(game_dir):
            return False
        for root, _, files in os.walk(game_dir):
            for fname in files:
                if fname.lower() in ("steam_api.dll.valve", "steam_api64.dll.valve"):
                    return True
        return False

    def _show_game_details_dialog(self, game_data):
        """Show game details in a custom dialog with tabbed interface"""
        dialog = QDialog(self)
        dialog.setWindowTitle("Game Details")
        dialog.setMinimumWidth(500)
        dialog.setModal(True)

        main_layout = QVBoxLayout(dialog)

        # Get background color from settings
        bg_color = self.settings.value("background_color", "#1E1E1E")

        # Create tab widget with styling
        tab_widget = QTabWidget()
        tab_widget.setStyleSheet(f"""
            QTabWidget::pane {{
                border: none;
            }}
            QTabBar::tab {{
                background: {bg_color};
                color: #888888;
                padding: 8px 16px;
                margin-right: 2px;
                border: none;
            }}
            QTabBar::tab:selected {{
                color: {self.accent_color};
                border-bottom: 2px solid {self.accent_color};
            }}
            QTabBar::tab:!selected {{
                color: #888888;
            }}
        """)

        appid = game_data.get("appid", "N/A")
        size_str = self._format_size(game_data.get("size_on_disk", 0))
        install_path = game_data.get("install_path", "N/A")
        library_path = game_data.get("library_path", "N/A")

        # ========== Tab 1: Overview ==========
        overview_tab = QWidget()
        overview_layout = QVBoxLayout(overview_tab)
        overview_layout.setContentsMargins(15, 15, 15, 15)

        # Game name
        name_label = QLabel(f"<h2>{game_data.get('game_name', 'Unknown')}</h2>")
        name_label.setTextFormat(Qt.TextFormat.RichText)
        overview_layout.addWidget(name_label)

        # Update status
        update_status = game_data.get("update_status", "checking")
        status_text = {
            "update_available": "New version available",
            "up_to_date": "Up to date",
            "checking": "Checking for updates...",
            "cannot_determine": "Unable to check updates",
        }.get(update_status, "Unknown")
        status_label = QLabel(status_text)
        status_label.setStyleSheet(f"color: {self.accent_color};")
        overview_layout.addWidget(status_label)

        overview_layout.addSpacing(15)

        # Game details
        details_layout = QFormLayout()
        details_layout.addRow("Steam App ID:", QLabel(appid))
        details_layout.addRow("Size:", QLabel(size_str))
        details_layout.addRow(
            "Library:",
            QLabel(os.path.basename(library_path) if library_path != "N/A" else "N/A"),
        )
        details_layout.addRow("Installation Path:", QLabel(install_path))
        overview_layout.addLayout(details_layout)

        overview_layout.addSpacing(15)

        # FakeAppId controls - only show if config management is enabled and on Linux
        self.fake_appid_checkbox = None
        self.fake_appid_input = None
        if platform.system() == "Linux" and is_slssteam_config_management_enabled():
            fake_appid_layout = QHBoxLayout()

            self.fake_appid_checkbox = QCheckBox("Add to SLSonline as:")
            self.fake_appid_checkbox.setToolTip(
                "Add this game to FakeAppIds in SLSsteam config.yaml to play online as another game"
            )
            fake_appid_layout.addWidget(self.fake_appid_checkbox)

            fake_appid_layout.addStretch()

            self.fake_appid_input = QLineEdit()
            self.fake_appid_input.setPlaceholderText("Spacewar (480)")
            self.fake_appid_input.setFixedWidth(200)
            self.fake_appid_input.setValidator(QIntValidator())
            self.fake_appid_input.setToolTip(
                "AppID to use for playing online (e.g. 480 for Spacewar). Leave empty for default."
            )
            fake_appid_layout.addWidget(self.fake_appid_input)

            overview_layout.addLayout(fake_appid_layout)

            # Check if AppID is valid
            appid_is_valid = appid and appid not in ("0", "N/A", "unknown", "480")

            if appid_is_valid:
                # Get fake_appid from textbox, default to "480" if empty
                fake_appid = self.fake_appid_input.text().strip()
                if not fake_appid:
                    fake_appid = "480"

                # Check if already in FakeAppIds
                config_path = get_user_config_path()
                if config_path.exists():
                    fake_app_ids = get_fake_app_ids(config_path, fake_appid)
                    self.fake_appid_checkbox.setChecked(appid in fake_app_ids)
                else:
                    self.fake_appid_checkbox.setChecked(False)

                # Connect signal
                self.fake_appid_checkbox.stateChanged.connect(
                    lambda state, gd=game_data, dlg=dialog: self._toggle_fake_appid(state, gd, dlg)
                )
            else:
                self.fake_appid_checkbox.setEnabled(False)
                self.fake_appid_input.setEnabled(False)
                if appid == "480":
                    self.fake_appid_checkbox.setToolTip(
                        "Spacewar (480) is the default game - no FakeAppId needed"
                    )
                else:
                    self.fake_appid_checkbox.setToolTip(
                        "Disabled: App ID is unknown or invalid"
                    )

        overview_layout.addSpacing(15)

        overview_layout.addStretch(1)

        # Validate/Update button - always visible
        update_btn = QPushButton()
        if update_status == "update_available":
            update_btn.setText("Download Update")
            update_btn.setToolTip(
                "A new version of this game is available. Click to download the update."
            )
        else:
            update_btn.setText("Validate Files")
            update_btn.setToolTip(
                "Verify game files and download any missing or corrupted ones."
            )

        update_btn.clicked.connect(lambda: self._fetch_game_manifest(game_data, dialog))
        overview_layout.addWidget(update_btn)

        overview_layout.addSpacing(15)

        # Open Folder and Close buttons (side-by-side)
        btn_row = QHBoxLayout()

        open_btn = QPushButton("Open Folder")
        def _open_folder():
            path = install_path
            if not path or path == "N/A" or not os.path.exists(path):
                QMessageBox.warning(
                    self,
                    "Open Folder",
                    f"Install path not found: {path}",
                )
                return
            try:
                path = os.path.normpath(os.path.abspath(str(path)))
                current_os = platform.system().lower()

                if current_os == "windows":
                    subprocess.run(["explorer", path], check=False)
                elif current_os == "darwin":  # macOS
                    subprocess.run(['open', path], check=False)
                else:  # Linux and other Unix-like
                    subprocess.run(['xdg-open', path], check=False)
                    
            except Exception as e:
                QMessageBox.warning(
                    self,
                    "Open Folder",
                    f"Failed to open folder: {e}",
                )
                

        open_btn.clicked.connect(_open_folder)

        # Make both buttons expand equally to fill the row
        open_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dialog.accept)
        close_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        btn_row.addWidget(open_btn)
        btn_row.addWidget(close_btn)

        overview_layout.addLayout(btn_row)

        tab_widget.addTab(overview_tab, "Overview")

        # ========== Tab 2: Uninstall ==========
        uninstall_tab = QWidget()
        uninstall_layout = QVBoxLayout(uninstall_tab)
        uninstall_layout.setContentsMargins(15, 15, 15, 15)

        # Linux cleanup options
        self.remove_compatdata_checkbox = None
        self.remove_saves_checkbox = None
        self.remove_from_library_checkbox = None
        self.remove_shortcuts_checkbox = None

        if platform.system() == "Linux":
            appid_is_valid = appid and appid not in ("0", "N/A", "unknown")

            linux_options_label = QLabel("Linux Options")
            linux_options_label.setStyleSheet(f"""
                font-weight: bold;
                color: {self.accent_color};
            """)
            uninstall_layout.addWidget(linux_options_label)

            self.remove_compatdata_checkbox = QCheckBox(
                "Remove Proton/Wine compatibility data"
            )
            if appid_is_valid:
                self.remove_compatdata_checkbox.setToolTip(
                    "Removes the Proton/Wine prefix which contains game configuration and may contain saves"
                )
            else:
                self.remove_compatdata_checkbox.setEnabled(False)
                self.remove_compatdata_checkbox.setToolTip(
                    "Disabled: App ID is unknown or invalid"
                )
            uninstall_layout.addWidget(self.remove_compatdata_checkbox)

            self.remove_saves_checkbox = QCheckBox("Remove Steam Cloud saves")
            if appid_is_valid:
                self.remove_saves_checkbox.setToolTip(
                    "Removes saved games stored in Steam's cloud sync folder"
                )
            else:
                self.remove_saves_checkbox.setEnabled(False)
                self.remove_saves_checkbox.setToolTip(
                    "Disabled: App ID is unknown or invalid"
                )
            uninstall_layout.addWidget(self.remove_saves_checkbox)

            self.remove_from_library_checkbox = QCheckBox("Remove from Steam library")
            if appid_is_valid:
                self.remove_from_library_checkbox.setToolTip(
                    "Removes this game from SLSstean's AdditionalApps list in config.yaml"
                )
            else:
                self.remove_from_library_checkbox.setEnabled(False)
                self.remove_from_library_checkbox.setToolTip(
                    "Disabled: App ID is unknown or invalid"
                )
            uninstall_layout.addWidget(self.remove_from_library_checkbox)

            self.remove_shortcuts_checkbox = QCheckBox("Remove desktop shortcuts")
            if appid_is_valid:
                self.remove_shortcuts_checkbox.setToolTip(
                    "Removes desktop shortcuts and icons created for this game"
                )
            else:
                self.remove_shortcuts_checkbox.setEnabled(False)
                self.remove_shortcuts_checkbox.setToolTip(
                    "Disabled: App ID is unknown or invalid"
                )
            uninstall_layout.addWidget(self.remove_shortcuts_checkbox)

            uninstall_layout.addSpacing(20)

        uninstall_desc = QLabel(
            "Remove this game from your system. This will delete all game files."
        )
        uninstall_desc.setWordWrap(True)
        uninstall_layout.addWidget(uninstall_desc)

        uninstall_layout.addSpacing(15)

        uninstall_layout.addStretch(1)

        # Button group
        uninstall_btn = QPushButton("Uninstall Game")
        uninstall_btn.clicked.connect(lambda: self._uninstall_game(game_data, dialog))
        uninstall_layout.addWidget(uninstall_btn)

        uninstall_layout.addSpacing(15)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dialog.accept)
        uninstall_layout.addWidget(close_btn)

        tab_widget.addTab(uninstall_tab, "Uninstall")

        # ========== Tab 3: Tools ==========
        tools_tab = QWidget()
        tools_layout = QVBoxLayout(tools_tab)
        tools_layout.setContentsMargins(15, 15, 15, 15)

        tools_desc = QLabel("Additional tools and utilities for this game.")
        tools_desc.setWordWrap(True)
        tools_layout.addWidget(tools_desc)

        tools_layout.addSpacing(15)

        # Steamless button
        steamless_btn = QPushButton("Remove DRM")
        steamless_btn.setToolTip(
            "Remove copy protection (DRM) from game executables"
        )
        steamless_btn.clicked.connect(
            lambda checked, dir=install_path, name=game_data.get("game_name", "Unknown"):
                self.main_window.task_manager.run_steamless_for_game(dir, name)
        )
        tools_layout.addWidget(steamless_btn)

        # Make Executable button (Linux only)
        if platform.system() == "Linux":
            chmod_btn = QPushButton("Make Executable")
            chmod_btn.setToolTip(
                "Make all executables and scripts in the game folder runnable"
            )
            chmod_btn.clicked.connect(
                lambda checked, dir=install_path, name=game_data.get("game_name", "Unknown"):
                    self.main_window.task_manager.run_chmod_for_game(dir, name, show_dialog=True)
            )
            tools_layout.addWidget(chmod_btn)

        sgdb_api_key = self.settings.value("sgdb_api_key", "", type=str)
        if sgdb_api_key and platform.system() == "Linux" and is_slssteam_mode_enabled():
            shortcuts_btn = QPushButton("Create Shortcuts")
            shortcuts_btn.setToolTip(
                "Create desktop shortcuts and icons from Steam Grid DB"
            )
            shortcuts_btn.clicked.connect(
                lambda: self._create_shortcuts(game_data, dialog)
            )
            tools_layout.addWidget(shortcuts_btn)

        # Fix Game Install button
        fix_install_btn = QPushButton("Fix Game Install")
        fix_install_btn.setToolTip(
            "Remove Steam installation file and reinstall to fix issues"
        )
        fix_install_btn.clicked.connect(
            lambda checked, data=game_data, dlg=dialog: self._fix_game_install(data, dlg)
        )
        tools_layout.addWidget(fix_install_btn)

        def _update_goldberg_button_state():
            applied_now = self._is_goldberg_applied(install_path)
            apply_goldberg_btn.setText(
                "Remove Goldberg" if applied_now else "Apply Goldberg"
            )
            apply_goldberg_btn.setToolTip(
                "Apply Goldberg files to the game folder to play it without using Steam client."
                if not applied_now
                else "Restore original files and remove Goldberg files from this game."
            )
            return applied_now

        apply_goldberg_btn = QPushButton()
        _update_goldberg_button_state()

        def _on_goldberg_clicked():
            game_name = game_data.get("game_name", "Unknown")
            applied_now = self._is_goldberg_applied(install_path)
            if applied_now:
                self.main_window.task_manager.remove_goldberg_from_game(
                    install_path, appid, game_name, show_dialog=True
                )
            else:
                self.main_window.task_manager.apply_goldberg_to_game(
                    install_path, appid, game_name, show_dialog=True
                )
            _update_goldberg_button_state()
            # Refresh the list to update labels and state
            self._refresh_game_list()

        apply_goldberg_btn.clicked.connect(_on_goldberg_clicked)
        tools_layout.addWidget(apply_goldberg_btn)

        tools_layout.addStretch(1)

        # Close button
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dialog.accept)
        tools_layout.addWidget(close_btn)

        tab_widget.addTab(tools_tab, "Tools")

        # Add tabs to dialog
        main_layout.addWidget(tab_widget)

        dialog.exec()

    def _fetch_game_manifest(self, game_data, dialog):
        """Fetch manifest from Morrenus API and add to job queue"""
        app_id = game_data.get("appid", "0")
        update_status = game_data.get("update_status", "cannot_determine")

        # Validate AppID
        if not app_id or app_id == "0":
            QMessageBox.warning(
                self,
                "Invalid App ID",
                f"Cannot download manifest: App ID is invalid or missing for '{game_data.get('game_name', 'Unknown')}'.",
            )
            return

        game_name = game_data.get("game_name", "Unknown")

        # Only use local ZIP if game is up_to_date
        use_local_zip = update_status == "up_to_date"

        # Check for local manifest if applicable
        local_zip_path = None
        if use_local_zip:
            manifests_dir = Path(get_base_path()) / "morrenus_manifests"
            local_zip_path = manifests_dir / f"accela_fetch_{app_id}.zip"
            if not local_zip_path.exists():
                local_zip_path = None

        # Determine if we need to show confirmation dialog
        need_api_download = local_zip_path is None

        if need_api_download:
            # Confirm fetch operation
            reply = QMessageBox.question(
                self,
                "Confirm Download",
                f"This will use your Morrenus API quota.\n\n"
                f"Download manifest for '{game_name}' (App ID: {app_id})?\n\n"
                f"The manifest will be downloaded and added to the queue.\n"
                f"Your existing installation will be verified and fixed.\n\n"
                f"Continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )

            if reply == QMessageBox.StandardButton.No:
                return

            # Show progress dialog for API download
            progress = QProgressDialog(
                f"Downloading manifest for {game_name}...", "Cancel", 0, 0, self
            )
            progress.setWindowTitle("Downloading")
            progress.setWindowModality(Qt.WindowModality.WindowModal)
            progress.setWindowFlags(
                progress.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
            )
            progress.show()

            try:
                # Call Morrenus API to download manifest
                filepath, error_msg = morrenus_api.download_manifest(app_id)

                if filepath:
                    # Success!
                    progress.close()

                    # Pass metadata for using existing install path
                    metadata = {
                        "appid": game_data.get("appid"),
                        "library_path": game_data.get("library_path"),
                        "install_path": game_data.get("install_path"),
                    }

                    # Add the manifest to the job queue
                    self.main_window.job_queue.add_job(filepath, metadata)

                    # Close dialogs silently
                    dialog.accept()
                    self.accept()  # Close the GameLibraryDialog
                else:
                    # Error
                    progress.close()
                    QMessageBox.critical(
                        self,
                        "Download Failed",
                        f"Failed to download manifest for '{game_name}' (App ID: {app_id}):\n\n{error_msg}",
                    )

            except Exception as e:
                # Exception occurred
                progress.close()
                logger.exception(f"Error fetching manifest for AppID {app_id}: {e}")
                QMessageBox.critical(
                    self, "Error", f"An error occurred while fetching manifest:\n\n{str(e)}"
                )
        else:
            # Use local ZIP directly without API call
            filepath = str(local_zip_path)

            # Pass metadata for using existing install path
            metadata = {
                "appid": game_data.get("appid"),
                "library_path": game_data.get("library_path"),
                "install_path": game_data.get("install_path"),
            }

            # Add the manifest to the job queue
            self.main_window.job_queue.add_job(filepath, metadata)

            # Close dialogs silently
            dialog.accept()
            self.accept()  # Close the GameLibraryDialog

    def _uninstall_game(self, game_data, dialog):
        """Uninstall the game by removing folder and ACF file"""
        # Check additional removal options (Linux only)
        remove_compatdata = False
        remove_saves = False
        remove_from_library = False
        remove_shortcuts = False

        if platform.system() == "Linux":
            remove_compatdata = (
                self.remove_compatdata_checkbox.isChecked()
                if self.remove_compatdata_checkbox
                else False
            )
            remove_saves = (
                self.remove_saves_checkbox.isChecked()
                if self.remove_saves_checkbox
                else False
            )
            remove_from_library = (
                self.remove_from_library_checkbox.isChecked()
                if self.remove_from_library_checkbox
                else False
            )
            remove_shortcuts = (
                self.remove_shortcuts_checkbox.isChecked()
                if self.remove_shortcuts_checkbox
                else False
            )

        # Get confirmation message from GameManager
        confirm_msg = self.game_manager.get_uninstall_confirmation_message(game_data)

        # Confirm uninstall
        reply = QMessageBox.question(
            self,
            "Confirm Uninstall",
            confirm_msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.No:
            return

        # Perform uninstall using GameManager
        success, error_msg = self.game_manager.uninstall_game(
            game_data, remove_compatdata=remove_compatdata, remove_saves=remove_saves, remove_from_library=remove_from_library, remove_shortcuts=remove_shortcuts
        )

        if success:
            game_name = game_data.get("game_name", "Unknown")
            QMessageBox.information(
                self,
                "Uninstall Complete",
                f"'{game_name}' has been successfully uninstalled.",
            )
            dialog.accept()
            # No need to explicitly refresh - the signal will handle it
        else:
            game_name = game_data.get("game_name", "Unknown")
            QMessageBox.critical(
                self,
                "Uninstall Failed",
                f"Failed to uninstall '{game_name}':\n\n{error_msg}",
            )

    def _create_shortcuts(self, game_data, dialog):
        """Create desktop shortcuts and icons for the game"""
        app_id = game_data.get("appid", "0")
        game_name = game_data.get("game_name", "Unknown")
        sgdb_api_key = self.settings.value("sgdb_api_key", "", type=str)

        # Validate AppID
        if not app_id or app_id == "0":
            QMessageBox.warning(
                self,
                "Invalid App ID",
                f"Cannot create shortcuts: App ID is invalid or missing for '{game_name}'.",
            )
            return

        # Confirm shortcuts creation
        reply = QMessageBox.question(
            self,
            "Confirm Shortcuts",
            f"Create desktop shortcuts and icons for '{game_name}' (App ID: {app_id})?\n\n"
            f"Requires a valid Steam Grid DB API key.\n\n"
            f"Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.No:
            return

        # Show progress dialog
        progress = QProgressDialog(
            f"Creating shortcuts for {game_name}...", "Cancel", 0, 0, self
        )
        progress.setWindowTitle("Shortcuts")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setWindowFlags(
            progress.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )
        progress.show()

        try:
            # Import and create the ApplicationShortcutsTask
            from core.tasks.application_shortcuts import ApplicationShortcutsTask
            from utils.task_runner import TaskRunner

            shortcuts_task = ApplicationShortcutsTask()
            shortcuts_task.set_api_key(sgdb_api_key)

            # Connect signals
            shortcuts_task.progress.connect(lambda msg: progress.setLabelText(msg))
            shortcuts_task.completed.connect(
                lambda success: self._on_shortcuts_complete(
                    success, game_name, progress, dialog
                )
            )
            shortcuts_task.error.connect(
                lambda error: self._on_shortcuts_error(error, game_name, progress)
            )

            # Run the task
            task_runner = TaskRunner()
            worker = task_runner.run(shortcuts_task.run, app_id, game_name)

            # Store references to prevent garbage collection
            self._current_shortcuts_task = shortcuts_task
            self._current_shortcuts_runner = task_runner

        except Exception as e:
            progress.close()
            logger.exception(f"Error creating shortcuts for AppID {app_id}: {e}")
            QMessageBox.critical(
                self,
                "Error",
                f"An error occurred:\n\n{str(e)}",
            )

    def _on_shortcuts_complete(self, success, game_name, progress, dialog):
        """Handle shortcuts creation completion"""
        progress.close()

        # Clean up references
        self._current_shortcuts_task = None
        self._current_shortcuts_runner = None

        if success:
            QMessageBox.information(
                self,
                "Shortcuts Created",
                f"Desktop shortcuts and icons for '{game_name}' have been successfully created.",
            )
        else:
            QMessageBox.warning(
                self,
                "Shortcuts Failed",
                f"Failed to create shortcuts for '{game_name}'. Check the logs for details.",
            )

    def _on_shortcuts_error(self, error, game_name, progress):
        """Handle shortcuts creation error"""
        progress.close()

        # Clean up references
        self._current_shortcuts_task = None
        self._current_shortcuts_runner = None

        QMessageBox.critical(
            self,
            "Shortcuts Error",
            f"Error creating shortcuts for '{game_name}':\n\n{error}",
        )

    def _fix_game_install(self, game_data, dialog):
        """Fix game installation by removing ACF file."""
        game_name = game_data.get("game_name", "Unknown")
        library_path = game_data.get("library_path")
        appid = game_data.get("appid", "0")
        library_index = game_data.get("library_index", 0)

        # Confirm with user
        reply = QMessageBox.question(
            self,
            "Fix Game Install",
            f"Remove Steam installation file (.acf) for '{game_name}'?\n\n"
            f"Steam will verify and download any missing files.\n\n"
            f"Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        # Remove ACF file
        if library_path and appid and appid not in ("0", "N/A", "unknown"):
            acf_path = os.path.join(library_path, "steamapps", f"appmanifest_{appid}.acf")
            if os.path.exists(acf_path):
                os.remove(acf_path)
                logger.info(f"Removed ACF file: {acf_path}")

                # On Linux, try to trigger reinstall via SLSsteam API
                if sys.platform == "linux":
                    command = f"install|{appid}|{library_index}"
                    slssteam_api_send(command)

                # Show success dialog
                QMessageBox.information(
                    self,
                    "Game Install Fixed",
                    f"The Steam installation file for '{game_name}' has been removed.\n\n"
                    f"Steam will verify and download any missing files."
                )
            else:
                QMessageBox.warning(
                    self,
                    "File Not Found",
                    f"Could not find installation file for '{game_name}'.\n\n"
                    f"The game may already be removed from Steam."
                )
        else:
            QMessageBox.warning(
                self,
                "Invalid Game Data",
                f"Cannot fix installation: App ID is invalid or missing for '{game_name}'."
            )

    def _toggle_fake_appid(self, state, game_data, dialog):
        """Toggle FakeAppId for this game to enable playing online as Spacewar"""
        if not self.fake_appid_input or not self.fake_appid_checkbox:
            return

        appid = game_data.get("appid", "")
        game_name = game_data.get("game_name", "Unknown")

        # Get fake_appid from textbox, default to "480" if empty
        fake_appid = self.fake_appid_input.text().strip()
        if not fake_appid:
            fake_appid = "480"

        # Validate AppID
        if not appid or appid in ("0", "N/A", "unknown", "480"):
            self.fake_appid_checkbox.setChecked(False)
            return

        config_path = get_user_config_path()

        if state == Qt.CheckState.Checked.value:
            # Add to FakeAppIds
            success = add_fake_app_id(config_path, appid, game_name, fake_appid)
            if not success:
                self.fake_appid_checkbox.setChecked(False)
        else:
            # Remove from FakeAppIds
            success = remove_fake_app_id(config_path, appid, fake_appid)
            if not success:
                self.fake_appid_checkbox.setChecked(True)

    def closeEvent(self, a0):
        """Ensure all image fetch threads are cleaned up when dialog closes"""
        # Set closing flag to prevent any callbacks from executing
        self._closing = True

        # Stop checking for update completion (dialog-local state only)
        self._checking_updates = False

        # Disconnect all signals to prevent accumulation on next open
        try:
            self.game_manager.scan_complete.disconnect(self._on_scan_complete)
            self.game_manager.library_updated.disconnect(self._refresh_game_list)
            self.game_manager.game_update_status_changed.disconnect(
                self._on_game_update_status_changed
            )
            self.games_list.itemSelectionChanged.disconnect(self._on_item_selected)
        except TypeError:
            # Signals may already be disconnected, ignore
            pass

        # Stop all active image fetchers
        for app_id, fetcher in list(self._active_fetchers.items()):
            try:
                fetcher.stop()
                fetcher.finished.disconnect(self._on_item_image_fetched)
            except (TypeError, RuntimeError):
                # Signal may not be connected or object deleted
                pass
        self._active_fetchers.clear()

        # Stop checking for update completion
        self._checking_updates = False

        # Clean up shortcuts task if running
        if hasattr(self, "_current_shortcuts_task") and self._current_shortcuts_task:
            try:
                self._current_shortcuts_task.stop()
            except Exception as e:
                logger.warning(f"Error stopping shortcuts task: {e}")
            self._current_shortcuts_task = None

        if (
            hasattr(self, "_current_shortcuts_runner")
            and self._current_shortcuts_runner
        ):
            try:
                self._current_shortcuts_runner.stop()
            except Exception as e:
                logger.warning(f"Error cleaning up shortcuts runner: {e}")
            self._current_shortcuts_runner = None

        # Clear image cache
        self._image_cache.clear()

        super().closeEvent(a0)
