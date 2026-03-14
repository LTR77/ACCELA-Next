"""
CLI Manager for ACCELA - Handles command-line mode for ZIP file processing.

When ACCELA is invoked with ZIP file arguments, this module takes over
to provide a simplified CLI experience without the main window.
"""

import logging
import os
import re
import shutil
import subprocess
import sys

from PyQt6.QtCore import QEventLoop
from PyQt6.QtGui import QFont

from core.steam_helpers import fix_greenluma_offline_mode, get_steam_libraries
from core.tasks.process_zip_task import ProcessZipTask
from core.tasks.download_depots_task import DownloadDepotsTask

from utils.settings import get_settings
from utils.task_runner import TaskRunner
from utils.paths import Paths

# Import text menus for CLI mode (urwid-based, cross-platform)
from ui.text_menus import (
    select_depots,
    select_dlcs,
    select_steam_library,
    select_destination_path,
)

LINUX_TERMINALS = [
    ["wezterm", "start", "--always-new-process", "--"],
    ["konsole", "-e"],
    ["gnome-terminal", "--"],
    ["ptyxis", "--"],
    ["alacritty", "-e"],
    ["tilix", "-e"],
    ["xfce4-terminal", "-e"],
    ["terminator", "-x"],
    ["mate-terminal", "-e"],
    ["lxterminal", "-e"],
    ["xterm", "-e"],
    ["kitty", "-e"],
]


def _get_terminal_command(appid=None, zip_path=None):
    """Get the terminal command to run CLI mode.

    Args:
        appid: AppID to download from Morrenus API
        zip_path: Path to a ZIP file to process

    Returns:
        List of command arguments, or None if no terminal available
    """
    if sys.platform != 'linux':
        return None

    # Get the directory where accela is installed
    script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    run_script = os.path.join(script_dir, 'run.sh')

    if not os.path.exists(run_script):
        return None

    # Build the base command
    if appid:
        base_cmd = [run_script, "-cli", "--appid", str(appid)]
    elif zip_path:
        base_cmd = [run_script, "-cli", zip_path]
    else:
        return None

    # Find first available terminal
    for terminal in LINUX_TERMINALS:
        term_path = shutil.which(terminal[0])
        if term_path:
            return [term_path] + terminal[1:] + base_cmd

    return None


def open_cli_terminal(appid=None, zip_path=None):
    """Open a new terminal running ACCELA CLI mode.

    Args:
        appid: AppID to download from Morrenus API
        zip_path: Path to a ZIP file to process
    """
    cmd = _get_terminal_command(appid, zip_path)
    if not cmd:
        return False

    try:
        subprocess.Popen(cmd, start_new_session=True)
        return True
    except Exception:
        return False


