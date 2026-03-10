import os
import logging
from pathlib import Path
from PIL import Image
import numpy as np
import time
import concurrent.futures
import shutil
import hashlib
import json
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QProgressBar, QLabel, QPushButton, QApplication
from PyQt6.QtCore import Qt, QTimer, QObject, pyqtSignal

from utils.helpers import get_base_path
from utils.paths import Paths

logger = logging.getLogger(__name__)


class ProgressDialog(QDialog):
    """Progress dialog for GIF processing"""
    def __init__(self, parent=None):
        # Don't rely on main window - use QApplication.activeWindow() or None
        super().__init__(parent)
        self.setWindowTitle("Processing GIFs")
        self.setModal(True)
        self.setMinimumWidth(400)

        # Set window flags to make it a standalone dialog
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.WindowTitleHint | Qt.WindowType.CustomizeWindowHint)

        # Make sure it stays on top during processing
        self.setWindowModality(Qt.WindowModality.ApplicationModal)

        layout = QVBoxLayout()

        self.label = QLabel("Preparing to process GIFs...")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.label)

        self.progress_bar = QProgressBar()
        layout.addWidget(self.progress_bar)

        self.details_label = QLabel("")
        self.details_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.details_label)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        layout.addWidget(self.cancel_button)

        self.setLayout(layout)

    def update_progress(self, current, total, status=""):
        """Update progress bar and labels"""
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)
        self.label.setText(f"Processing GIFs: {current}/{total}")
        if status:
            self.details_label.setText(status)

    def center_on_screen(self):
        """Center the dialog on screen"""
        screen = QApplication.primaryScreen().geometry()
        size = self.geometry()
        self.move(
            (screen.width() - size.width()) // 2,
            (screen.height() - size.height()) // 2
        )


