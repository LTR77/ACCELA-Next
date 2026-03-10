import multiprocessing
import os
import sys
from urllib.parse import unquote

if sys.platform == "win32":
    try:
        import ctypes

        myappid = "god.is.in.the.wired.accela"
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
    except ImportError:
        pass


from PyQt6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer
from ui.main_window import MainWindow
from ui.theme import update_appearance

from managers.cli_manager import run_cli_mode, open_cli_terminal

from utils.logger import setup_logging
from utils.settings import get_settings
from utils.yaml_config_manager import (
    backup_config_on_startup,
    ensure_slssteam_api_enabled,
    get_user_config_path,
)

project_root = os.path.abspath(os.path.dirname(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

try:
    pass
except ImportError:
    pass

def main():
    logger = setup_logging()
    from utils.version import app_version

    logger.info("========================================")
    logger.info(f"ACCELA {app_version} starting...")
    logger.info("========================================")

    # People only have substance within the memories of other people.

    app = QApplication(sys.argv)

    # Parse command-line arguments
    cli_mode = False
    command_line_zips = []
    command_line_appid = None

    # Parse args as list so we can skip the appid value
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ('-cli', '--cli'):
            cli_mode = True
        elif arg == '--appid' and i + 1 < len(args):
            # Next argument is the appid (GUI mode only, requires -cli for CLI mode)
            appid_str = args[i + 1]
            if appid_str.isdigit():
                command_line_appid = int(appid_str)
            else:
                logger.error(f"Invalid AppID: {appid_str} (must be a number)")
            i += 1  # Skip the appid value
        elif arg.startswith('accela://'):
            # Handle custom URL scheme
            # Format: accela://download/730 (GUI) or accela://cli/download/730 (CLI)
            try:
                # Parse URL manually to handle paths correctly
                # accela://cli/download/730 -> cli, download, 730
                # accela://zip//home/user/file.zip -> zip, /home/user/file.zip
                url_content = arg[9:]  # Remove 'accela://'

                # Check for cli prefix first
                if url_content.startswith('cli/'):
                    cli_mode = True
                    rest = url_content[4:]  # Remove 'cli/'
                else:
                    rest = url_content

                # Split action and param
                if '/' in rest:
                    action, param = rest.split('/', 1)
                    param = unquote(param)
                else:
                    action = rest
                    param = None

                if cli_mode:
                    if action == 'download' and param and param.isdigit():
                        command_line_appid = int(param)
                        logger.info(f"Found accela://cli/download URL for AppID: {param}")
                    elif action == 'zip' and param:
                        if os.path.exists(param):
                            command_line_zips.append(param)
                            logger.info(f"Found ZIP file from URL: {param}")
                        else:
                            logger.warning(f"ZIP file not found from URL: {param}")
                    else:
                        logger.warning(f"Invalid accela://cli URL format: {arg}")
                else:
                    # GUI mode
                    if action == 'download' and param and param.isdigit():
                        command_line_appid = int(param)
                        logger.info(f"Found accela://download URL for AppID: {param} (GUI mode)")
                    elif action == 'zip' and param:
                        if os.path.exists(param):
                            command_line_zips.append(param)
                            logger.info(f"Found ZIP file from URL: {param} (GUI mode)")
                        else:
                            logger.warning(f"ZIP file not found from URL: {param}")
                    else:
                        logger.warning(f"Invalid accela:// URL format: {arg}")
            except Exception as e:
                logger.error(f"Failed to parse URL {arg}: {e}")
        elif arg.lower().endswith('.zip'):
            # Normalize path to handle relative paths correctly
            zip_path = os.path.abspath(arg)
            if os.path.exists(zip_path):
                command_line_zips.append(zip_path)
                logger.info(f"Found ZIP file from command line: {zip_path}")
            else:
                logger.warning(f"ZIP file not found: {arg}")
        i += 1  # Move to next argument

    # AppID and ZIP files are mutually exclusive
    if command_line_appid and command_line_zips:
        logger.error("Cannot use --appid and .zip files together. Choose one.")
        return

    # CLI mode: activated by -cli flag OR by --appid OR by accela://cli/ URL
    if cli_mode and (command_line_zips or command_line_appid):
        # Check if we should open in external terminal (accela://cli/ URLs)
        if cli_mode and sys.platform == 'linux':
            if command_line_appid:
                logger.info(f"Opening CLI mode in external terminal for AppID {command_line_appid}")
                if open_cli_terminal(appid=command_line_appid):
                    logger.info("Terminal opened successfully")
                    return
            elif command_line_zips:
                logger.info(f"Opening CLI mode in external terminal for {len(command_line_zips)} ZIP(s)")
                if open_cli_terminal(zip_path=command_line_zips[0]):
                    logger.info("Terminal opened successfully")
                    return

        # Fallback to internal CLI mode (when terminal couldn't be opened)
        if command_line_appid:
            logger.info(f"Will process AppID {command_line_appid} from Morrenus API in CLI mode")
            return run_cli_mode(app, None, logger, appid=command_line_appid)
        else:
            logger.info(f"Will process {len(command_line_zips)} ZIP file(s) from command line in CLI mode")
            logger.info("Entering CLI mode - skipping main window")
            return run_cli_mode(app, command_line_zips, logger)

    # Backup SLSsteam config on startup
    config_path = get_user_config_path()
    backup_created = backup_config_on_startup(config_path)
    if backup_created:
        logger.info("SLSsteam config backup created at startup")

    # Ensure SLSsteam API is enabled (only if config exists)
    if config_path.exists():
        if ensure_slssteam_api_enabled(config_path):
            logger.info("SLSsteam API enabled in config")

    # Load settings
    settings = get_settings()
    accent_color = settings.value("accent_color", "#C06C84")
    bg_color = settings.value("background_color", "#000000")

    # Check for UI mode (e.g., Sonic) which may override colors/font
    ui_mode = settings.value("ui_mode", "default")
    font_file = None
    initial_font = None

    if ui_mode == "sonic":
        # Sonic palette: blue background, yellow accent
        accent_color = "#ffcc00"
        bg_color = "#002c83"
        font_file = settings.value("font-file", "sonic/sonic-1-hud-font.otf")
        initial_font = QFont()
    else:
        # Load user's font settings
        font_family = settings.value("font", "TrixieCyrG-Plain")
        font_size = settings.value("font-size", 10, type=int)
        font_style = settings.value("font-style", "Normal")
        
        initial_font = QFont(font_family)
        initial_font.setPointSize(font_size)
        if font_style == "Italic":
            initial_font.setItalic(True)
        elif font_style == "Bold":
            initial_font.setBold(True)
        elif font_style == "Bold Italic":
            initial_font.setBold(True)
            initial_font.setItalic(True)

    # Fix offline mode in loginusers.vdf if GreenLuma is enabled
    from core.steam_helpers import fix_greenluma_offline_mode
    fix_greenluma_offline_mode()

    # Apply palette + font
    font_ok, font_info = update_appearance(app, accent_color, bg_color, font=initial_font, font_file=font_file)

    if font_ok:
        logger.info(f"Successfully loaded and applied custom font: '{str(font_info)}'")
    else:
        logger.warning(f"Failed to load custom font from: '{str(font_info)}'")

    try:
        main_win = MainWindow()
        main_win.show()
        logger.info("Main window displayed successfully.")

        # Process command-line ZIP files after window is fully initialized
        if command_line_zips or command_line_appid:
            def process_command_line_args():
                """Add command-line ZIP files/AppID to queue after window initialization completes"""
                from core.morrenus_api import download_manifest

                if command_line_appid:
                    logger.info(f"Downloading manifest for AppID {command_line_appid} from Morrenus API")
                    zip_path, error = download_manifest(command_line_appid)
                    if error:
                        logger.error(f"Failed to download manifest: {error}")
                        return
                    logger.info(f"Adding to queue: AppID {command_line_appid}")
                    main_win.job_queue.add_job(zip_path)
                else:
                    logger.info(f"Adding {len(command_line_zips)} ZIP file(s) from command line to queue")
                    for zip_path in command_line_zips:
                        logger.info(f"Adding to queue: {os.path.basename(zip_path)}")
                        main_win.job_queue.add_job(zip_path)

            # Use singleShot to defer until after window initialization
            QTimer.singleShot(0, process_command_line_args)

        sys.exit(app.exec())
    except Exception as e:
        logger.critical(
            f"A critical error occurred, and the application must close. Error: {e}",
            exc_info=True,
        )
        sys.exit(1)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
