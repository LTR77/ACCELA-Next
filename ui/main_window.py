import atexit
import logging
import os
import sys
from pathlib import Path
from collections import deque
from PyQt6.QtCore import Qt, QUrl, QTimer
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QIcon, QShortcut, QKeySequence
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QStatusBar,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from components.custom_widgets import ScaledFontLabel, ScaledLabel
from managers.audio_manager import AudioManager
from managers.game_manager import GameManager
from managers.job_queue_manager import JobQueueManager
from managers.task_manager import TaskManager
from managers.ui_state_manager import UIStateManager
from managers.gif_manager import GIFManager
from ui.bottom_titlebar import BottomTitleBar
from ui.dialogs.fetchmanifest import FetchManifestDialog
from ui.dialogs.gamelibrary import GameLibraryDialog
from ui.dialogs.settings import SettingsDialog
from ui.dialogs.lain import LainMinigameDialog
from ui.dialogs.status import StatusDialog
from ui.dialogs.credits import CreditsDialog
from ui.dialogs.settings import SettingsDialog
from utils.logger import qt_log_handler
from utils.settings import get_settings
from utils.paths import Paths

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self._setup_window_properties()
        self._initialize_managers()
        self._setup_ui()
        self._setup_resize_handles()
        self.ui_state.apply_style_settings()
        self._setup_audio()
        self._setup_key_sequence_detector()
        self._setup_exit_shortcut()

    def _setup_window_properties(self):
        """Configure basic window properties"""
        self.setWindowTitle("ACCELA")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setGeometry(100, 100, 800, 600)

        # Set window icon
        icon_path = Paths.resource("logo/icon.ico")
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        else:
            logger.warning(f"Could not find window icon at: {str(icon_path)}")

        # Windows-specific taskbar setup
        if sys.platform == "win32":
            self._setup_windows_taskbar()

    def _setup_exit_shortcut(self):
        """Setup Ctrl+Q shortcut to exit the application"""
        self.exit_shortcut = QShortcut(QKeySequence("Ctrl+Q"), self)
        self.exit_shortcut.activated.connect(self.close)
        logger.info("Ctrl+Q exit shortcut registered")

    def _setup_key_sequence_detector(self):
        """Setup key sequence detection for L->A->I->N"""
        self.key_sequence = deque(maxlen=4)  # Stores last 4 keys
        self.sequence_timeout = QTimer(self)
        self.sequence_timeout.setSingleShot(True)
        self.sequence_timeout.timeout.connect(self.key_sequence.clear)

        # Target sequence (case-insensitive)
        self.target_sequence = ["l", "a", "i", "n"]

    def keyPressEvent(self, event):
        """Override keyPressEvent to detect key sequences"""
        # Get the key as a string
        key_text = event.text().lower()

        if key_text:  # Only process alphanumeric keys
            self.key_sequence.append(key_text)
            self.sequence_timeout.start(3000)  # Reset after 3 seconds of inactivity

            # Check if sequence matches
            if list(self.key_sequence) == self.target_sequence:
                self._on_lain_sequence_activated()
                self.key_sequence.clear()  # Reset after activation

        # Call parent to ensure normal key handling still works
        super().keyPressEvent(event)

    def _on_lain_sequence_activated(self):
        """Handle L->A->I->N sequence activation"""
        logger.info("LAIN sequence detected!")
        self.open_lain_minigame()

    def open_lain_minigame(self):
        """Open the Serial Experiments Lain minigame"""
        dialog = LainMinigameDialog(self)
        dialog.game_completed.connect(self.on_minigame_completed)
        dialog.exec()

    def on_minigame_completed(self, score):
        """Handle minigame completion"""
        logger.info(f"Lain minigame completed with score: {score}")

        # You could add score to user stats, unlock features, etc.
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("The Wired")
        msg_box.setText(f"Connection Terminated\n\nFinal Score: {score}")
        msg_box.exec()

    def _setup_windows_taskbar(self):
        """Windows-specific taskbar configuration"""
        try:
            import ctypes

            myappid = "god.is.in.the.wired.accela"
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
        except Exception as e:
            logger.warning(f"Could not set AppUserModelID: {e}")

    def _initialize_managers(self):
        """Initialize all manager classes"""
        self.settings = get_settings()

        # Initialize settings-dependent properties
        self.accent_color = self.settings.value("accent_color", "#C06C84")
        self.background_color = self.settings.value("background_color", "#000000")

        # Core managers
        self.task_manager = TaskManager(self)
        self.gif_manager = GIFManager(self)
        self.ui_state = UIStateManager(self)
        self.job_queue = JobQueueManager(self)
        self.audio_manager = AudioManager(self)
        self.game_manager = GameManager(self)

        logger.info("Starting initial game library scan...")
        self.game_manager.scan_steam_libraries_async()

    def _setup_ui(self):
        """Setup the main UI components"""
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.layout = QVBoxLayout(self.central_widget)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)

        # Get titlebar position setting
        self.titlebar_position = self.settings.value(
            "titlebar_position", "bottom", type=str
        )

        # Create titlebar first if positioned at top
        if self.titlebar_position == "top":
            self.bottom_titlebar = BottomTitleBar(self)
            self.layout.addWidget(self.bottom_titlebar)

        self._create_main_content()
        self._create_bottom_section()
        self.update_gif_display()

        # Add titlebar at bottom if not already added at top
        if self.titlebar_position != "top":
            self.bottom_titlebar = BottomTitleBar(self)
            self.layout.addWidget(self.bottom_titlebar)

        self.setAcceptDrops(True)

    def _setup_resize_handles(self):
        """Setup invisible resize handles for all edges and corners"""
        handle_width = 6

        class ResizeHandle(QWidget):
            def __init__(self, edge_name, main_window):
                super().__init__(main_window)
                self.edge_name = edge_name
                self.main_window = main_window

                self.resizing = False
                self.resize_start_pos = None
                self.resize_start_geom = None

            def mousePressEvent(self, event):
                if event.button() != Qt.MouseButton.LeftButton:
                    return

                edge_map = {
                    "left": Qt.Edge.LeftEdge,
                    "right": Qt.Edge.RightEdge,
                    "top": Qt.Edge.TopEdge,
                    "bottom": Qt.Edge.BottomEdge,
                    "top_left": Qt.Edge.LeftEdge | Qt.Edge.TopEdge,
                    "top_right": Qt.Edge.RightEdge | Qt.Edge.TopEdge,
                    "bottom_left": Qt.Edge.LeftEdge | Qt.Edge.BottomEdge,
                    "bottom_right": Qt.Edge.RightEdge | Qt.Edge.BottomEdge,
                }
                edge = edge_map.get(
                    self.edge_name, Qt.Edge.RightEdge | Qt.Edge.BottomEdge
                )
                window = self.main_window.windowHandle()

                # Wayland and Windows
                if window and window.isExposed() and window.startSystemResize(edge):
                    event.accept()
                    return

                # X11 fallback
                self.resizing = True
                self.resize_start_pos = event.globalPosition().toPoint()
                self.resize_start_geom = self.main_window.geometry()

                self.grabMouse()
                event.accept()

            def mouseMoveEvent(self, event):
                if not self.resizing:
                    return

                delta = event.globalPosition().toPoint() - self.resize_start_pos
                geom = self.resize_start_geom

                x, y, w, h = geom.x(), geom.y(), geom.width(), geom.height()

                if "right" in self.edge_name:
                    w += delta.x()
                if "bottom" in self.edge_name:
                    h += delta.y()
                if "left" in self.edge_name:
                    x += delta.x()
                    w -= delta.x()
                if "top" in self.edge_name:
                    y += delta.y()
                    h -= delta.y()

                w = max(w, self.main_window.minimumWidth())
                h = max(h, self.main_window.minimumHeight())

                self.main_window.setGeometry(x, y, w, h)

            def mouseReleaseEvent(self, event):
                if self.resizing:
                    self.releaseMouse()
                    self.resizing = False
                event.accept()

        self.resize_handles = {}

        # Corner handles first (they take priority)
        for name in ["top_left", "top_right", "bottom_left", "bottom_right"]:
            handle = ResizeHandle(name, self)
            handle.setCursor(self._get_cursor_for_edge(name))

            if name == "top_left":
                handle.setGeometry(0, 0, handle_width, handle_width)
            elif name == "top_right":
                handle.setGeometry(
                    self.width() - handle_width, 0, handle_width, handle_width
                )
            elif name == "bottom_left":
                handle.setGeometry(
                    0, self.height() - handle_width, handle_width, handle_width
                )
            elif name == "bottom_right":
                handle.setGeometry(
                    self.width() - handle_width,
                    self.height() - handle_width,
                    handle_width,
                    handle_width,
                )

            handle.setStyleSheet("background: transparent;")
            self.resize_handles[name] = handle

        # Edge handles (excluding corners)
        for name in ["left", "right", "top", "bottom"]:
            handle = ResizeHandle(name, self)
            handle.setCursor(self._get_cursor_for_edge(name))

            if name == "left":
                handle.setGeometry(
                    0, handle_width, handle_width, self.height() - 2 * handle_width
                )
            elif name == "right":
                handle.setGeometry(
                    self.width() - handle_width,
                    handle_width,
                    handle_width,
                    self.height() - 2 * handle_width,
                )
            elif name == "top":
                handle.setGeometry(
                    handle_width, 0, self.width() - 2 * handle_width, handle_width
                )
            elif name == "bottom":
                handle.setGeometry(
                    handle_width,
                    self.height() - handle_width,
                    self.width() - 2 * handle_width,
                    handle_width,
                )

            handle.setStyleSheet("background: transparent;")
            self.resize_handles[name] = handle

    def _get_cursor_for_edge(self, edge):
        """Get appropriate cursor for each resize edge"""
        cursors = {
            "left": Qt.CursorShape.SizeHorCursor,
            "right": Qt.CursorShape.SizeHorCursor,
            "top": Qt.CursorShape.SizeVerCursor,
            "bottom": Qt.CursorShape.SizeVerCursor,
            "top_left": Qt.CursorShape.SizeFDiagCursor,
            "top_right": Qt.CursorShape.SizeBDiagCursor,
            "bottom_left": Qt.CursorShape.SizeBDiagCursor,
            "bottom_right": Qt.CursorShape.SizeFDiagCursor,
        }
        return cursors.get(edge, Qt.CursorShape.ArrowCursor)

    def resizeEvent(self, event):
        """Update resize handle positions when window is resized"""
        super().resizeEvent(event)
        if hasattr(self, "resize_handles"):
            handle_width = 6
            if "left" in self.resize_handles:
                self.resize_handles["left"].setGeometry(
                    0, handle_width, handle_width, self.height() - 2 * handle_width
                )
            if "right" in self.resize_handles:
                self.resize_handles["right"].setGeometry(
                    self.width() - handle_width,
                    handle_width,
                    handle_width,
                    self.height() - 2 * handle_width,
                )
            if "top" in self.resize_handles:
                self.resize_handles["top"].setGeometry(
                    handle_width, 0, self.width() - 2 * handle_width, handle_width
                )
            if "bottom" in self.resize_handles:
                self.resize_handles["bottom"].setGeometry(
                    handle_width,
                    self.height() - handle_width,
                    self.width() - 2 * handle_width,
                    handle_width,
                )
            if "top_left" in self.resize_handles:
                self.resize_handles["top_left"].setGeometry(
                    0, 0, handle_width, handle_width
                )
            if "top_right" in self.resize_handles:
                self.resize_handles["top_right"].setGeometry(
                    self.width() - handle_width, 0, handle_width, handle_width
                )
            if "bottom_left" in self.resize_handles:
                self.resize_handles["bottom_left"].setGeometry(
                    0, self.height() - handle_width, handle_width, handle_width
                )
            if "bottom_right" in self.resize_handles:
                self.resize_handles["bottom_right"].setGeometry(
                    self.width() - handle_width,
                    self.height() - handle_width,
                    handle_width,
                    handle_width,
                )

    def _create_main_content(self):
        """Create the main content area with drop zone"""
        # Create a main container with a layout that will expand
        self.main_container = QWidget()
        self.main_container.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.layout.addWidget(self.main_container, 3)  # 3 parts of available space

        self.main_layout = QVBoxLayout(self.main_container)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        # Drop zone container - this will take most of the space
        self.drop_zone_container = QWidget()
        self.drop_zone_container.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.drop_zone_layout = QVBoxLayout(self.drop_zone_container)
        self.drop_zone_layout.setContentsMargins(0, 0, 0, 0)
        self.drop_zone_layout.setSpacing(0)

        # GIF display label
        self.drop_zone_gif = ScaledLabel()
        self.drop_zone_gif.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.drop_zone_gif.setMinimumHeight(150)
        self.drop_zone_gif.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # Instruction label
        self.drop_text_label = ScaledFontLabel("Drag and Drop Zip here")
        self.drop_text_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.drop_text_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.drop_text_label.setMinimumHeight(32)
        self.drop_text_label.setMaximumHeight(48)

        # Add to drop zone layout
        self.drop_zone_layout.addWidget(self.drop_zone_gif, 9)  # main.gif / downloading gifs SIZE
        self.drop_zone_layout.addWidget(self.drop_text_label, 1)  # text below GIF
        self.main_layout.addWidget(self.drop_zone_container, 10)

        # Progress indicators
        self.progress_container = QWidget()
        self.progress_layout = QVBoxLayout(self.progress_container)
        self.progress_layout.setContentsMargins(20, 5, 20, 5)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self._update_progress_bar_style()
        self.progress_layout.addWidget(self.progress_bar)

        self.speed_label = QLabel("")
        self.speed_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.speed_label.setVisible(False)
        self.progress_layout.addWidget(self.speed_label)

        self.main_layout.addWidget(
            self.progress_container, 1
        )  # Minimal space for progress

    def _create_bottom_section(self):
        """Create the bottom section with queue and logs"""
        self.bottom_widget = QWidget()
        self.bottom_layout = QHBoxLayout(self.bottom_widget)
        self.bottom_layout.setContentsMargins(5, 5, 5, 5)

        # Queue panel
        self.ui_state.setup_queue_panel()
        self.bottom_layout.addWidget(self.ui_state.queue_widget, 1)

        # Log output
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        qt_log_handler.new_record.connect(self.log_output.append)
        self.bottom_layout.addWidget(self.log_output, 1)

        self.layout.addWidget(self.bottom_widget, 1)
        self.ui_state.queue_widget.setVisible(False)

    def _setup_audio(self):
        """Setup audio effects"""
        # Audio is already set up in AudioManager.__init__(), just ensure settings are applied
        self.audio_manager.apply_audio_settings()

    def _apply_audio_settings(self):
        """Apply the current audio settings"""
        self.audio_manager.apply_audio_settings()

    def update_gif_display(self, enabled=None):
        """Update GIF display visibility and adjust window layout"""
        if enabled is None:
            enabled = self.settings.value("gif_display_enabled", True, type=bool)

        if enabled:
            if self.height() < 400:
                self.resize(self.width(), max(400, self.height()))
            self.main_layout.setStretchFactor(self.drop_zone_gif, 9)
            self.drop_zone_gif.setVisible(True)
            self.layout.setStretchFactor(self.main_container, 3)
            self.layout.setStretchFactor(self.bottom_widget, 1)
        else:
            current_height = self.height()
            gif_height = self.drop_zone_gif.height()
            new_height = max(200, current_height - gif_height)
            self.resize(self.width(), new_height)
            self.main_layout.setStretchFactor(self.drop_zone_gif, 0)
            self.drop_zone_gif.setVisible(False)
            self.layout.setStretchFactor(self.main_container, 1)
            self.layout.setStretchFactor(self.bottom_widget, 3)

        # Update UI
        self.update()
        logger.info(f"GIF display updated: {'enabled' if enabled else 'disabled'}")

    def _update_progress_bar_style(self):
        """Update progress bar styling"""
        self.progress_bar.setStyleSheet(f"""
            QProgressBar {{
                max-height: 10px;
                border: 1px solid {self.accent_color};
                border-radius: 5px;
                text-align: center;
                color: #FFFFFF;
            }}
            QProgressBar::chunk {{
                background-color: {self.accent_color};
                border-radius: 5px;
            }}
        """)

    # Public methods for dialogs
    def open_settings(self):
        dialog = SettingsDialog(self)
        dialog.exec()

    def open_fetch_dialog(self):
        self.ui_state.fetch_dialog = FetchManifestDialog(self)
        self.ui_state.fetch_dialog.exec()
        self.ui_state.fetch_dialog = None

    def open_game_library(self):
        """Open the Game Library dialog"""
        dialog = GameLibraryDialog(self)
        dialog.exec()

    def open_status_dialog(self):
        """Open the Status dialog showing DDM, SLScheevo, and Steamless status"""
        dialog = StatusDialog(self)
        dialog.exec()

    def open_credits_dialog(self):
        """Open the Credits dialog"""
        dialog = CreditsDialog(self)
        dialog.exec()

    # Event handlers
    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if all(
                url.isLocalFile() and url.toLocalFile().lower().endswith(".zip")
                for url in urls
            ):
                event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        urls = event.mimeData().urls()
        new_jobs = [
            url.toLocalFile()
            for url in urls
            if url.isLocalFile() and url.toLocalFile().lower().endswith(".zip")
        ]

        if new_jobs:
            logger.info(f"Added {len(new_jobs)} file(s) to the queue via drag-drop.")
            for job_path in new_jobs:
                self.job_queue.add_job(job_path)

    def closeEvent(self, event):
        """Handle application shutdown"""
        try:
            self._cleanup_logging()
            self.task_manager.cleanup()
            self.job_queue.clear()
            self.game_manager.cleanup()
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")

        super().closeEvent(event)

    def reposition_titlebar(self, position):
        """Dynamically reposition the titlebar without restart"""
        if not hasattr(self, "bottom_titlebar") or not self.bottom_titlebar:
            return

        # Remove titlebar from current position
        self.layout.removeWidget(self.bottom_titlebar)
        self.bottom_titlebar.setParent(None)

        # Add titlebar to new position
        if position == "top":
            self.layout.insertWidget(0, self.bottom_titlebar)
        else:  # bottom
            self.layout.addWidget(self.bottom_titlebar)

        # Update the stored position
        self.titlebar_position = position
        logger.info(f"Titlebar repositioned to: {position}")

    def _cleanup_logging(self):
        """Clean up logging system"""
        try:
            atexit.unregister(logging.shutdown)
            logging.getLogger().removeHandler(qt_log_handler)
            qt_log_handler.close()
            logger.info("QtLogHandler removed and atexit hook unregistered.")
            logging.shutdown()
        except Exception as e:
            print(f"Error during custom logger shutdown: {e}")
