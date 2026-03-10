import logging

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
)

from components.custom_widgets import ScaledFontLabel, ScaledLabel
from utils.settings import get_settings

logger = logging.getLogger(__name__)


class SteamlessResumeDialog(QDialog):
    """Dialog showing a brief summary of Steamless processing results."""

    def __init__(self, game_name, exe_count, processed_count, success, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Steamless Complete")
        self.setMinimumWidth(400)
        self.setMinimumHeight(300)
        self.setModal(True)

        self._setup_ui(game_name, exe_count, processed_count, success)

        logger.debug(
            f"SteamlessResumeDialog initialized: {game_name}, {exe_count} found, {processed_count} processed"
        )

    def _setup_ui(self, game_name, exe_count, processed_count, success):
        """Setup the dialog UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # Get colors from settings
        settings = get_settings()
        accent_color = settings.value("accent_color", "#C06C84")
        bg_color = settings.value("background_color", "#1E1E1E")

        # Title
        title = ScaledFontLabel("Steamless Processing Complete")
        title.setStyleSheet(f"font-size: 16pt; color: {accent_color};")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        # Game name
        game_label = ScaledLabel(f"Game: {game_name}")
        game_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(game_label)

        # Separator
        separator = QLabel()
        separator.setFixedHeight(1)
        separator.setStyleSheet(f"background-color: {accent_color};")
        layout.addWidget(separator)

        # Stats layout
        stats_layout = QVBoxLayout()
        stats_layout.setSpacing(10)

        # Executables found
        found_label = ScaledLabel(f"Found {exe_count} executable(s)")
        found_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        stats_layout.addWidget(found_label)

        # Processed count
        processed_label = ScaledLabel(f"Processed: {processed_count} executable(s)")
        processed_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        stats_layout.addWidget(processed_label)

        layout.addLayout(stats_layout)

        # Status message
        if success and processed_count > 0:
            status_text = "Completed Successfully"
            status_color = "#00FF00"
        elif processed_count > 0:
            status_text = "All DRM Removed"
            status_color = "#00FF00"  # Green - DRM that was found was removed
        elif exe_count > 0 and processed_count == 0:
            status_text = "No DRM Found"
            status_color = "#888888"  # Gray - informational, not an error
        else:
            status_text = "No Executables Processed"
            status_color = "#FF6B6B"

        status_label = ScaledFontLabel(status_text)
        status_label.setStyleSheet(f"color: {status_color}; font-size: 12pt;")
        status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(status_label)

        layout.addSpacing(10)

        # OK button
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        button_box.accepted.connect(self.accept)
        button_box.setCenterButtons(True)
        layout.addWidget(button_box)
