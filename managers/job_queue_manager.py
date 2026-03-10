import os
import sys
import logging
import time
from PyQt6.QtWidgets import QMessageBox, QFileDialog

from core import steam_helpers

logger = logging.getLogger(__name__)


class JobQueueManager:
    def __init__(self, main_window):
        self.main_window = main_window
        self.job_queue = []  # List of dicts: {"path": file_path, "metadata": {...}}
        self.jobs_completed_count = 0
        self.slssteam_prompt_pending = False
        self.is_showing_completion_dialog = False

    def add_job(self, file_path, metadata=None):
        """Add a job to the queue

        Args:
            file_path: Path to the manifest file
            metadata: Optional dict with job metadata (appid, library_path, install_path)
        """
        if not os.path.exists(file_path):
            logger.error(f"Failed to add job: file {file_path} does not exist.")
            QMessageBox.critical(
                self.main_window, "Error", f"Could not add job: File not found at {file_path}"
            )
            return

        job = {"path": file_path, "metadata": metadata or {}}
        self.job_queue.append(job)
        logger.info(f"Added new job to queue: {os.path.basename(file_path)}")

        self._update_ui_state()

        if not self.main_window.task_manager.is_processing:
            logger.info("Not processing, starting new job from queue.")
            self.main_window.log_output.clear()
            self._start_next_job()
        else:
            logger.info("App is busy, job added to queue.")

    def move_item_up(self):
        """Move selected queue item up"""
        current_row = self.main_window.ui_state.queue_list_widget.currentRow()
        if current_row > 0:
            item = self.job_queue.pop(current_row)
            self.job_queue.insert(current_row - 1, item)
            self._update_queue_display()
            self.main_window.ui_state.queue_list_widget.setCurrentRow(current_row - 1)

    def move_item_down(self):
        """Move selected queue item down"""
        current_row = self.main_window.ui_state.queue_list_widget.currentRow()
        if current_row != -1 and current_row < len(self.job_queue) - 1:
            item = self.job_queue.pop(current_row)
            self.job_queue.insert(current_row + 1, item)
            self._update_queue_display()
            self.main_window.ui_state.queue_list_widget.setCurrentRow(current_row + 1)

    def remove_item(self):
        """Remove selected queue item"""
        current_row = self.main_window.ui_state.queue_list_widget.currentRow()
        if current_row == -1:
            logger.debug("Remove item clicked, but no item is selected.")
            return

        try:
            removed_job = self.job_queue.pop(current_row)
            logger.info(f"Removed job from queue: {os.path.basename(removed_job['path'])}")
            self._update_queue_display()

            if current_row < self.main_window.ui_state.queue_list_widget.count():
                self.main_window.ui_state.queue_list_widget.setCurrentRow(current_row)
            elif self.main_window.ui_state.queue_list_widget.count() > 0:
                self.main_window.ui_state.queue_list_widget.setCurrentRow(current_row - 1)

        except Exception as e:
            logger.error(f"Error removing queue item: {e}", exc_info=True)

    def _start_next_job(self):
        """Start the next job in queue"""
        self._update_ui_state()

        if not self.job_queue:
            self._handle_queue_completion()
            return

        next_job = self.job_queue[0]
        file_path = next_job["path"]
        metadata = next_job.get("metadata", {})
        self.main_window.task_manager.start_zip_processing(file_path, metadata)
        self.job_queue.pop(0)
        self._update_ui_state()

    def _handle_queue_completion(self):
        """Handle when queue is empty"""
        if self.is_showing_completion_dialog:
            return

        self.is_showing_completion_dialog = True
        try:
            was_pending = self.slssteam_prompt_pending
            self.slssteam_prompt_pending = False

            if was_pending:
                from utils.settings import get_settings
                settings = get_settings()
                prompt_steam_restart = settings.value("prompt_steam_restart", True, type=bool)

                if prompt_steam_restart:
                    self._prompt_for_steam_restart()
                else:
                    logger.info("Steam restart prompt disabled by settings. Skipping prompt.")
            elif self.jobs_completed_count > 0:
                QMessageBox.information(
                    self.main_window,
                    "Queue Finished",
                    f"All {self.jobs_completed_count} job(s) have finished successfully!",
                )

            self.jobs_completed_count = 0
        finally:
            self.is_showing_completion_dialog = False

    def _update_ui_state(self):
        """Update UI based on queue state"""
        has_jobs = len(self.job_queue) > 0
        is_processing = self.main_window.task_manager.is_processing

        self.main_window.ui_state.update_queue_visibility(is_processing, has_jobs)
        self._update_queue_display()

    def _update_queue_display(self):
        """Update the queue list widget"""
        self.main_window.ui_state.queue_list_widget.clear()
        self.main_window.ui_state.queue_list_widget.addItems(
            [os.path.basename(job["path"]) for job in self.job_queue]
        )

    def _check_if_safe_to_start_next_job(self):
        """Check if it's safe to start the next job"""
        if (not self.main_window.task_manager.is_processing and
            not self.main_window.task_manager.is_awaiting_zip_task_stop and
            not self.main_window.task_manager.is_awaiting_speed_monitor_stop and
            not self.main_window.task_manager.is_awaiting_download_stop and
            not self.main_window.task_manager.achievement_task_runner):  # Also wait for achievement cleanup

            logger.debug("All thread cleanup flags are clear. Safe to start next job.")
            self._start_next_job()
        else:
            logger.debug(
                f"Not starting next job yet. State: "
                f"is_processing={self.main_window.task_manager.is_processing}, "
                f"awaiting_zip={self.main_window.task_manager.is_awaiting_zip_task_stop}, "
                f"awaiting_speed={self.main_window.task_manager.is_awaiting_speed_monitor_stop}, "
                f"awaiting_download={self.main_window.task_manager.is_awaiting_download_stop}, "
                f"achievement_runner={self.main_window.task_manager.achievement_task_runner is not None}"
            )

    def _prompt_for_steam_restart(self):
        """Prompt user to restart Steam with complete restart logic"""
        title = "GreenLuma Integration" if sys.platform == "win32" else "SLSsteam Integration"
        reply = QMessageBox.question(
            self.main_window,
            title,
            "Wrapper files have been created. Would you like to restart Steam now to apply the changes?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            logger.info("User agreed to restart Steam.")

            if sys.platform == "linux":
                # First, kill Steam if it's running
                logger.info("Attempting to kill Steam process...")
                steam_helpers.kill_steam_process()

                time.sleep(1)

                # Try to start Steam with the helper function
                result = steam_helpers.start_steam()

                if result == "NEEDS_USER_PATH":
                    # Prompt user for both library files
                    logger.warning("SLSsteam libraries not found. Please locate them manually.")

                    # First library: SLSsteam.so
                    filePath1, _ = QFileDialog.getOpenFileName(
                        self.main_window,
                        "Select SLSsteam.so",
                        os.path.expanduser("~"),
                        "SLSsteam.so (SLSsteam.so libSLSsteam.so)"
                    )

                    if not filePath1:
                        logger.info("User cancelled file selection for SLSsteam.so")
                        return

                    # Second library: library-inject.so (could be libSLS-library-inject.so)
                    filePath2, _ = QFileDialog.getOpenFileName(
                        self.main_window,
                        "Select library-inject.so",
                        os.path.expanduser("~"),
                        "library-inject.so (library-inject.so libSLS-library-inject.so)"
                    )

                    if not filePath2:
                        logger.info("User cancelled file selection for library-inject.so")
                        return

                    # Try to start Steam with both libraries
                    result = steam_helpers.start_steam_with_slssteam(filePath1, filePath2)
                    if result == "SUCCESS":
                        logger.info("Started Steam with SLSsteam.so and library-inject.so")
                    elif result == "NEEDS_USER_PATH":
                        # This shouldn't happen since we just provided paths, but handle it
                        QMessageBox.warning(
                            self.main_window,
                            "Execution Failed",
                            "One or both of the selected library files are invalid or don't exist."
                        )
                    else:
                        QMessageBox.warning(
                            self.main_window,
                            "Execution Failed",
                            "Could not start Steam with the selected libraries."
                        )
                elif result == "SUCCESS":
                    logger.info("Steam started successfully with cached libraries.")
                else:
                    logger.warning("Failed to start Steam.")
                    QMessageBox.warning(
                        self.main_window,
                        "Execution Failed",
                        "Could not start Steam."
                    )

            else:
                # Windows platform
                steam_path = steam_helpers.find_steam_install()
                if steam_path:
                    logger.info("Closing Steam...")
                    if not steam_helpers.kill_steam_process():
                        logger.info(
                            "Steam process was not running or could not be killed."
                        )

                    time.sleep(1)

                    # Check for DLLInjector.exe first
                    injector_path = os.path.join(steam_path, "DLLInjector.exe")
                    if os.path.exists(injector_path):
                        logger.info("Windows Wrapper Mode: Launching DLLInjector.exe...")
                        if not steam_helpers.run_dll_injector(steam_path):
                            QMessageBox.warning(
                                self.main_window,
                                "Injector Failed",
                                f"Could not launch DLLInjector.exe from {steam_path}.",
                            )
                    else:
                        # Check for user32.dll as fallback
                        user32_path = os.path.join(steam_path, "user32.dll")
                        if os.path.exists(user32_path):
                            logger.info("DLLInjector.exe not found, but user32.dll exists. Starting Steam normally...")
                            steam_helpers.start_steam()  # GreenLuma will load via DLL
                        else:
                            QMessageBox.warning(
                                self.main_window,
                                "Injector Not Found",
                                "DLLInjector.exe not found in Steam folder. GreenLuma may not work correctly.",
                            )
                else:
                    QMessageBox.warning(
                        self.main_window,
                        "Error",
                        "Could not find Steam installation path.",
                    )

    def clear(self):
        """Clear the job queue"""
        self.job_queue.clear()
        self._update_ui_state()
