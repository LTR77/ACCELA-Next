from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QMovie, QFont, QFontMetrics
from PyQt6.QtWidgets import QLabel, QPushButton

class ScaledLabel(QLabel):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setMinimumSize(1, 1)
        self._movie = None

    def setMovie(self, movie):
        if self._movie:
            self._movie.frameChanged.disconnect(self.on_frame_changed)
        self._movie = movie
        if self._movie:
            self._movie.frameChanged.connect(self.on_frame_changed)

    def on_frame_changed(self, frame_number):
        if self.size().width() > 0 and self.size().height() > 0 and self._movie:
            pixmap = self._movie.currentPixmap()
            scaled_pixmap = pixmap.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            super().setPixmap(scaled_pixmap)

    def resizeEvent(self, event):
        if self._movie:
            self.on_frame_changed(0)
        super().resizeEvent(event)


class ScaledFontLabel(QLabel):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setMinimumSize(1, 1)
        self.setWordWrap(True)  # Enable word wrap
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)  # Center text

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Get text metrics to check if text fits
        font = self.font()
        text = self.text()

        if text:
            # Start with height-based size
            new_size = max(8, min(72, int(self.height() * 0.4)))
            font.setPointSize(new_size)

            # Check if text fits width-wise
            test_font = QFont(font)
            test_font.setPointSize(new_size)
            metrics = QFontMetrics(test_font)
            text_width = metrics.horizontalAdvance(text)

            # Reduce font size if text is too wide (with some padding)
            while text_width > self.width() * 0.9 and new_size > 8:
                new_size -= 1
                test_font.setPointSize(new_size)
                metrics = QFontMetrics(test_font)
                text_width = metrics.horizontalAdvance(text)

            font.setPointSize(new_size)

        self.setFont(font)


class ScaledButton(QPushButton):
    """QPushButton that automatically scales its font to fit the button size"""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setMinimumSize(1, 1)
        self.max_font_size = 14

    def set_max_font_size(self, size):
        """Set maximum font size for scaling"""
        self.max_font_size = max(8, size)
        self._scale_font()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._scale_font()

    def setText(self, text):
        """Override setText to trigger font scaling immediately"""
        super().setText(text)
        self._scale_font()

    def _scale_font(self):
        """Calculate and set appropriate font size for current text and button size"""
        text = self.text()
        button_width = self.width()
        button_height = self.height()

        if text and button_width > 0 and button_height > 0:
            font = self.font()
            new_size = max(8, min(self.max_font_size, int(button_height * 0.4)))
            font.setPointSize(new_size)
            self.setFont(font)
