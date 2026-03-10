"""
Text-based menu system for CLI mode using urwid.
Supports both Linux and Windows terminals.
"""

import sys
import os
import logging 
from typing import Optional, Any, Union

if sys.platform == "win32":
    try:
        import windows_curses
        windows_curses.enable()
    except ImportError:
        pass

import urwid

logger = logging.getLogger(__name__)


class BaseTextMenu:
    """Base class for all text menus with common functionality."""

    def __init__(self, title: str, subtitle: str = ""):
        self.title = title
        self.subtitle = subtitle
        self.loop: Optional[urwid.MainLoop] = None
        self.result: Optional[Any] = None
        self.layout: urwid.Widget = urwid.Text("")  # Initialize default layout

    def run(self) -> Any:
        """Run the menu and return the result."""
        # Return early if result was set during __init__ (auto-skip case)
        if self.result is not None:
            return self.result

        self._build_menu()

        self.loop = urwid.MainLoop(
            self.layout,
            self._get_palette(),
            unhandled_input=self._handle_input,
            handle_mouse=False,
        )
        self.loop.run()
        return self.result

    def _get_palette(self) -> list:
        return [
            ('header', 'white,bold', '', 'bold'),
            ('title', 'white,bold', '', 'bold'),
            ('selected', 'light magenta,bold', '', 'standout'),
            ('info', 'light gray', '', ''),
            ('default', 'white', '', ''),
            ('footer', 'light magenta', '', ''),
        ]

    def _handle_input(self, key: Union[str, tuple]) -> Optional[bool]:
        """Handle keyboard input."""
        if isinstance(key, tuple):
            return None
        if key in ('q', 'Q', 'esc', 'Esc'):
            self.result = None
            raise urwid.ExitMainLoop()
        elif key == 'enter':
            return False
        elif key in ('up', 'down', 'page up', 'page down'):
            return False
        return None

    def _build_menu(self):
        """Subclasses must implement this to build the menu."""
        raise NotImplementedError

    def _create_header(self) -> urwid.Widget:
        """Create the menu header."""
        if self.subtitle:
            text = f"{self.title}\n{self.subtitle}"
        else:
            text = self.title

        header = urwid.Text(('header', text))
        divider = urwid.Divider('─')
        return urwid.Pile([header, divider])

    def _create_footer(self, instructions: str) -> urwid.Widget:
        """Create the menu footer with instructions."""
        footer = urwid.Text(('info', instructions))
        return urwid.AttrMap(footer, 'footer')


