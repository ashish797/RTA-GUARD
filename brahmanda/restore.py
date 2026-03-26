"""
RTA-GUARD — Restore Operations (Phase 6.7)
"""

from __future__ import annotations

import json
import logging
import shutil
import sqlite3
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional, List, Dict, Any

from brahmanda.backup import BackupManager, BackupManifest, BackupStore, BackupEncryptor, BackupType

logger = logging.getLogger(__name__)


class RestoreMode(Enum):
    FULL = "full"
    SELECTIVE = "selective"
    DRY_RUN = "dry_run"


class RestoreStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    VALIDATED = "validated"


@dataclass
class RestoreLog:
    restore_id: str
    backup_id: str
    mode: str
    status: str = "pending"
    started_at: float = 0.0
    completed_at: float = 0.0
    tables_restored: List[str] = field(default_factory=list)
    config_files_restored: List[str] = field(default_factory=list)
    target_timestamp: Optional[float] = None
    error_message: str = ""
    operator: str = ""
    notes: str = ""

    def __post_init__(self):
        if not self.started_at:
            self.started_at = time.time()

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "RestoreLog":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class RestoreEngine:
    def __init__(self, backup_manager: BackupManager, db_path: str = "", config_dir: str = "",
                 restore_log_path: str = "/tmp/rta-guard/restore_log.json"):
        self.backup_manager = backup_manager
        self.db_path = db_path
        self.config_dir = config_dir
        self.restore_log_path = Path(restore_log_path)
        self._restore_logs: List[RestoreLog] = []
        self._load_restore_logs()

    def _load_restore_logs(self):
        if self.restore_log_path.exists():
            try:
                data = json.loads(self.restore_log_path.read_text())
                self._restore_logs = [RestoreLog.from_dict(d) for d in data]
            except (json.JSONDecodeError, KeyError):
                self._restore_logs = []

    def _save_restore_logs(self):
        self.restore_log_path.parent.mkdir(parents=True, exist_ok=True)
        data = [r.to_dict() for r in self._restore_logs]
        self.restore_log_path.write_text(json.dumps(data, indent=2))

    def _log_restore(self, log_entry: RestoreLog):
        self._restore_logs.append(log_entry)
        self._save_restore_logs()

    def find_closest_backup(self, target_timestamp: float) -> Optional[BackupManifest]:
        backups = self.backup_manager.store.list_manifests()
        candidates = [b for b in backups if b.completed_at <= target_timestamp and b.status in ("completed", "verified")]
        if not candidates:
            return None
        full_backups = [b for b in candidates if b.backup_type == BackupType.FULL.value]
        if full_backups:
            return max(full_backups, key=lambda b: b.completed_at)
        return max(candidates, key=lambda b: b.completed_at)

    def point_in_time_restore(self, target_timestamp: float, dry_run: bool = False, operator: str = "") -> RestoreLog:
        backup = self.find_closest_backup(target_timestamp)
        if not backup:
            log_entry = RestoreLog(restore_id=f"pit_{int(time.time())}", backup_id="none",
                                   mode=RestoreMode.DRY_RUN.value if dry_run else RestoreMode.FULL.value,
                                   status=RestoreStatus.FAILED.value, target_timestamp=target_timestamp,
                                   error_message="No suitable backup found before target timestamp", operator=operator)
            self._log_restore(log_entry)
            return log_entry
        return self.restore_from_backup(
            backup_id=backup.backup_id, dry_run=dry_run, operator=operator,
            notes=f"Point-in-time restore targeting {datetime.fromtimestamp(target_timestamp, tz=timezone.utc).isoformat()}")

    def restore_from_backup(self, backup_id: str, tables: Optional[List[str]] = None,
                            config_files: Optional[List[str]] = None, dry_run: bool = False,
                            operator: str = "", notes: str = "") -> RestoreLog:
        restore_id = f"restore_{int(time.time())}"
        mode = RestoreMode.DRY_RUN.value if dry_run else (RestoreMode.SELECTIVE.value if (tables or config_files) else RestoreMode.FULL.value)
        log_entry = RestoreLog(restore_id=restore_id, backup_id=backup_id, mode=mode,
                               status=RestoreStatus.IN_PROGRESS.value, operator=operator, notes=notes)
        self._log_restore(log_entry)
        manifest = self.backup_manager.store.get_manifest(backup_id)
        if not manifest:
            log_entry.status = RestoreStatus.FAILED.value
            log_entry.error_message = f"Backup {backup_id} not found"
            self._save_restore_logs()
            return log_entry
        backup_path = Path(manifest.backup_path)
        if not backup_path.exists():
            log_entry.status = RestoreStatus.FAILED.value
            log_entry.error_message = f"Backup path {manifest.backup_path} does not exist"
            self._save_restore_logs()
            return log_entry
        try:
            if dry_run:
                valid = self._validate_backup(manifest)
                log_entry.status = RestoreStatus.VALIDATED.value if valid else RestoreStatus.FAILED.value
                if not valid:
                    log_entry.error_message = "Backup validation failed"
                log_entry.completed_at = time.time()
                self._save_restore_logs()
                return log_entry
            db_backup = backup_path / "database.sqlite"
            db_encrypted = backup_path / "database.sqlite.enc"
            if db_encrypted.exists() and self.backup_manager.encryptor._key:
                decrypted_data = self.backup_manager.encryptor.decrypt(db_encrypted.read_bytes())
                if self.db_path:
                    Path(self.db_path).write_bytes(decrypted_data)
                    log_entry.tables_restored = self._list_tables(self.db_path)
            elif db_backup.exists() and self.db_path:
                if tables:
                    self._selective_db_restore(db_backup, self.db_path, tables)
                    log_entry.tables_restored = tables
                else:
                    shutil.copy2(db_backup, self.db_path)
                    log_entry.tables_restored = self._list_tables(self.db_path)
            config_backup = backup_path / "config"
            if config_backup.exists() and self.config_dir:
                if config_files:
                    for cf in config_files:
                        src = config_backup / cf
                        dst = Path(self.config_dir) / cf
                        if src.exists():
                            dst.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(src, dst)
                            log_entry.config_files_restored.append(cf)
                else:
                    dst = Path(self.config_dir)
                    if dst.exists():
                        shutil.rmtree(dst)
                    shutil.copytree(config_backup, dst)
                    log_entry.config_files_restored = [str(f.relative_to(config_backup)) for f in config_backup.rglob("*") if f.is_file()]
            log_entry.status = RestoreStatus.COMPLETED.value
            log_entry.completed_at = time.time()
        except Exception as e:
            log_entry.status = RestoreStatus.FAILED.value
            log_entry.error_message = str(e)
            log_entry.completed_at = time.time()
        self._save_restore_logs()
        return log_entry

    def dry_run_restore(self, backup_id: str, operator: str = "") -> RestoreLog:
        return self.restore_from_backup(backup_id=backup_id, dry_run=True, operator=operator, notes="Dry-run validation")

    def get_restore_history(self, limit: int = 50, status: Optional[str] = None) -> List[RestoreLog]:
        logs = self._restore_logs
        if status:
            logs = [r for r in logs if r.status == status]
        logs.sort(key=lambda x: x.started_at, reverse=True)
        return logs[:limit]

    def _validate_backup(self, manifest: BackupManifest) -> bool:
        backup_path = Path(manifest.backup_path)
        if not backup_path.exists():
            return False
        db_backup = backup_path / "database.sqlite"
        db_encrypted = backup_path / "database.sqlite.enc"
        if db_encrypted.exists():
            if not self.backup_manager.encryptor._key:
                return False
            try:
                decrypted = self.backup_manager.encryptor.decrypt(db_encrypted.read_bytes())
                return decrypted.startswith(b"SQLite format 3")
            except Exception:
                return False
        elif db_backup.exists():
            try:
                conn = sqlite3.connect(str(db_backup))
                conn.execute("SELECT count(*) FROM sqlite_master")
                conn.close()
                return True
            except sqlite3.DatabaseError:
                return False
        return True

    def _selective_db_restore(self, source_db: Path, target_db: str, tables: List[str]):
        src_conn = sqlite3.connect(str(source_db))
        dst_conn = sqlite3.connect(target_db)
        try:
            for table in tables:
                src_cur = src_conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
                if not src_cur.fetchone():
                    continue
                schema_cur = src_conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,))
                schema = schema_cur.fetchone()
                if not schema:
                    continue
                dst_conn.execute(f"DROP TABLE IF EXISTS [{table}]")
                dst_conn.execute(schema[0])
                rows = src_conn.execute(f"SELECT * FROM [{table}]").fetchall()
                if rows:
                    placeholders = ",".join(["?"] * len(rows[0]))
                    dst_conn.executemany(f"INSERT INTO [{table}] VALUES ({placeholders})", rows)
            dst_conn.commit()
        finally:
            src_conn.close()
            dst_conn.close()

    def _list_tables(self, db_path: str) -> List[str]:
        try:
            conn = sqlite3.connect(db_path)
            cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cur.fetchall()]
            conn.close()
            return tables
        except Exception:
            return []


_engine: Optional[RestoreEngine] = None

def get_restore_engine(**kwargs) -> RestoreEngine:
    global _engine
    if _engine is None:
        _engine = RestoreEngine(**kwargs)
    return _engine

def reset_restore_engine():
    global _engine
    _engine = None
