import logging
import os
import re
import sys
from io import BytesIO
from pathlib import Path

import requests
from PIL import Image

from PyQt6.QtCore import QObject, pyqtSignal
from utils.yaml_config_manager import is_slssteam_mode_enabled

logger = logging.getLogger(__name__)


class ApplicationShortcutsTask(QObject):
    """Create desktop shortcuts and icons using Steam Grid DB API"""

    progress = pyqtSignal(str)
    progress_percentage = pyqtSignal(int)
    completed = pyqtSignal(bool)
    error = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._is_running = True
        self.api_key = None

    def set_api_key(self, api_key):
        """Set the Steam Grid DB API key"""
        self.api_key = api_key

    def stop(self):
        """Stop the task"""
        self._is_running = False

    def run(self, appid, game_name):
        """Run the application shortcuts creation task"""
        try:
            # Only available on Linux with SLSsteam mode enabled
            if sys.platform != "linux":
                logger.error("Application shortcuts are only supported on Linux")
                self.error.emit("Application shortcuts are only supported on Linux")
                return False

            if not is_slssteam_mode_enabled():
                logger.error("SLSsteam mode must be enabled to create shortcuts")
                self.error.emit("SLSsteam mode must be enabled to create shortcuts")
                return False

            if not self.api_key:
                logger.error("No Steam Grid DB API key provided")
                self.error.emit("No Steam Grid DB API key provided")
                return False

            if not self._is_running:
                return False

            self.progress.emit(
                f"Creating application shortcuts for {game_name} (AppID: {appid})"
            )
            self.progress_percentage.emit(10)

            # Get game info from Steam Grid DB
            game_data = self._get_game_data(appid)
            if not game_data:
                logger.error(f"Could not find game data for AppID {appid}")
                self.error.emit(f"Could not find game data for AppID {appid}")
                return False

            if not self._is_running:
                return False

            self.progress_percentage.emit(30)

            # Download and process icon
            icon_url = self._get_icon_url(game_data["id"])
            if not icon_url:
                logger.error(f"Could not find icon for game {game_name}")
                self.error.emit(f"Could not find icon for game {game_name}")
                return False

            if not self._is_running:
                return False

            self.progress_percentage.emit(50)

            # Download and save icons in multiple sizes
            self._save_icons(icon_url, appid)

            if not self._is_running:
                return False

            self.progress_percentage.emit(80)

            # Create desktop entry
            self._create_desktop_entry(appid, game_name, game_data["name"])

            self.progress_percentage.emit(100)
            self.progress.emit(
                f"Successfully created application shortcuts for {game_name}"
            )

            self.completed.emit(True)
            return True

        except Exception as e:
            logger.error(f"Failed to create application shortcuts: {e}")
            self.error.emit(str(e))
            return False

    def _get_game_data(self, appid):
        """Get game data from Steam Grid DB API"""
        try:
            headers = {"Authorization": f"Bearer {self.api_key}"}

            response = requests.get(
                f"https://www.steamgriddb.com/api/v2/games/steam/{appid}",
                headers=headers,
                timeout=10,
            )
            response.raise_for_status()

            return response.json()["data"]
        except Exception as e:
            logger.error(f"Failed to get game data: {e}")
            return None

    def _get_icon_url(self, game_id):
        """Get icon URL from Steam Grid DB API"""
        try:
            headers = {"Authorization": f"Bearer {self.api_key}"}

            response = requests.get(
                f"https://www.steamgriddb.com/api/v2/icons/game/{game_id}",
                headers=headers,
                params={"types": "static", "limit": 1},
                timeout=10,
            )
            response.raise_for_status()

            data = response.json()["data"]
            if data:
                return data[0]["url"]
            return None
        except Exception as e:
            logger.error(f"Failed to get icon URL: {e}")
            return None

    def _save_icons(self, icon_url, appid):
        """Download and save icons in multiple sizes"""
        try:
            # Download image
            response = requests.get(icon_url, timeout=10)
            response.raise_for_status()

            img_data = response.content
            img = Image.open(BytesIO(img_data)).convert("RGBA")

            # Icon sizes
            icon_sizes = [16, 24, 32, 48, 64, 96, 128, 256]
            icon_name = f"steam_icon_{appid}.png"
            icon_base = Path.home() / ".local" / "share" / "icons" / "hicolor"

            for size in icon_sizes:
                if not self._is_running:
                    return

                target_dir = icon_base / f"{size}x{size}" / "apps"
                target_dir.mkdir(parents=True, exist_ok=True)

                resized = img.resize((size, size), Image.Resampling.LANCZOS)
                out_path = target_dir / icon_name
                resized.save(out_path, "PNG")

                self.progress.emit(f"Installed icon {size}x{size} → {out_path}")

        except Exception as e:
            logger.error(f"Failed to save icons: {e}")
            raise

    def _create_desktop_entry(self, appid, game_name, sgdb_name):
        """Create desktop entry file"""
        try:
            desktop_dir = Path.home() / ".local" / "share" / "applications"
            desktop_dir.mkdir(parents=True, exist_ok=True)

            # Clean up the desktop name
            desktop_name = re.sub(r"[\/\0]", "", sgdb_name).strip()
            desktop_file = f"{desktop_name}.desktop"
            desktop_path = desktop_dir / desktop_file

            desktop_contents = f"""[Desktop Entry]
Name={sgdb_name}
Comment=Play this game on Steam
Exec=steam steam://rungameid/{appid}
Icon=steam_icon_{appid}
Terminal=false
Type=Application
Categories=Game;
"""

            with open(desktop_path, "w", encoding="utf-8") as f:
                f.write(desktop_contents)

            self.progress.emit(f"Created desktop entry → {desktop_path}")

        except Exception as e:
            logger.error(f"Failed to create desktop entry: {e}")
            raise
