# Split responsibility from main.py
# Split into readable functions in appliance with DRY

from PyQt6.QtGui import QColor, QFont, QFontDatabase, QPalette
from utils.paths import Paths
from pathlib import Path
import logging
import random

ACCENT_COLOR_LIST = ["#C06C84", "#CE2029", "#035096", "#00FA9A", "#FF8C00"]

def normal_palette_colors(background_color,accent_color): 
    return {
        QPalette.ColorRole.Window: background_color,
        QPalette.ColorRole.WindowText: accent_color,
        QPalette.ColorRole.Base: background_color.darker(120),
        QPalette.ColorRole.AlternateBase: background_color,
        QPalette.ColorRole.ToolTipBase: accent_color,
        QPalette.ColorRole.ToolTipText: background_color,
        QPalette.ColorRole.Text: accent_color,
        QPalette.ColorRole.Button: background_color,
        QPalette.ColorRole.ButtonText: accent_color,
        QPalette.ColorRole.BrightText: accent_color.lighter(120),
        QPalette.ColorRole.Link: accent_color.lighter(120),
        QPalette.ColorRole.Highlight: accent_color,
        QPalette.ColorRole.HighlightedText: background_color,
        QPalette.ColorRole.PlaceholderText: accent_color.darker(120),
    }

def disabled_palette_colors(disabled_bg, disabled_text, background_color):
    return {
        QPalette.ColorRole.Button: disabled_bg,
        QPalette.ColorRole.ButtonText: disabled_text,
        QPalette.ColorRole.Text: disabled_text,
        QPalette.ColorRole.WindowText: disabled_text,
        QPalette.ColorRole.Base: background_color.darker(140),
    }

def apply_palette(app,accent,background):
    app.setStyle("Fusion")
    dark_palette = QPalette()

    background_color = QColor(background)
    accent_color = QColor(accent)
    
    disabled_bg = background_color.darker(200)
    disabled_text = QColor(100, 100, 100)

    for role, color in normal_palette_colors(background_color,accent_color).items():
        dark_palette.setColor(role, color)
    for role,color in disabled_palette_colors(disabled_bg,disabled_text,background_color).items():
        dark_palette.setColor(QPalette.ColorGroup.Disabled, role, color)

    app.setPalette(dark_palette)

    hover_lightness = 120
    selected_lightness = 150
    checked_lightness = 200
    doubled_lightness = 250
    background_color_effect = background_color
    if background_color_effect == QColor("#000000"):
        background_color_effect = QColor("#282828")

    gradient_border = f"""
            border-top: 2px solid {accent_color.lighter(120).name()};
            border-bottom: 2px solid {accent_color.lighter(120).name()};
            border-left: 2px solid qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {accent_color.lighter(120).name()}, stop:0.5 {background_color.lighter(120).name()}, stop:1 {accent_color.lighter(120).name()});
            border-right: 2px solid qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {accent_color.lighter(120).name()}, stop:0.5 {background_color.lighter(120).name()}, stop:1 {accent_color.lighter(120).name()});
    """
    gradient_border_full = f"""
            border-top: 2px solid {accent_color.lighter(120).name()};
            border-bottom: 2px solid {accent_color.lighter(120).name()};
            border-left: 2px solid {accent_color.lighter(120).name()};
            border-right: 2px solid {accent_color.lighter(120).name()};
    """

    app.setStyleSheet(f"""
        QLineEdit {{
            background-color: {background_color.name()};
            color: {accent_color.name()};
            border: 1px solid {accent_color.name()};
            padding: 8px;
        }}

        QLineEdit:hover {{
            background-color: {background_color.name()};
            color: {accent_color.name()};
        }}

        QCheckBox {{
            background-color: {background_color.name()};
            color: {accent_color.name()};
            padding: 8px;
            spacing: 8px;
        }}

        QCheckBox::indicator {{
            width: 12px;
            height: 12px;
            background: {background_color.name()};
            {gradient_border}
        }}

        QCheckBox::indicator:checked {{
            background: {accent_color.name()};
        }}

        QCheckBox::indicator:hover {{
            {gradient_border_full}
        }}

        QDialog {{
            background-color: {background_color.name()};
            color: {accent_color.name()};
        }}

        QListWidget {{
            background-color: {background_color.darker(120).name()};
            color: {accent_color.name()};
            border-radius: 4px;
            /* VVV REMOVES THE WEIRD LITTLE TEXT BORDER/BACKGROUND IN DEPOT SELECTION VVV */
            outline: 0;
            border: none;
        }}

        QListWidget::item {{
            background-color: {background_color.darker(120).name()};
            color: {accent_color.name()};
            border-radius: 4px;
            padding: 6px;
        }}

        QListWidget::item:hover {{
            background-color: {background_color_effect.lighter(hover_lightness).name()};
            color: {accent_color.name()};
        }}

        QListWidget::item:selected {{
            background-color: {background_color_effect.lighter(selected_lightness).name()};
            color: {accent_color.name()};
        }}

        QListWidget::item:checked {{
            background-color: {background_color_effect.lighter(checked_lightness).name()};
            color: {accent_color.name()};
            font-weight: bold;
        }}

        QListWidget::item:checked:selected {{
            background-color: {background_color_effect.lighter(doubled_lightness).name()};
            color: {accent_color.name()};
        }}

        QListWidget::indicator {{
            {gradient_border}
            border-radius: 4px;
        }}

        QListWidget::indicator:unchecked {{
            background-color: {background_color.name()};
        }}

        QListWidget::indicator:checked {{
            background-color: {accent_color.name()};
        }}

        QListWidget::indicator:hover {{
            {gradient_border_full}
        }}

        QPushButton {{
            background-color: {background_color.name()};
            color: {accent_color.name()};
            padding: 6px 6px;
            {gradient_border}
            font-weight: bold;
        }}

        QPushButton:hover {{
            background-color: {accent_color.name()};
            color: {background_color.name()};
            {gradient_border_full}
        }}

        QPushButton:disabled {{
            background-color: {disabled_bg.name()};
            color: {disabled_text.name()};
            border: 1px solid {disabled_text.name()};
            font-weight: normal;
        }}

        QPushButton:disabled:hover {{
            background-color: {disabled_bg.name()};
            color: {disabled_text.name()};
        }}

        QLabel {{
            color: {accent_color.name()};
        }}

        QToolTip {{
            background-color: {background_color.name()};
            color: {accent_color.name()};
            padding: 6px;
        }}
    """)

