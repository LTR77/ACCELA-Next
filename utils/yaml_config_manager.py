"""
YAML Configuration Manager

Provides helper functions for modifying YAML config files while preserving
comments, formatting, and whitespace.
"""

import logging
import os
import re
import shutil
from pathlib import Path

from utils.settings import get_settings

logger = logging.getLogger(__name__)

BACKUP_SUFFIX = ".bak"


def is_slssteam_mode_enabled() -> bool:
    """
    Check if SLSsteam mode is enabled in settings.

    Returns:
        True if SLSsteam mode is enabled, False otherwise
    """
    settings = get_settings()
    return settings.value("slssteam_mode", False, type=bool)


def is_slssteam_config_management_enabled() -> bool:
    """
    Check if SLSsteam config management is enabled in settings.

    Returns:
        True if config management is enabled, False otherwise
    """
    settings = get_settings()
    return settings.value("sls_config_management", True, type=bool)


def get_fake_appid_for_online() -> str:
    """
    Get the FakeAppId to use for playing games online.

    Returns:
        The appid from settings, or "480" (Spacewar) if not set
    """
    settings = get_settings()
    fake_appid = settings.value("fake_appid_for_online", "", type=str).strip()
    return fake_appid if fake_appid else "480"


def _create_backup(config_path: Path) -> bool:
    """
    Create a backup of the config file.

    Creates config.yaml.bak with the current config content.
    Only creates backup if source file exists.
    Does not overwrite existing backup if new file is smaller (protection against
    incomplete/corrupted files).

    Args:
        config_path: Path to the config file to backup

    Returns:
        True if backup was created or already exists, False otherwise
    """
    try:
        if not config_path.exists():
            return False

        backup_path = config_path.with_suffix(BACKUP_SUFFIX)

        # Check if backup already exists and new file is smaller
        if backup_path.exists():
            new_size = config_path.stat().st_size
            backup_size = backup_path.stat().st_size
            if new_size < backup_size:
                logger.debug(
                    f"Skipping backup: new file ({new_size} bytes) is smaller than "
                    f"existing backup ({backup_size} bytes)"
                )
                return True  # Keep existing backup, return success

        shutil.copy2(config_path, backup_path)
        logger.info(f"Created backup: {backup_path}")
        return True
    except Exception as e:
        logger.error(f"Failed to create backup for {config_path}: {e}", exc_info=True)
        return False


def backup_config_on_startup(config_path: Path) -> bool:
    """
    Create a backup of the config file on application startup.

    Should be called once at startup before any modifications are made.
    Backs up to config.yaml.bak (overwrites any existing backup).

    Args:
        config_path: Path to the config.yaml file

    Returns:
        True if backup exists or was created, False if config file missing
    """
    return _create_backup(config_path)


def _atomic_write(config_path: Path, content: str) -> bool:
    """
    Atomically write content to config file.

    Writes to a temporary file first, then atomically replaces the original.
    This ensures the original file is not corrupted if write is interrupted.

    Args:
        config_path: Path to the config file
        content: Content to write

    Returns:
        True if write succeeded, False otherwise
    """
    try:
        # Write to temp file in same directory (same filesystem = atomic rename)
        temp_path = config_path.with_suffix(config_path.suffix + ".tmp")
        with open(temp_path, "w", encoding="utf-8") as f:
            f.write(content)
        # Atomic replace
        os.replace(temp_path, config_path)
        return True
    except Exception as e:
        logger.error(f"Failed to atomically write {config_path}: {e}", exc_info=True)
        # Clean up temp file if it exists
        if temp_path.exists():
            try:
                temp_path.unlink()
            except Exception:
                pass
        return False


def ensure_slssteam_api_enabled(config_path: Path) -> bool:
    """
    Ensure SLSsteam API is enabled in config.yaml.

    Sets API: yes if not already present or set to a different value.
    Only performs the update if SLSsteam mode and config management are enabled in settings.

    Args:
        config_path: Path to the SLSsteam config.yaml file

    Returns:
        True if API is enabled (already was or was set), False on error or if mode is disabled
    """
    if not is_slssteam_mode_enabled():
        logger.debug("SLSsteam mode is disabled, skipping API enable check")
        return False
    if not is_slssteam_config_management_enabled():
        logger.debug("SLSsteam config management is disabled, skipping API enable check")
        return False
    return update_yaml_boolean_value(config_path, "API", True)


