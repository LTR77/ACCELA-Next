import logging
import os
import hashlib
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path

import requests
import yaml
from PyQt6.QtCore import QObject, pyqtSignal

from utils.helpers import get_base_path
from utils.settings import get_settings

logger = logging.getLogger(__name__)

REMOTE_UPDATES_URL = "https://raw.githubusercontent.com/AceSLS/SLSsteam/refs/heads/main/res/updates.yaml"


class DownloadSLSsteamTask(QObject):
    progress = pyqtSignal(str)
    progress_percentage = pyqtSignal(int)
    completed = pyqtSignal(str)
    error = pyqtSignal()

    def __init__(self, steam_path=None):
        super().__init__()
        self._is_running = True
        self._steam_path = steam_path

    def run(self):
        """Download and install SLSsteam from GitHub releases"""
        logger.info("Starting SLSsteam download task")

        try:
            slssteam_dir = get_base_path() / "SLSsteam"

            self.progress.emit("Fetching latest SLSsteam release information...")
            release_data = self._fetch_latest_release()

            if not release_data:
                self.progress.emit(
                    "Error: Could not fetch release information from GitHub"
                )
                self.error.emit()
                return

            self.progress.emit(
                f"Latest release: {release_data.get('tag_name', 'Unknown')}"
            )

            download_url = self._find_7z_download_url(release_data)
            if not download_url:
                self.progress.emit("Error: Could not find SLSsteam-Any.7z in releases")
                self.error.emit()
                return

            self.progress.emit(f"Downloading {download_url}")
            temp_dir = tempfile.mkdtemp()

            try:
                downloaded_file = self._download_file(download_url, temp_dir)

                self.progress.emit(f"Extracting archive to {slssteam_dir}")

                # Create directory if it doesn't exist
                slssteam_dir.mkdir(parents=True, exist_ok=True)

                if os.path.exists(slssteam_dir):
                    self.progress.emit("Removing old SLSsteam installation...")
                    shutil.rmtree(slssteam_dir)
                    slssteam_dir.mkdir(parents=True, exist_ok=True)

                self._extract_7z(downloaded_file, slssteam_dir)

                # Look for setup.sh in the extracted files (may be at root or in subdirs)
                setup_script = self._find_setup_script(slssteam_dir)
                if not setup_script:
                    self.progress.emit("Error: setup.sh not found in archive")
                    self.error.emit()
                    return

                self.progress.emit(f"Found setup.sh at: {setup_script}")
                self.progress.emit("Setting up SLSsteam...")
                self._run_setup_script(setup_script, slssteam_dir)

                # Merge new config entries (PlayNotOwnedGames handled by AdditionalApps)
                self.progress.emit("Updating config with new entries...")
                self._merge_config_entries(slssteam_dir)

                # Save version info
                self._save_version_info(
                    slssteam_dir, release_data.get("tag_name", "Unknown")
                )

                # Patch steam.sh and create steam.cfg if steam_path is provided
                if self._steam_path:
                    self.progress.emit("Patching steam.sh for SLSsteam...")

                    # Detect Steam installation type (Flatpak or Native)
                    install_type = self._get_steam_install_type(self._steam_path)

                    # Copy .so files to Flatpak path if needed
                    if install_type == "flatpak":
                        self.progress.emit("Copying SLSsteam libraries to Flatpak path...")
                        self._copy_so_to_flatpak(slssteam_dir)

                    # Patch steam.sh
                    self._patch_steam_sh(self._steam_path, install_type)

                    # Create steam.cfg to block updates
                    self._create_steam_cfg(self._steam_path)

                    self.progress.emit("SLSsteam configuration completed successfully!")

                self.progress.emit("SLSsteam installation completed successfully!")
                self.completed.emit(
                    "SLSsteam has been successfully downloaded and installed."
                )

            finally:
                self._cleanup_temp_dir(temp_dir)

        except Exception as e:
            logger.error(f"SLSsteam download task failed: {e}", exc_info=True)
            self.progress.emit(f"Error: {e}")
            self.error.emit()
            raise

    def _fetch_latest_release(self):
        """Fetch the latest release from GitHub API"""
        url = "https://api.github.com/repos/AceSLS/SLSsteam/releases/latest"

        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"Failed to fetch GitHub release: {e}")
            return None

    def _find_7z_download_url(self, release_data):
        """Find the SLSsteam-Any.7z download URL from release data"""
        assets = release_data.get("assets", [])
        for asset in assets:
            if asset.get("name") == "SLSsteam-Any.7z":
                return asset.get("browser_download_url")
        return None

    def _download_file(self, url, dest_dir):
        """Download file from URL with progress tracking"""
        response = requests.get(url, stream=True, timeout=60)
        response.raise_for_status()

        filename = "SLSsteam-Any.7z"
        dest_path = os.path.join(dest_dir, filename)

        total_size = int(response.headers.get("content-length", 0))
        downloaded = 0

        with open(dest_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                if not self._is_running:
                    raise Exception("Download cancelled")

                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)

                    if total_size > 0:
                        percentage = int((downloaded / total_size) * 100)
                        self.progress_percentage.emit(percentage)

        return dest_path

    def _extract_7z(self, archive_path, dest_dir):
        """Extract 7z archive using system 7z command"""
        logger.info(f"Extracting {archive_path} to {dest_dir}")

        # Try both 7z and 7za (p7zip command)
        for cmd in ["7z", "7za"]:
            result = subprocess.run(
                [cmd, "x", archive_path, f"-o{dest_dir}", "-y"],
                capture_output=True,
                text=True,
            )

            # Check if extraction succeeded by looking for critical files
            setup_script = self._find_setup_script(dest_dir)

            if result.returncode == 0 and setup_script:
                logger.info(f"Archive extracted successfully using {cmd}")
                # Log any warnings but don't treat them as errors
                if result.stderr:
                    logger.warning(f"7z warnings from {cmd}: {result.stderr}")
                return
            elif setup_script:
                # Extraction mostly succeeded (exit code != 0) but critical files are present
                # This happens when 7z encounters issues like dangerous links but still extracts most files
                logger.warning(
                    f"7z extraction completed with warnings (exit code {result.returncode}): {result.stderr}"
                )
                logger.info(f"Critical files extracted successfully to {dest_dir}")
                return

        # If we get here, both commands failed and no critical files were extracted
        logger.error(
            f"7z extraction failed with exit code {result.returncode}. stderr: {result.stderr}"
        )
        raise Exception(
            f"7z extraction failed. Please ensure p7zip is installed: {result.stderr}"
        )

    @staticmethod
    def find_steamclient_so():
        """Find steamclient.so in user's Steam installation"""
        from core.steam_helpers import find_steam_install

        steam_path = find_steam_install()
        if not steam_path:
            logger.debug("Steam installation not found")
            return None

        steam_path = Path(steam_path) / "ubuntu12_32" / "steamclient.so"
        if steam_path.exists():
            logger.debug(f"Found steamclient.so at {steam_path}")
            return str(steam_path)

        logger.debug("steamclient.so not found in Steam installation")
        return None

    @staticmethod
    def compute_file_hash(filepath):
        """Compute SHA-256 hash of a file"""
        sha256 = hashlib.sha256()
        try:
            with open(filepath, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    if not chunk:
                        break
                    sha256.update(chunk)
            return sha256.hexdigest()
        except Exception as e:
            logger.error(f"Failed to compute hash for {filepath}: {e}")
            return None

    @staticmethod
    def fetch_remote_hashes():
        """Fetch remote updates.yaml and extract all hashes"""
        try:
            response = requests.get(REMOTE_UPDATES_URL, timeout=10)
            response.raise_for_status()
            data = yaml.safe_load(response.text)

            all_hashes = []
            safe_mode_hashes = data.get("SafeModeHashes", {})
            for timestamp, entries in safe_mode_hashes.items():
                if isinstance(entries, list):
                    for entry in entries:
                        parts = entry.strip().split()
                        if parts:
                            all_hashes.append(parts[0])

            logger.debug(f"Fetched {len(all_hashes)} hashes from remote updates.yaml")
            return all_hashes
        except Exception as e:
            logger.error(f"Failed to fetch remote hashes: {e}")
            return None

    @staticmethod
    def check_steamclient_hash():
        """Check if user's steamclient.so hash matches remote"""
        local_path = DownloadSLSsteamTask.find_steamclient_so()

        if not local_path:
            return {"found": False, "hash": None, "mismatch": None}

        local_hash = DownloadSLSsteamTask.compute_file_hash(local_path)
        if not local_hash:
            return {"found": True, "hash": None, "mismatch": None, "error": True}

        remote_hashes = DownloadSLSsteamTask.fetch_remote_hashes()
        if remote_hashes is None:
            return {"found": True, "hash": local_hash, "mismatch": None, "error": True}

        mismatch = local_hash not in remote_hashes
        return {
            "found": True,
            "hash": local_hash,
            "mismatch": mismatch,
        }

    @staticmethod
    def check_update_available():
        """Check if an update is available for SLSsteam"""
        try:
            response = requests.get(
                "https://api.github.com/repos/AceSLS/SLSsteam/releases/latest",
                timeout=10,
            )
            response.raise_for_status()
            release_data = response.json()

            latest_version = release_data.get("tag_name", "Unknown")
            latest_date = release_data.get("published_at", "")

            # Check if SLSsteam is installed (check both ACCELA installation and manual installation)
            xdg_data_home = os.environ.get("XDG_DATA_HOME") or os.path.expanduser(
                "~/.local/share"
            )
            slssteam_dir = Path(xdg_data_home) / "ACCELA" / "SLSsteam"
            slssteam_manual = Path(xdg_data_home) / "SLSsteam" / "SLSsteam.so"

            # Check if SLSsteam is installed either through ACCELA or manually
            accela_installed = slssteam_dir.exists()
            manual_installed = slssteam_manual.exists()

            if not accela_installed and not manual_installed:
                return {
                    "update_available": True,
                    "latest_version": latest_version,
                    "latest_date": latest_date,
                    "installed": False,
                    "installed_version": None,
                }

            # Check for version file in ACCELA installation
            installed_version = None
            is_accela_install = False
            if accela_installed:
                version_file = slssteam_dir / "VERSION"
                if version_file.exists():
                    with open(version_file, "r") as f:
                        installed_version = f.read().strip()
                    is_accela_install = True

            # Only compare versions if we have a version file (ACCELA installation)
            # For manual installations, we can't determine the version, so don't show update available
            if is_accela_install and installed_version:
                update_available = installed_version != latest_version
            else:
                # Manual installation or no version file - assume up to date
                # (we can't easily determine the version of manually installed SLSsteam)
                update_available = False
                installed_version = (
                    "Unknown (manual install)" if not is_accela_install else "Unknown"
                )

            # Check steamclient.so hash compatibility
            hash_check = DownloadSLSsteamTask.check_steamclient_hash()

            return {
                "update_available": update_available,
                "latest_version": latest_version,
                "latest_date": latest_date,
                "installed": True,
                "installed_version": installed_version,
                "steamclient_found": hash_check.get("found", False),
                "steamclient_hash": hash_check.get("hash", "") or "",
                "steamclient_mismatch": hash_check.get("mismatch"),
                "steamclient_error": hash_check.get("error", False),
            }

        except Exception as e:
            logger.error(f"Failed to check for SLSsteam updates: {e}")
            return {
                "update_available": False,
                "latest_version": "Unknown",
                "latest_date": "",
                "installed": False,
                "installed_version": None,
                "error": str(e),
                "steamclient_found": False,
                "steamclient_hash": "",
                "steamclient_mismatch": None,
                "steamclient_error": True,
            }

    def _find_setup_script(self, base_dir):
        """Recursively search for setup.sh in the extracted directory"""
        for root, dirs, files in os.walk(base_dir):
            if "setup.sh" in files:
                return os.path.join(root, "setup.sh")
        return None

    def _save_version_info(self, slssteam_dir, version):
        """Save the installed version to a VERSION file"""
        try:
            version_file = slssteam_dir / "VERSION"
            with open(version_file, "w") as f:
                f.write(version)
            logger.info(f"Saved version {version} to VERSION file")
        except Exception as e:
            logger.warning(f"Failed to save version info: {e}")

    def _run_setup_script(self, script_path, work_dir):
        """Execute setup.sh script"""
        st = os.stat(script_path)
        os.chmod(script_path, st.st_mode | stat.S_IEXEC)

        self.progress.emit("Running setup.sh install...")

        process = subprocess.Popen(
            [script_path, "install"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=work_dir,
        )

        for line in iter(process.stdout.readline, ""):
            if not self._is_running:
                process.terminate()
                raise Exception("Setup cancelled")
            self.progress.emit(f"setup.sh: {line.strip()}")

        process.wait()

        if process.returncode != 0:
            raise Exception(f"setup.sh failed with exit code {process.returncode}")

    def _cleanup_temp_dir(self, temp_dir):
        """Clean up temporary directory"""
        try:
            shutil.rmtree(temp_dir)
        except Exception as e:
            logger.warning(f"Failed to clean up temp dir {temp_dir}: {e}")

    def _merge_config_entries(self, slssteam_dir):
        """Merge new config entries from default config into user's config.

        This ensures any new configuration options added in updates are available
        to the user with their default values, without overwriting existing settings.
        If the user config doesn't exist, copies the default config.
        """
        try:
            # Path to the default config in extracted SLSsteam
            default_config_path = slssteam_dir / "res" / "config.yaml"

            # Path to user's config
            xdg_config_home = os.environ.get("XDG_CONFIG_HOME")
            if xdg_config_home:
                user_config_dir = Path(xdg_config_home) / "SLSsteam"
            else:
                user_config_dir = Path.home() / ".config" / "SLSsteam"
            user_config_path = user_config_dir / "config.yaml"

            if not default_config_path.exists():
                logger.warning(f"Default config not found at {default_config_path}")
                return

            # If user config doesn't exist, create directory and copy default config
            if not user_config_path.exists():
                logger.info(
                    f"User config not found, creating from default at {user_config_path}"
                )
                user_config_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy(default_config_path, user_config_path)
                self.progress.emit("Created new config from default")

                # NOTE: PlayNotOwnedGames setting is now handled by AdditionalApps
                # No longer needed - games are added to AdditionalApps list instead
                # settings = get_settings()
                # slssteam_mode = settings.value("slssteam_mode", False, type=bool)

                # if slssteam_mode:
                #     update_yaml_boolean_value(
                #         user_config_path, "PlayNotOwnedGames", True
                #     )
                #     self.progress.emit("PlayNotOwnedGames setting enabled")
                # else:
                #     self.progress.emit("SLSsteam mode is disabled in settings")
                return

            # NOTE: PlayNotOwnedGames setting is now handled by AdditionalApps
            # No longer needed - games are added to AdditionalApps list instead
            # settings = get_settings()
            # slssteam_mode = settings.value("slssteam_mode", False, type=bool)

            # play_not_owned_changed = False
            # if slssteam_mode:
            #     play_not_owned_changed = update_yaml_boolean_value(
            #         user_config_path, "PlayNotOwnedGames", True
            #     )

            #     if play_not_owned_changed:
            #         self.progress.emit("PlayNotOwnedGames setting enabled")
            #     else:
            #         self.progress.emit("PlayNotOwnedGames is already enabled")
            # else:
            #     self.progress.emit("SLSsteam mode is disabled in settings")

        except Exception as e:
            logger.warning(f"Failed to update config: {e}")
            # Don't emit error - this is not critical for the installation

    def _get_steam_install_type(self, steam_path):
        """Detect if Steam installation is Flatpak or Native"""
        if ".var/app/com.valvesoftware.Steam" in steam_path:
            return "flatpak"
        return "native"

    def _copy_so_to_flatpak(self, slssteam_dir):
        """Copy .so files to Flatpak's SLSsteam directory"""
        try:
            flatpak_slssteam_dir = os.path.expanduser(
                "~/.var/app/com.valvesoftware.Steam/.local/share/SLSsteam"
            )
            os.makedirs(flatpak_slssteam_dir, exist_ok=True)

            # Copy library-inject.so and SLSsteam.so
            for so_file in ["library-inject.so", "SLSsteam.so"]:
                src = os.path.join(slssteam_dir, so_file)
                dst = os.path.join(flatpak_slssteam_dir, so_file)
                if os.path.exists(src):
                    shutil.copy2(src, dst)
                    logger.info(f"Copied {so_file} to Flatpak path")
        except Exception as e:
            logger.warning(f"Failed to copy .so files to Flatpak path: {e}")

    def _patch_steam_sh(self, steam_path, install_type):
        """Patch steam.sh to load SLSsteam libraries via LD_AUDIT"""
        try:
            steam_sh = os.path.join(steam_path, "steam.sh")
            if not os.path.exists(steam_sh):
                logger.warning(f"steam.sh not found at {steam_sh}")
                return

            # Determine LD_AUDIT paths based on install type
            if install_type == "flatpak":
                ld_audit = (
                    os.path.expanduser(
                        "~/.var/app/com.valvesoftware.Steam/.local/share/SLSsteam/"
                    )
                    + "library-inject.so:"
                    + os.path.expanduser(
                        "~/.var/app/com.valvesoftware.Steam/.local/share/SLSsteam/"
                    )
                    + "SLSsteam.so"
                )
            else:
                # Native installation
                ld_audit = (
                    os.path.expanduser("~/.local/share/SLSsteam/library-inject.so:")
                    + os.path.expanduser("~/.local/share/SLSsteam/SLSsteam.so")
                )

            # Read steam.sh
            with open(steam_sh, "r") as f:
                lines = f.readlines()

            # Remove existing LD_AUDIT export lines
            new_lines = [
                line for line in lines if "export LD_AUDIT=" not in line
            ]

            # Insert LD_AUDIT export after line 10 (index 10)
            # sed '10a ...' inserts after line 10, so we use index 10
            insert_index = min(10, len(new_lines))
            new_lines.insert(insert_index, f"export LD_AUDIT={ld_audit}\n")

            # Write back
            with open(steam_sh, "w") as f:
                f.writelines(new_lines)

            logger.info(f"Patched steam.sh with LD_AUDIT for {install_type}")

        except Exception as e:
            logger.warning(f"Failed to patch steam.sh: {e}")

    def _create_steam_cfg(self, steam_path):
        """Create steam.cfg to block Steam updates"""
        try:
            steam_cfg = os.path.join(steam_path, "steam.cfg")
            content = (
                "BootStrapperInhibitAll=enable\n"
                "BootStrapperForceSelfUpdate=disable\n"
            )
            with open(steam_cfg, "w") as f:
                f.write(content)
            logger.info(f"Created steam.cfg at {steam_path}")
        except Exception as e:
            logger.warning(f"Failed to create steam.cfg: {e}")

    def stop(self):
        """Stop the task"""
        logger.info("SLSsteam download task received stop signal")
        self._is_running = False
