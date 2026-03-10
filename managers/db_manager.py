import sqlite3
import json
import logging
import shutil
import time
import threading

# Handle optional compression dependency
try:
    import zstandard as zstd
except ImportError:
    zstd = None

from utils.helpers import get_base_path
from utils.paths import Paths,Path

logger = logging.getLogger(__name__)

# 14 Days in seconds (14 * 24 * 60 * 60)
EXPIRATION_SECONDS = 1_209_600 

class DatabaseManager:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(DatabaseManager, cls).__new__(cls)
                cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        if zstd is None:
            logger.critical("Module 'zstandard' is missing! Database functionality will fail. Please 'pip install zstandard'")
        
        self.db_path = self._setup_database_path()
        self.conn = self._connect_db()
        self.cctx = zstd.ZstdCompressor(level=3) if zstd else None
        self.dctx = zstd.ZstdDecompressor() if zstd else None
        
        self._initialized = True
        logger.info(f"DatabaseManager initialized at: {self.db_path}")

    def _setup_database_path(self):
        """
        Ensures the database exists in a writable user location (%APPDATA%).
        If missing, copies the seed DB from the internal PyInstaller bundle.
        """
        # 1. Writable location (e.g. %APPDATA%/ACCELA/steam_headers.db)
        writable_path = get_base_path() / "steam_headers.db"
        
        # 2. Seed location (Internal PyInstaller path: data/steam_headers.db)
        # Adjusted to look in the 'data' folder as per your directory structure
        seed_path = Paths.base("data/steam_headers.db")

        if not writable_path.exists():
            get_base_path().mkdir(parents=True, exist_ok=True)
            
            if seed_path.exists():
                logger.info(f"Seeding database from {seed_path}")
                try:
                    shutil.copy2(seed_path, writable_path)
                except Exception as e:
                    logger.error(f"Failed to copy seed database: {e}")
                    self._create_empty_db(writable_path)
            else:
                logger.warning(f"Seed database not found at {seed_path}. Creating empty DB.")
                self._create_empty_db(writable_path)
        
        return writable_path

    def _connect_db(self):
        try:
            # check_same_thread=False allows ImageFetcher threads to read safely
            conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            conn.row_factory = sqlite3.Row
            return conn
        except sqlite3.Error as e:
            logger.error(f"DB Connection failed: {e}")
            return None

    def _create_empty_db(self, path):
        try:
            conn = sqlite3.connect(str(path))
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS apps (
                    appid INTEGER PRIMARY KEY,
                    name TEXT,
                    header_path TEXT,
                    installdir TEXT,
                    depots_json BLOB,
                    last_updated INTEGER
                )
            """)
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Schema creation failed: {e}")

    def get_header_url(self, appid):
        """
        Get header URL with expiration check.
        Returns None if the entry is older than 14 days to trigger a refresh,
        since header images can change with game updates.
        """
        if not self.conn or not self.dctx:
            return None

        try:
            cur = self.conn.cursor()
            cur.execute(
                "SELECT header_path, last_updated FROM apps WHERE appid = ?", 
                (appid,)
            )
            row = cur.fetchone()
            
            if not row or not row['header_path']:
                return None

            last_updated = row['last_updated'] or 0
            now = int(time.time())
            age = now - last_updated

            if age > EXPIRATION_SECONDS:
                logger.debug(f"Header URL for AppID {appid} is stale ({age//86400} days old). Will refresh.")
                return None

            return self._construct_full_url(row['header_path'], appid)

        except Exception as e:
            logger.error(f"DB Read Error for header_url {appid}: {e}")
            return None

    def get_app_info(self, appid):
        """
        Retrieves app metadata. 
        Returns None if the AppID is not found (Complete Miss) or Expired.
        """
        if not self.conn or not self.dctx:
            return None

        try:
            cur = self.conn.cursor()
            cur.execute(
                "SELECT name, header_path, installdir, depots_json, last_updated FROM apps WHERE appid = ?", 
                (appid,)
            )
            row = cur.fetchone()
            
            if not row:
                return None  # Complete Miss

            # --- Expiration Logic ---
            last_updated = row['last_updated'] or 0
            now = int(time.time())
            age = now - last_updated

            if age > EXPIRATION_SECONDS:
                logger.info(f"AppID {appid} data is stale ({age//86400} days old). Treating as miss to force refresh.")
                return None 
            # ------------------------

            # Decompress Depots
            depots_data = {}
            if row['depots_json']:
                try:
                    decompressed = self.dctx.decompress(row['depots_json'])
                    depots_data = json.loads(decompressed)
                except Exception as e:
                    logger.error(f"Decompression error for {appid}: {e}")

            # Extract buildid logic
            buildid = None
            if "branches" in depots_data:
                buildid = depots_data.get("branches", {}).get("public", {}).get("buildid")
                # Clean up dictionary
                if "branches" in depots_data:
                    del depots_data["branches"]

            full_header_url = self._construct_full_url(row['header_path'], appid)

            return {
                "appid": appid,
                "name": row['name'],
                "installdir": row['installdir'],
                "header_url": full_header_url,
                "depots": depots_data,
                "buildid": buildid,
                "source": "database"
            }

        except Exception as e:
            logger.error(f"DB Read Error {appid}: {e}")
            return None

    def upsert_app_info(self, appid, data):
        """
        Writes new data to the DB. 
        Used only when the API finds data that the DB was missing.
        If only header_url is provided, updates just the header without touching other fields.
        """
        if not self.conn or not self.cctx:
            return

        try:
            # Normalize URL to relative path (to match builder format)
            header_raw = data.get("header_url")
            header_path = self._normalize_header_path(appid, header_raw) if header_raw else None
            
            now = int(time.time())
            cur = self.conn.cursor()

            # If we only have header_url, do a partial update to preserve existing data
            if header_path and len(data) == 1 and "header_url" in data:
                # Check if entry exists
                cur.execute("SELECT appid FROM apps WHERE appid = ?", (appid,))
                if cur.fetchone():
                    # Update only header_path and last_updated
                    cur.execute("""
                        UPDATE apps SET header_path = ?, last_updated = ? WHERE appid = ?
                    """, (header_path, now, appid))
                    self.conn.commit()
                    logger.info(f"Database healed: Updated header for AppID {appid}")
                    return
                # If entry doesn't exist, fall through to full insert

            # Full insert/replace with all data
            name = data.get("name", f"App {appid}")
            installdir = data.get("installdir")
            
            # Handle BuildID packing for storage
            depots_to_save = data.get("depots", {}).copy()
            if data.get("buildid"):
                depots_to_save["branches"] = {"public": {"buildid": data["buildid"]}}
            
            # Compress
            depots_json_str = json.dumps(depots_to_save)
            depots_compressed = self.cctx.compress(depots_json_str.encode('utf-8'))

            cur.execute("""
                INSERT OR REPLACE INTO apps 
                (appid, name, header_path, installdir, depots_json, last_updated)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (appid, name, header_path, installdir, depots_compressed, now))
            
            self.conn.commit()
            logger.info(f"Database healed: Added/Updated AppID {appid}")

        except Exception as e:
            logger.error(f"DB Write Error {appid}: {e}")

    def _normalize_header_path(self, appid, url):
        """Converts full URL -> relative storage path"""
        if not url or not isinstance(url, str): return None
        url = url.split("?", 1)[0]
        if "/apps/" in url:
            return url.split("/apps/", 1)[1]
        return f"{appid}/header.jpg"

    def _construct_full_url(self, header_path, appid):
        """Converts relative storage path -> full URL"""
        if not header_path: return None
        if header_path.startswith("http"): return header_path
        return f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{header_path}"

    def close(self):
        if self.conn: self.conn.close()
