import logging
import os
import ssl
import requests
import urllib3
from pathlib import Path
from requests.adapters import HTTPAdapter
from urllib3.util.ssl_ import create_urllib3_context
from utils.settings import get_settings
from utils.helpers import get_base_path

logger = logging.getLogger(__name__)

BASE_URL = "https://manifest.morrenus.xyz/api/v1"


class SSLAdapter(HTTPAdapter):
    """
    Custom HTTPAdapter that uses a more permissive SSL configuration.
    Helps with environments that have outdated CA bundles or SSL issues.
    """
    def init_poolmanager(self, *args, **kwargs):
        ctx = create_urllib3_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        # Try to set a more compatible set of ciphers
        try:
            ctx.set_ciphers('DEFAULT:@SECLEVEL=1')
        except ssl.SSLError:
            pass  # Some systems don't support SECLEVEL
        kwargs['ssl_context'] = ctx
        return super().init_poolmanager(*args, **kwargs)


# Create a session with custom SSL configuration for problematic environments
_session = requests.Session()
_session.verify = False  # Disable SSL verification globally for this session
_session.mount('https://', SSLAdapter())
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Error messages for specific HTTP status codes
API_ERROR_MESSAGES = {
    401: "Invalid or missing API key. Please check your credentials in Settings.",
    403: "Access denied. Your account may be blocked or the App ID is not accessible.",
    404: "Game not found in library. The App ID may be incorrect or not available.",
    429: "Daily API limit exceeded. Please try again later.",
    500: "Server error. The manifest may be corrupted or temporarily unavailable.",
}


def _handle_api_error(response):
    """
    Handles API errors for specific status codes and returns an error message.
    Returns None if error is handled, or the original exception for generic handling.
    """
    status_code = response.status_code

    if status_code in API_ERROR_MESSAGES:
        error_msg = API_ERROR_MESSAGES[status_code]
        logger.error(f"API error ({status_code}): {error_msg}")
        return error_msg

    return None


def _get_headers():
    """
    Retrieves the Morrenus API key from settings and constructs auth headers.
    """
    settings = get_settings()
    api_key = settings.value("morrenus_api_key", "", type=str)
    if not api_key:
        logger.warning("Morrenus API key is not set in settings.")
        return None
    return {"Authorization": f"Bearer {api_key}"}


def search_games(query):
    """
    Searches for games on the Morrenus API.
    """
    headers = _get_headers()
    if headers is None:
        return {"error": "API Key is not set. Please set it in Settings."}

    params = {"q": query, "limit": 50}
    url = f"{BASE_URL}/search"
    logger.info(f"Searching Morrenus API: {url} with query: {query}")

    try:
        response = _session.get(url, headers=headers, params=params, timeout=10)
        # Check for specific API errors first
        error_msg = _handle_api_error(response)
        if error_msg:
            return {"error": error_msg}
        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError as e:
        response = e.response
        response_text = response.text if response is not None else ""
        status_code = response.status_code if response is not None else "N/A"
        logger.error(f"API search HTTP error: {e} - {response_text}")
        try:
            if response is None:
                return {"error": f"API Error ({status_code}): {e}"}
            error_detail = response.json().get("detail", response_text)
            return {"error": f"API Error ({status_code}): {error_detail}"}
        except requests.exceptions.JSONDecodeError:
            return {"error": f"API Error ({status_code}): {response_text}"}
    except requests.exceptions.RequestException as e:
        logger.error(f"API search failed: {e}")
        error_str = str(e).lower()
        if "ssl" in error_str or "wrong_version_number" in error_str:
            return {"error": "SSL connection failed. This may be caused by a proxy, firewall, or network configuration blocking HTTPS connections."}
        return {"error": f"Request Failed: {e}"}
    except Exception as e:
        logger.error(f"An unexpected error occurred during search: {e}", exc_info=True)
        return {"error": f"An unexpected error occurred: {e}"}