def run_cli_mode(app, command_line_zips, logger, appid=None):
    """Run ACCELA in CLI mode - show only DepotSelectionDialog for ZIP files.

    Args:
        app: QApplication instance
        command_line_zips: List of ZIP file paths to process
        logger: Logger instance
        appid: Optional AppID to download manifest from Morrenus API
    """
    # Load settings for CLI mode
    settings = get_settings()

    logger.info("=" * 50)
    logger.info("ACCELA CLI Mode")
    logger.info("=" * 50)

    # Fix GreenLuma offline mode
    fix_greenluma_offline_mode()

    # Apply ACCELA theme
    from main import update_appearance
    accent_color = settings.value("accent_color", "#C06C84")
    bg_color = settings.value("background_color", "#000000")

    # Load font from settings (same logic as UIStateManager)
    font_family = settings.value("font", "TrixieCyrG-Plain")
    font_size = settings.value("font-size", 10, type=int)
    font_style = settings.value("font-style", "Normal")

    font = QFont(font_family)
    font.setPointSize(font_size)
    if font_style == "Italic":
        font.setItalic(True)
    elif font_style == "Bold":
        font.setBold(True)
    elif font_style == "Bold Italic":
        font.setBold(True)
        font.setItalic(True)

    font_ok, font_info = update_appearance(app, accent_color, bg_color, font)
    if font_ok:
        logger.info(f"CLI mode: theme applied, font '{font_info}' loaded")
    else:
        logger.warning(f"CLI mode: failed to load custom font")

    # If appid is provided, download manifest from Morrenus API
    if appid:
        logger.info(f"Downloading manifest for AppID {appid} from Morrenus API")
        zip_path, error = download_morrenus_manifest(appid)
        if error:
            logger.error(f"Failed to download manifest: {error}")
            logger.info("Exiting CLI mode.")
            return
        command_line_zips = [zip_path]
        logger.info(f"Manifest downloaded: {os.path.basename(zip_path) if zip_path else 'Unknown'}")

    def get_destination_path_cli():
        """Get destination path based on settings (same logic as TaskManager)"""
        slssteam_mode = settings.value("slssteam_mode", False, type=bool)
        library_mode = settings.value("library_mode", False, type=bool)

        if slssteam_mode or library_mode:
            libraries = get_steam_libraries()
            if libraries:
                path = select_steam_library(libraries)
                if path:
                    return path
                return None

        # Use text-based destination path selection
        default_path = os.path.expanduser("~")
        path = select_destination_path(default_path)
        return path

    total_zips = len(command_line_zips)

    for index, zip_path in enumerate(command_line_zips):
        current_job = index + 1
        logger.info(f"\n[{current_job}/{total_zips}] Processing: {os.path.basename(zip_path) if zip_path else 'Unknown'}")

        # Step 1: Process ZIP file
        logger.info("Parsing ZIP file...")
        zip_task = ProcessZipTask()

        game_data_holder = [None]

        def on_zip_processed(result):
            game_data_holder[0] = result
            loop.quit()

        # TaskRunner.run() returns the worker
        zip_task_runner = TaskRunner()
        zip_task_runner.run(zip_task.run, zip_path).finished.connect(on_zip_processed)

        # Create a local event loop to wait for ZIP processing
        loop = QEventLoop()
        zip_task_runner.cleanup_complete.connect(loop.quit)
        loop.exec()

        game_data = game_data_holder[0]

        if not game_data or not game_data.get("depots"):
            logger.warning(f"No depots found in {os.path.basename(zip_path) if zip_path else 'Unknown'}")
            continue

        # Step 2: Show depot selection menu
        logger.info(f"Showing depot selection for: {game_data.get('game_name', 'Unknown')}")

        selected_depots = select_depots(
            game_data["appid"],
            game_data["game_name"],
            game_data["depots"],
            game_data.get("header_url"),
        )

        if not selected_depots:
            logger.info("Depot selection cancelled or no depots selected, skipping this ZIP")
            continue

        logger.info(f"Selected {len(selected_depots)} depots")

        # Step 2.5: DLC selection (Windows + SLSsteam mode only)
        slssteam_mode = settings.value("slssteam_mode", False, type=bool)
        if sys.platform == "win32" and slssteam_mode and game_data.get("dlcs"):
            logger.info("Windows + SLSsteam mode detected, showing DLC selection...")
            selected_dlcs = select_dlcs(game_data["dlcs"])
            if selected_dlcs:
                game_data["selected_dlcs"] = selected_dlcs
                logger.info(f"Selected {len(selected_dlcs)} DLCs")

        # Step 3: Get destination path (respects SLSsteam/library mode settings)
        dest_path = get_destination_path_cli()

        if not dest_path:
            logger.info("Destination folder not selected, skipping this ZIP")
            continue

        logger.info(f"Destination: {dest_path}")

        # Step 4: Start download
        logger.info("\n" + "=" * 40)
        logger.info("Starting download...")
        logger.info("=" * 40)

        game_data["selected_depots_list"] = selected_depots

        download_task = DownloadDepotsTask()
        download_task.progress.connect(logger.info)

        # TaskRunner.run() returns the worker, store it
        download_task_runner = TaskRunner()
        download_worker = download_task_runner.run(
            download_task.run, game_data, selected_depots, dest_path
        )

        # Wait for download to complete
        download_loop = QEventLoop()

        def on_download_complete():
            download_loop.quit()

        download_worker.finished.connect(on_download_complete)
        download_loop.exec()

        # Step 5: Run all post-processing steps
        logger.info("\n" + "=" * 40)
        logger.info("Running post-processing...")
        logger.info("=" * 40)

        # Create a CLI task manager to handle all post-processing
        cli_task_manager = CLITaskManager(settings, logger)
        cli_task_manager.run_post_processing(game_data, download_task, dest_path)

        logger.info("\n" + "=" * 40)
        logger.info(f"Download complete: {game_data.get('game_name', 'Unknown')}")
        logger.info("=" * 40)

    logger.info(f"\n{'=' * 50}")
    logger.info(f"All {total_zips} ZIP(s) processed")
    logger.info(f"{'=' * 50}")

    # Stop all active TaskRunners to prevent QThread errors on exit
    TaskRunner.stop_all_active()

    # Process pending events to ensure clean Qt shutdown
    app.processEvents()

    # Remove Qt log handler and shutdown logging before exit to prevent atexit callback errors
    # (the Qt C++ object may be deleted before Python's logging shutdown)
    from utils.logger import qt_log_handler
    root_logger = logging.getLogger()
    try:
        root_logger.removeHandler(qt_log_handler)
    except (RuntimeError, TypeError):
        pass  # Handler may already be deleted

    # Manually shutdown logging to prevent atexit from trying to access deleted Qt objects
    logging.shutdown()

    sys.exit(0)


