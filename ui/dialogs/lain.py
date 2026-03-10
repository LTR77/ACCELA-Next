import logging
import random
import time
from datetime import datetime

from components.custom_widgets import ScaledFontLabel, ScaledLabel, ScaledButton
from PyQt6.QtGui import QColor, QFont, QPixmap
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QTextEdit,
    QProgressBar,
    QGroupBox,
    QSizePolicy,
    QGridLayout,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal

logger = logging.getLogger(__name__)


class LainMinigameDialog(QDialog):
    """Serial Experiments Lain themed minigame: The Wired Terminal"""

    game_completed = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("The Wired Terminal")
        self.resize(800, 600)
        self.setMinimumSize(600, 500)

        # Game state
        self.score = 0
        self.level = 1
        self.time_left = 120.0
        self.max_time = 120.0
        self.game_active = False
        self.current_commands = []
        self.current_target = ""
        self.completed_sequences = 0
        self.grace_period_time = 0.0
        self.bonus_time_to_add = 0.0
        self.grace_duration = 0.0
        self.grace_duration_start_from = 3.0

        # Initialize with Lain-themed commands
        self.commands_pool = [
            "CONNECT", "DISCONNECT", "NAVI", "LAYER09", "SCHIZOPHRENIA",
            "KNIGHTS", "ACID", "PROTOCOL7", "WIRED", "TACHIKOMA", "LETSALLLOVELAIN",
            "ECHIDNA", "BLUE", "ROSE", "PSYCHO", "DIVINE", "CHIPS", "NEURONS",
            "MEMORY", "REALITY", "INTERFACE", "SERVER", "CLIENT", "UPLOAD", "GODISINTHEWIRED",
            "ACCELA", "BABEL", "CYBERIA", "DEUS", "EPTO", "FRAGMENT", "GIG", "HORNET",
            "INFORNO", "JACKIN", "LILITH", "MASK", "NOISE", "OMEGA", "PHANTOM",
            "QUANTUM", "ROOT", "SCILAB", "TRANCE", "UNIX", "VOID", "WAVE", "XANADU",
            "YGGDRASIL", "ZERO", "ANOMALY", "BEAR", "CRYPT", "DARK", "ENTITY", "FLOW",
            "GHOST", "HACK", "ICON", "JUDGMENT", "KEY", "LOGOS", "METAVERSE", "NODE",
            "OSCILLATION", "PARADOX", "QUERY", "RIBBON", "SHADOW", "TUNNEL", "UNKNOWN",
            "VISION", "WALL", "XEROX", "YOUTH", "ZEAL", "ABSTRACT", "BOOT", "CHAIN",
            "DREAM", "ERROR", "FALSE", "GATE", "HELLO", "IDENTITY", "JUMP", "KNOT",
            "LEGACY", "MIRAGE", "NET", "ORACLE", "PRIME", "QUEST", "RIFT", "SIGNAL",
            "TRACE", "UTOPIA", "VEIL", "WITNESS", "XENON", "YIELD", "ZENITH"
        ]

        self.layout = QVBoxLayout(self)

        # Title
        title = ScaledFontLabel("THE WIRED TERMINAL")
        title.setMinimumHeight(48)
        self.layout.addWidget(title)

        # Subtitle
        subtitle = ScaledFontLabel("Layer 0" + str(random.randint(1, 9)))
        subtitle.setFixedHeight(36)
        self.layout.addWidget(subtitle)

        # Stats display
        stats_layout = QHBoxLayout()

        self.score_label = ScaledFontLabel(f"SCORE: {self.score:06d}")
        self.score_label.setFixedHeight(36)
        stats_layout.addWidget(self.score_label)

        self.level_label = ScaledFontLabel(f"LAYER: {self.level}")
        self.level_label.setFixedHeight(36)
        stats_layout.addWidget(self.level_label)

        self.completed_label = ScaledFontLabel(f"SEQUENCES: {self.completed_sequences}")
        self.completed_label.setFixedHeight(36)
        stats_layout.addWidget(self.completed_label)

        self.layout.addLayout(stats_layout, 2)

        # Time progress bar
        self.time_bar = QProgressBar()
        self.time_bar.setRange(0, int(self.max_time))
        self.time_bar.setValue(int(self.time_left))
        self.time_bar.setFormat("TIME REMAINING: %v SECONDS")
        self.layout.addWidget(self.time_bar, 1)

        # Terminal display
        terminal_group = QGroupBox("TERMINAL OUTPUT")
        terminal_layout = QVBoxLayout()

        self.terminal_display = QTextEdit()
        self.terminal_display.setReadOnly(True)
        self.terminal_display.setMaximumHeight(150)
        terminal_layout.addWidget(self.terminal_display, 3)

        self.target_label = ScaledFontLabel("TARGET SEQUENCE:")
        self.target_label.setFixedHeight(38)
        self.target_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        terminal_layout.addWidget(self.target_label, 2)

        terminal_group.setLayout(terminal_layout)
        self.layout.addWidget(terminal_group, 1)

        # Command buttons
        commands_group = QGroupBox("AVAILABLE COMMANDS")
        commands_layout = QGridLayout()

        # Button grid for commands
        self.command_buttons = []
        for i in range(4):  # 4 rows
            for j in range(3):  # 3 columns
                btn = ScaledButton("")
                btn.setMinimumHeight(30)
                btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                btn.setHidden(True)
                index = i * 3 + j
                btn.clicked.connect(self._create_button_handler(index))
                commands_layout.addWidget(btn, i, j)
                self.command_buttons.append(btn)

        commands_group.setLayout(commands_layout)
        self.layout.addWidget(commands_group, 3)

        # Control buttons
        control_layout = QHBoxLayout()

        self.start_button = QPushButton("INITIALIZE CONNECTION")
        self.start_button.clicked.connect(self.start_game)
        control_layout.addWidget(self.start_button)

        self.layout.addLayout(control_layout, 1)

        # Game timer
        self.game_timer = QTimer()
        self.game_timer.timeout.connect(self.update_timer)

        # Message timer for terminal updates
        self.message_timer = QTimer()
        self.message_timer.timeout.connect(self.add_terminal_message)
        self.message_timer.setInterval(3000)  # Add message every 3 seconds

        # Bonus time timer (for slowly adding bonus time during grace period)
        self.bonus_timer = QTimer()
        self.bonus_timer.timeout.connect(self.add_bonus_time)
        self.bonus_timer.setInterval(200)  # Add bonus time every 200ms

        # Initialize with welcome message
        self._add_terminal_text(">>> SYSTEM BOOT...\n")
        self._add_terminal_text(">>> WIRED TERMINAL v1.337\n")
        self._add_terminal_text(">>> WELCOME TO LAYER 09\n")
        self._add_terminal_text(">>> INITIALIZE CONNECTION TO BEGIN\n")

        logger.debug("LainMinigameDialog initialized.")

    def _create_button_handler(self, index):
        """Create a closure for button click handling"""
        return lambda: self.command_clicked(index)

    def _add_terminal_text(self, text):
        """Add text to terminal with Lain-style formatting"""
        current = self.terminal_display.toPlainText()
        self.terminal_display.setText(current + text)
        self.terminal_display.verticalScrollBar().setValue(
            self.terminal_display.verticalScrollBar().maximum()
        )

    def start_game(self):
        """Start the minigame"""
        if not self.game_active:
            self.game_active = True
            self.score = 0
            self.level = 1
            self.time_left = self.max_time
            self.completed_sequences = 0
            self.grace_period_time = 0.0
            self.bonus_time_to_add = 0.0
            self.update_display()

            self.start_button.setHidden(True)  # Hide start button

            # Show command buttons
            for btn in self.command_buttons:
                btn.setHidden(False)

            self._add_terminal_text("\n>>> CONNECTION ESTABLISHED\n")
            self._add_terminal_text(">>> PROTOCOL SYNCHRONIZED\n")
            self._add_terminal_text(">>> BEGIN INPUT SEQUENCE\n")

            self.generate_new_sequence()
            self.game_timer.start(100)  # Update every 100ms for smoother float updates
            self.message_timer.start()  # Start terminal messages

            logger.info("Lain minigame started.")

    def generate_new_sequence(self):
        """Generate a new target sequence for the player to input"""
        sequence_length = min(3 + self.level // 2, 8)  # Sequences (3-8 commands)

        # Select random commands for this sequence
        self.current_commands = random.sample(self.commands_pool, sequence_length)
        self.current_target = " -> ".join(self.current_commands)

        # Update target display - ScaledLabel will handle font scaling
        self.target_label.setText(f"TARGET SEQUENCE: {self.current_target}")

        # Create button commands - use the entire commands pool
        all_commands = list(self.commands_pool)
        random.shuffle(all_commands)

        # Make sure ALL sequence commands are in the buttons
        button_commands = list(self.current_commands)  # Sequence commands first

        # Add remaining commands from pool (excluding duplicates)
        for cmd in all_commands:
            if cmd not in button_commands and len(button_commands) < 12:
                button_commands.append(cmd)

        # If we still need more, add random commands
        while len(button_commands) < 12:
            button_commands.append(random.choice(self.commands_pool))

        # Shuffle final list
        random.shuffle(button_commands)

        # Update buttons
        for i, btn in enumerate(self.command_buttons):
            btn.setText(button_commands[i])
            btn.setEnabled(True)

        # Add to terminal
        self._add_terminal_text(f">>> NEW TARGET: {self.current_target}\n")

    def command_clicked(self, index):
        """Handle command button click"""
        if not self.game_active or self.grace_period_time > 0:
            return

        clicked_command = self.command_buttons[index].text()

        # Check if this is the next command in sequence
        if self.current_commands and clicked_command == self.current_commands[0]:
            # Correct command
            self.current_commands.pop(0)
            self.command_buttons[index].setEnabled(False)

            # Add to terminal
            self._add_terminal_text(f">>> INPUT: {clicked_command} ✓ [+1.0s]\n")
            self.time_left += 0.5  # Success time

            # Check if sequence completed
            if not self.current_commands:
                self.sequence_completed()
        else:
            # Wrong command
            self.score = max(0, self.score - 50)
            self.time_left = max(10.0, self.time_left - 5.0)  # Penalty time

            # Add to terminal
            self._add_terminal_text(f">>> INPUT: {clicked_command} ✗ [-5.0s]\n")

            self.update_display()

    def sequence_completed(self):
        """Handle completed sequence"""
        sequence_bonus = 100 * self.level
        time_bonus = int(self.time_left / self.max_time * 200)
        self.score += sequence_bonus + time_bonus
        self.completed_sequences += 1

        self._add_terminal_text(">>> SEQUENCE COMPLETE ✓\n")
        self._add_terminal_text(f">>> BONUS: {sequence_bonus} + TIME: {time_bonus * 0.01}s\n")

        # Level up every 3 sequences
        if self.completed_sequences % 3 == 0:
            self.level += 1
            self._add_terminal_text(f">>> ACCESSING LAYER {self.level:02d}\n")

        self.add_terminal_message()

        # Calculate grace period - starts at 5s, decreases by 0.25s per sequence, minimum 0.5s
        self.grace_duration = max(0.5, self.grace_duration_start_from - (self.completed_sequences * 0.25))

        # Calculate bonus time to add during grace period
        self.bonus_time_to_add = float(time_bonus) * 0.01

        # Start grace period
        self.grace_period_time = self.grace_duration
        self.bonus_timer.start()

        # Random grace period start messages
        grace_start_messages = [
            ">>> Taking a break... connecting to alternate reality",
            ">>> Relaxing for a moment in the Wired",
            ">>> Syncing neural patterns... momentary pause",
            ">>> Consciousness fragmentation in progress",
            ">>> Brief interface recalibration",
            ">>> Let's all love Lain for a moment",
            ">>> Experiencing temporal dilation",
            ">>> Memory fragment analysis initiated",
            ">>> Protocol 7: Momentary disconnection",
            ">>> Scanning for new layers... please wait",
            ">>> Reality distortion field stabilizing",
            ">>> ECHIDNA system processing complete sequences",
            ">>> Tachikoma units performing maintenance",
            ">>> Navi recommends a brief respite",
            ">>> Psyche integration in progress",
            ">>> Wired signal strength recalibrating",
            ">>> Consciousness upload paused",
            ">>> Interface with Layer 09 momentarily suspended"
        ]

        self._add_terminal_text(f"{random.choice(grace_start_messages)} [{self.grace_duration:.1f}s]\n")

        self.update_display()

        # Generate new sequence
        self.generate_new_sequence()

    def add_bonus_time(self):
        """Slowly add bonus time during grace period - now using floats"""
        if self.bonus_time_to_add > 0 and self.grace_period_time > 0:
            # Add a portion of the bonus each tick (0.2 seconds per tick since timer is 200ms)
            time_to_add = min(0.2, self.bonus_time_to_add)  # Add up to 0.2s per tick
            self.time_left += time_to_add
            self.bonus_time_to_add -= time_to_add

            # Update display to show time being added
            self.update_display()

            if self.bonus_time_to_add <= 0:
                self.bonus_timer.stop()

    def update_timer(self):
        """Update the game timer - now using floats"""
        if not self.game_active:
            return

        # Handle grace period first
        if self.grace_period_time > 0:
            self.grace_period_time -= 0.1

            if self.grace_period_time <= 0:
                # Grace period ended
                self.grace_period_time = 0.0
                self.time_left += self.bonus_time_to_add
                self.bonus_time_to_add = 0.0
                self.bonus_timer.stop()

                # Random grace period end messages
                grace_end_messages = [
                    ">>> Entering the Wired once more",
                    ">>> Neural pathways re-engaged",
                    ">>> Protocol 7 reactivated",
                    ">>> Reconnecting to Layer 09",
                    ">>> Consciousness stream resumed",
                    ">>> Interface synchronization complete",
                    ">>> Present day, present time",
                    ">>> God is in the Wired",
                    ">>> Let's all love Lain",
                    ">>> ECHIDNA system online",
                    ">>> Navi connection restored",
                    ">>> Reality distortion: nominal",
                    ">>> Memory fragments integrated",
                    ">>> Psyche monitor: active",
                    ">>> Wired access: granted",
                    ">>> Tachikoma units: ready",
                    ">>> Schizophrenia protocol: standby",
                    ">>> Layer 09: accessible"
                ]

                self._add_terminal_text(f"{random.choice(grace_end_messages)}\n")
        else:
            # Normal gameplay
            self.time_left -= 0.1

            if self.time_left <= 0:
                self.end_game()
                return

        # Always update display
        self.update_display()

    def update_display(self):
        """Update all display elements"""
        self.score_label.setText(f"SCORE: {self.score:06d}")
        self.level_label.setText(f"LAYER: {self.level}")
        self.completed_label.setText(f"SEQUENCES: {self.completed_sequences}")
        self.time_bar.setValue(int(self.time_left))

        # Update time format and styling
        if self.grace_period_time > 0:
            self.time_bar.setFormat(f"GRACE PERIOD: {self.grace_period_time:.1f}s")
            # Fast white flash (every 200ms = 5 times per second)
            flash = int(time.time() * 5) % 2
            if flash:
                self.time_bar.setStyleSheet("""
                    QProgressBar {
                        color: black;
                        text-align: center;
                    }
                    QProgressBar::chunk {
                        background-color: white;
                    }
                """)
            else:
                self.time_bar.setStyleSheet("""
                    QProgressBar {
                        color: white;
                        text-align: center;
                    }
                    QProgressBar::chunk {
                        background-color: #00cc00;
                    }
                """)
        elif self.time_left <= 30:
            self.time_bar.setFormat(f"⚠ TIME CRITICAL: {self.time_left:.1f}s ⚠")
            # Flash warning color
            flash = int(self.time_left * 5) % 2  # Multiply by 10 for more frequent flashing
            if flash:
                self.time_bar.setStyleSheet("""
                    QProgressBar::chunk {
                        background-color: #ff0066;
                    }
                """)
            else:
                self.time_bar.setStyleSheet("""
                    QProgressBar::chunk {
                        background-color: #00aaff;
                    }
                """)
        else:
            self.time_bar.setFormat(f"TIME REMAINING: {self.time_left:.1f}s")
            self.time_bar.setStyleSheet("")

    def add_terminal_message(self):
        """Add random Lain-themed messages to terminal"""
        if not self.game_active:
            return

        messages = [
            ">>> NAVI: ALL IS WELL",
            ">>> SCANNING FREQUENCIES",
            ">>> MEMORY FRAGMENTS DETECTED",
            ">>> LET'S ALL LOVE LAIN",
            ">>> PROTOCOL 7 ACTIVE",
            ">>> CONSCIOUSNESS STREAMING",
            ">>> TACHIKOMA UNITS ONLINE",
            ">>> REALITY DISTORTION: 0." + str(random.randint(1, 99)),
            ">>> ECHIDNA SYSTEM NOMINAL",
            ">>> CONNECTING TO THE WIRED",
            ">>> PSYCHE MONITOR: STABLE",
            ">>> SCHIZOPHRENIA PROTOCOL: DISABLED",
            ">>> KNIGHTS OF THE EASTERN CALCULUS: ACTIVE",
            ">>> ACCELA INTERFACE: STABLE",
            ">>> CYBERIA CAFE: CONNECTED",
            ">>> BABLE PROTOCOL: ENGAGED",
            ">>> DEUS EX MACHINA: STANDBY",
            ">>> PHANTOM CONSCIOUSNESS DETECTED",
            ">>> QUANTUM ENTANGLEMENT: NOMINAL",
            ">>> ROOT ACCESS: GRANTED",
            ">>> TRANCE STATE: MAINTAINED",
            ">>> VOID PROTOCOL: ACTIVE",
            ">>> WAVE FUNCTION COLLAPSED",
            ">>> XANADU ACCESS POINT: FOUND",
            ">>> YGGDRASIL CONNECTION: SECURE",
            ">>> ZERO DAY EXPLOIT: PATCHED",
            ">>> ANOMALY DETECTED IN LAYER 09",
            ">>> CRYPTIC MESSAGE DECODING",
            ">>> DARK MATTER INTERFACE: ONLINE",
            ">>> ENTITY RECOGNITION: ACTIVE",
            ">>> FLOW CONTROL: OPTIMAL",
            ">>> GHOST IN THE MACHINE: ABSENT",
            ">>> HACK ATTEMPT: DEFLECTED",
            ">>> ICON GENERATION: COMPLETE",
            ">>> JUDGMENT PROTOCOL: DISABLED",
            ">>> KEY EXCHANGE: SUCCESSFUL",
            ">>> LOGOS INTEGRATION: STABLE",
            ">>> METAVERSE GATEWAY: OPEN",
            ">>> NODE SYNCHRONIZATION: 100%",
            ">>> OSCILLATION FREQUENCY: LOCKED",
            ">>> PARADOX RESOLUTION: IN PROGRESS",
            ">>> QUERY RESOLVED",
            ">>> RIBBON CABLE: SECURE",
            ">>> SHADOW PROTOCOL: ENGAGED",
            ">>> TUNNEL TO LAYER 08: OPEN",
            ">>> UNKNOWN SIGNAL: ANALYZING",
            ">>> VISION AUGMENTATION: ACTIVE",
            ">>> WALL BREACH: CONTAINED",
            ">>> XEROX PARC PROTOCOL: ACTIVE",
            ">>> YOUTH MEMORY: ACCESSED",
            ">>> ZEAL MODE: DISABLED"
        ]

        if random.random() < 0.2:
            self._add_terminal_text(random.choice(messages) + "\n")

    def end_game(self):
        """End the current game session"""
        self.game_active = False
        self.game_timer.stop()
        self.message_timer.stop()
        self.bonus_timer.stop()
        self.grace_period_time = 0.0
        self.bonus_time_to_add = 0.0

        # Calculate final score
        level_bonus = self.level * 50
        sequence_bonus = self.completed_sequences * 75
        final_score = self.score + level_bonus + sequence_bonus

        # Terminal messages
        self._add_terminal_text("\n>>> CONNECTION TERMINATED\n")
        self._add_terminal_text(">>> SESSION SUMMARY:\n")
        self._add_terminal_text(f">>> LEVEL REACHED: {self.level}\n")
        self._add_terminal_text(f">>> SEQUENCES: {self.completed_sequences}\n")
        self._add_terminal_text(f">>> FINAL SCORE: {final_score}\n")

        # Lain quotes based on score
        if final_score >= 1000:
            quote = ">>> LET'S ALL LOVE LAIN"
        elif final_score >= 500:
            quote = ">>> PRESENT DAY, PRESENT TIME"
        elif final_score >= 200:
            quote = ">>> AND YOU DON'T SEEM TO UNDERSTAND"
        else:
            quote = ">>> GOD IS IN THE WIRED"

        self._add_terminal_text(f">>> {quote}\n")

        # Update buttons
        self.start_button.setHidden(False)
        self.start_button.setText("REINITIALIZE CONNECTION")

        # Hide all command buttons
        for btn in self.command_buttons:
            btn.setText("")
            btn.setEnabled(False)
            btn.setHidden(True)

        # Reset time bar style
        self.time_bar.setStyleSheet("")

        # Emit score
        self.game_completed.emit(final_score)

        logger.info(f"Lain minigame ended with score: {final_score}")

        # Ask to play again
        reply = QMessageBox.question(
            self, "Session Terminated",
            f"Final Score: {final_score}\n\n"
            "Would you like to play again?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes
        )

        if reply == QMessageBox.StandardButton.Yes:
            # Reset for new game
            self.terminal_display.clear()
            self._add_terminal_text(">>> REINITIALIZING...\n")
            self._add_terminal_text(">>> THE WIRED AWAITS\n")
            self.start_game()

    def closeEvent(self, event):
        """Handle dialog closing"""
        self.game_timer.stop()
        self.message_timer.stop()
        self.bonus_timer.stop()
        super().closeEvent(event)