class GIFManager:
    def __init__(self, main_window):
        self.main_window = main_window
        self.settings = main_window.settings
        self.disable_color_gifs = self.settings.value("disable_color_gifs", False, type=bool)
        # Store the current disable_color_gifs setting for comparison
        self._current_disable_color_gifs = self.disable_color_gifs
        self.regenerate_anyway = False
        # Don't create progress dialog here - create it when needed
        self.progress_dialog = None

    def _create_progress_dialog(self):
        """Create progress dialog without parent or with main window only if it's visible"""
        if self.main_window and self.main_window.isVisible():
            self.progress_dialog = ProgressDialog(self.main_window)
        else:
            # Create without parent
            self.progress_dialog = ProgressDialog()
            self.progress_dialog.center_on_screen()
        return self.progress_dialog

    def process_gif_batch(self, output_dir, accent_color):
        """
        Process all GIFs from multiple input directories in parallel
        """
        output_dir.mkdir(exist_ok=True)

        # Clean up old hex files and non-standard colorized files
        self._cleanup_old_files(output_dir)

        # Find all unique GIFs across input directories (first found wins)
        input_dirs = [
            get_base_path() / "gifs" / "custom",
            Paths.resource("gif")
        ]

        gif_list = self._find_unique_gifs(input_dirs)

        if not gif_list:
            logger.warning("No GIF files found in any input directory")
            return

        logger.info(f"Found {len(gif_list)} unique GIFs across {len(input_dirs)} directories")

        # Create color-specific subdirectory
        color_subdir = output_dir / accent_color.lstrip('#')
        color_subdir.mkdir(exist_ok=True)

        # Check if disable_color_gifs setting has changed
        setting_changed = self._check_disable_color_gifs_setting_changed(color_subdir)

        regeneration_needed = self._check_regeneration(gif_list, input_dirs, color_subdir)

        # Force regeneration if disable_color_gifs setting has changed
        if setting_changed or self.regenerate_anyway:
            logger.info(f"disable_color_gifs setting changed, forcing regeneration")
            regeneration_needed = True

        if not regeneration_needed:
            logger.info("All GIFs are up to date, updating symlinks only.")
            self._update_color_symlinks(gif_list, color_subdir, output_dir)
            return

        # pt.r stop being stupid, it continues if regeneration_needed is false here
        QTimer.singleShot(100, lambda: self._process_with_progress(gif_list, input_dirs, color_subdir, output_dir, accent_color))

    def _process_with_progress(self, gif_list, input_dirs, color_subdir, output_dir, accent_color):
        """Process GIFs with progress updates"""
        # Create and show progress dialog
        self._create_progress_dialog()
        self.progress_dialog.show()

        # Process events to ensure dialog is displayed
        QApplication.processEvents()

        message = f"{'Copying' if self.disable_color_gifs else 'Colorizing'} {len(gif_list)} GIFs"
        logger.info(message)
        start_time = time.time()

        # Update progress dialog
        self.progress_dialog.update_progress(0, len(gif_list), message)

        # Process events to update the dialog
        QApplication.processEvents()

        # Use parallel processing
        completed_count = self._process_gifs_parallel_with_progress(gif_list, input_dirs, color_subdir, accent_color)

        total_time = time.time() - start_time
        logger.info(f"Completed processing {completed_count}/{len(gif_list)} GIFs in {total_time:.2f}s "
                    f"({total_time / max(completed_count, 1):.2f}s per GIF)")

        self._write_hashes_file(color_subdir)

        # Update the disable_color_gifs setting file after processing
        self._update_disable_color_gifs_setting(color_subdir)

        self._update_color_symlinks(gif_list, color_subdir, output_dir)

        self.regenerate_anyway = False

        # Close progress dialog
        self.progress_dialog.accept()

        # Only reload movies if main window exists and is visible
        if self.main_window and hasattr(self.main_window.ui_state, '_reload_movies'):
            self.main_window.ui_state._reload_movies()

    def _process_gifs_parallel_with_progress(self, gif_list, input_dirs, color_subdir, accent_color):
        """
        Process GIFs in parallel batches with progress updates
        """
        cpu_count = os.cpu_count() or 4
        max_workers = min(cpu_count, len(gif_list), 14)

        logger.info(f"Processing with {max_workers} workers")

        # Prepare batch data - pass only serializable data
        batch_data = []
        for gif_name in gif_list:
            source_dir = self._find_gif_source(input_dirs, gif_name)
            if source_dir:
                batch_data.append({
                    'name': gif_name,
                    'source_path': str(source_dir / gif_name),
                    'output_path': str(color_subdir / gif_name),
                    'accent_color': accent_color,
                    'disable_color_gifs': self.disable_color_gifs  # Pass the flag as data
                })

        # Process in parallel using ThreadPoolExecutor
        completed_count = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_gif = {
                executor.submit(self._process_single_gif_thread_worker, gif_data): gif_data
                for gif_data in batch_data
            }

            for future in concurrent.futures.as_completed(future_to_gif):
                gif_data = future_to_gif[future]
                try:
                    result = future.result()
                    if result:
                        completed_count += 1
                        # Update progress dialog
                        self.progress_dialog.update_progress(completed_count, len(batch_data), f"Processed: {gif_data['name']}")

                        # Process events to update the UI
                        if completed_count % 5 == 0:  # Update more frequently
                            QApplication.processEvents()

                        if completed_count % 10 == 0:
                            logger.info(f"Progress: {completed_count}/{len(batch_data)} GIFs processed")
                except Exception as e:
                    logger.error(f"Error processing {gif_data['name']}: {e}")

                # Check if dialog was cancelled
                if not self.progress_dialog or not self.progress_dialog.isVisible():
                    logger.info("Processing cancelled by user")
                    executor.shutdown(wait=False, cancel_futures=True)
                    break

        return completed_count

    def _check_disable_color_gifs_setting_changed(self, color_subdir):
        """
        Check if the disable_color_gifs setting has changed from the last processed state
        Returns True if changed, False if same or no previous setting found
        """
        setting_file = color_subdir / "disable_color_gifs_setting.txt"

        # First check if colorized directory exists and has GIFs
        if not color_subdir.exists():
            logger.debug(f"Color subdirectory doesn't exist: {color_subdir}")
            return True

        # Check if there are any GIFs in the directory
        has_gifs = any(file.suffix.lower() == '.gif' for file in color_subdir.iterdir())
        if not has_gifs:
            logger.debug(f"No GIFs found in color subdirectory: {color_subdir}")
            return True

        if not setting_file.exists():
            logger.debug(f"No previous disable_color_gifs setting file found at {setting_file}")
            return True  # No previous setting, so we need to process

        try:
            with open(setting_file, 'r') as f:
                previous_setting = f.read().strip()

            # Convert to boolean - handle both "1"/"0" and "True"/"False" formats
            if previous_setting in ["1", "True", "true"]:
                previous_bool = True
            elif previous_setting in ["0", "False", "false"]:
                previous_bool = False
            else:
                logger.warning(f"Invalid setting value in file: {previous_setting}")
                return True

            current_bool = bool(self.disable_color_gifs)

            logger.debug(f"Previous setting: '{previous_setting}' -> {previous_bool}")
            logger.debug(f"Current setting: {self.disable_color_gifs} -> {current_bool}")

            if previous_bool != current_bool:
                logger.info(f"disable_color_gifs setting changed: previous={previous_bool}, current={current_bool}")
                return True
            else:
                logger.debug(f"disable_color_gifs setting unchanged: {current_bool}")
                return False

        except Exception as e:
            logger.warning(f"Error reading disable_color_gifs setting file: {e}")
            return True

    def _update_disable_color_gifs_setting(self, color_subdir):
        """
        Update the disable_color_gifs setting file with the current value
        """
        setting_file = color_subdir / "disable_color_gifs_setting.txt"

        try:
            # Store as 1 for True, 0 for False
            setting_value = "1" if self.disable_color_gifs else "0"
            with open(setting_file, 'w') as f:
                f.write(setting_value)
            logger.debug(f"Updated disable_color_gifs setting file: {setting_value}")
        except Exception as e:
            logger.warning(f"Error writing disable_color_gifs setting file: {e}")

    def _cleanup_old_files(self, output_dir):
        """Remove hex.txt and non-standard colorized files"""
        hex_file_path = output_dir / "hex.txt"
        if hex_file_path.exists():
            try:
                hex_file_path.unlink()
                logger.info(f"Removed old hex.txt file: {hex_file_path}")
            except Exception as e:
                logger.warning(f"Could not remove hex.txt file: {e}")

        try:
            for file_path in output_dir.iterdir():
                if "_" in file_path.name and file_path.is_file():
                    file_path.unlink()
                    logger.debug(f"Removed non-standard colorized file: {file_path.name}")
        except Exception as e:
            logger.warning(f"Error cleaning up non-standard files: {e}")

    def _find_unique_gifs(self, input_dirs):
        """
        Find all unique GIF files across input directories.
        Returns the first occurrence of each GIF filename found in the directories.
        """
        gif_files = {}

        for input_dir in input_dirs:
            if not input_dir.exists():
                logger.warning(f"Input directory does not exist: {input_dir}")
                continue

            logger.debug(f"Scanning directory: {input_dir}")
            for file_path in input_dir.iterdir():
                if file_path.is_file() and file_path.suffix.lower() == '.gif':
                    filename = file_path.name
                    if filename not in gif_files:
                        gif_files[filename] = input_dir
                        logger.debug(f"Found GIF: {filename} in {input_dir}")

        return list(gif_files.keys())

    def _check_regeneration(self, gif_list, input_dirs, color_subdir):
        """
        Check if any GIFs need regeneration by comparing hashes
        Returns True if any GIF needs regeneration
        """
        logger.info("Batch checking for regeneration needs...")

        # Load existing hashes
        existing_hashes = self._load_hashes(color_subdir)
        needs_regeneration = False

        for gif_name in gif_list:
            source_dir = self._find_gif_source(input_dirs, gif_name)
            if not source_dir:
                continue

            input_path = source_dir / gif_name
            output_path = color_subdir / gif_name

            # Check if regeneration is needed
            if self._should_regenerate_gif(input_path, output_path, gif_name, existing_hashes):
                needs_regeneration = True
                # We can break early if we find at least one that needs regeneration
                break

        return needs_regeneration

    def _process_gifs_parallel(self, gif_list, input_dirs, color_subdir, accent_color):
        """
        Process GIFs in parallel batches without pickle issues
        """
        cpu_count = os.cpu_count() or 4
        max_workers = min(cpu_count, len(gif_list), 14)

        logger.info(f"Processing with {max_workers} workers")

        # Prepare batch data - pass only serializable data
        batch_data = []
        for gif_name in gif_list:
            source_dir = self._find_gif_source(input_dirs, gif_name)
            if source_dir:
                batch_data.append({
                    'name': gif_name,
                    'source_path': str(source_dir / gif_name),
                    'output_path': str(color_subdir / gif_name),
                    'accent_color': accent_color,
                    'disable_color_gifs': self.disable_color_gifs  # Pass the flag as data
                })

        # Process in parallel using ThreadPoolExecutor instead of ProcessPoolExecutor
        completed_count = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_gif = {
                executor.submit(self._process_single_gif_thread_worker, gif_data): gif_data
                for gif_data in batch_data
            }

            for future in concurrent.futures.as_completed(future_to_gif):
                gif_data = future_to_gif[future]
                try:
                    result = future.result()
                    if result:
                        completed_count += 1
                        if completed_count % 10 == 0:
                            logger.info(f"Progress: {completed_count}/{len(batch_data)} GIFs processed")
                except Exception as e:
                    logger.error(f"Error processing {gif_data['name']}: {e}")

        return completed_count

    def _process_single_gif_thread_worker(self, gif_data):
        """
        Worker function for processing a single GIF in a thread
        """
        try:
            return self._process_single_gif_thread(
                gif_data['source_path'],
                gif_data['output_path'],
                gif_data['accent_color'],
                gif_data['name'],
                gif_data['disable_color_gifs']
            )
        except Exception as e:
            logger.error(f"Worker error for {gif_data['name']}: {e}")
            return False

    def _process_single_gif_thread(self, input_path, output_path, accent_color, gif_name, disable_color_gifs):
        """
        Process a single GIF in a thread with hash-based caching
        """
        # Convert back to Path objects for operations
        input_path = Path(input_path)
        output_path = Path(output_path)
        output_dir = output_path.parent

        # Check if we need to regenerate
        if output_path.exists():
            source_hash = self._calculate_gif_hash(input_path)
            existing_hash = self._get_stored_hash(gif_name, output_dir)

            if source_hash and existing_hash and source_hash == existing_hash:
                logger.debug(f"Using cached: {output_path.name}")
                return True

        # Process the GIF based on the disable_color_gifs flag
        if disable_color_gifs:
            return self._copy_gif_directly(input_path, output_path, gif_name)
        else:
            return self._apply_color_to_gif(input_path, output_path, accent_color, gif_name)

    def _apply_color_to_gif(self, input_path, output_path, accent_color, gif_name):
        """
        Apply color transformation to GIF (only used if disable_color_gifs=False)
        """
        start_time = time.time()

        try:
            # Parse target color
            target_rgb = tuple(int(accent_color.lstrip('#')[i:i+2], 16) for i in (0, 2, 4))
            target_h, target_s, target_v = self._rgb_to_hsv(*target_rgb)

            with Image.open(input_path) as gif:
                # Extract all frames
                frames = []
                frame_durations = []
                original_info = gif.info.copy()
                try:
                    while True:
                        frame = gif.copy().convert('RGBA')
                        frames.append(frame)
                        frame_durations.append(gif.info.get('duration', 100))
                        gif.seek(gif.tell() + 1)
                except EOFError:
                    pass

                if not frames:
                    return False

                processed_frames = self._process_frames(frames, target_h, target_s, target_v)

                self._save_gif(processed_frames, frame_durations, original_info, output_path)

                # Store hash for this GIF in temporary storage
                self._store_temp_hash(gif_name, input_path, output_path.parent)

                elapsed = time.time() - start_time
                if elapsed > 0.5:
                    logger.debug(f"Colorized {input_path.name}: {elapsed:.3f}s")

                return True

        except Exception as e:
            logger.error(f"Error processing {input_path}: {e}")
            # Fallback: copy original
            try:
                shutil.copy2(input_path, output_path)
                logger.info(f"Fallback copy created for: {input_path.name}")
                return True
            except Exception as copy_error:
                logger.error(f"Fallback copy also failed for {input_path}: {copy_error}")
                return False

    def _copy_gif_directly(self, input_path, output_path, gif_name):
        """
        Simply copy GIF file from source to destination (only used if disable_color_gifs=True)
        """
        start_time = time.time()

        try:
            # Copy the file
            shutil.copy2(input_path, output_path)

            # Store hash for caching
            self._store_temp_hash(gif_name, input_path, output_path.parent)

            elapsed = time.time() - start_time
            if elapsed > 0.5:
                logger.debug(f"Copied {input_path.name}: {elapsed:.3f}s")

            return True

        except Exception as e:
            logger.error(f"Error copying {input_path}: {e}")
            return False

    def _load_hashes(self, output_dir):
        """Load existing hashes from hashes.json"""
        hashes_path = output_dir / "hashes.json"
        if hashes_path.exists():
            try:
                with open(hashes_path, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Could not load hashes.json: {e}")
        return {}

    def _write_hashes_file(self, output_dir):
        """Write hashes.json"""
        hashes_path = output_dir / "hashes.json"
        try:
            # Collect all temporary hashes
            final_hashes = {}
            for file_path in output_dir.iterdir():
                if file_path.is_file() and file_path.suffix.lower() == '.gif':
                    gif_name = file_path.name
                    hash_file = output_dir / f".{gif_name}.hash"
                    if hash_file.exists():
                        try:
                            with open(hash_file, 'r') as f:
                                final_hashes[gif_name] = f.read().strip()
                            # Clean up temp hash file
                            hash_file.unlink()
                        except Exception as e:
                            logger.warning(f"Could not read hash for {gif_name}: {e}")

            # Write final hashes.json
            with open(hashes_path, 'w') as f:
                json.dump(final_hashes, f, indent=2)
            logger.info(f"Saved {len(final_hashes)} hashes to {hashes_path}")

        except Exception as e:
            logger.error(f"Could not write hashes.json: {e}")

    def _store_temp_hash(self, gif_name, input_path, output_dir):
        """Store hash temporarily in individual files to avoid read/write conflicts"""
        try:
            source_hash = self._calculate_gif_hash(input_path)
            if source_hash:
                hash_file = output_dir / f".{gif_name}.hash"
                with open(hash_file, 'w') as f:
                    f.write(source_hash)
        except Exception as e:
            logger.warning(f"Could not store temp hash for {gif_name}: {e}")

    def _get_stored_hash(self, gif_name, output_dir):
        """Get stored hash from temporary file"""
        hash_file = output_dir / f".{gif_name}.hash"
        if hash_file.exists():
            try:
                with open(hash_file, 'r') as f:
                    return f.read().strip()
            except Exception:
                pass
        return None

    def _calculate_gif_hash(self, file_path):
        """Calculate SHA256 hash of a GIF file"""
        try:
            hasher = hashlib.sha256()
            with open(file_path, 'rb') as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hasher.update(chunk)
            return hasher.hexdigest()
        except Exception as e:
            logger.error(f"Error calculating hash for {file_path}: {e}")
            return None

    def _should_regenerate_gif(self, input_path, output_path, gif_name, existing_hashes):
        """Check if we need to regenerate the colorized GIF"""
        if self.regenerate_anyway:
            logger.info("GIFs Regeneration has been forced.")
            return True

        if not output_path.exists():
            logger.info(f"GIFs Regeneration has started because {output_path} doesn't exist")
            return True

        if not input_path.exists():
            logger.warn(f"Detected that {input_path} doesn't exist, but won't do anything about it")

        current_hash = self._calculate_gif_hash(input_path)
        if not current_hash:
            logger.info(f"GIFs need regeneration: {input_path}/{gif_name} -> {output_path}/{gif_name} because the hash doesn't exist")
            return True

        existing_hash = existing_hashes.get(gif_name)
        if not existing_hash:
            logger.info(f"GIFs need regeneration: {input_path}/{gif_name} -> {output_path}/{gif_name} because gifs' hash doesn't exist")
            return True

        if existing_hash != current_hash:
            logger.info(f"GIFs need regeneration: {input_path}/{gif_name} -> {output_path}/{gif_name} because the hash {existing_hash} != {current_hash}")
            return True

        return False

    def _process_frames(self, frames, target_h, target_s, target_v):
        """Process all frames with color transformation"""
        processed_frames = []

        for frame in frames:
            img_array = np.array(frame, dtype=np.float32)
            processed_array = self._apply_color_transform(img_array, target_h, target_s, target_v)
            processed_frames.append(Image.fromarray(processed_array.astype(np.uint8), 'RGBA'))

        return processed_frames

    def _apply_color_transform(self, img_array, target_h, target_s, target_v):
        """Apply color transformation to image array"""
        # Extract channels
        r, g, b, a = img_array[..., 0], img_array[..., 1], img_array[..., 2], img_array[..., 3]

        # Calculate colorfulness (std dev) for each pixel
        rgb_mean = (r + g + b) / 3.0
        rgb_std = np.sqrt(((r - rgb_mean)**2 + (g - rgb_mean)**2 + (b - rgb_mean)**2) / 3.0)

        # Create mask for colored pixels
        colored_mask = (a > 10) & (rgb_std > 5)

        if not np.any(colored_mask):
            return img_array  # No colored pixels to process

        # Extract colored pixels
        colored_pixels = img_array[colored_mask]
        colored_rgb = colored_pixels[:, :3]

        # Convert colored RGB to HSV
        colored_hsv = self._rgb_to_hsv_batch(colored_rgb)

        # Calculate average saturation and value
        avg_s = np.mean(colored_hsv[:, 1])
        avg_v = np.mean(colored_hsv[:, 2])

        # Avoid division by zero
        avg_s = max(avg_s, 0.001)
        avg_v = max(avg_v, 0.001)

        # Apply transformations
        new_h = np.full(colored_hsv.shape[0], target_h)
        new_s = np.clip(colored_hsv[:, 1] * (target_s / avg_s), 0.0, 1.0)
        new_v = np.clip(colored_hsv[:, 2] * (target_v / avg_v), 0.0, 1.0)

        # Convert back to RGB
        new_rgb = self._hsv_to_rgb_batch(new_h, new_s, new_v)

        # Update the colored pixels
        result_array = img_array.copy()
        result_array[colored_mask, :3] = new_rgb

        return result_array

    def _rgb_to_hsv_batch(self, rgb_array):
        """Convert RGB to HSV for batch of pixels"""
        r, g, b = rgb_array[..., 0], rgb_array[..., 1], rgb_array[..., 2]
        r, g, b = r/255.0, g/255.0, b/255.0

        mx = np.maximum(np.maximum(r, g), b)
        mn = np.minimum(np.minimum(r, g), b)
        df = mx - mn

        h = np.zeros_like(mx)
        s = np.zeros_like(mx)
        v = mx

        # Avoid division by zero
        df_nonzero = df != 0

        # Calculate hue
        mask_r = (mx == r) & df_nonzero
        mask_g = (mx == g) & df_nonzero
        mask_b = (mx == b) & df_nonzero

        h[mask_r] = (60 * ((g[mask_r] - b[mask_r]) / df[mask_r]) + 360) % 360
        h[mask_g] = (60 * ((b[mask_g] - r[mask_g]) / df[mask_g]) + 120) % 360
        h[mask_b] = (60 * ((r[mask_b] - g[mask_b]) / df[mask_b]) + 240) % 360

        # Calculate saturation
        s[mx != 0] = df[mx != 0] / mx[mx != 0]

        return np.stack([h, s, v], axis=-1)

    def _hsv_to_rgb_batch(self, h, s, v):
        """Convert HSV to RGB for batch of pixels"""
        h = h % 360
        hi = (h / 60).astype(int) % 6
        f = (h / 60) - (h / 60).astype(int)

        p = v * (1 - s)
        q = v * (1 - f * s)
        t = v * (1 - (1 - f) * s)

        # Initialize result arrays
        r = np.zeros_like(h)
        g = np.zeros_like(h)
        b = np.zeros_like(h)

        # Assign based on hue segment
        masks = [hi == i for i in range(6)]
        conditions = [
            (v, t, p),    # hi == 0
            (q, v, p),    # hi == 1
            (p, v, t),    # hi == 2
            (p, q, v),    # hi == 3
            (t, p, v),    # hi == 4
            (v, p, q)     # hi == 5
        ]

        for i, (rr, gg, bb) in enumerate(conditions):
            mask = masks[i]
            r[mask] = rr[mask]
            g[mask] = gg[mask]
            b[mask] = bb[mask]

        # Scale to 0-255 and stack
        rgb = np.stack([r * 255, g * 255, b * 255], axis=-1)
        return np.clip(rgb, 0, 255).astype(np.float32)

    def _rgb_to_hsv(self, r, g, b):
        """Convert single RGB pixel to HSV"""
        r, g, b = r/255.0, g/255.0, b/255.0
        mx = max(r, g, b)
        mn = min(r, g, b)
        df = mx - mn

        if mx == mn:
            h = 0.0
        elif mx == r:
            h = (60 * ((g - b) / df) + 360) % 360
        elif mx == g:
            h = (60 * ((b - r) / df) + 120) % 360
        elif mx == b:
            h = (60 * ((r - g) / df) + 240) % 360
        else:
            h = 0.0

        s = 0.0 if mx == 0 else df / mx
        v = mx
        return (h, s, v)

    def _save_gif(self, frames, durations, gif_info, output_path):
        """Save frames as GIF"""
        if frames:
            frames[0].save(
                output_path,
                save_all=True,
                append_images=frames[1:],
                duration=durations,
                loop=gif_info.get('loop', 0),
                optimize=True,
                disposal=2
            )

    def _update_color_symlinks(self, gif_list, color_subdir, output_dir):
        """Update all symlinks to point to current colorized versions"""
        logger.info("Updating symlinks to current color...")
        successful_links = 0

        for gif_name in gif_list:
            colorized_path = color_subdir / gif_name
            symlink_path = output_dir / gif_name

            if colorized_path.exists():
                try:
                    # On Windows NT, copy instead of symlink
                    if os.name == 'nt':
                        shutil.copy2(colorized_path, symlink_path)
                        logger.debug(f"Copied {gif_name} (Windows NT system)")
                    else:
                        self._create_color_symlink(colorized_path, symlink_path)
                        logger.debug(f"Created symlink for {gif_name}")

                    successful_links += 1

                except OSError as e:
                    logger.error(f"Failed to create link/copy for {gif_name}: {e}")
                except Exception as e:
                    logger.error(f"Unexpected error with {gif_name}: {e}")
            else:
                logger.warning(f"Colorized file not found for {gif_name}")

        logger.info(f"Update complete: {successful_links}/{len(gif_list)} links/copies created")

    def _create_color_symlink(self, target_path, symlink_path):
        """Create symlink pointing to colorized file"""
        try:
            if symlink_path.exists() or symlink_path.is_symlink():
                symlink_path.unlink()

            # Create relative symlink
            target_rel = os.path.relpath(target_path, symlink_path.parent)
            symlink_path.symlink_to(target_rel)
            return True
        except Exception as e:
            logger.warning(f"Symlink failed for {symlink_path.name}: {e}")
            try:
                shutil.copy2(target_path, symlink_path)
                return True
            except Exception as copy_error:
                logger.error(f"File copy also failed: {copy_error}")
                return False

    def _find_gif_source(self, input_dirs, gif_name):
        """Find which input directory contains the GIF file"""
        for input_dir in input_dirs:
            potential_path = input_dir / gif_name
            if potential_path.exists():
                return input_dir
        return None
