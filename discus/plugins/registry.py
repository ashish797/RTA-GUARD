"""
RTA-GUARD — Plugin Registry

SQLite-based registry for installed plugins.
Tracks: installation, metadata, test results, integrity fingerprints.
"""
import json
import sqlite3
import time
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger("discus.plugins.registry")

DEFAULT_DB_PATH = Path.home() / ".rta-guard" / "plugins.db"


@dataclass
class InstalledPlugin:
    """Record of an installed plugin."""
    plugin_id: str
    name: str
    version: str
    description: str = ""
    author: str = ""
    category: str = "general"
    tags: List[str] = field(default_factory=list)
    hooks: List[str] = field(default_factory=list)
    install_path: str = ""
    fingerprint: str = ""
    enabled: bool = True
    installed_at: float = 0.0
    last_tested: Optional[float] = None
    test_passed: Optional[bool] = None
    test_output: str = ""
    config: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plugin_id": self.plugin_id,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "author": self.author,
            "category": self.category,
            "tags": self.tags,
            "hooks": self.hooks,
            "install_path": self.install_path,
            "fingerprint": self.fingerprint,
            "enabled": self.enabled,
            "installed_at": self.installed_at,
            "last_tested": self.last_tested,
            "test_passed": self.test_passed,
            "test_output": self.test_output,
            "config": self.config,
        }


class PluginRegistry:
    """SQLite-backed registry for installed plugins."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS plugins (
                    plugin_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    version TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    author TEXT DEFAULT '',
                    category TEXT DEFAULT 'general',
                    tags TEXT DEFAULT '[]',
                    hooks TEXT DEFAULT '[]',
                    install_path TEXT DEFAULT '',
                    fingerprint TEXT DEFAULT '',
                    enabled INTEGER DEFAULT 1,
                    installed_at REAL NOT NULL,
                    last_tested REAL,
                    test_passed INTEGER,
                    test_output TEXT DEFAULT '',
                    config TEXT DEFAULT '{}'
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS plugin_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    plugin_id TEXT NOT NULL,
                    session_id TEXT,
                    hook TEXT NOT NULL,
                    violated INTEGER DEFAULT 0,
                    severity TEXT DEFAULT 'pass',
                    message TEXT DEFAULT '',
                    score REAL DEFAULT 0.0,
                    duration_ms REAL DEFAULT 0.0,
                    timestamp REAL NOT NULL,
                    FOREIGN KEY (plugin_id) REFERENCES plugins(plugin_id)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_runs_plugin ON plugin_runs(plugin_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_runs_ts ON plugin_runs(timestamp)
            """)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def register(self, plugin: InstalledPlugin) -> None:
        """Register or update a plugin in the registry."""
        with self._conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO plugins
                (plugin_id, name, version, description, author, category,
                 tags, hooks, install_path, fingerprint, enabled, installed_at,
                 last_tested, test_passed, test_output, config)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                plugin.plugin_id, plugin.name, plugin.version,
                plugin.description, plugin.author, plugin.category,
                json.dumps(plugin.tags), json.dumps(plugin.hooks),
                plugin.install_path, plugin.fingerprint,
                int(plugin.enabled), plugin.installed_at or time.time(),
                plugin.last_tested, int(plugin.test_passed) if plugin.test_passed is not None else None,
                plugin.test_output, json.dumps(plugin.config),
            ))
        logger.info(f"Registered plugin: {plugin.plugin_id} v{plugin.version}")

    def unregister(self, plugin_id: str) -> bool:
        """Remove a plugin from the registry."""
        with self._conn() as conn:
            cursor = conn.execute("DELETE FROM plugins WHERE plugin_id = ?", (plugin_id,))
            conn.execute("DELETE FROM plugin_runs WHERE plugin_id = ?", (plugin_id,))
            return cursor.rowcount > 0

    def get(self, plugin_id: str) -> Optional[InstalledPlugin]:
        """Get a plugin by ID."""
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM plugins WHERE plugin_id = ?", (plugin_id,)).fetchone()
            return self._row_to_plugin(row) if row else None

    def list_all(self, category: Optional[str] = None, enabled_only: bool = False) -> List[InstalledPlugin]:
        """List all plugins, optionally filtered."""
        query = "SELECT * FROM plugins"
        params = []
        conditions = []
        if category:
            conditions.append("category = ?")
            params.append(category)
        if enabled_only:
            conditions.append("enabled = 1")
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY category, name"

        with self._conn() as conn:
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_plugin(r) for r in rows]

    def set_enabled(self, plugin_id: str, enabled: bool) -> bool:
        """Enable or disable a plugin."""
        with self._conn() as conn:
            cursor = conn.execute(
                "UPDATE plugins SET enabled = ? WHERE plugin_id = ?",
                (int(enabled), plugin_id)
            )
            return cursor.rowcount > 0

    def record_run(self, plugin_id: str, session_id: str, hook: str,
                   violated: bool, severity: str, message: str,
                   score: float, duration_ms: float) -> None:
        """Record a plugin execution run."""
        with self._conn() as conn:
            conn.execute("""
                INSERT INTO plugin_runs
                (plugin_id, session_id, hook, violated, severity, message, score, duration_ms, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                plugin_id, session_id, hook, int(violated),
                severity, message, score, duration_ms, time.time(),
            ))

    def get_runs(self, plugin_id: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """Get recent plugin runs."""
        query = "SELECT * FROM plugin_runs"
        params = []
        if plugin_id:
            query += " WHERE plugin_id = ?"
            params.append(plugin_id)
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        with self._conn() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def get_stats(self, plugin_id: Optional[str] = None) -> Dict[str, Any]:
        """Get aggregate stats for plugins."""
        base = "SELECT COUNT(*) as total_runs, SUM(violated) as violations, AVG(duration_ms) as avg_ms FROM plugin_runs"
        params = []
        if plugin_id:
            base += " WHERE plugin_id = ?"
            params.append(plugin_id)

        with self._conn() as conn:
            row = conn.execute(base, params).fetchone()
            total_plugins = conn.execute("SELECT COUNT(*) FROM plugins").fetchone()[0]
            enabled_plugins = conn.execute("SELECT COUNT(*) FROM plugins WHERE enabled=1").fetchone()[0]

            return {
                "total_plugins": total_plugins,
                "enabled_plugins": enabled_plugins,
                "total_runs": row["total_runs"] or 0,
                "total_violations": row["violations"] or 0,
                "avg_duration_ms": round(row["avg_ms"] or 0, 2),
            }

    def update_test_result(self, plugin_id: str, passed: bool, output: str) -> bool:
        """Update test results for a plugin."""
        with self._conn() as conn:
            cursor = conn.execute("""
                UPDATE plugins SET last_tested = ?, test_passed = ?, test_output = ?
                WHERE plugin_id = ?
            """, (time.time(), int(passed), output, plugin_id))
            return cursor.rowcount > 0

    def _row_to_plugin(self, row: sqlite3.Row) -> InstalledPlugin:
        return InstalledPlugin(
            plugin_id=row["plugin_id"],
            name=row["name"],
            version=row["version"],
            description=row["description"],
            author=row["author"],
            category=row["category"],
            tags=json.loads(row["tags"]),
            hooks=json.loads(row["hooks"]),
            install_path=row["install_path"],
            fingerprint=row["fingerprint"],
            enabled=bool(row["enabled"]),
            installed_at=row["installed_at"],
            last_tested=row["last_tested"],
            test_passed=bool(row["test_passed"]) if row["test_passed"] is not None else None,
            test_output=row["test_output"],
            config=json.loads(row["config"]),
        )
