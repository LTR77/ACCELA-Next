import logging

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from components.custom_widgets import ScaledFontLabel, ScaledLabel
from utils.logger import open_log_directory
from utils.settings import get_settings

logger = logging.getLogger(__name__)


class StatusDialog(QDialog):
    """Dialog showing the status of tools for the last installed game."""

    # Status colors
    STATUS_OK = "#00FF00"
    STATUS_IN_PROGRESS = "#FFA500"
    STATUS_ERROR = "#FF0000"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.setWindowTitle("Last Download Task Status")
        self.resize(450, 180)
        self.setMinimumSize(400, 150)

        # Get status from task_manager
        self._gather_status()

        self._setup_ui()

        logger.debug("StatusDialog initialized.")

    def _gather_status(self):
        """Gather status from task_manager"""
        # Get accent color for not_run state
        settings = get_settings()
        accent_color = settings.value("accent_color", "#C06C84")

        if self.parent and hasattr(self.parent, "task_manager"):
            task_manager = self.parent.task_manager
            status = task_manager.get_component_status()

            # Map status strings to colors
            status_map = {
                "ok": task_manager.STATUS_OK,
                "in_progress": task_manager.STATUS_IN_PROGRESS,
                "error": task_manager.STATUS_ERROR,
                "not_run": accent_color,
            }

            self.ddm_status = status_map.get(
                status["ddm_status"], task_manager.STATUS_OK
            )
            self.ddm_status_text = status["ddm_status_text"]
            self.slscheevo_status = status_map.get(
                status["slscheevo_status"], task_manager.STATUS_OK
            )
            self.slscheevo_status_text = status["slscheevo_status_text"]
            self.steamless_status = status_map.get(
                status["steamless_status"], task_manager.STATUS_OK
            )
            self.steamless_status_text = status["steamless_status_text"]

            # Get last installed game name
            self.last_game_name = (
                task_manager._last_installed_game or "No game installed"
            )
        else:
            # Fallback if no parent - all components are "not run"
            self.ddm_status = accent_color
            self.ddm_status_text = "Not run"
            self.slscheevo_status = accent_color
            self.slscheevo_status_text = "Not run"
            self.steamless_status = accent_color
            self.steamless_status_text = "Not run"
            self.last_game_name = "No game installed"

    def _setup_ui(self):
        """Setup the dialog UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(5)

        # Title
        title = ScaledFontLabel("Last Download Task Status")
        title.setStyleSheet("font-size: 14pt;")
        layout.addWidget(title)

        # Last installed game name
        game_label = ScaledLabel(self.last_game_name)
        game_label.setStyleSheet("font-size: 10pt")
        layout.addWidget(game_label)

        # Spacer
        layout.addSpacing(5)

        # Status group
        status_group = QGroupBox()
        status_group.setStyleSheet("QGroupBox { border: none; }")
        status_layout = QVBoxLayout()
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.setSpacing(3)

        # DDM status
        ddm_row = self._create_status_row(" Download Manager", self.ddm_status, self.ddm_status_text)
        status_layout.addLayout(ddm_row)

        # SLScheevo status
        slscheevo_row = self._create_status_row(
            " Achievements", self.slscheevo_status, self.slscheevo_status_text
        )
        status_layout.addLayout(slscheevo_row)

        # Steamless status
        steamless_row = self._create_status_row(
            " DRM Removal", self.steamless_status, self.steamless_status_text
        )
        status_layout.addLayout(steamless_row)

        status_group.setLayout(status_layout)
        layout.addWidget(status_group)

        # Spacer
        layout.addStretch()

        # Bottom buttons layout
        button_layout = QHBoxLayout()

        # Open logs button
        logs_button = QPushButton("Open Logs")
        logs_button.clicked.connect(self._open_logs)
        button_layout.addWidget(logs_button)

        button_layout.addStretch()

        # Dialog buttons
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        button_layout.addWidget(buttons)

        layout.addLayout(button_layout)

    def _open_logs(self):
        """Open the logs directory"""
        open_log_directory()

    def _create_status_row(self, name, color, status_text):
        """Create a status row with colored indicator and text"""
        row_layout = QHBoxLayout()

        # Colored circle indicator
        indicator = QLabel()
        indicator.setFixedSize(12, 12)
        indicator.setStyleSheet(f"""
            QLabel {{
                border-radius: 6px;
                background-color: {color};
            }}
        """)

        # Component name
        name_label = ScaledLabel(name)
        name_label.setMinimumWidth(150)

        # Status text
        status_label = ScaledLabel(status_text)

        row_layout.addWidget(indicator)
        row_layout.addWidget(name_label)
        row_layout.addWidget(status_label, alignment=Qt.AlignmentFlag.AlignRight)

        return row_layout