class DepotSelectionMenu(BaseTextMenu):
    """Text-based depot selection menu with multi-selection using urwid.CheckBox."""

    def __init__(self, app_id: str, game_name: str, depots: dict, header_url: Optional[str] = None):
        subtitle = f"AppID: {app_id}"
        super().__init__(f"Select Depots to Download - {game_name}", subtitle)
        self.depots = depots
        self.selected_depots = set()
        self.checkboxes = {}

        # Auto-skip when only one depot is available
        if len(self.depots) == 1:
            depot_id = list(self.depots.keys())[0]
            depot_desc = self.depots[depot_id].get('desc', 'Unknown')
            self.selected_depots = {depot_id}
            self.result = [depot_id]
            logger.info(f"Auto-selected single depot: {depot_id} - {depot_desc}")

    def _build_menu(self):
        """Build the depot selection menu."""
        sorted_depots = self._sort_depots()

        items = []
        for depot_id, depot_data in sorted_depots:
            item = self._create_depot_item(depot_id, depot_data)
            items.append(item)

        # Add confirm button at the end
        confirm_btn = urwid.Button(
            "  ✓ Confirm Selection  ",
            on_press=self._on_confirm_pressed,
        )
        items.append(urwid.AttrMap(confirm_btn, 'footer', 'footer:focus'))

        walker = urwid.SimpleListWalker(items)
        listbox = urwid.ListBox(walker)

        header = self._create_header()

        instructions = (
            "↑/↓: Navigate  Space: Toggle  "
            "A: All  D: None  Q: Cancel"
        )
        footer = self._create_footer(instructions)

        self.layout = urwid.Frame(
            urwid.AttrMap(listbox, 'default'),
            header=urwid.AttrMap(header, 'header'),
            footer=footer,
        )

    def _on_confirm_pressed(self, btn):
        """Handle confirm button press."""
        if self.selected_depots:
            self.result = list(self.selected_depots)
            raise urwid.ExitMainLoop()

    def _create_depot_item(self, depot_id: str, depot_data: dict):
        """Create a depot item widget using CheckBox."""
        desc = depot_data.get('desc', f'Depot {depot_id}')
        size = depot_data.get('size')

        size_str = ""
        if size:
            try:
                size_bytes = int(size)
                if size_bytes > 0:
                    size_gb = size_bytes / (1024 ** 3)
                    size_str = f" <{size_gb:.2f} GB>"
            except (ValueError, TypeError):
                pass

        item_text = f"{depot_id} - {desc}{size_str}"
        checked = depot_id in self.selected_depots

        checkbox = urwid.CheckBox(
            item_text,
            state=checked,
            on_state_change=self._on_checkbox_changed,
            user_data=depot_id,
        )

        self.checkboxes[depot_id] = checkbox
        return urwid.AttrMap(checkbox, 'default', 'selected')

    def _on_checkbox_changed(self, checkbox, new_state, user_data):
        """Handle checkbox state change."""
        depot_id = user_data
        if new_state:
            self.selected_depots.add(depot_id)
        else:
            self.selected_depots.discard(depot_id)

    def _sort_depots(self) -> list:
        """Sort depots using same logic as GUI version."""
        def get_sort_key(depot_item):
            depot_id, depot_data = depot_item

            os_val = depot_data.get("oslist")
            if os_val is None:
                os_str = "zzzz"
            else:
                os_str = os_val.lower()

            os_priority = 4
            if os_str == "windows":
                os_priority = 1
            elif os_str == "linux":
                os_priority = 2
            elif "all" in os_str:
                os_priority = 3
            elif os_str in ("macosx", "macos"):
                os_priority = 5

            desc_str = depot_data.get("desc", "").lower()
            lang_val = depot_data.get("language")

            lang_priority = 3
            lang_sort_key = lang_val.lower() if lang_val else "zzzz"

            is_no_language = (
                lang_val is None
                and "english" not in desc_str
                and "japanese" not in desc_str
            )

            if "english" in desc_str:
                lang_priority = 1
                lang_sort_key = lang_val.lower() if lang_val else "english"
            elif is_no_language:
                lang_priority = 1
                lang_sort_key = "english"
            elif "japanese" in desc_str:
                lang_priority = 2
                lang_sort_key = "japanese"

            return (os_priority, lang_priority, lang_sort_key, depot_id)

        return sorted(self.depots.items(), key=get_sort_key)

    def _handle_input(self, key: Union[str, tuple]) -> Optional[bool]:
        """Handle special keyboard shortcuts."""
        if isinstance(key, tuple):
            return None
        if key in ('q', 'Q', 'esc', 'Esc'):
            self.result = None
            raise urwid.ExitMainLoop()
        elif key in ('a', 'A'):
            # Select all
            self.selected_depots = set(self.depots.keys())
            self._update_all_checkboxes()
            return False
        elif key in ('d', 'D'):
            # Deselect all
            self.selected_depots = set()
            self._update_all_checkboxes()
            return False
        # Note: Enter now navigates down (to Confirm button)
        else:
            return super()._handle_input(key)

    def _update_all_checkboxes(self):
        """Update all checkboxes to reflect current selection."""
        for depot_id, checkbox in self.checkboxes.items():
            checkbox.set_state(depot_id in self.selected_depots, do_callback=False)