def update_yaml_boolean_value(config_path: Path, key: str, value: bool) -> bool:
    """
    Updates a boolean value in YAML config using regex pattern matching.

    This function preserves ALL comments, whitespace, and formatting by only
    modifying the specific value line for the given key.

    Args:
        config_path: Path to the YAML config file
        key: The YAML key to update (e.g., 'PlayNotOwnedGames')
        value: Boolean value to set

    Returns:
        True if value was updated, False if already set correctly or key not found
    """
    try:
        if not config_path.exists():
            logger.warning(f"Config file not found at {config_path}")
            return False

        # Read the file content
        with open(config_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Regex pattern to match the key with its current value
        # Captures: (1) indentation, (2) key name, (3) current value
        pattern = re.compile(
            r"^(\s*)"
            + re.escape(key)
            + r"\s*:\s*(yes|no|true|false|Yes|No|True|False)\b",
            re.MULTILINE,
        )

        match = pattern.search(content)
        if not match:
            logger.warning(f"Key '{key}' not found in config file {config_path}")
            return False

        indent = match.group(1)
        old_value = match.group(2)

        # Always use yes/no format for SLSsteam compatibility
        new_value = "yes" if value else "no"

        # Check if already set correctly
        if old_value.lower() == new_value.lower():
            logger.debug(f"Key '{key}' is already set to {new_value}")
            return False

        # Create replacement string preserving indentation
        replacement = f"{indent}{key}: {new_value}"

        # Replace only the matched line
        new_content = pattern.sub(replacement, content)

        # Write back to file atomically
        if not _atomic_write(config_path, new_content):
            return False

        logger.info(f"Updated '{key}' to {new_value} in {config_path}")
        return True

    except Exception as e:
        logger.error(f"Failed to update '{key}' in {config_path}: {e}", exc_info=True)
        return False


def get_user_config_path() -> Path:
    """
    Get the path to the user's SLSsteam config.yaml file.

    Uses XDG_CONFIG_HOME if set, otherwise defaults to ~/.config.

    Returns:
        Path to the config.yaml file
    """
    xdg_config_home_str = os.environ.get("XDG_CONFIG_HOME", "")
    xdg_config_home = (
        Path(xdg_config_home_str).expanduser() if xdg_config_home_str else Path()
    )

    if xdg_config_home_str and xdg_config_home.is_absolute():
        config_dir = xdg_config_home / "SLSsteam"
    else:
        config_dir = Path.home() / ".config" / "SLSsteam"

    return config_dir / "config.yaml"


def _fix_additional_apps_indentation(content: str) -> tuple[str, bool]:
    """
    Fix indentation of AdditionalApps list items if they lack proper formatting.

    Ensures all list items under AdditionalApps: have 2-space indentation.
    Only fixes items within the AdditionalApps section, not other YAML lists.

    Args:
        content: The YAML file content

    Returns:
        Tuple of (fixed_content, was_modified)
    """
    # Find AdditionalApps section and only fix list items within it
    additional_apps_pattern = re.compile(r"^AdditionalApps:\s*$", re.MULTILINE)
    match = additional_apps_pattern.search(content)

    if not match:
        # No AdditionalApps section found, no changes needed
        return content, False

    # Find the end of AdditionalApps section (next top-level key or end of file)
    section_start = match.end()
    # Skip the newline after "AdditionalApps:"
    if section_start < len(content) and content[section_start] == "\n":
        section_start += 1
    after_section = content[section_start:]

    # Look for next top-level key (at start of line, word character)
    next_key_pattern = re.compile(r"^[A-Za-z]", re.MULTILINE)
    next_match = next_key_pattern.search(after_section)

    if next_match:
        section_end = section_start + next_match.start()
    else:
        section_end = len(content)

    # Extract just the AdditionalApps section content
    section_content = content[section_start:section_end]

    # Pattern to find list items that need fixing: "- item" or "-item" (no or 1 space indent)
    # within the AdditionalApps section
    misaligned_item_pattern = re.compile(
        r"(^)(\s*)-(\s*)([^\n#]+?)(?=\s*(?:#|$))", re.MULTILINE
    )

    # Find and fix misaligned items by adding 2-space indentation
    fixed_section = misaligned_item_pattern.sub(r"\1  - \4", section_content)

    was_modified = fixed_section != section_content
    if was_modified:
        # Reconstruct the content with fixed section
        fixed_content = content[:section_start] + fixed_section + content[section_end:]
        logger.debug("Fixed indentation of AdditionalApps list items")
        return fixed_content, True

    return content, False


def _get_app_tokens_section(content: str) -> str:
    """
    Extract the AppTokens section from YAML content.

    Returns only the content between AppTokens: and the next top-level key.
    Returns empty string if AppTokens section not found.

    Args:
        content: The YAML file content

    Returns:
        The AppTokens section content, or empty string if not found
    """
    app_tokens_pattern = re.compile(r"^AppTokens:\s*$", re.MULTILINE)
    match = app_tokens_pattern.search(content)

    if not match:
        return ""

    section_start = match.end()
    if section_start < len(content) and content[section_start] == "\n":
        section_start += 1
    after_section = content[section_start:]

    # Look for next top-level key (at start of line, word character)
    next_key_pattern = re.compile(r"^[A-Za-z][A-Za-z0-9]*:\s*$", re.MULTILINE)
    next_match = next_key_pattern.search(after_section)

    if next_match:
        section_end = section_start + next_match.start()
    else:
        section_end = len(content)

    return content[section_start:section_end]


def _fix_app_tokens_indentation(content: str) -> tuple[str, bool]:
    """
    Fix indentation of AppTokens entries to have 2-space indentation.

    Ensures all entries under AppTokens: have proper 2-space indentation.
    Only fixes items within the AppTokens section, not other YAML entries.

    Args:
        content: The YAML file content

    Returns:
        Tuple of (fixed_content, was_modified)
    """
    # Find AppTokens section
    app_tokens_pattern = re.compile(r"^AppTokens:\s*$", re.MULTILINE)
    match = app_tokens_pattern.search(content)

    if not match:
        # No AppTokens section found, no changes needed
        return content, False

    # Find the end of AppTokens section
    section_start = match.end()
    # Skip the newline after "AppTokens:"
    if section_start < len(content) and content[section_start] == "\n":
        section_start += 1
    after_section = content[section_start:]

    # Look for next top-level key (at start of line, word character, not a comment)
    # Ignore blank lines and comments (#) when looking for next section
    next_key_pattern = re.compile(r"^[A-Za-z][A-Za-z0-9]*:\s*$", re.MULTILINE)
    next_match = next_key_pattern.search(after_section)

    # Find the last token entry (line starting with digits)
    # This ensures we stop at the last token, not at subsequent comments
    last_token_pattern = re.compile(r"^\s*\d+\s*:\s*[^\n]*$", re.MULTILINE)
    last_token_matches = list(last_token_pattern.finditer(after_section))

    if last_token_matches:
        # End section after the last token line (include trailing newlines)
        last_token_end = last_token_matches[-1].end()
        # Find the next newline after the last token to include blank lines
        newline_after_token = after_section.find("\n", last_token_end)
        if newline_after_token != -1:
            section_end = section_start + newline_after_token + 1
        elif next_match:
            section_end = section_start + next_match.start()
        else:
            section_end = len(content)
    elif next_match:
        section_end = section_start + next_match.start()
    else:
        section_end = len(content)

    # Extract just the AppTokens section content
    section_content = content[section_start:section_end]

    # Pattern to find ALL token entries (any indentation) and force 2-space indentation
    # Matches lines starting with optional whitespace followed by digits and colon
    token_pattern = re.compile(r"(^)(\s*)(\d+)(\s*:\s*[^\n]*)", re.MULTILINE)

    # Replace all tokens with 2-space indentation
    fixed_section = token_pattern.sub(r"\1  \3\4", section_content)

    was_modified = fixed_section != section_content
    if was_modified:
        # Reconstruct the content with fixed section
        fixed_content = content[:section_start] + fixed_section + content[section_end:]
        logger.debug("Fixed indentation of AppTokens entries")
        return fixed_content, True

    return content, False


def fix_slssteam_config_indentation(config_path: Path) -> bool:
    """
    Fix indentation of AdditionalApps and AppTokens entries in SLSsteam config.yaml.

    This function ensures all list items under AdditionalApps: and entries under
    AppTokens: have proper 2-space indentation. Should be called after game library
    scan to fix any misformatted entries in the config file.
    Only performs the fix if SLSsteam mode and config management are enabled in settings.

    Args:
        config_path: Path to the YAML config file

    Returns:
        True if file was modified, False if already correct, file doesn't exist, or mode is disabled
    """
    if not is_slssteam_mode_enabled():
        logger.debug("SLSsteam mode is disabled, skipping indentation fix")
        return False
    if not is_slssteam_config_management_enabled():
        logger.debug("SLSsteam config management is disabled, skipping indentation fix")
        return False

    try:
        if not config_path.exists():
            return False

        with open(config_path, "r", encoding="utf-8") as f:
            content = f.read()

        fixed_content, was_modified_apps = _fix_additional_apps_indentation(content)
        fixed_content, was_modified_tokens = _fix_app_tokens_indentation(fixed_content)

        was_modified = was_modified_apps or was_modified_tokens

        if was_modified:
            if not _atomic_write(config_path, fixed_content):
                return False
            if was_modified_apps and was_modified_tokens:
                logger.info(
                    f"Fixed AdditionalApps and AppTokens indentation in {config_path}"
                )
            elif was_modified_apps:
                logger.info(f"Fixed AdditionalApps indentation in {config_path}")
            else:
                logger.info(f"Fixed AppTokens indentation in {config_path}")

        return was_modified

    except Exception as e:
        logger.error(f"Failed to fix indentation in {config_path}: {e}", exc_info=True)
        return False


def add_additional_app(config_path: Path, app_id: str, comment: str = "") -> bool:
    """
    Adds an AppID to the AdditionalApps list in SLSsteam config.yaml.

    This function preserves ALL comments, whitespace, and formatting by only
    appending to the list if the AppID is not already present. Also fixes
    indentation of existing items if needed.
    Only performs the addition if SLSsteam mode and config management are enabled in settings.

    Args:
        config_path: Path to the YAML config file
        app_id: The AppID to add
        comment: Optional comment to add after the AppID

    Returns:
        True if AppID was added, False if already exists, error, or mode is disabled
    """
    if not is_slssteam_mode_enabled():
        logger.debug("SLSsteam mode is disabled, skipping add additional app")
        return False
    if not is_slssteam_config_management_enabled():
        logger.debug("SLSsteam config management is disabled, skipping add additional app")
        return False

    try:
        # If file doesn't exist, create it with the new entry
        if not config_path.exists():
            # Ensure parent directory exists
            config_path.parent.mkdir(parents=True, exist_ok=True)
            if comment:
                new_entry = f"AdditionalApps:\n  - {app_id}   # {comment}\n"
            else:
                new_entry = f"AdditionalApps:\n  - {app_id}\n"
            if not _atomic_write(config_path, new_entry):
                return False
            logger.info(f"Created config file with AppID '{app_id}' in {config_path}")
            return True

        # Read the file content
        with open(config_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Fix indentation of existing AdditionalApps items
        fixed_content, _ = _fix_additional_apps_indentation(content)

        # Check if AppID already exists in AdditionalApps list
        # Match patterns like: "- 12345" or "- 12345   # comment"
        app_id_pattern = re.compile(
            rf"^\s*-\s*{re.escape(app_id)}\s*(?:#.*)?$", re.MULTILINE
        )

        if app_id_pattern.search(fixed_content):
            logger.debug(f"AppID '{app_id}' already exists in AdditionalApps")
            return False

        # Find AdditionalApps section
        additional_apps_pattern = re.compile(r"^AdditionalApps:\s*$", re.MULTILINE)
        match = additional_apps_pattern.search(fixed_content)

        if match:
            # Append to existing list
            # Find the end of the list by finding the last item (line starting with "-")
            start_pos = match.end()
            remaining = fixed_content[start_pos:]
            lines = remaining.split("\n")

            # Find position after the last list item
            insert_pos = start_pos
            last_item_end = start_pos

            for i, line in enumerate(lines):
                stripped = line.strip()
                if stripped.startswith("-"):
                    # This is a list item - update the end position
                    last_item_end = start_pos + sum(
                        len(lines[j]) + 1 for j in range(i + 1)
                    )
                elif not stripped:
                    # Empty line - continue
                    continue
                elif stripped.startswith("#"):
                    # Comment line - continue (comments can follow list items)
                    continue
                else:
                    # Any other non-empty, non-comment, non-list line is a new section
                    break
            else:
                # End of file
                last_item_end = len(fixed_content)

            insert_pos = last_item_end

            # Build new entry with proper indentation (2 spaces for list items)
            if comment:
                new_entry = f"  - {app_id}   # {comment}\n"
            else:
                new_entry = f"  - {app_id}\n"

            new_content = (
                fixed_content[:insert_pos] + new_entry + fixed_content[insert_pos:]
            )
        else:
            # Create new AdditionalApps section with proper indentation
            if comment:
                new_entry = f"AdditionalApps:\n  - {app_id}   # {comment}\n"
            else:
                new_entry = f"AdditionalApps:\n  - {app_id}\n"

            new_content = fixed_content + "\n" + new_entry

        # Write back to file atomically
        if not _atomic_write(config_path, new_content):
            return False

        logger.info(f"Added AppID '{app_id}' to AdditionalApps in {config_path}")
        return True

    except Exception as e:
        logger.error(
            f"Failed to add AppID '{app_id}' to {config_path}: {e}", exc_info=True
        )
        return False


def remove_additional_app(config_path: Path, app_id: str) -> bool:
    """
    Removes an AppID from the AdditionalApps list in SLSsteam config.yaml.

    This function removes the AppID entry while preserving other content,
    comments, and formatting.
    Only performs the removal if SLSsteam mode and config management are enabled in settings.

    Args:
        config_path: Path to the YAML config file
        app_id: The AppID to remove

    Returns:
        True if AppID was removed, False if not found, error, or mode is disabled
    """
    if not is_slssteam_mode_enabled():
        logger.debug("SLSsteam mode is disabled, skipping remove additional app")
        return False
    if not is_slssteam_config_management_enabled():
        logger.debug("SLSsteam config management is disabled, skipping remove additional app")
        return False

    try:
        if not config_path.exists():
            logger.debug(f"Config file does not exist at {config_path}")
            return False

        with open(config_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Pattern to match AppID in AdditionalApps list (with optional comment)
        # Matches: "- 12345" or "- 12345   # comment"
        app_id_pattern = re.compile(
            rf"^\s*-\s*{re.escape(app_id)}\s*(?:#.*)?$", re.MULTILINE
        )

        match = app_id_pattern.search(content)
        if not match:
            logger.debug(f"AppID '{app_id}' not found in AdditionalApps")
            return False

        # Find the line start and end
        line_start = content.rfind("\n", 0, match.start()) + 1  # Include newline before
        if line_start == 0:
            line_start = 0  # First line, no newline before
        line_end = content.find("\n", match.end())
        if line_end == -1:
            line_end = len(content)  # End of file

        # Check if there's a newline after the line
        if line_end < len(content) and content[line_end] == "\n":
            line_end += 1  # Include the newline

        # Remove the line
        new_content = content[:line_start] + content[line_end:]

        # Write back to file atomically
        if not _atomic_write(config_path, new_content):
            return False

        logger.info(f"Removed AppID '{app_id}' from AdditionalApps in {config_path}")
        return True

    except Exception as e:
        logger.error(
            f"Failed to remove AppID '{app_id}' from {config_path}: {e}", exc_info=True
        )
        return False


def add_dlc_data(
    config_path: Path, parent_app_id: str, dlc_id: str, dlc_name: str
) -> bool:
    """
    Adds a DLC entry to DlcData section in SLSsteam config.yaml.

    Format:
        DlcData:
          ParentAppId:
            DlcAppId: "Dlc Name"

    This function preserves ALL comments, whitespace, and formatting.
    Only performs the addition if SLSsteam mode and config management are enabled in settings.

    Args:
        config_path: Path to the YAML config file
        parent_app_id: The parent game AppID
        dlc_id: The DLC AppID
        dlc_name: The DLC name

    Returns:
        True if DLC was added, False if already exists, error, or mode is disabled
    """
    if not is_slssteam_mode_enabled():
        logger.debug("SLSsteam mode is disabled, skipping add DLC data")
        return False
    if not is_slssteam_config_management_enabled():
        logger.debug("SLSsteam config management is disabled, skipping add DLC data")
        return False

    try:
        if not config_path.exists():
            logger.warning(f"Config file not found at {config_path}")
            return False

        # Read the file content
        with open(config_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Find DlcData section
        dlc_data_pattern = re.compile(r"^DlcData:\s*$", re.MULTILINE)
        match = dlc_data_pattern.search(content)

        if match:
            dlc_data_start = match.start()
            dlc_data_end = match.end()

            # Find parent AppID under DlcData
            parent_pattern = re.compile(
                rf"^(\s*){re.escape(parent_app_id)}:\s*$", re.MULTILINE
            )
            parent_match = parent_pattern.search(content, dlc_data_end)

            if parent_match:
                # Check if DLC already exists under this parent
                parent_line_end = parent_match.end()
                remaining = content[parent_line_end:]

                # Look for next sibling (another AppID at same indent) or end of DlcData
                next_parent_pattern = re.compile(
                    rf"^(\s{{{len(parent_match.group(1))}}})[0-9]", re.MULTILINE
                )
                next_match = next_parent_pattern.search(remaining)

                if next_match:
                    parent_section = remaining[: next_match.start()]
                else:
                    # Find end of DlcData section
                    after_dlcdata = content[dlc_data_end:]
                    end_match = re.compile(r"^[A-Za-z]", re.MULTILINE).search(
                        after_dlcdata
                    )
                    if end_match:
                        parent_section = remaining[
                            : dlc_data_end + end_match.start() - parent_line_end
                        ]
                    else:
                        parent_section = remaining

                # Check if DLC already exists
                dlc_check_pattern = re.compile(
                    rf'^\s*{re.escape(dlc_id)}:\s*"', re.MULTILINE
                )
                if dlc_check_pattern.search(parent_section):
                    logger.debug(
                        f"DLC '{dlc_id}' already exists under AppID '{parent_app_id}'"
                    )
                    return False

                parent_indent = len(parent_match.group(1))

                # Find insertion position
                if next_match:
                    insert_pos = parent_line_end + next_match.start()
                else:
                    after_dlcdata = content[dlc_data_end:]
                    end_match = re.compile(r"^[A-Za-z]", re.MULTILINE).search(
                        after_dlcdata
                    )
                    if end_match:
                        insert_pos = dlc_data_end + end_match.start()
                    else:
                        insert_pos = len(content)

                # Build new DLC entry with proper indentation
                new_entry = f'{" " * (parent_indent + 2)}{dlc_id}: "{dlc_name}"\n'
                new_content = content[:insert_pos] + new_entry + content[insert_pos:]
            else:
                # Add new parent AppID section under DlcData
                remaining = content[dlc_data_end:]
                next_key_pattern = re.compile(r"^[A-Za-z]", re.MULTILINE)
                next_match = next_key_pattern.search(remaining)

                if next_match:
                    insert_pos = dlc_data_end + next_match.start()
                else:
                    insert_pos = len(content)

                # Build new section with DLC (parent at indent 2, DLC at indent 4)
                new_entry = f'  {parent_app_id}:\n    {dlc_id}: "{dlc_name}"\n'
                new_content = content[:insert_pos] + new_entry + content[insert_pos:]
        else:
            # Create new DlcData section with DLC
            new_entry = f'DlcData:\n  {parent_app_id}:\n    {dlc_id}: "{dlc_name}"\n'
            new_content = content + "\n" + new_entry

        # Write back to file atomically
        if not _atomic_write(config_path, new_content):
            return False

        logger.info(
            f"Added DLC '{dlc_name}' ({dlc_id}) to DlcData under "
            f"AppID '{parent_app_id}' in {config_path}"
        )
        return True

    except Exception as e:
        logger.error(
            f"Failed to add DLC '{dlc_id}' to {config_path}: {e}", exc_info=True
        )
        return False


def add_app_token(config_path: Path, app_id: str, token: str) -> bool:
    """
    Add an AppToken to the AppTokens section in SLSsteam config.yaml.

    Format:
        AppTokens:
          app_id: token_value

    This function ensures proper 2-space indentation for all entries.
    Only performs the addition if SLSsteam mode and config management are enabled in settings.

    Args:
        config_path: Path to the YAML config file
        app_id: The AppID
        token: The application token

    Returns:
        True if added/updated, False if already exists, error, or mode is disabled
    """
    if not is_slssteam_mode_enabled():
        logger.debug("SLSsteam mode is disabled, skipping add app token")
        return False
    if not is_slssteam_config_management_enabled():
        logger.debug("SLSsteam config management is disabled, skipping add app token")
        return False

    try:
        if not config_path.exists():
            logger.warning(f"Config file not found at {config_path}")
            return False

        # Read the file content
        with open(config_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Check if AppTokens section exists
        app_tokens_pattern = re.compile(r"^AppTokens:\s*$", re.MULTILINE)
        match = app_tokens_pattern.search(content)

        if not match:
            # Create new AppTokens section at the end
            new_entry = f"AppTokens:\n  {app_id}: {token}\n"
            if not _atomic_write(config_path, content + new_entry):
                return False
            logger.info(
                f"Added AppToken for '{app_id}' to new AppTokens section in {config_path}"
            )
            return True

        # Fix indentation of all tokens FIRST (before any modifications)
        fixed_content, was_fixed = _fix_app_tokens_indentation(content)

        # Write the fixed content if indentation was corrected
        if was_fixed:
            if not _atomic_write(config_path, fixed_content):
                return False
            logger.debug("Fixed AppTokens indentation before adding new token")
            content = fixed_content
        else:
            content = fixed_content

        # Now search for the token ONLY within the AppTokens section (not in FakeAppIds, etc.)
        app_tokens_section = _get_app_tokens_section(content)
        existing_pattern = re.compile(
            rf"^  {re.escape(app_id)}\s*:\s*(.+)$", re.MULTILINE
        )
        existing_match = existing_pattern.search(app_tokens_section)

        if existing_match:
            existing_token = existing_match.group(1).strip()
            if existing_token == token:
                logger.debug(f"AppToken for '{app_id}' already exists with same value")
                return False
            else:
                # Update existing token - calculate position in original content
                # Find start of AppTokens section in original content
                app_tokens_start = content.find("AppTokens:\n")
                if app_tokens_start == -1:
                    app_tokens_start = content.find("AppTokens:")
                # Position of the token in original content
                line_start_in_section = existing_match.start()
                line_start = (
                    app_tokens_start + len("AppTokens:\n") + line_start_in_section
                )
                line_end = line_start + len(existing_match.group(0))
                new_line = f"  {app_id}: {token}"
                new_content = content[:line_start] + new_line + content[line_end:]
                if not _atomic_write(config_path, new_content):
                    return False
                logger.info(f"Updated AppToken for '{app_id}' in {config_path}")
                return True

        # Add new token after AppTokens:
        new_token_line = f"  {app_id}: {token}"

        # Find first existing token to insert before (after _fix_app_tokens_indentation, all have 2-space indent)
        token_line_pattern = re.compile(r"(^AppTokens:\n)(  \S+:[^\n]*)", re.MULTILINE)
        token_match = token_line_pattern.search(content)

        if token_match:
            # Insert after first token, preserving everything before AppTokens:
            new_content = (
                content[: token_match.end()]  # Up to first token (no \n at end)
                + "\n"
                + new_token_line  # \n + new token (rest already has \n)
                + content[token_match.end() :]  # Remaining tokens (starts with \n)
            )
        else:
            # No existing tokens found - append after AppTokens: line
            new_content = content.replace(
                "AppTokens:", "AppTokens:\n" + new_token_line, 1
            )

        if not _atomic_write(config_path, new_content):
            return False

        logger.info(f"Added AppToken for '{app_id}' to AppTokens in {config_path}")
        return True

    except Exception as e:
        logger.error(
            f"Failed to add AppToken '{app_id}' to {config_path}: {e}", exc_info=True
        )
        return False


def get_app_tokens(config_path: Path) -> dict[str, str]:
    """
    Get all AppTokens from SLSsteam config.yaml.

    Args:
        config_path: Path to the YAML config file

    Returns:
        Dict mapping app_id -> token
    """
    tokens = {}

    try:
        if not config_path.exists():
            logger.debug(f"Config file not found at {config_path}")
            return tokens

        with open(config_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Find AppTokens section and extract all entries
        app_tokens_pattern = re.compile(r"^AppTokens:\s*$", re.MULTILINE)
        match = app_tokens_pattern.search(content)

        if not match:
            return tokens

        # Find the end of AppTokens section (next top-level key or end of file)
        section_start = match.end()
        after_section = content[section_start:]

        # Look for next top-level key (at start of line, word character)
        next_key_pattern = re.compile(r"^[A-Za-z]", re.MULTILINE)
        next_match = next_key_pattern.search(after_section)

        if next_match:
            section_end = section_start + next_match.start()
        else:
            section_end = len(content)

        section_content = content[section_start:section_end]

        # Pattern to match token entries: "  app_id: token_value"
        token_pattern = re.compile(rf"^\s*(\d+)\s*:\s*(.+)$", re.MULTILINE)

        for token_match in token_pattern.finditer(section_content):
            app_id = token_match.group(1).strip()
            token = token_match.group(2).strip()
            tokens[app_id] = token

    except Exception as e:
        logger.error(f"Failed to read AppTokens from {config_path}: {e}", exc_info=True)

    return tokens


def get_fake_app_ids(config_path: Path, fake_appid: str = "") -> set[str]:
    """
    Get all FakeAppIds from SLSsteam config.yaml.

    Args:
        config_path: Path to the YAML config file
        fake_appid: Optional fake appid to filter by (defaults to settings value or "480")

    Returns:
        Set of app_id strings that are in FakeAppIds
    """
    fake_app_ids = set()

    # Use provided fake_appid or get from settings, default to "480"
    if not fake_appid:
        fake_appid = get_fake_appid_for_online()

    try:
        if not config_path.exists():
            logger.debug(f"Config file not found at {config_path}")
            return fake_app_ids

        with open(config_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Find FakeAppIds section and extract all entries
        fake_appids_pattern = re.compile(r"^FakeAppIds:\s*$", re.MULTILINE)
        match = fake_appids_pattern.search(content)

        if not match:
            return fake_app_ids

        # Find the end of FakeAppIds section (next top-level key or end of file)
        section_start = match.end()
        after_section = content[section_start:]

        # Look for next top-level key (at start of line, word character)
        next_key_pattern = re.compile(r"^[A-Za-z]", re.MULTILINE)
        next_match = next_key_pattern.search(after_section)

        if next_match:
            section_end = section_start + next_match.start()
        else:
            section_end = len(content)

        section_content = content[section_start:section_end]

        # Pattern to match FakeAppId entries: "  app_id: <fake_appid>   # comment"
        entry_pattern = re.compile(rf"^\s*(\d+)\s*:\s*{re.escape(fake_appid)}", re.MULTILINE)

        for entry_match in entry_pattern.finditer(section_content):
            app_id = entry_match.group(1).strip()
            fake_app_ids.add(app_id)

    except Exception as e:
        logger.error(f"Failed to read FakeAppIds from {config_path}: {e}", exc_info=True)

    return fake_app_ids


def add_fake_app_id(config_path: Path, app_id: str, game_name: str = "", fake_appid: str = "") -> bool:
    """
    Add an AppID to the FakeAppIds list in SLSsteam config.yaml.

    Format:
        FakeAppIds:
          appid: <fake_appid>   # Game Name -> SLSonline

    This function preserves ALL comments, whitespace, and formatting.
    Only performs the addition if SLSsteam mode and config management are enabled in settings.

    Args:
        config_path: Path to the YAML config file
        app_id: The AppID to add
        game_name: Optional game name for comment
        fake_appid: Optional fake appid to use (defaults to settings value or "480")

    Returns:
        True if AppID was added, False if already exists, error, or mode is disabled
    """
    if not is_slssteam_mode_enabled():
        logger.debug("SLSsteam mode is disabled, skipping add fake app id")
        return False
    if not is_slssteam_config_management_enabled():
        logger.debug("SLSsteam config management is disabled, skipping add fake app id")
        return False

    # Use provided fake_appid or get from settings, default to "480"
    if not fake_appid:
        fake_appid = get_fake_appid_for_online()
    # Determine the suffix for the comment
    suffix = "Spacewar" if fake_appid == "480" else "SLSonline"

    try:
        # If file doesn't exist, create it with the new entry
        if not config_path.exists():
            # Ensure parent directory exists
            config_path.parent.mkdir(parents=True, exist_ok=True)
            if game_name:
                new_entry = f"FakeAppIds:\n  {app_id}: {fake_appid}   # {game_name} -> {suffix}\n"
            else:
                new_entry = f"FakeAppIds:\n  {app_id}: {fake_appid}\n"
            if not _atomic_write(config_path, new_entry):
                return False
            logger.info(f"Created config file with FakeAppId '{app_id}' in {config_path}")
            return True

        # Read the file content
        with open(config_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Check if AppID already exists in FakeAppIds list
        # Match patterns like: "  12345: <fake_appid>" or "  12345: <fake_appid>   # comment"
        existing_pattern = re.compile(
            rf"^\s*{re.escape(app_id)}\s*:\s*{re.escape(fake_appid)}", re.MULTILINE
        )

        if existing_pattern.search(content):
            logger.debug(f"AppID '{app_id}' already exists in FakeAppIds")
            return False

        # Find FakeAppIds section
        fake_appids_pattern = re.compile(r"^FakeAppIds:\s*$", re.MULTILINE)
        match = fake_appids_pattern.search(content)

        if match:
            # Append to existing section
            section_start = match.end()
            # Skip the newline after "FakeAppIds:"
            if section_start < len(content) and content[section_start] == "\n":
                section_start += 1
            remaining = content[section_start:]
            lines = remaining.split("\n")

            # Find position after the last entry (line starting with digits)
            insert_pos = section_start
            last_entry_end = section_start

            for i, line in enumerate(lines):
                stripped = line.strip()
                # Check if line starts with a digit (it's an entry)
                if stripped and stripped[0].isdigit():
                    # This is an entry - update the end position
                    last_entry_end = section_start + sum(
                        len(lines[j]) + 1 for j in range(i + 1)
                    )
                elif not stripped:
                    # Empty line - continue
                    continue
                elif stripped.startswith("#"):
                    # Comment line - continue
                    continue
                else:
                    # Any other non-empty, non-comment, non-entry line is a new section
                    break
            else:
                # End of file
                last_entry_end = len(content)

            insert_pos = last_entry_end

            # Build new entry with proper indentation (2 spaces for entries)
            if game_name:
                new_entry = f"  {app_id}: {fake_appid}   # {game_name} -> {suffix}\n"
            else:
                new_entry = f"  {app_id}: {fake_appid}\n"

            new_content = (
                content[:insert_pos] + new_entry + content[insert_pos:]
            )
        else:
            # Create new FakeAppIds section with proper indentation
            if game_name:
                new_entry = f"FakeAppIds:\n  {app_id}: {fake_appid}   # {game_name} -> {suffix}\n"
            else:
                new_entry = f"FakeAppIds:\n  {app_id}: {fake_appid}\n"

            new_content = content + "\n" + new_entry

        # Write back to file atomically
        if not _atomic_write(config_path, new_content):
            return False

        logger.info(f"Added AppID '{app_id}' to FakeAppIds in {config_path}")
        return True

    except Exception as e:
        logger.error(
            f"Failed to add FakeAppId '{app_id}' to {config_path}: {e}", exc_info=True
        )
        return False


def remove_fake_app_id(config_path: Path, app_id: str, fake_appid: str = "") -> bool:
    """
    Remove an AppID from the FakeAppIds list in SLSsteam config.yaml.

    This function removes the AppID entry while preserving other content,
    comments, and formatting.
    Only performs the removal if SLSsteam mode and config management are enabled in settings.

    Args:
        config_path: Path to the YAML config file
        app_id: The AppID to remove
        fake_appid: Optional fake appid to use (defaults to settings value or "480")

    Returns:
        True if AppID was removed, False if not found, error, or mode is disabled
    """
    if not is_slssteam_mode_enabled():
        logger.debug("SLSsteam mode is disabled, skipping remove fake app id")
        return False
    if not is_slssteam_config_management_enabled():
        logger.debug("SLSsteam config management is disabled, skipping remove fake app id")
        return False

    # Use provided fake_appid or get from settings, default to "480"
    if not fake_appid:
        fake_appid = get_fake_appid_for_online()

    try:
        if not config_path.exists():
            logger.debug(f"Config file does not exist at {config_path}")
            return False

        with open(config_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Pattern to match AppID in FakeAppIds list (with optional comment)
        # Matches: "  12345: <fake_appid>" or "  12345: <fake_appid>   # comment"
        app_id_pattern = re.compile(
            rf"^\s*{re.escape(app_id)}\s*:\s*{re.escape(fake_appid)}(?:\s*#.*)?$", re.MULTILINE
        )

        match = app_id_pattern.search(content)
        if not match:
            logger.debug(f"AppID '{app_id}' not found in FakeAppIds")
            return False

        # Find the line start and end
        line_start = content.rfind("\n", 0, match.start()) + 1  # Include newline before
        if line_start == 0:
            line_start = 0  # First line, no newline before
        line_end = content.find("\n", match.end())
        if line_end == -1:
            line_end = len(content)  # End of file

        # Check if there's a newline after the line
        if line_end < len(content) and content[line_end] == "\n":
            line_end += 1  # Include the newline

        # Remove the line
        new_content = content[:line_start] + content[line_end:]

        # Write back to file atomically
        if not _atomic_write(config_path, new_content):
            return False

        logger.info(f"Removed AppID '{app_id}' from FakeAppIds in {config_path}")
        return True

    except Exception as e:
        logger.error(
            f"Failed to remove FakeAppId '{app_id}' from {config_path}: {e}", exc_info=True
        )
        return False