def apply_font(app, font, font_file):
    """
    Applies the font to the application.
    
    If font_file is provided, loads that font file and applies it.
    If font is provided (with a family name), checks if it's a system font and uses it.
    Otherwise, falls back to the default TrixieCyrG font.
    """

    logger = logging.getLogger(__name__)
    default_font_file = "TrixieCyrG-Plain Regular.otf"
    
    # If a specific font file is provided, load it
    if font_file:
        font_resource = font_file
    elif font and font.family():
        # Check if the font family exists in the system
        font_family = font.family()
        available_families = QFontDatabase.families()
        
        if font_family in available_families:
            # Font is a system font, just apply it directly
            logger.debug(f"Using system font: {font_family}")
            app.setFont(font)
            return True, font_family
        else:
            # Font family not found, try to load default
            logger.debug(f"Font family '{font_family}' not found in system, using default")
            font_resource = default_font_file
    else:
        font_resource = default_font_file

    # Resolve font_resource: accept Path, absolute path, or relative resource path
    try:
        if isinstance(font_resource, (str,)):
            # If it's an absolute path and exists, use it; otherwise treat as resource path
            candidate = Path(font_resource)
            if candidate.is_absolute() and candidate.exists():
                font_path = candidate
            else:
                font_path = Paths.resource(font_resource)
        elif isinstance(font_resource, Path):
            font_path = font_resource
        else:
            font_path = Paths.resource(str(font_resource))
    except Exception:
        font_path = Paths.resource(str(font_resource))

    logger.debug(f"Attempting to load font from: {font_path}")
    if not font_path.exists():
        logger.warning(f"Font file not found at: {font_path}")
        return False, font_path

    font_id = QFontDatabase.addApplicationFont(str(font_path))
    if font_id == -1:
        logger.warning(f"QFontDatabase failed to load font: {font_path}")
        return False, font_path

    families = QFontDatabase.applicationFontFamilies(font_id)
    if not families:
        logger.warning(f"No font families returned for: {font_path}")
        return False, font_path

    font_name = families[0]
    if not font:
        font = QFont(font_name, 10)
    else:
        # If a font file was provided, force the family to the loaded one
        font.setFamily(font_name)
    app.setFont(font)

    # Prefer returning the registered family name
    return True, families[0]

def update_appearance(app, accent=random.choice(ACCENT_COLOR_LIST), background="#000000", font=None, font_file=None):
    """Apply a dynamic palette and custom font to the application

    font_file: relative resource path (eg. "res/sonic-1-hud-font.otf") to load
    instead of the default embedded font.
    """

    apply_palette(app,accent,background)
    return apply_font(app,font,font_file)