class DlcSelectionMenu(BaseTextMenu):
    """Text-based DLC selection menu using urwid.CheckBox."""

    def __init__(self, dlcs: dict):
        title = "Select DLC for SLSsteam Wrapper" if sys.platform != "win32" else "Select DLC for GreenLuma Wrapper"
        super().__init__(title)
        self.dlcs = dlcs
        self.selected_dlcs = set()
        self.checkboxes = {}

    def _build_menu(self):
        """Build the DLC selection menu."""
        items = []
        for dlc_id, dlc_desc in self.dlcs.items():
            item = self._create_dlc_item(dlc_id, dlc_desc)
            items.append(item)

        # Add confirm button at the end
        confirm_btn = urwid.Button(
            "  ✓ Confirm Selection  ",
            on_press=self._on_confirm_pressed,
        )
        items.append(urwid.AttrMap(confirm_btn, 'footer', 'footer-focus'))

        walker = urwid.SimpleListWalker(items)
        listbox = urwid.ListBox(walker)

        header = self._create_header()

        instructions = (
            "↑/↓: Navigate  Space: Toggle  "
            "A: All  D: None  Q: Cancel"
        )
        footer = self._create_footer(instructions)

        self.layout = urwid.Frame(
            urwid.AttrMap(listbox, 'default'),
            header=urwid.AttrMap(header, 'header'),
            footer=footer,
        )

    def _on_confirm_pressed(self, btn):
        """Handle confirm button press."""
        if self.selected_dlcs:
            self.result = list(self.selected_dlcs)
            raise urwid.ExitMainLoop()

    def _create_dlc_item(self, dlc_id: str, dlc_desc: str):
        """Create a DLC item widget."""
        item_text = f"{dlc_id} - {dlc_desc}"
        checked = dlc_id in self.selected_dlcs

        checkbox = urwid.CheckBox(
            item_text,
            state=checked,
            on_state_change=self._on_checkbox_changed,
            user_data=dlc_id,
        )

        self.checkboxes[dlc_id] = checkbox
        return urwid.AttrMap(checkbox, 'default', 'selected')

    def _on_checkbox_changed(self, checkbox, new_state, user_data):
        """Handle checkbox state change."""
        dlc_id = user_data
        if new_state:
            self.selected_dlcs.add(dlc_id)
        else:
            self.selected_dlcs.discard(dlc_id)

    def _handle_input(self, key: Union[str, tuple]) -> Optional[bool]:
        """Handle special keyboard shortcuts."""
        if isinstance(key, tuple):
            return None
        if key in ('q', 'Q', 'esc', 'Esc'):
            self.result = None
            raise urwid.ExitMainLoop()
        elif key in ('a', 'A'):
            self.selected_dlcs = set(self.dlcs.keys())
            self._update_all_checkboxes()
            return False
        elif key in ('d', 'D'):
            self.selected_dlcs = set()
            self._update_all_checkboxes()
            return False
        # Note: Enter now navigates down (to Confirm button)
        else:
            return super()._handle_input(key)

    def _update_all_checkboxes(self):
        """Update all checkboxes to reflect current selection."""
        for dlc_id, checkbox in self.checkboxes.items():
            checkbox.set_state(dlc_id in self.selected_dlcs, do_callback=False)


class SteamLibraryMenu(BaseTextMenu):
    """Text-based Steam library selection menu using urwid.RadioButton."""

    def __init__(self, library_paths: list):
        super().__init__("Select Steam Library")
        self.library_paths = library_paths
        self.radio_buttons = {}
        self._radio_group = []  # urwid radio button group
        self._listbox = None  # ListBox reference
        self._selected_path = library_paths[0] if library_paths else None  # Current selection

        # Auto-skip when only one library is available
        if len(self.library_paths) == 1:
            logger.info(f"Auto-selected single Steam library: {self._selected_path}")
            self.result = self._selected_path

    def _build_menu(self):
        """Build the library selection menu."""
        items = []
        for path in self.library_paths:
            item = self._create_library_item(path)
            items.append(item)

        # Add confirm button at the end
        confirm_btn = urwid.Button(
            "  ✓ Confirm Selection  ",
            on_press=self._on_confirm_pressed,
        )
        items.append(urwid.AttrMap(confirm_btn, 'footer', 'footer-focus'))

        walker = urwid.SimpleListWalker(items)
        listbox = urwid.ListBox(walker)
        self._listbox = listbox  # Store reference

        header = self._create_header()

        instructions = "↑/↓: Navigate  Enter: Confirm  Q: Cancel"
        footer = self._create_footer(instructions)

        self.layout = urwid.Frame(
            urwid.AttrMap(listbox, 'default'),
            header=urwid.AttrMap(header, 'header'),
            footer=footer,
        )

    def _on_confirm_pressed(self, btn):
        """Handle confirm button press."""
        if self._selected_path:
            self.result = self._selected_path
            raise urwid.ExitMainLoop()

    def _create_library_item(self, path: str):
        """Create a library item widget."""
        radio = urwid.RadioButton(
            self._radio_group,
            path,
            state=path == self.library_paths[0] if self.library_paths else False,
            on_state_change=self._on_radio_changed,
            user_data=path,
        )
        self.radio_buttons[path] = radio
        return urwid.AttrMap(radio, 'default', 'selected')

    def _on_radio_changed(self, radio, new_state, user_data):
        """Handle radio button selection."""
        if new_state:
            self._selected_path = user_data

    def _handle_input(self, key: Union[str, tuple]) -> Optional[bool]:
        """Handle special keyboard shortcuts."""
        if isinstance(key, tuple):
            return None
        if key in ('q', 'Q', 'esc', 'Esc'):
            self.result = None
            raise urwid.ExitMainLoop()
        # Note: Enter now navigates down (to Confirm button)
        else:
            return super()._handle_input(key)


