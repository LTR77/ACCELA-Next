import logging

from PyQt6.QtWidgets import (
    QDialog,
    QPushButton,
    QVBoxLayout,
    QGroupBox,
    QLabel,
    QWidget,
)
from PyQt6.QtCore import Qt

from utils.settings import get_settings

logger = logging.getLogger(__name__)


class CreditsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Credits")
        self.setMinimumWidth(400)
        self.setMinimumHeight(250)
        self.resize(400, 342)  # Set exact size as requested
        self.settings = get_settings()
        self.main_layout = QVBoxLayout(self)
        self.main_window = parent
        self.accent_color = self.settings.value("accent_color", "#C06C84")

        logger.debug("Opening CreditsDialog.")

        # Apply styling (match settings dialog)
        self.setStyleSheet(f"""
            QGroupBox {{
                color: {self.accent_color};
            }}
        """)

        # Create credits content
        self._create_credits_content()

        # Dialog buttons
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.reject)
        self.main_layout.addWidget(close_button)

    def _create_credits_content(self):
        """Create the credits content"""
        credits_widget = QWidget()
        credits_layout = QVBoxLayout(credits_widget)
        credits_layout.setContentsMargins(15, 15, 15, 15)

        # --- Credits Information ---
        credits_group = QGroupBox("Credits")
        credits_info_layout = QVBoxLayout()

        # Developer information
        dev_label = QLabel("Developed by: Lain Iwakura")
        dev_label.setStyleSheet(
            f"font-size: 14px; font-weight: bold; color: {self.accent_color};"
        )
        credits_info_layout.addWidget(dev_label)

        # Address information
        address_label = QLabel("Address: Mimorigasaka, Setagaya Ward, Tokyo")
        address_label.setStyleSheet("font-size: 12px; margin-top: 10px;")
        credits_info_layout.addWidget(address_label)

        # Phone information
        phone_label = QLabel("Phone: 858-924-0180")
        phone_label.setStyleSheet("font-size: 12px; margin-top: 5px;")
        credits_info_layout.addWidget(phone_label)

        credits_group.setLayout(credits_info_layout)
        credits_layout.addWidget(credits_group)

        # --- Special Thanks ---
        special_thanks_group = QGroupBox("Special Thanks")
        special_thanks_layout = QVBoxLayout()

        tools_label = QLabel(
            "• GreenLuma\n• SLSsteam\n• Steamless\n• DepotDownloaderMod\n• SLScheevo"
        )
        tools_label.setStyleSheet("font-size: 11px; color: #CCCCCC; margin-left: 15px;")
        special_thanks_layout.addWidget(tools_label)

        special_thanks_group.setLayout(special_thanks_layout)
        credits_layout.addWidget(special_thanks_group)

        self.main_layout.addWidget(credits_widget)
