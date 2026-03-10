import logging
import os
import platform
import re
import sys
import urllib.request
from pathlib import Path

from PyQt6.QtCore import QObject, Qt, QThread, pyqtSignal
from PyQt6.QtGui import QCursor, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from utils.image_fetcher import ImageFetcher

logger = logging.getLogger(__name__)

class DepotSelectionDialog(QDialog):
    def __init__(self, app_id, game_name, depots, header_url, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select Depots to Download")
        self.depots = depots
        self.game_name = game_name
        self.header_url = header_url
        self.resize(485, 520)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 10)
        layout.setSpacing(10)

        self.anchor_row = -1

        self.header_label = QLabel("Loading header image...")
        self.header_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.header_label.setFixedHeight(108)
        layout.addWidget(self.header_label)
        self._fetch_header_image(app_id)

        content_widget = QVBoxLayout()
        content_widget.setContentsMargins(10, 0, 10, 0)

        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)

        def get_sort_key(depot_item):
            _depot_id, depot_data = depot_item

            os_val = depot_data.get("oslist")
            if os_val is None:
                os_str = "zzzz"
            else:
                os_str = os_val.lower()

            os_priority = 4

            if os_str == "windows":
                os_priority = 1
            elif os_str == "linux":
                os_priority = 2
            elif "all" in os_str:
                os_priority = 3
            elif os_str == "macosx" or os_str == "macos":
                os_priority = 5

            desc_str = depot_data.get("desc", "").lower()
            lang_val = depot_data.get("language")

            lang_priority = 3
            lang_sort_key = lang_val.lower() if lang_val else "zzzz"

            is_no_language = (
                lang_val is None
                and "english" not in desc_str
                and "japanese" not in desc_str
            )

            if "english" in desc_str:
                lang_priority = 1
                lang_sort_key = lang_val.lower() if lang_val else "english"
            elif is_no_language:
                lang_priority = 1
                lang_sort_key = "english"
            elif "japanese" in desc_str:
                lang_priority = 2
                lang_sort_key = "japanese"

            final_key = (os_priority, lang_priority, lang_sort_key)
            logger.debug(
                f"Depot {_depot_id}: OS='{os_val}', Lang='{lang_val}', Desc='{depot_data.get('desc', '')}'"
            )
            logger.debug(
                f"    -> Key: {final_key} (OS_Prio: {os_priority}, Lang_Prio: {lang_priority}, Lang_Key: '{lang_sort_key}')"
            )

            return final_key

        logger.debug("--- Starting Depot Sort ---")
        sorted_depots = sorted(self.depots.items(), key=get_sort_key)
        logger.debug("--- Depot Sort Finished ---")

        is_first_depot = True

        for depot_id, depot_data in sorted_depots:
            original_desc = depot_data["desc"]

            original_desc = re.sub(
                r"\s*-\s*Depot\s*" + re.escape(depot_id),
                "",
                original_desc,
                flags=re.IGNORECASE,
            )

            tags = ""
            base_desc = original_desc.strip()
            tags_match = re.match(r"^((?:\[.*?\]\s*)*)(.*)", original_desc)
            if tags_match:
                tags = tags_match.group(1).strip()
                base_desc = tags_match.group(2).strip()

            is_generic_fallback = bool(
                re.fullmatch(r"Depot \d+", base_desc, re.IGNORECASE)
            )

            if is_first_depot:
                if is_generic_fallback:
                    final_desc = f"{tags} {self.game_name}".strip()
                else:
                    final_desc = original_desc

                is_first_depot = False
            else:
                if is_generic_fallback:
                    final_desc = tags
                else:
                    final_desc = original_desc

            if depot_data.get("size"):
                try:
                    size_gb = int(depot_data["size"]) / (1024**3)
                    final_desc += f" <{size_gb:.2f} GB>"
                except (ValueError, TypeError):
                    pass

            item_text = f"{depot_id} - {final_desc}"

            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, depot_id)
            item.setCheckState(Qt.CheckState.Unchecked)

            # Removes ItemIsUserCheckable flag to disable internal checkbox handling, handled manually in self.on_depot_item_clicked
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
            self.list_widget.addItem(item)

        # Makes list widget update stylesheets for the items
        QApplication.processEvents()

        content_widget.addWidget(self.list_widget)

        self.list_widget.itemClicked.connect(self.on_depot_item_clicked)

        button_layout = QHBoxLayout()
        select_all_button = QPushButton("Select All")
        select_all_button.clicked.connect(
            lambda: self._toggle_all_checkboxes(check=True)
        )
        button_layout.addWidget(select_all_button)

        deselect_all_button = QPushButton("Deselect All")
        deselect_all_button.clicked.connect(
            lambda: self._toggle_all_checkboxes(check=False)
        )
        button_layout.addWidget(deselect_all_button)
        content_widget.addLayout(button_layout)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        content_widget.addWidget(buttons)
        
        layout.addLayout(content_widget)

    def on_depot_item_clicked(self, item):
        modifiers = QApplication.keyboardModifiers()
        current_row = self.list_widget.row(item)

        current_state = item.checkState()
        new_state = (
            Qt.CheckState.Unchecked
            if current_state == Qt.CheckState.Checked
            else Qt.CheckState.Checked
        )

        if modifiers == Qt.KeyboardModifier.ShiftModifier:
            if self.anchor_row == -1:
                item.setCheckState(new_state)
                self.anchor_row = current_row
            else:
                try:
                    anchor_item = self.list_widget.item(self.anchor_row)
                    if anchor_item is None:
                        raise RuntimeError("Anchor item is None")
                    target_state = anchor_item.checkState()
                except Exception as e:
                    logger.warning(f"Could not find anchor item for shift-click: {e}")
                    target_state = new_state

                start_row = min(self.anchor_row, current_row)
                end_row = max(self.anchor_row, current_row)

                self.list_widget.blockSignals(True)
                for i in range(start_row, end_row + 1):
                    row_item = self.list_widget.item(i)
                    if row_item is not None:
                        row_item.setCheckState(target_state)
                self.list_widget.blockSignals(False)

        else:
            item.setCheckState(new_state)
            self.anchor_row = current_row

    def _toggle_all_checkboxes(self, check=True):
        state = Qt.CheckState.Checked if check else Qt.CheckState.Unchecked
        self.list_widget.blockSignals(True)
        for i in range(self.list_widget.count()):
            row_item = self.list_widget.item(i)
            if row_item is not None:
                row_item.setCheckState(state)
        self.list_widget.blockSignals(False)

        self.anchor_row = -1

    def _fetch_header_image(self, app_id):
        self._current_app_id = app_id
        url = ImageFetcher.get_header_image_url(app_id)

        self.worker_thread = QThread(self)
        self.fetcher = ImageFetcher(url)
        self.fetcher.moveToThread(self.worker_thread)

        self.worker_thread.started.connect(self.fetcher.run)
        self.fetcher.finished.connect(self.on_image_fetched)

        self.fetcher.finished.connect(self.worker_thread.quit)
        self.fetcher.finished.connect(self.fetcher.deleteLater)
        self.worker_thread.finished.connect(self.worker_thread.deleteLater)

        self.worker_thread.start()

    def on_image_fetched(self, image_data):
        if image_data:
            pixmap = QPixmap()
            pixmap.loadFromData(image_data)
            # Scale to full dialog width (485px), height auto (Steam header is ~2.14:1 ratio = ~227px height)
            scaled = pixmap.scaledToWidth(self.width(), Qt.TransformationMode.SmoothTransformation)
            self.header_label.setPixmap(scaled)
            self.header_label.setFixedHeight(scaled.height())
            self.header_label.setStyleSheet("")  # Remove loading background
        else:
            # Image fetch failed (404), try to get the correct URL from Steam API
            logger.debug(f"Image fetch failed, attempting to refresh from API")
            self._trigger_header_refresh()
    
    def _trigger_header_refresh(self):
        """
        Fetch the correct header URL from Steam API when generic URL fails.
        """
        app_id = getattr(self, '_current_app_id', None)
        if not app_id:
            self._show_no_image()
            return
        
        logger.debug(f"Fetching header URL from Steam API for appid {app_id}")
        
        try:
            # Fetch the correct URL from Steam API (synchronous but fast)
            api_url = ImageFetcher._fetch_header_from_web_api(app_id)
            
            if api_url:
                logger.info(f"Got header URL from API for appid {app_id}: {api_url}")
                
                # Update database with fresh URL
                try:
                    from managers.db_manager import DatabaseManager
                    db = DatabaseManager()
                    db.upsert_app_info(app_id, {"header_url": api_url})
                except Exception as e:
                    logger.debug(f"Could not update DB: {e}")
                
                # Re-fetch the image with the correct URL
                self.retry_thread = QThread(self)
                self.retry_fetcher = ImageFetcher(api_url)
                self.retry_fetcher.moveToThread(self.retry_thread)
                
                self.retry_thread.started.connect(self.retry_fetcher.run)
                self.retry_fetcher.finished.connect(self._on_retry_image_fetched)
                self.retry_fetcher.finished.connect(self.retry_thread.quit)
                self.retry_fetcher.finished.connect(self.retry_fetcher.deleteLater)
                self.retry_thread.finished.connect(self.retry_thread.deleteLater)
                
                self.retry_thread.start()
            else:
                logger.debug(f"No header URL found in API for appid {app_id}")
                self._show_no_image()
        except Exception as e:
            logger.warning(f"Failed to refresh header for appid {app_id}: {e}")
            self._show_no_image()
    
    def _on_retry_image_fetched(self, image_data):
        """Handle the retry image fetch result."""
        if image_data:
            pixmap = QPixmap()
            pixmap.loadFromData(image_data)
            scaled = pixmap.scaledToWidth(self.width(), Qt.TransformationMode.SmoothTransformation)
            self.header_label.setPixmap(scaled)
            self.header_label.setFixedHeight(scaled.height())
            self.header_label.setStyleSheet("")
            logger.info(f"Successfully loaded header image after refresh")
        else:
            self._show_no_image()
    
    def _show_no_image(self):
        """Show fallback text when image is not available."""
        self.header_label.setText("Header image not available.")
        self.header_label.setStyleSheet("")

    def get_selected_depots(self):
        selected = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item is None:
                continue
            if item.checkState() == Qt.CheckState.Checked:
                selected.append(item.data(Qt.ItemDataRole.UserRole))
        return selected

    def closeEvent(self, a0):
        """Ensure image fetch thread is cleaned up when dialog closes"""
        if hasattr(self, "worker_thread") and self.worker_thread is not None:
            try:
                # Check if thread is still valid and running
                if not self.worker_thread.isFinished():
                    self.worker_thread.quit()
                    self.worker_thread.wait()
            except RuntimeError:
                # Thread has already been deleted by Qt
                pass
        super().closeEvent(a0)

