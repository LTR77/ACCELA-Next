import os
import random
import logging
from pathlib import Path
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QMovie, QFont
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QHBoxLayout,
    QApplication,
    QFrame,
)

from utils.helpers import get_base_path
from utils.paths import Paths

logger = logging.getLogger(__name__)


class UIStateManager:
    def __init__(self, main_window):
        self.main_window = main_window
        self.settings = main_window.settings

        # UI state
        self.fetch_dialog = None
        self.depot_dialog = None
        self.current_movie = None
        self.random_gif_path = None
        self.download_movie = None
        self.main_movie = None

        # Queue UI elements
        self.queue_widget = None
        self.queue_list_widget = None
        self.queue_move_up_button = None
        self.queue_move_down_button = None
        self.queue_remove_button = None
        self.pause_button = None
        self.cancel_button = None

        self.disable_default_gifs = self.settings.value("disable_default_gifs", False)

        self._initialize_gifs()
        # Gifs are set up later in apply_style_settings()

    def _initialize_gifs(self):
        """Initialize GIF resources"""
        colored_dir = get_base_path() / "gifs/colorized"
        os.makedirs(str(colored_dir), exist_ok=True)

        self.remove_old_downloading_gifs()

        # Custom downloading GIFs (excluding defaults)
        custom_patterns = ["downloading_custom*.gif"]
        self.download_gifs = []
        for pattern in custom_patterns:
            for p in colored_dir.glob(pattern):
                # Exclude default GIFs
                if "downloading_lain" not in p.name:
                    self.download_gifs.append(str(p))

        # Default downloading GIFs
        self.default_download_gifs = []
        default_dir = get_base_path() / "gifs/colorized"
        for p in default_dir.glob("downloading_lain*.gif"):
            self.default_download_gifs.append(str(p))

        # Sort both lists
        self.download_gifs.sort()
        self.default_download_gifs.sort()

        logger.debug(f"Found {len(self.download_gifs)} custom GIFs")
        logger.debug(f"Found {len(self.default_download_gifs)} default GIFs")

    def remove_old_downloading_gifs(self):
        """Remove old downloading*.gif files and rename custom ones to sequential names"""
        total_removed = 0
        total_renamed = 0

        gifs_base = get_base_path() / "gifs"

        if not gifs_base.exists():
            logger.warning(f"Directory does not exist: {gifs_base}")
            return {"removed": 0, "renamed": 0}

        # Remove old downloading*.gif files
        colorized_dir = gifs_base / "colorized"

        if colorized_dir.exists() and colorized_dir.is_dir():
            removed_count = 0
            for file_path in colorized_dir.rglob("downloading*.gif"):
                # EXCLUDE downloading_lain*.gif and downloading_custom*.gif
                filename_lower = file_path.name.lower()
                if "downloading_lain" in filename_lower or "downloading_custom" in filename_lower:
                    continue

                try:
                    file_path.unlink()
                    removed_count += 1
                    logger.info(f"Removed from colorized: {file_path}")
                except Exception as e:
                    logger.error(f"Failed to remove {file_path}: {e}")

            total_removed += removed_count
            if removed_count > 0:
                logger.info(f"Removed {removed_count} downloading*.gif files from colorized")
        else:
            logger.warning(f"Colorized directory does not exist: {colorized_dir}")

        # Rename old downloading*.gif files
        custom_dir = gifs_base / "custom"

        if custom_dir.exists() and custom_dir.is_dir():
            # Find all generic downloading*.gif files (exclude _custom and _lain)
            files_to_rename = []
            for file_path in custom_dir.rglob("downloading*.gif"):
                filename_lower = file_path.name.lower()
                if ("_custom" not in filename_lower and "_lain" not in filename_lower):
                    files_to_rename.append(file_path)

            if files_to_rename:
                # Sort the files (case-insensitive)
                files_to_rename.sort(key=lambda x: x.name.lower())

                # Find existing downloading_custom*.gif files to determine used indices
                used_indices = set()
                for file_path in custom_dir.rglob("downloading_custom*.gif"):
                    try:
                        # Extract number from filename: downloading_custom{number}.gif
                        stem = file_path.stem
                        if stem.lower().startswith("downloading_custom"):
                            num_str = stem[18:]  # Remove "downloading_custom"
                            if num_str and num_str.isdigit():
                                used_indices.add(int(num_str))
                    except (ValueError, AttributeError, IndexError):
                        pass

                # Rename files in sequence
                renamed_count = 0
                for file_path in files_to_rename:
                    try:
                        # Find next available index
                        index = 1
                        while index in used_indices:
                            index += 1

                        new_name = f"downloading_custom{index}.gif"
                        new_path = file_path.parent / new_name

                        # Rename the file
                        file_path.rename(new_path)
                        renamed_count += 1
                        used_indices.add(index)  # Mark this index as used
                        logger.info(f"Renamed: {file_path.name} -> {new_name}")

                    except Exception as e:
                        logger.error(f"Failed to rename {file_path}: {e}")

                total_renamed = renamed_count
                if renamed_count > 0:
                    logger.info(f"Renamed {renamed_count} downloading*.gif files to sequential names")
            else:
                logger.info("No files to rename in custom directory")
        else:
            logger.warning(f"Custom directory does not exist: {custom_dir}")

        logger.info(f"Total: {total_removed} files removed, {total_renamed} files renamed")
        return {"removed": total_removed, "renamed": total_renamed}

    def _update_gifs(self):
        """Update GIFs with current accent color"""
        output_dir = get_base_path() / "gifs" / "colorized"
        self.main_window.gif_manager.process_gif_batch(output_dir, self.main_window.accent_color)
        self._reload_movies()

    def _reload_movies(self):
        """Reload movie objects with current GIFs"""
        if not hasattr(self.main_window, "drop_zone_gif"):
            return
        main_gif_path = get_base_path() / "gifs/colorized/main.gif"
        default_gif_path = Paths.resource("gif/main.gif")

        ui_mode = self.settings.value("ui_mode", "default")
        sonic_main_applied = False
        if ui_mode == "sonic":
            sonic_gif = Paths.resource("sonic/gifs/main.gif")
            default_gif_path = sonic_gif
            sonic_main_applied = True

        if hasattr(self.main_movie, "main_movie"):
            if self.main_movie:
                self.main_movie.stop()

        self.main_movie = QMovie(str(default_gif_path))
        self.main_movie.start()
        self.main_window.drop_zone_gif.setMovie(self.main_movie)
        self.current_movie = self.main_movie

        if main_gif_path.exists() and not sonic_main_applied:
            self.main_movie.stop()
            self.main_movie = QMovie(str(main_gif_path))
            self.main_window.drop_zone_gif.setMovie(self.main_movie)
            self.main_movie.start()
            self.current_movie = self.main_movie

        if self.main_window.task_manager.current_job or self.main_window.task_manager.current_job:
            self.switch_to_download_gif()

    def setup_queue_panel(self):
        """Setup the download queue panel"""
        self.queue_widget = QWidget()
        queue_layout = QVBoxLayout(self.queue_widget)
        queue_layout.setContentsMargins(0, 0, 5, 0)

        # Queue label
        queue_label = QLabel("Download Queue")
        queue_label.setStyleSheet(f"color: {self.main_window.accent_color};")
        queue_layout.addWidget(queue_label)

        # Queue list
        self.queue_list_widget = QListWidget()
        self.queue_list_widget.setToolTip(
            "Current download queue. Select an item to move it."
        )
        queue_layout.addWidget(self.queue_list_widget)

        # Queue buttons
        self._setup_queue_buttons(queue_layout)

    def _setup_queue_buttons(self, parent_layout):
        """Setup queue control buttons"""
        queue_button_layout = QHBoxLayout()

        self.queue_move_up_button = QPushButton("Move Up")
        self.queue_move_up_button.clicked.connect(
            self.main_window.job_queue.move_item_up
        )
        queue_button_layout.addWidget(self.queue_move_up_button)

        self.queue_move_down_button = QPushButton("Move Down")
        self.queue_move_down_button.clicked.connect(
            self.main_window.job_queue.move_item_down
        )
        queue_button_layout.addWidget(self.queue_move_down_button)

        self.queue_remove_button = QPushButton("Remove")
        self.queue_remove_button.clicked.connect(self.main_window.job_queue.remove_item)
        queue_button_layout.addWidget(self.queue_remove_button)

        self.pause_button = QPushButton("Pause")
        self.pause_button.clicked.connect(self.main_window.task_manager.toggle_pause)
        self.pause_button.setVisible(False)
        queue_button_layout.addWidget(self.pause_button)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(
            self.main_window.task_manager.cancel_current_job
        )
        self.cancel_button.setVisible(False)
        queue_button_layout.addWidget(self.cancel_button)

        parent_layout.addLayout(queue_button_layout)

    def apply_style_settings(self):
        """Apply current style settings to UI"""
        self.main_window.background_color = self.settings.value(
            "background_color", "#000000"
        )
        self.main_window.accent_color = self.settings.value("accent_color", "#C06C84")

        # Load font family
        font_family = self.settings.value("font", "TrixieCyrG-Plain")

        # Load size (default 10). If Sonic mode and user left default 10, bump to 12
        font_size = self.settings.value("font-size", 10, type=int)

        # Create font
        font = QFont(font_family)
        font.setPointSize(font_size)

        # Set font style
        font_style = self.settings.value("font-style", "Normal")
        if font_style == "Italic":
            font.setItalic(True)
        elif font_style == "Bold":
            font.setBold(True)
        elif font_style == "Bold Italic":
            font.setBold(True)
            font.setItalic(True)
        # "Normal" is the default, so no changes needed

        self.main_window.font = font

        # Update application appearance
        from main import update_appearance

        # UI mode (e.g., 'sonic') may override colors and font file
        ui_mode = self.settings.value("ui_mode", "default")

        font_file = None
        if ui_mode == "sonic":
            # Sonic mode: use specific palette (blue background, yellow accent)
            self.main_window.accent_color = "#ffcc00"
            self.main_window.background_color = "#002c83"
            font_file = self.settings.value("font-file", "sonic/sonic-1-hud-font.otf")

        font_ok, font_info = update_appearance(
            QApplication.instance(),
            self.main_window.accent_color,
            self.main_window.background_color,
            self.main_window.font,
            font_file=font_file,
        )

        if ui_mode == "sonic" and font_ok:
            # Sync main window font family to loaded Sonic font
            sonic_font = QFont(font_info)
            sonic_font.setPointSize(font_size)
            self.main_window.font = sonic_font

        # Apply styles to various UI elements
        self._apply_background_color()
        self._apply_accent_color()
        self._update_gifs()

    def _apply_background_color(self):
        """Apply background color to main content"""
        main_frame = self.main_window.central_widget.findChild(QFrame)
        if main_frame:
            main_frame.setStyleSheet(
                f"background-color: {self.main_window.background_color};"
            )

    def _apply_accent_color(self):
        """Apply accent color to UI elements"""
        accent_style = f"color: {self.main_window.accent_color};"

        # Drop text label
        self.main_window.drop_text_label.setStyleSheet(accent_style)

        # Queue label
        if hasattr(self, "queue_widget") and self.queue_widget:
            queue_label = self.queue_widget.findChild(QLabel)
            if queue_label:
                queue_label.setStyleSheet(accent_style)

        # Progress bar
        self.main_window._update_progress_bar_style()

        # Log output
        self.main_window.log_output.setStyleSheet(accent_style)

        # Bottom titlebar
        if hasattr(self.main_window, "bottom_titlebar"):
            self.main_window.bottom_titlebar.update_style()

    def update_queue_visibility(self, is_processing, has_jobs):
        """Update queue visibility based on current state"""
        if not is_processing and not has_jobs:
            if self.queue_widget:
                self.queue_widget.setVisible(False)
            self.main_window.drop_text_label.setText("Drag and Drop Zip here")
            self._show_main_gif()
        else:
            if self.queue_widget:
                self.queue_widget.setVisible(True)
            if not is_processing:
                self.main_window.drop_text_label.setText(
                    "Queue idle. Ready for next job."
                )

    def _show_main_gif(self):
        """Show the main GIF animation"""
        if (self.current_movie != self.main_movie and self.main_movie and self.main_movie.isValid()):
            self.main_window.drop_zone_gif.setMovie(self.main_movie)
            self.main_movie.start()
            self.current_movie = self.main_movie

    def switch_to_download_gif(self):
        """Switch to a random download GIF"""
        # Update setting from current value
        self.disable_default_gifs = self.settings.value("disable_default_gifs", False, type=bool)

        if self.current_movie:
            self.current_movie.stop()

        colored_dir = get_base_path() / "gifs/colorized"
        os.makedirs(str(colored_dir), exist_ok=True)

        # Determine which GIFs to use based on setting
        ui_mode = self.settings.value("ui_mode", "default")
        if ui_mode == "sonic":
            sonic_dir = Paths.resource("sonic/gifs")
            sonic_downloads = []
            if sonic_dir.exists() and sonic_dir.is_dir():
                sonic_downloads.extend([str(p) for p in sonic_dir.glob("downloading*.gif")])

            if sonic_downloads:
                available_gifs = sorted(sonic_downloads)
            else:
                available_gifs = []
        elif self.disable_default_gifs:
            # Use only custom GIFs
            custom_gifs = sorted([str(p) for p in colored_dir.glob("downloading_custom*.gif")])

            # Filter out default GIFs (if they exist in the custom directory)
            default_names = ["downloading_lain"]
            available_gifs = [gif for gif in custom_gifs if not any(name in gif for name in default_names)]

            # If no custom GIFs found, fall back to defaults
            if not available_gifs:
                available_gifs = self.default_download_gifs
                logger.warning("No custom GIFs found, using defaults")
        else:
            # Use only default GIFs
            available_gifs = self.default_download_gifs

        # Make sure we have GIFs to use
        if not available_gifs:
            logger.error("No download GIFs available!")
            self.main_window.drop_text_label.setText("Downloading...")
            return

        # Select and load a random GIF
        self.random_gif_path = random.choice(available_gifs)
        self.download_movie = QMovie(self.random_gif_path)

        if self.download_movie.isValid():
            self.current_movie = self.download_movie
            self.main_window.drop_zone_gif.setMovie(self.current_movie)
            self.current_movie.start()
        else:
            logger.error(f"Failed to load GIF: {self.random_gif_path}")
            self.main_window.drop_text_label.setText("Downloading...")
