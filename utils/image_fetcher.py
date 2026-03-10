from PyQt6.QtCore import QObject, pyqtSignal, QUrl
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
import logging
import time
import requests
from functools import wraps
from managers.db_manager import DatabaseManager

logger = logging.getLogger(__name__)

# Global network manager - shared across all fetchers, lives on main thread
_network_manager = None

def get_network_manager():
    """Get or create the global QNetworkAccessManager (must be called from main thread)"""
    global _network_manager
    if _network_manager is None:
        _network_manager = QNetworkAccessManager()
    return _network_manager

def time_function(func):
    """Decorator to time function execution"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.time()
        result = func(*args, **kwargs)
        end_time = time.time()
        execution_time = (end_time - start_time) * 1000
        logger.debug(f"{func.__name__} executed in {execution_time:.2f}ms")
        return result
    return wrapper

def sendRequest(url):
    """Fast URL validation using HEAD requests"""
    try:
        response = requests.head(url, timeout=1.5, headers={"User-Agent": "Mozilla/5.0"}, allow_redirects=True)
        if response.status_code == 200:
            return True
        return False
    except Exception as e:
        logger.debug(f"URL check failed for {url}: {e}")
        return False

class ImageFetcher(QObject):
    """Async image fetcher using Qt's QNetworkAccessManager (no threads needed)"""
    finished = pyqtSignal(bytes)

    def __init__(self, url: str):
        super().__init__()
        self.url = url
        self._stopped = False
        self._reply = None
        self._start_time = None

    def stop(self):
        """Abort the request and prevent signal emission"""
        self._stopped = True
        if self._reply is not None:
            self._reply.abort()

    def start(self):
        """Start the async fetch using QNetworkAccessManager"""
        if self._stopped:
            return
        
        self._start_time = time.time()
        manager = get_network_manager()
        
        request = QNetworkRequest(QUrl(self.url))
        request.setRawHeader(b"User-Agent", b"Mozilla/5.0")
        
        self._reply = manager.get(request)
        self._reply.finished.connect(self._on_finished)  # type: ignore[union-attr]

    def _on_finished(self):
        """Handle the network reply"""
        if self._stopped or self._reply is None:
            if self._reply:
                self._reply.deleteLater()
            return
        
        reply = self._reply
        self._reply = None
        
        try:
            if reply.error() == QNetworkReply.NetworkError.NoError:
                data = reply.readAll().data()  # .data() returns Python bytes
                if self._start_time:
                    download_time = (time.time() - self._start_time) * 1000
                    logger.debug(f"Downloaded {len(data)} bytes from {self.url} in {download_time:.2f}ms")
                if not self._stopped:
                    self.finished.emit(data)
            else:
                logger.debug(f"Failed to fetch image from {self.url}: {reply.errorString()}")
                if not self._stopped:
                    self.finished.emit(b"")
        finally:
            reply.deleteLater()

    # Legacy method for compatibility - redirects to start()
    def run(self):
        """Legacy method - use start() instead"""
        self.start()

    @staticmethod
    @time_function
    def _get_best_image_url(app_id: int, url_list: list) -> str:
        """URL checking with HEAD requests to find a working image URL"""
        logger.debug(f"Starting URL validation for app {app_id} with {len(url_list)} URLs")

        # If there's only one URL, just return it immediately
        if len(url_list) == 1:
            logger.debug(f"Only one URL available, returning: {url_list[0]}")
            return url_list[0]

        start_time = time.time()

        for i, url in enumerate(url_list):
            # If this is the last URL, just return it without checking
            if i == len(url_list) - 1:
                total_time = (time.time() - start_time) * 1000
                logger.debug(f"Last URL, returning without check: {url} (total time: {total_time:.2f}ms)")
                return url

            if sendRequest(url):
                total_time = (time.time() - start_time) * 1000
                logger.debug(f"Selected valid image URL: {url} (found in {total_time:.2f}ms)")
                return url
        
        # Should not reach here, but return first URL as fallback
        return url_list[0]

    @staticmethod
    @time_function
    def get_header_image_url(app_id: int) -> str:
        # 1. Try DB for the specific hash URL (FAST)
        try:
            db_url = DatabaseManager().get_header_url(app_id)
            if db_url:
                return db_url
        except Exception:
            pass

        # 2. Fallback to generic URL construction
        # If this fails during download, _trigger_header_refresh in gamelibrary.py
        # will fetch the correct hashed URL from the API asynchronously
        urls = [
            f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{app_id}/header.jpg",
            f"https://cdn.akamai.steamstatic.com/steam/apps/{app_id}/header.jpg",
            f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{app_id}/library_header.jpg",
            f"https://cdn.akamai.steamstatic.com/steam/apps/{app_id}/library_header.jpg",
            f"https://cdn.akamai.steamstatic.com/steam/apps/{app_id}/library_hero.jpg",
        ]

        if app_id == "3949040":
            return "https://cdn.akamai.steamstatic.com/steam/apps/3949040/library_hero.jpg"

        # Return first URL immediately - validation is too slow for UI
        # Failed downloads will trigger async refresh via gamelibrary._trigger_header_refresh
        return urls[0]
    
    @staticmethod
    def _fetch_header_from_web_api(app_id: int) -> str | None:
        """
        Fetch the header image URL from Steam's Web API.
        This gets the correct hashed URL for games that use the new format.
        """
        try:
            url = f"https://store.steampowered.com/api/appdetails?appids={app_id}"
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            app_data = data.get(str(app_id), {})
            if app_data.get("success"):
                header_url = app_data.get("data", {}).get("header_image")
                if header_url:
                    # Remove query string for cleaner URL
                    return header_url.split("?")[0]
        except Exception as e:
            logger.debug(f"Web API fetch failed for app {app_id}: {e}")
        return None

    @staticmethod
    @time_function
    def get_capsule_image_url(app_id: int) -> str:
        urls = [
            f"https://cdn.akamai.steamstatic.com/steam/apps/{app_id}/capsule_184x69.jpg",
            f"https://cdn.akamai.steamstatic.com/steam/apps/{app_id}/library_capsule.jpg",
        ]

        if app_id == "3949040":
            return "https://cdn.akamai.steamstatic.com/steam/apps/3949040/library_capsule.jpg"

        logger.debug(f"Capsule image URLs for app {app_id}: {[url.split('/')[-1] for url in urls]}")
        return ImageFetcher._get_best_image_url(app_id, urls)