class DestinationPathMenu(BaseTextMenu):
    """Text-based destination path selection."""

    def __init__(self, default_path: Optional[str] = None):
        super().__init__("Select Destination Folder")
        self.default_path = default_path or os.path.expanduser("~")
        self.current_path = self.default_path
        self.edit: Optional[urwid.Edit] = None

    def _build_menu(self):
        """Build the path selection menu."""
        # Current path display
        path_label = urwid.Text(('title', "Current Path:"))
        path_display = urwid.Text(('default', f"  {self.current_path}"))

        # Navigation options
        nav_options = urwid.Text(('info', "\nOptions:"))
        opt1 = urwid.Text("  [Enter] - Use current path")
        opt2 = urwid.Text("  [Type]  - Enter new path")
        opt3 = urwid.Text("  [H]     - Go to home directory (~)")
        opt4 = urwid.Text("  [Q]     - Cancel")

        # Edit widget for path input
        edit_label = urwid.Text(('title', "\nEnter path:"))
        self.edit = urwid.Edit("", self.current_path)

        # Create pile
        pile = urwid.Pile([
            path_label,
            path_display,
            urwid.Divider(' '),
            nav_options,
            opt1,
            opt2,
            opt3,
            opt4,
            urwid.Divider(' '),
            edit_label,
            urwid.AttrMap(self.edit, 'default'),
        ])

        header = self._create_header()

        self.layout = urwid.Frame(
            urwid.AttrMap(pile, 'default'),
            header=urwid.AttrMap(header, 'header'),
        )

    def _handle_input(self, key: Union[str, tuple]) -> Optional[bool]:
        """Handle keyboard input."""
        if isinstance(key, tuple):
            return None
        if key in ('q', 'Q', 'esc', 'Esc'):
            self.result = None
            raise urwid.ExitMainLoop()
        elif key == 'enter':
            if self.edit:
                path = self.edit.get_edit_text().strip()
                if path:
                    self.result = os.path.expanduser(os.path.expandvars(path))
                else:
                    self.result = self.default_path
            else:
                self.result = self.default_path
            raise urwid.ExitMainLoop()
        elif key in ('h', 'H'):
            if self.edit:
                self.edit.set_edit_text("~")
            return False
        else:
            # Let urwid handle typing in edit widget
            return None


# Convenience functions

def select_depots(app_id: str, game_name: str, depots: dict, header_url: Optional[str] = None) -> list:
    """Show depot selection menu."""
    menu = DepotSelectionMenu(app_id, game_name, depots, header_url)
    return menu.run()


def select_dlcs(dlcs: dict) -> list:
    """Show DLC selection menu."""
    if not dlcs:
        return []
    menu = DlcSelectionMenu(dlcs)
    return menu.run() or []


def select_steam_library(library_paths: list) -> Optional[str]:
    """Show Steam library selection menu."""
    if not library_paths:
        return None
    menu = SteamLibraryMenu(library_paths)
    return menu.run()


def select_destination_path(default_path: Optional[str] = None) -> Optional[str]:
    """Show destination path selection menu."""
    menu = DestinationPathMenu(default_path)
    return menu.run()