class CLITaskManager:
    """CLI version of TaskManager that handles all post-processing steps without UI."""

    def __init__(self, settings, logger):
        self.settings = settings
        self.logger = logger
        self.game_data = None
        self.download_task = None
        self.current_dest_path = None
        self.slssteam_mode_was_active = False

    def run_post_processing(self, game_data, download_task, dest_path):
        """Run all post-processing steps after download completion."""
        self.game_data = game_data
        self.download_task = download_task
        self.current_dest_path = dest_path
        self.slssteam_mode_was_active = self.settings.value("slssteam_mode", False, type=bool)

        # Get size on disk
        size_on_disk = 0
        if self.download_task:
            size_on_disk = self.download_task.total_download_size_for_this_job
            self.logger.info(f"Retrieved SizeOnDisk from download task: {size_on_disk}")

        # Create ACF file
        self._create_acf_file(size_on_disk)

        # Write app token to file (non-SLSsteam mode)
        self._write_app_token(dest_path)

        # Move manifests to depotcache
        self._move_manifests_to_depotcache()

        # Save main depot info
        self._save_main_depot_info()

        # Set Linux binary permissions
        if sys.platform == "linux":
            self._set_linux_binary_permissions()

        # Add AppIDs to SLSsteam config on Linux
        if sys.platform == "linux" and self.slssteam_mode_was_active:
            self._add_appids_to_slssteam_config()

        # Auto-apply Goldberg after download completion
        auto_apply_goldberg = self.settings.value("auto_apply_goldberg", False, type=bool)
        if auto_apply_goldberg and self.game_data and self.current_dest_path:
            safe_game_name_fallback = (
                re.sub(r"[^\w\s-]", "", self.game_data.get("game_name", ""))
                .strip()
                .replace(" ", "_")
            )
            install_folder_name = self.game_data.get(
                "installdir", safe_game_name_fallback
            )
            if not install_folder_name:
                install_folder_name = f"App_{self.game_data['appid']}"

            game_directory = os.path.join(
                self.current_dest_path, "steamapps", "common", install_folder_name
            )
            self.logger.info("Auto-applying Goldberg after download completion")
            self._apply_goldberg(
                game_directory,
                str(self.game_data.get("appid", "")),
                self.game_data.get("game_name", ""),
            )

        # Steamless processing
        steamless_enabled = self.settings.value("use_steamless", False, type=bool)
        if steamless_enabled:
            self.logger.info("Steamless is enabled, starting DRM removal...")
            self._run_steamless()

        # Application shortcuts (Linux + SLSsteam mode)
        shortcuts_enabled = self.settings.value("create_application_shortcuts", False, type=bool)
        if shortcuts_enabled and self.slssteam_mode_was_active and sys.platform == "linux":
            self.logger.info("Application shortcuts creation is enabled...")
            self._run_application_shortcuts()

        # Achievement generation
        achievements_enabled = self.settings.value("generate_achievements", False, type=bool)
        if achievements_enabled:
            self.logger.info("Achievement generation is enabled...")
            self._run_achievement_generation()

        # GreenLuma AppList files (Windows + SLSsteam mode)
        if self.slssteam_mode_was_active:
            if sys.platform == "win32":
                self.logger.info("Windows Wrapper Mode active. Creating GreenLuma AppList files...")
                self._create_greenluma_files()
            elif sys.platform == "linux":
                self.logger.info("SLSsteam mode active on Linux, GreenLuma files skipped")

        self.logger.info("All post-processing steps completed")

    def _create_acf_file(self, size_on_disk):
        """Create Steam ACF manifest file"""
        if not self.game_data or not self.current_dest_path:
            return

        self.logger.info("Generating Steam .acf manifest file...")

        safe_game_name_fallback = (
            re.sub(r"[^\w\s-]", "", self.game_data.get("game_name", ""))
            .strip()
            .replace(" ", "_")
        )
        install_folder_name = self.game_data.get("installdir", safe_game_name_fallback)
        if not install_folder_name:
            install_folder_name = f"App_{self.game_data['appid']}"

        acf_path = os.path.join(
            self.current_dest_path,
            "steamapps",
            f"appmanifest_{self.game_data['appid']}.acf",
        )

        buildid = self.game_data.get("buildid", "0")
        depots_content = ""
        selected_depots = self.game_data.get("selected_depots_list", [])
        all_manifests = self.game_data.get("manifests", {})
        all_depots = self.game_data.get("depots", {})

        # Platform configuration
        platform_config = ""
        empty_platform_config = '\t"UserConfig"\n\t{\n\t}\n\t"MountedConfig"\n\t{\n\t}'

        if sys.platform == "linux":
            downloading_windows_depots = False
            downloading_linux_depots = False

            for depot_id in selected_depots:
                depot_id_str = str(depot_id)
                depot_info = all_depots.get(depot_id_str, {})
                platform = (depot_info.get("oslist") or "").lower() or "unknown"

                if platform == "windows":
                    downloading_windows_depots = True
                elif platform == "linux":
                    downloading_linux_depots = True

            if downloading_windows_depots:
                self.logger.info("Windows depots on Linux - adding Proton configuration")
                platform_config = (
                    '\t"UserConfig"\n'
                    "\t{\n"
                    '\t\t"platform_override_dest"\t\t"linux"\n'
                    '\t\t"platform_override_source"\t\t"windows"\n'
                    "\t}\n"
                    '\t"MountedConfig"\n'
                    "\t{\n"
                    '\t\t"platform_override_dest"\t\t"linux"\n'
                    '\t\t"platform_override_source"\t\t"windows"\n'
                    "\t}"
                )
            elif downloading_linux_depots:
                platform_config = empty_platform_config
            else:
                platform_config = empty_platform_config
        else:
            platform_config = empty_platform_config

        # Build depot content
        if selected_depots and all_manifests:
            for depot_id in selected_depots:
                depot_id_str = str(depot_id)
                manifest_gid = all_manifests.get(depot_id_str)
                depot_info = all_depots.get(depot_id_str, {})
                depot_size = depot_info.get("size", "0")

                if manifest_gid:
                    depots_content += (
                        f'\t\t"{depot_id_str}"\n'
                        f"\t\t{{\n"
                        f'\t\t\t"manifest"\t\t"{manifest_gid}"\n'
                        f'\t\t\t"size"\t\t"{depot_size}"\n'
                        f"\t\t}}\n"
                    )

        installed_depots_str = f'\t"InstalledDepots"\n\t{{\n{depots_content}\t}}' if depots_content else '\t"InstalledDepots"\n\t{\n\t}'

        acf_content = (
            f'"AppState"\n'
            f"{{\n"
            f'\t"appid"\t\t"{self.game_data["appid"]}"\n'
            f'\t"Universe"\t\t"1"\n'
            f'\t"name"\t\t"{self.game_data["game_name"]}"\n'
            f'\t"StateFlags"\t\t"4"\n'
            f'\t"installdir"\t\t"{install_folder_name}"\n'
            f'\t"SizeOnDisk"\t\t"{size_on_disk}"\n'
            f'\t"buildid"\t\t"{buildid}"\n'
            f"{installed_depots_str}"
        )

        if platform_config:
            acf_content += f"\n{platform_config}"

        acf_content += "\n}"

        try:
            with open(acf_path, "w", encoding="utf-8") as f:
                f.write(acf_content)
            self.logger.info(f"Created .acf file at {acf_path}")
        except IOError as e:
            self.logger.error(f"Error creating .acf file: {e}")

    def _write_app_token(self, dest_path):
        """Write app token to file for non-SLSsteam mode"""
        if self.slssteam_mode_was_active:
            return

        if not self.game_data:
            return

        app_token = self.game_data.get("app_token")
        if not app_token:
            return

        safe_game_name_fallback = (
            re.sub(r"[^\w\s-]", "", self.game_data.get("game_name", ""))
            .strip()
            .replace(" ", "_")
        )
        install_folder_name = self.game_data.get("installdir") or safe_game_name_fallback
        if not install_folder_name:
            install_folder_name = f"App_{self.game_data['appid']}"

        game_dir = os.path.join(dest_path, "steamapps", "common", install_folder_name)
        token_file = os.path.join(game_dir, "apptoken.txt")

        try:
            os.makedirs(game_dir, exist_ok=True)
            with open(token_file, 'w') as f:
                f.write(app_token)
            self.logger.info(f"Wrote app token to {token_file}")
        except Exception as e:
            self.logger.error(f"Failed to write app token to file: {e}")

    def _move_manifests_to_depotcache(self):
        """Move manifests from temp to depotcache"""
        if not self.game_data or not self.current_dest_path:
            return

        import tempfile

        temp_manifest_dir = os.path.join(tempfile.gettempdir(), "mistwalker_manifests")
        if not os.path.exists(temp_manifest_dir):
            return

        target_depotcache_dir = os.path.join(self.current_dest_path, "depotcache")

        try:
            os.makedirs(target_depotcache_dir, exist_ok=True)
            manifests_map = self.game_data.get("manifests", {})

            if not manifests_map:
                shutil.rmtree(temp_manifest_dir)
                return

            moved_count = 0
            for depot_id, manifest_gid in manifests_map.items():
                manifest_filename = f"{depot_id}_{manifest_gid}.manifest"
                source_path = os.path.join(temp_manifest_dir, manifest_filename)
                dest = os.path.join(target_depotcache_dir, manifest_filename)
                if os.path.exists(source_path):
                    shutil.move(source_path, dest)
                    moved_count += 1

            self.logger.info(f"Moved {moved_count} manifest files to depotcache.")
            shutil.rmtree(temp_manifest_dir)
        except Exception as e:
            self.logger.error(f"Failed to move manifests to depotcache: {e}")

    def _save_main_depot_info(self):
        """Save main depot ID and manifest to persistent file"""
        from pathlib import Path
        from utils.helpers import get_base_path

        if not self.game_data:
            return

        appid = self.game_data.get("appid")
        if not appid:
            return

        selected_depots = self.game_data.get("selected_depots_list", [])
        all_manifests = self.game_data.get("manifests", {})

        if not selected_depots or not all_manifests:
            return

        main_depot_id = str(selected_depots[0])
        manifest_id = all_manifests.get(main_depot_id)
        if not manifest_id:
            return

        try:
            depots_dir = Path(get_base_path()) / "depots"
            depots_dir.mkdir(parents=True, exist_ok=True)

            depot_file = depots_dir / f"{appid}.depot"
            with open(depot_file, "w") as f:
                f.write(f"{main_depot_id}: {manifest_id}\n")

            self.logger.info(f"Saved main depot info: {appid}:{manifest_id}")
        except Exception as e:
            self.logger.error(f"Failed to save depot info: {e}")

    def _set_linux_binary_permissions(self):
        """Set executable permissions for Linux binaries"""
        if not self.game_data or not self.current_dest_path:
            return

        safe_game_name_fallback = (
            re.sub(r"[^\w\s-]", "", self.game_data.get("game_name", ""))
            .strip()
            .replace(" ", "_")
        )
        install_folder_name = self.game_data.get("installdir", safe_game_name_fallback)
        if not install_folder_name:
            install_folder_name = f"App_{self.game_data['appid']}"

        game_directory = os.path.join(
            self.current_dest_path, "steamapps", "common", install_folder_name
        )

        if not os.path.exists(game_directory):
            return

    def _apply_goldberg(self, game_directory: str, appid: str, game_name: str) -> bool:
        """Apply Goldberg files to a game directory (CLI mode)."""
        self.logger.info(
            f"Applying Goldberg for game: {game_name} (AppID: {appid}) in {game_directory}"
        )

        if not game_directory or not os.path.exists(game_directory):
            self.logger.warning(f"Game directory not found: {game_directory}")
            return False

        # Find directories containing steam_api DLLs
        found_dirs = set()
        for root, _, files in os.walk(game_directory):
            for fname in files:
                if fname.lower() in ("steam_api.dll", "steam_api64.dll"):
                    found_dirs.add(root)

        if not found_dirs:
            self.logger.info("No steam_api DLLs found in game directory tree")
            return False

        # Source Goldberg directory in bundled deps
        goldberg_src = Paths.deps("Goldberg")
        if not goldberg_src.exists():
            self.logger.error(f"Goldberg source not found: {goldberg_src}")
            return False

        processed = 0
        try:
            for dest_dir in found_dirs:
                # Track which DLLs existed originally in this folder
                original_dlls_in_dir = set()
                for base in ("steam_api.dll", "steam_api64.dll"):
                    if os.path.exists(os.path.join(dest_dir, base)):
                        original_dlls_in_dir.add(base)

                # Rename DLLs if present
                for base in ("steam_api.dll", "steam_api64.dll"):
                    src_path = os.path.join(dest_dir, base)
                    if os.path.exists(src_path):
                        try:
                            target_path = src_path + ".valve"
                            if not os.path.exists(target_path):
                                os.replace(src_path, target_path)
                                self.logger.info(
                                    f"Renamed {src_path} -> {target_path}"
                                )
                            else:
                                self.logger.info(
                                    f"Target already exists, skipping rename: {target_path}"
                                )
                        except Exception as e:
                            self.logger.warning(f"Failed to rename {src_path}: {e}")

                # Copy only the matching Goldberg DLL(s)
                for base in original_dlls_in_dir:
                    src_dll = goldberg_src / base
                    dest_dll = os.path.join(dest_dir, base)
                    try:
                        if src_dll.exists():
                            shutil.copy2(str(src_dll), dest_dll)
                            self.logger.info(
                                f"Copied Goldberg DLL {src_dll} -> {dest_dll}"
                            )
                        else:
                            self.logger.warning(
                                f"Goldberg DLL not found in deps: {src_dll}"
                            )
                    except Exception as e:
                        self.logger.warning(
                            f"Failed to copy Goldberg DLL {src_dll} to {dest_dll}: {e}"
                        )

                # Copy Goldberg contents into this directory
                for item in goldberg_src.iterdir():
                    if item.name.lower() in (
                        "steam_api.dll",
                        "steam_api64.dll",
                        "steam_appid.txt",
                    ):
                        continue
                    dest_path = os.path.join(dest_dir, item.name)
                    try:
                        if item.is_dir():
                            shutil.copytree(str(item), dest_path, dirs_exist_ok=True)
                            self.logger.info(f"Copied dir {item} -> {dest_path}")
                        else:
                            shutil.copy2(str(item), dest_path)
                            self.logger.info(f"Copied file {item} -> {dest_path}")
                    except Exception as e:
                        self.logger.warning(f"Failed to copy {item} to {dest_path}: {e}")

                # Write steam_appid.txt with provided appid
                try:
                    appid_file = os.path.join(dest_dir, "steam_appid.txt")
                    with open(appid_file, "w", encoding="utf-8") as f:
                        f.write(str(appid))
                    self.logger.info(f"Wrote steam_appid.txt to {appid_file}")
                except Exception as e:
                    self.logger.warning(
                        f"Failed to write steam_appid.txt in {dest_dir}: {e}"
                    )

                processed += 1

            self.logger.info(
                f"Applied Goldberg files to {processed} folder(s)."
            )
            return True

        except Exception as e:
            self.logger.exception(f"Error applying Goldberg: {e}")
            return False

        self.logger.info(f"Setting executable permissions in: {game_directory}")

        linux_binary_extensions = {".sh", ".x86", ".x86_64", ".bin"}
        elf_magic = b"\x7fELF"
        chmod_count = 0

        for root, dirs, files in os.walk(game_directory):
            for file in files:
                file_path = os.path.join(root, file)
                file_lower = file.lower()

                should_chmod = False
                if any(file_lower.endswith(ext) for ext in linux_binary_extensions):
                    should_chmod = True
                elif "." not in file:
                    try:
                        file_size = os.path.getsize(file_path)
                        if file_size >= 1024:
                            with open(file_path, "rb") as f:
                                if f.read(4) == elf_magic:
                                    should_chmod = True
                    except (IOError, OSError):
                        continue

                if should_chmod:
                    try:
                        current_mode = os.stat(file_path).st_mode
                        if not (current_mode & 0o111):
                            os.chmod(file_path, current_mode | 0o755)
                            chmod_count += 1
                    except OSError:
                        pass

        if chmod_count > 0:
            self.logger.info(f"Set executable permissions for {chmod_count} Linux binaries")

    def _add_appids_to_slssteam_config(self):
        """Add downloaded AppIDs to SLSsteam config.yaml on Linux"""
        from utils.yaml_config_manager import (
            get_user_config_path,
            add_additional_app,
            add_dlc_data,
        )

        if not self.game_data:
            return

        try:
            config_path = get_user_config_path()
            if not config_path.exists():
                return

            main_appid = self.game_data.get("appid")
            game_name = self.game_data.get("game_name", "")
            if main_appid:
                add_additional_app(config_path, str(main_appid), game_name)
                self.logger.info(f"Added AppID '{main_appid}' to SLSsteam config")

            selected_dlcs: list = self.game_data.get("selected_dlcs", [])  # type: ignore
            dlcs: dict = self.game_data.get("dlcs", {})  # type: ignore

            if main_appid and selected_dlcs and len(selected_dlcs) > 64:
                for dlc_id in selected_dlcs:
                    dlc_name = dlcs.get(dlc_id, "")
                    add_dlc_data(config_path, str(main_appid), str(dlc_id), dlc_name)

            self.logger.info("AppIDs added to SLSsteam config")
        except Exception as e:
            self.logger.warning(f"Failed to add AppIDs to SLSsteam config: {e}")

    def _run_steamless(self):
        """Run Steamless DRM removal"""
        if not self.current_dest_path or not self.game_data:
            return

        safe_game_name_fallback = (
            re.sub(r"[^\w\s-]", "", self.game_data.get("game_name", ""))
            .strip()
            .replace(" ", "_")
        )
        install_folder_name = self.game_data.get("installdir", safe_game_name_fallback)
        if not install_folder_name:
            install_folder_name = f"App_{self.game_data['appid']}"

        game_directory = os.path.join(
            self.current_dest_path, "steamapps", "common", install_folder_name
        )

        if not os.path.exists(game_directory):
            return

        from core.tasks.steamless_task import SteamlessTask

        self.logger.info("Starting Steamless DRM Removal...")
        self.logger.info(f"Processing directory: {game_directory}")

        steamless_task = SteamlessTask()
        steamless_task.progress.connect(self.logger.info)

        loop = QEventLoop()
        steamless_task.result.connect(lambda success: loop.quit())
        steamless_task.finished.connect(loop.quit)
        steamless_task.set_game_directory(game_directory)
        steamless_task.start()
        loop.exec()

        self.logger.info("Steamless processing completed")

    def _run_application_shortcuts(self):
        """Create application shortcuts"""
        if not self.game_data:
            return

        # Only available on Linux with SLSsteam mode enabled
        if sys.platform != "linux":
            self.logger.info("Application shortcuts are only supported on Linux")
            return

        from utils.yaml_config_manager import is_slssteam_mode_enabled
        if not is_slssteam_mode_enabled():
            self.logger.info("SLSsteam mode is disabled, skipping shortcuts creation")
            return

        app_id = self.game_data.get("appid")
        game_name = self.game_data.get("game_name")
        if not app_id:
            return

        sgdb_api_key = self.settings.value("sgdb_api_key", "", type=str)
        if not sgdb_api_key:
            return

        try:
            from core.tasks.application_shortcuts import ApplicationShortcutsTask
        except ImportError:
            self.logger.error("ApplicationShortcutsTask module not found")
            return

        self.logger.info("Creating application shortcuts...")

        shortcuts_task = ApplicationShortcutsTask()
        shortcuts_task.set_api_key(sgdb_api_key)
        shortcuts_task.progress.connect(self.logger.info)

        loop = QEventLoop()
        shortcuts_task.completed.connect(loop.quit)
        TaskRunner().run(shortcuts_task.run, app_id, game_name)
        loop.exec()

        self.logger.info("Application shortcuts created")

    def _run_achievement_generation(self):
        """Generate achievements using SLScheevo"""
        if not self.game_data:
            return

        app_id = self.game_data.get("appid")
        if not app_id:
            return

        from core.tasks.generate_achievements_task import GenerateAchievementsTask

        self.logger.info("Generating achievements...")

        achievement_task = GenerateAchievementsTask()
        achievement_task.progress.connect(self.logger.info)

        loop = QEventLoop()

        def on_achievement_complete(result):
            if result and result.get("success"):
                self.logger.info(f"Achievement generation completed: {result.get('message')}")
            else:
                self.logger.info(f"Achievement generation failed: {result.get('message') if result else 'Unknown error'}")
            loop.quit()

        achievement_runner = TaskRunner()
        achievement_runner.run(achievement_task.run, app_id).finished.connect(
            lambda r: on_achievement_complete(r)
        )
        loop.exec()

    def _create_greenluma_files(self):
        """Create GreenLuma AppList files on Windows"""
        if not self.game_data:
            return

        from core import steam_helpers
        from utils.yaml_config_manager import is_slssteam_config_management_enabled

        try:
            # Check if config management is enabled
            if not is_slssteam_config_management_enabled():
                self.logger.debug("GreenLuma config management is disabled, skipping AppList file creation")
                return

            steam_path = steam_helpers.find_steam_install()
            if not steam_path:
                self.logger.error("Could not find Steam path. Skipping GreenLuma file creation.")
                return

            app_list_dir = os.path.join(steam_path, "AppList")
            if not os.path.exists(app_list_dir):
                os.makedirs(app_list_dir)
                self.logger.info(f"Created AppList directory at: {app_list_dir}")

            game_appid = self.game_data.get("appid")
            if not game_appid:
                return

            # Create main AppList file (with duplicate check)
            if not self._app_id_exists_in_applist(app_list_dir, game_appid):
                next_num = self._find_next_applist_number(app_list_dir, self.logger)
                filepath = os.path.join(app_list_dir, f"{next_num}.txt")
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(str(game_appid))
                self.logger.info(f"Created GreenLuma file: {filepath} for AppID: {game_appid}")
            else:
                self.logger.info(f"AppID {game_appid} already exists in AppList folder. Skipping file creation.")

            # Create DLC AppList files (with duplicate check)
            selected_dlcs: list = self.game_data.get("selected_dlcs", [])  # type: ignore
            for dlc_id in selected_dlcs:
                if not self._app_id_exists_in_applist(app_list_dir, dlc_id):
                    next_num = self._find_next_applist_number(app_list_dir, self.logger)
                    filepath = os.path.join(app_list_dir, f"{next_num}.txt")
                    with open(filepath, "w", encoding="utf-8") as f:
                        f.write(str(dlc_id))
                    self.logger.info(f"Created GreenLuma file: {filepath} for DLC: {dlc_id}")
                else:
                    self.logger.info(f"DLC AppID {dlc_id} already exists in AppList folder. Skipping file creation.")

            # Copy NoQuestion.bin and StealthMode.bin
            source_dir = Paths.deps()
            for filename in ["NoQuestion.bin", "StealthMode.bin"]:
                source_path = os.path.join(source_dir, filename)
                dest_path = os.path.join(steam_path, filename)
                try:
                    if os.path.exists(source_path):
                        if not os.path.exists(dest_path):
                            shutil.copy2(source_path, dest_path)
                            self.logger.info(f"Copied {filename} to Steam folder")
                        else:
                            self.logger.info(f"{filename} already exists in Steam folder, skipping")
                    else:
                        self.logger.warning(f"Source {filename} not found in deps folder")
                except Exception as e:
                    self.logger.error(f"Failed to copy {filename}: {e}")

        except Exception as e:
            self.logger.error(f"Failed to create GreenLuma files: {e}", exc_info=True)

    @staticmethod
    def _find_next_applist_number(app_list_dir, logger=None):
        """Find the next available AppList number"""
        if not os.path.exists(app_list_dir):
            os.makedirs(app_list_dir)
            return 1

        max_num = 0
        try:
            for filename in os.listdir(app_list_dir):
                match = re.match(r"^(\d+)\.txt$", filename)
                if match:
                    num = int(match.group(1))
                    if num > max_num:
                        max_num = num
        except Exception as e:
            if logger:
                logger.error(f"Error scanning AppList directory: {e}")

        return max_num + 1

    @staticmethod
    def _app_id_exists_in_applist(app_list_dir, app_id_to_check):
        """Check if AppID already exists in AppList"""
        if not os.path.exists(app_list_dir):
            return False

        try:
            for filename in os.listdir(app_list_dir):
                if filename.lower().endswith(".txt"):
                    filepath = os.path.join(app_list_dir, filename)
                    try:
                        with open(filepath, "r", encoding="utf-8") as f:
                            content = f.read().strip()
                            if content == app_id_to_check:
                                return True
                    except Exception:
                        pass
        except Exception as e:
            # Can't use self.logger in static method
            pass

        return False
