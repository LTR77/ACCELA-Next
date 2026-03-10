import logging

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QColor, QIcon, QMovie, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QWidget, QSizePolicy

from utils.helpers import get_base_path#, resource_path
from utils.settings import get_settings

from utils.version import app_version

from .assets import (
    AUDIO_SVG,
    BOOK_SVG,
    GEAR_SVG,
    MAXIMIZE,
    MINIMIZE,
    PALETTE_SVG,
    POWER_SVG,
    SEARCH_SVG,
)

logger = logging.getLogger(__name__)


class ClickableLabel(QLabel):
    def __init__(self, text, parent=None, callback=None):
        super().__init__(text, parent)
        self.callback = callback
        self.setStyleSheet("cursor: pointer;")

    def mousePressEvent(self, ev):
        if self.callback:
            self.callback()
        super().mousePressEvent(ev)


class BottomTitleBar(QFrame):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.drag_pos = None
        self.setFixedHeight(32)

        self.no_previous_state = True
        self._apply_style()

        logger.debug("CustomTitleBar initialized.")

        layout = QHBoxLayout()
        layout.setContentsMargins(5, 0, 5, 0)
        layout.setSpacing(5)

        left_widget = QWidget()
        left_layout = QHBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)

        self.navi_label = QLabel()
        self.navi_movie = QMovie(str(get_base_path() / "gifs/colorized/navi.gif"))

        if self.navi_movie.isValid():
            self.navi_movie.jumpToFrame(0)
            orig = self.navi_movie.currentImage().size()
            h, w = (20, int(20 * (orig.width() / orig.height())) if orig.height() > 0 else 57)  # fallback number 84x29 -> 57x20
            self.navi_movie.setScaledSize(QSize(w, h))
            self.navi_label.setFixedSize(w, h)
            self.navi_label.setMovie(self.navi_movie)
            self.navi_movie.start()

        left_layout.addWidget(self.navi_label, alignment=Qt.AlignmentFlag.AlignLeft)

        right_widget = QWidget()
        right_layout = QHBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(2)

        # Maintains normal size even when left side is big
        right_layout.addStretch()

        self.status_button = self._create_colored_circle_button("#FF0000", parent.open_status_dialog, "Download Status")
        right_layout.addWidget(self.status_button)

        self.search_button = self._create_svg_button(SEARCH_SVG, parent.open_fetch_dialog, "Download Game")
        right_layout.addWidget(self.search_button)

        self.game_library_button = self._create_svg_button(BOOK_SVG, parent.open_game_library, "Game Library")
        right_layout.addWidget(self.game_library_button)

        self.settings_button = self._create_svg_button(GEAR_SVG, parent.open_settings, "Settings")
        right_layout.addWidget(self.settings_button)

        # Window control buttons (minimize, maximize)
        self.minimize_button = self._create_svg_button(MINIMIZE, self._minimize_window, "Minimize")
        right_layout.addWidget(self.minimize_button)

        self.maximize_button = self._create_svg_button(MAXIMIZE, self._maximize_window, "Maximize")
        right_layout.addWidget(self.maximize_button)

        self.close_button = self._create_svg_button(POWER_SVG, parent.close, "Close")
        right_layout.addWidget(self.close_button)

        version_label = ClickableLabel(app_version, parent, parent.open_credits_dialog)
        version_label.setStyleSheet("color: #888888;")
        version_label.setToolTip("View credits")
        self.title_label = QLabel("ACCELA")

        left_layout.addWidget(version_label, alignment=Qt.AlignmentFlag.AlignLeft)

        # Calculate actual widths of side widgets
        left_widget.setMinimumSize(left_widget.sizeHint())
        right_widget.setMinimumSize(right_widget.sizeHint())

        # Force both side widgets to have the same width
        max_side_width = max(left_widget.sizeHint().width(), right_widget.sizeHint().width())
        left_widget.setFixedWidth(max_side_width)
        right_widget.setFixedWidth(max_side_width)

        # Set size policies
        left_widget.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        right_widget.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        # Title label setup for perfect centering
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        layout.addWidget(left_widget, 0, Qt.AlignmentFlag.AlignLeft)

        # super duper secret comment telling you to have a great day :)
        layout.addWidget(self.title_label, 1)

        layout.addWidget(right_widget, 0, Qt.AlignmentFlag.AlignRight)

        self.setLayout(layout)

    def _apply_style(self):
        """Apply style settings from the parent window"""
        settings = get_settings()
        bg_color = settings.value("background_color", "#000000")
        accent_color = settings.value("accent_color", "#C06C84")

        self.setStyleSheet(f"""
            QFrame {{
                background-color: {bg_color};
            }}
            QToolTip {{
                color: {accent_color};
                background-color: {bg_color};
                border: 1px solid {accent_color};
                padding: 2px;
            }}
        """)

        # Update title label color
        if hasattr(self, "title_label"):
            self.title_label.setStyleSheet(f"color: {accent_color}; font-size: 14pt;")

    def update_style(self):
        """Update the style when colors change"""
        self._apply_style()
        self._update_button_colors()
        self._update_button_styles()

    def _update_button_styles(self):
        """Update all button styles with custom border and background color"""
        settings = get_settings()
        accent_color = QColor(settings.value("accent_color", "#C06C84"))
        background_color = QColor(settings.value("background_color", "#000000"))
        background_color_hover = background_color
        hover_lightness = 150
        if background_color == QColor("#000000"):
            background_color_hover = QColor("#282828")
            hover_lightness = 120

        button_style = f"""
            QPushButton {{
                background-color: {background_color.name()};
                border: none;
                border-radius: 3px;
                padding: 1px;
            }}
            QPushButton:hover {{
                background-color: {background_color_hover.lighter(hover_lightness).name()};
            }}
        """

        # Apply to all buttons
        buttons = [
            self.minimize_button,
            self.maximize_button,
            self.search_button,
            self.game_library_button,
            self.settings_button,
            self.close_button,
        ]

        for button in buttons:
            if button:
                button.setStyleSheet(button_style)

    def _update_button_colors(self):
        """Update all SVG button colors to match the current accent color"""
        settings = get_settings()
        accent_color = settings.value("accent_color", "#C06C84")

        # Update all SVG buttons
        buttons = [
            (self.minimize_button, MINIMIZE),
            (self.maximize_button, MAXIMIZE),
            (self.search_button, SEARCH_SVG),
            (self.game_library_button, BOOK_SVG),
            (self.settings_button, GEAR_SVG),
            (self.close_button, POWER_SVG),
        ]

        for button, svg_data in buttons:
            if button:
                self._update_svg_button_color(button, svg_data, accent_color)

        if self.no_previous_state:
            self._update_colored_circle_button(self.status_button, accent_color)

    def _update_colored_circle_button(self, button, color):
        """Update a colored circle button's color"""
        try:
            stylesheet = f"""
            QPushButton {{
                border-radius: 10px;
                background-color: {color};
                border: none;
            }}
            QPushButton:hover {{
                border: 2px solid {color};
                background-color: {color};
                opacity: 0.8;
            }}
            QPushButton:pressed {{
                opacity: 0.6;
            }}
            """

            button.setStyleSheet(stylesheet)

        except Exception as e:
            logger.error(f"Failed to update colored circle button: {e}", exc_info=True)

    def _update_svg_button_color(self, button, svg_data, color):
        """Update a single SVG button's color"""
        try:
            renderer = QSvgRenderer(svg_data.encode("utf-8"))
            icon_size = QSize(16, 16)

            pixmap = QPixmap(icon_size)
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)

            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            renderer.render(painter)

            painter.setCompositionMode(
                QPainter.CompositionMode.CompositionMode_SourceIn
            )
            painter.fillRect(pixmap.rect(), QColor(color))
            painter.end()

            icon = QIcon(pixmap)
            button.setIcon(icon)

        except Exception as e:
            logger.error(f"Failed to update SVG button color: {e}", exc_info=True)

    def _create_svg_button(self, svg_data, on_click, tooltip):
        try:
            button = QPushButton()
            button.setToolTip(tooltip)

            settings = get_settings()
            accent_color = QColor(settings.value("accent_color", "#C06C84"))
            background_color = QColor(settings.value("background_color", "#000000"))
            if background_color == QColor("#000000"):
                background_color = QColor("#282828")

            # Create colors for button styling
            hover_bg_color = background_color.lighter(120).name()
            border_hover_color = accent_color.darker(110).name()

            renderer = QSvgRenderer(svg_data.encode("utf-8"))
            icon_size = QSize(16, 16)

            pixmap = QPixmap(icon_size)
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)

            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            renderer.render(painter)

            painter.setCompositionMode(
                QPainter.CompositionMode.CompositionMode_SourceIn
            )
            painter.fillRect(pixmap.rect(), accent_color)
            painter.end()

            icon = QIcon(pixmap)

            button.setIcon(icon)
            button.setIconSize(icon_size)
            button.setFixedSize(20, 20)

            button.clicked.connect(on_click)
            return button
        except Exception as e:
            logger.error(f"Failed to create SVG button: {e}", exc_info=True)
            fallback_button = QPushButton("X")
            fallback_button.setFixedSize(20, 20)
            fallback_button.clicked.connect(on_click)
            return fallback_button

    def _create_colored_circle_button(self, color, callback, tooltip_text):
        """Create a simple colored circle button.

        Args:
            color: Hex color code for the button background
            callback: Function to call when button is clicked
            tooltip_text: Tooltip text to display on hover

        Returns:
            QPushButton: A colored circular button
        """
        button = QPushButton()
        button.setFixedSize(20, 20)

        if tooltip_text:
            button.setToolTip(tooltip_text)

        if callback:
            button.clicked.connect(callback)

        return button

    def _minimize_window(self):
        """Minimize the window"""
        self.parent.showMinimized()

    def _maximize_window(self):
        """Maximize or restore the window"""
        if self.parent.isMaximized():
            self.parent.showNormal()
        else:
            self.parent.showMaximized()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            # Check if we're not on a resize handle
            pos = event.pos()
            if not (
                pos.x() >= self.width() - 6
                or pos.x() <= 6
                or pos.y() <= 6
                or pos.y() >= self.height() - 6
            ):
                window = self.window().windowHandle()
                if window is not None:
                    window.startSystemMove()
            event.accept()


"""
The wired might actually be thought of as a highly advanced upper layer of the real world. In other words, physical reality is nothing but an illusion, a hologram of the information that flows to us through the wired.
This is because the body, physical motion, the activity of the human brain is merely a physical phenomenon, simply caused by synapses delivering electrical impulses.
The physical body exists at a less evolved plane only to verify one's existence in the universe.
"""
