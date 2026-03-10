import logging
import os
import platform
import re
import subprocess
import sys
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal

from utils.helpers import get_venv_python, _get_slscheevo_path, _get_slscheevo_save_path#, _ensure_template_file, resource_path, get_base_path, is_running_in_pyinstaller

logger = logging.getLogger(__name__)


class GenerateAchievementsTask(QObject):
    """Generate Steam achievement stats using SLScheevo wrapper"""

    progress = pyqtSignal(str)
    progress_percentage = pyqtSignal(int)
    completed = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._is_running = True
        self.process = None
        self.process_pid = None

        # Path to SLScheevo executable
        self.slscheevo_path = _get_slscheevo_path()

    def run(self, app_ids=None):
        """Run SLScheevo to generate achievement stats"""
        logger.info("Starting achievement generation task")
        self.progress.emit("Checking SLScheevo script...")

        try:
            # Check if SLScheevo executable exists
            if not self.slscheevo_path.exists():
                error_msg = (
                    f"SLScheevo executable not found at {self.slscheevo_path}. "
                    "Please ensure it's properly installed in src/deps/SLScheevo/"
                )
                self.progress.emit(f"{error_msg}")
                self.error.emit(error_msg)
                result = {
                    "success": False,
                    "return_code": -1,
                    "message": "SLScheevo executable not found",
                }
                self.completed.emit(result)
                return result

            self.progress.emit("SLScheevo executable found")
            logger.info(f"SLScheevo executable found at: {self.slscheevo_path}")

            save_dir = _get_slscheevo_save_path()

            logger.info(f"SLScheevo save directory: {save_dir}")

            # Prepare command
            # If using Python script, add python executable before the script path
            if str(self.slscheevo_path).endswith(".py"):
                # Check if we're in AppImage mode (has bundled venv)
                venv_python = get_venv_python()
                if venv_python:
                    command = [venv_python, str(self.slscheevo_path)]
                else:
                    command = ["python3", str(self.slscheevo_path)]
            else:
                command = [str(self.slscheevo_path)]

            # Add save directory
            # --silent makes SLScheevo automatically use the last saved account
            command.extend(["--noclear", "--save-dir", str(save_dir), "--silent", "--max-tries", "101"])

            # Add app IDs if provided
            if app_ids:
                if isinstance(app_ids, list):
                    app_ids_str = ",".join(str(app_id) for app_id in app_ids)
                else:
                    app_ids_str = str(app_ids)
                command.extend(["--appid", app_ids_str])

            logger.info(f"Executing command: {command}")

            self.progress.emit("Starting achievement generation...")
            self.progress.emit(f"Using SLScheevo: {self.slscheevo_path}")
            self.progress.emit(f"Save directory: {save_dir}")
            if app_ids:
                self.progress.emit(f"Target app IDs: {app_ids}")
            self.progress.emit("Using last saved account")

            # Start process with unbuffered output
            self.process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                cwd=self.slscheevo_path.parent,
                bufsize=1,  # Line buffered
                creationflags=subprocess.CREATE_NO_WINDOW
                if sys.platform == "win32"
                else 0,
            )

            self.process_pid = self.process.pid

            # Read output line by line (simpler approach without QThread)
            while True:
                if not self._is_running:
                    self.process.terminate()
                    break

                if self.process is None or self.process.stdout is None:
                    break

                line = self.process.stdout.readline()
                if not line:
                    # Check if process has ended
                    return_code = self.process.poll()
                    if return_code is not None:
                        break
                    continue

                line = line.rstrip()
                self._handle_output(line)

                # Check for timeout (simple check)
                if line.startswith("Progress:"):
                    # Could implement more sophisticated timeout handling here
                    pass

            # Wait for process to complete
            return_code = self.process.wait()

            self.process = None
            self.process_pid = None

            # Emit completion signal and return result
            # Exit code 0 = success with achievements generated
            # Exit code 10 = success but no achievements needed (all already exist)
            if return_code == 0:
                self.progress.emit("Achievement generation completed successfully")
                result = {
                    "success": True,
                    "return_code": return_code,
                    "message": "Generation completed",
                }
                self.completed.emit(result)
            elif return_code == 10:
                self.progress.emit("All achievement stats already exist - no generation needed")
                result = {
                    "success": True,
                    "return_code": return_code,
                    "message": "No missing stats files to generate",
                }
                self.completed.emit(result)
            else:
                error_msg = f"SLScheevo exited with code {return_code}"
                self.progress.emit(f"{error_msg}")
                self.error.emit(error_msg)
                result = {
                    "success": False,
                    "return_code": return_code,
                    "message": error_msg,
                }
                self.completed.emit(result)

            return result

        except subprocess.TimeoutExpired:
            error_msg = "SLScheevo timed out after 30 seconds"
            self.progress.emit(f"{error_msg}")
            if self.process:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
            result = {"success": False, "return_code": -1, "message": error_msg}
            self.completed.emit(result)
            return result
        except FileNotFoundError:
            error_msg = (
                "Python interpreter not found. Make sure Python is properly installed."
            )
            self.progress.emit(f"{error_msg}")
            logger.error(error_msg, exc_info=True)
            self.error.emit(error_msg)
            result = {"success": False, "return_code": -1, "message": error_msg}
            self.completed.emit(result)
            return result
        except Exception as e:
            error_msg = f"Unexpected error during achievement generation: {e}"
            self.progress.emit(f"{error_msg}")
            logger.error(error_msg, exc_info=True)
            if self.process:
                self.process.terminate()
            self.process = None
            self.process_pid = None
            self.error.emit(error_msg)
            result = {"success": False, "return_code": -1, "message": error_msg}
            self.completed.emit(result)
            return result

    def _handle_output(self, line):
        """Handle output from SLScheevo process"""
        if not self._is_running:
            return

        # Emit the line for UI display
        self.progress.emit(line)

        # Try to extract percentage from progress lines
        # SLScheevo outputs progress in format like: "[→] Progress: 5/20"
        progress_match = re.search(r"\[→\]\s*Progress:\s*(\d+)/(\d+)", line)
        if progress_match:
            current = int(progress_match.group(1))
            total = int(progress_match.group(2))
            if total > 0:
                percentage = int((current / total) * 100)
                self.progress_percentage.emit(percentage)

    def stop(self):
        """Stop the task and terminate the process"""
        logger.debug("Stop signal received by achievement generation task")

        self._is_running = False

        if self.process_pid:
            try:
                import psutil

                parent = psutil.Process(self.process_pid)
                children = parent.children(recursive=True)
                processes = [parent] + children

                for proc in processes:
                    try:
                        proc.terminate()
                    except psutil.NoSuchProcess:
                        pass

                # Wait for processes to terminate gracefully
                gone, alive = psutil.wait_procs(processes, timeout=3)
                for p in alive:
                    p.kill()  # Force kill if still alive
            except ImportError:
                # psutil not available, try direct termination
                if self.process:
                    try:
                        self.process.terminate()
                        self.process.wait(timeout=3)
                    except (subprocess.TimeoutExpired, ProcessLookupError, OSError):
                        pass
            except Exception as e:
                logger.error(f"Error stopping process: {e}")

        self.process = None
        self.process_pid = None