def download_manifest(app_id):
    """
    Downloads a manifest zip for a given app_id to a persistent folder.
    Returns (filepath, None) on success, or (None, error_message) on failure.
    """
    headers = _get_headers()
    if headers is None:
        return (None, "API Key is not set. Please set it in Settings.")

    url = f"{BASE_URL}/manifest/{app_id}"
    # Save to persistent folder
    manifests_dir = Path(get_base_path()) / "morrenus_manifests"
    manifests_dir.mkdir(parents=True, exist_ok=True)
    save_path = manifests_dir / f"accela_fetch_{app_id}.zip"
    logger.info(f"Attempting to download manifest for AppID {app_id} to {save_path}")

    try:
        with _session.get(url, headers=headers, stream=True, timeout=60) as r:
            # Check for specific API errors first
            error_msg = _handle_api_error(r)
            if error_msg:
                if os.path.exists(save_path):
                    os.remove(save_path)
                return (None, error_msg)
            r.raise_for_status()
            with open(save_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)

        logger.info(f"Manifest for {app_id} downloaded successfully to {save_path}")
        return (str(save_path), None)
    except requests.exceptions.HTTPError as e:
        response = e.response
        response_text = response.text if response is not None else ""
        status_code = response.status_code if response is not None else "N/A"
        logger.error(f"API download HTTP error: {e} - {response_text}")
        if os.path.exists(save_path):
            os.remove(save_path)
        try:
            if response is None:
                return (None, f"API Error ({status_code}): {e}")
            error_detail = response.json().get("detail", response_text)
            return (None, f"API Error ({status_code}): {error_detail}")
        except requests.exceptions.JSONDecodeError:
            return (None, f"API Error ({status_code}): {response_text}")
    except requests.exceptions.RequestException as e:
        logger.error(f"API download failed: {e}")
        if os.path.exists(save_path):
            os.remove(save_path)
        error_str = str(e).lower()
        if "ssl" in error_str or "wrong_version_number" in error_str:
            return (None, "SSL connection failed. This may be caused by a proxy, firewall, or network configuration blocking HTTPS connections.")
        return (None, f"Download Failed: {e}")
    except Exception as e:
        logger.error(f"An unexpected error occurred during download: {e}", exc_info=True)
        if os.path.exists(save_path):
            os.remove(save_path)
        return (None, f"An unexpected error occurred: {e}")


def get_user_stats():
    """
    Retrieves user statistics from the Morrenus API.
    Returns dict with user info or {"error": message} on failure.
    """
    settings = get_settings()
    api_key = settings.value("morrenus_api_key", "", type=str)
    if not api_key:
        return {"error": "API key is not set. Please set it in Settings."}

    url = f"{BASE_URL}/user/stats"
    params = {"api_key": api_key}
    logger.info("Fetching user stats from Morrenus API")

    try:
        response = _session.get(url, params=params, timeout=10)
        error_msg = _handle_api_error(response)
        if error_msg:
            return {"error": error_msg}
        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError as e:
        response = e.response
        response_text = response.text if response is not None else ""
        status_code = response.status_code if response is not None else "N/A"
        logger.error(f"API stats HTTP error: {e} - {response_text}")
        try:
            if response is None:
                return {"error": f"API Error ({status_code}): {e}"}
            error_detail = response.json().get("detail", response_text)
            return {"error": f"API Error ({status_code}): {error_detail}"}
        except requests.exceptions.JSONDecodeError:
            return {"error": f"API Error ({status_code}): {response_text}"}
    except requests.exceptions.RequestException as e:
        logger.error(f"API stats request failed: {e}")
        # Check for SSL errors that might indicate proxy/network issues
        error_str = str(e).lower()
        if "ssl" in error_str or "wrong_version_number" in error_str:
            return {"error": "SSL connection failed. This may be caused by a proxy, firewall, or network configuration blocking HTTPS connections."}
        return {"error": f"Request Failed: {e}"}
    except Exception as e:
        logger.error(f"Unexpected error fetching stats: {e}", exc_info=True)
        return {"error": f"An unexpected error occurred: {e}"}


def check_health():
    """
    Checks if the Morrenus API is healthy.
    Returns dict with health info or {"error": message} on failure.
    """
    url = f"{BASE_URL}/health"
    logger.info("Checking Morrenus API health")

    try:
        response = _session.get(url, timeout=5)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"API health check failed: {e}")
        error_str = str(e).lower()
        if "ssl" in error_str or "wrong_version_number" in error_str:
            return {"status": "unhealthy", "error": "SSL connection failed. Check proxy/firewall settings."}
        return {"status": "unhealthy", "error": str(e)}
    except Exception as e:
        logger.error(f"Unexpected error checking health: {e}", exc_info=True)
        return {"status": "unknown", "error": str(e)}
