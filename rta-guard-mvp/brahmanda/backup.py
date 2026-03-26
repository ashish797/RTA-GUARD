"""
RTA-GUARD — Backup Management (Phase 6.7)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import sqlite3
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from enum import Enum
from pathlib import Path
from typing import Optional, List, Dict, Any, Callable

logger = logging.getLogger(__name__)


class BackupType(Enum):
    FULL = "full"
    INCREMENTAL = "incremental"
    CONFIG = "config"
    AUDIT_LOG = "audit_log"


class BackupStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    VERIFIED = "verified"


@dataclass
class BackupManifest:
    backup_id: str
    backup_type: str
    status: str = "pending"
    created_at: float = 0.0
    completed_at: float = 0.0
    size_bytes: int = 0
    checksum: str = ""
    source_path: str = ""
    backup_path: str = ""
    encrypted: bool = False
    verified: bool = False
    tables_included: List[str] = field(default_factory=list)
    error_message: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = time.time()

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "BackupManifest":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class BackupEncryptor:
    def __init__(self, key: Optional[bytes] = None):
        self._key = key

    @staticmethod
    def generate_key() -> bytes:
        try:
            from cryptography.fernet import Fernet
            return Fernet.generate_key()
        except ImportError:
            import base64
            return base64.urlsafe_b64encode(os.urandom(32))

    def encrypt(self, data: bytes) -> bytes:
        if not self._key:
            return data
        try:
            from cryptography.fernet import Fernet
        except ImportError:
            return data
        return Fernet(self._key).encrypt(data)

    def decrypt(self, data: bytes) -> bytes:
        if not self._key:
            return data
        try:
            from cryptography.fernet import Fernet
        except ImportError:
            return data
        return Fernet(self._key).decrypt(data)

    def encrypt_file(self, src: Path, dst: Path) -> None:
        dst.write_bytes(self.encrypt(src.read_bytes()))

    def decrypt_file(self, src: Path, dst: Path) -> None:
        dst.write_bytes(self.decrypt(src.read_bytes()))


class BackupStore:
    DEFAULT_ROTATION = {"hourly": 30, "daily": 7, "monthly": 12}

    def __init__(self, backup_dir: str, rotation: Optional[Dict[str, int]] = None):
        self.backup_dir = Path(backup_dir)
        self.rotation = rotation or self.DEFAULT_ROTATION.copy()
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self._manifests: Dict[str, BackupManifest] = {}
        self._load_manifests()

    def _manifest_index_path(self) -> Path:
        return self.backup_dir / "manifest_index.json"

    def _load_manifests(self):
        idx = self._manifest_index_path()
        if idx.exists():
            try:
                data = json.loads(idx.read_text())
                self._manifests = {k: BackupManifest.from_dict(v) for k, v in data.items()}
            except (json.JSONDecodeError, KeyError):
                self._manifests = {}

    def _save_manifests(self):
        data = {k: v.to_dict() for k, v in self._manifests.items()}
        self._manifest_index_path().write_text(json.dumps(data, indent=2))

    def store_manifest(self, manifest: BackupManifest):
        self._manifests[manifest.backup_id] = manifest
        self._save_manifests()

    def get_manifest(self, backup_id: str) -> Optional[BackupManifest]:
        return self._manifests.get(backup_id)

    def list_manifests(self, backup_type: Optional[str] = None, since: Optional[float] = None) -> List[BackupManifest]:
        results = []
        for m in self._manifests.values():
            if backup_type and m.backup_type != backup_type:
                continue
            if since and m.created_at < since:
                continue
            results.append(m)
        results.sort(key=lambda x: x.created_at, reverse=True)
        return results

    def delete_backup(self, backup_id: str) -> bool:
        manifest = self._manifests.pop(backup_id, None)
        if manifest:
            path = Path(manifest.backup_path)
            if path.exists():
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
            self._save_manifests()
            return True
        return False

    def rotate(self) -> int:
        deleted = 0
        now = datetime.now(timezone.utc)
        cutoffs = {
            "hourly": now - timedelta(hours=self.rotation["hourly"]),
            "daily": now - timedelta(days=self.rotation["daily"]),
            "monthly": now - timedelta(days=self.rotation["monthly"] * 30),
        }
        for manifest in list(self._manifests.values()):
            created = datetime.fromtimestamp(manifest.created_at, tz=timezone.utc)
            btype = manifest.backup_type
            if btype == BackupType.INCREMENTAL.value:
                cat = "hourly"
            elif btype == BackupType.FULL.value:
                cat = "daily"
            elif btype in (BackupType.CONFIG.value, BackupType.AUDIT_LOG.value):
                cat = "monthly"
            else:
                continue
            if created < cutoffs.get(cat, now):
                self.delete_backup(manifest.backup_id)
                deleted += 1
        return deleted


class BackupManager:
    def __init__(self, db_path: str = "", config_dir: str = "", audit_log_dir: str = "",
                 backup_dir: str = "/tmp/rta-guard/backups", encryption_key: Optional[bytes] = None,
                 enabled: bool = False):
        self.enabled = enabled
        self.db_path = db_path
        self.config_dir = config_dir
        self.audit_log_dir = audit_log_dir
        self.store = BackupStore(backup_dir)
        self.encryptor = BackupEncryptor(encryption_key) if encryption_key else BackupEncryptor()
        self._last_full_backup: float = 0.0
        self._last_incremental_backup: float = 0.0

    def create_full_backup(self, verify: bool = True) -> BackupManifest:
        if not self.enabled:
            return BackupManifest(backup_id="disabled", backup_type="full", status="skipped")
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup_id = f"full_{ts}"
        backup_path = self.store.backup_dir / backup_id
        backup_path.mkdir(parents=True, exist_ok=True)
        manifest = BackupManifest(backup_id=backup_id, backup_type=BackupType.FULL.value,
                                  status=BackupStatus.IN_PROGRESS.value, source_path=self.db_path,
                                  backup_path=str(backup_path), encrypted=bool(self.encryptor._key))
        self.store.store_manifest(manifest)
        try:
            if self.db_path and Path(self.db_path).exists():
                db_backup = backup_path / "database.sqlite"
                self._sqlite_backup(self.db_path, str(db_backup))
                if self.encryptor._key:
                    encrypted_path = backup_path / "database.sqlite.enc"
                    self.encryptor.encrypt_file(db_backup, encrypted_path)
                    db_backup.unlink()
                    manifest.encrypted = True
            if self.config_dir and Path(self.config_dir).exists():
                shutil.copytree(self.config_dir, backup_path / "config")
            if self.audit_log_dir and Path(self.audit_log_dir).exists():
                shutil.copytree(self.audit_log_dir, backup_path / "audit_logs")
            manifest.size_bytes = self._dir_size(backup_path)
            manifest.checksum = self._compute_checksum(backup_path)
            manifest.status = BackupStatus.COMPLETED.value
            manifest.completed_at = time.time()
            self._last_full_backup = manifest.completed_at
            if verify:
                manifest.verified = self._verify_backup(manifest)
                manifest.status = BackupStatus.VERIFIED.value if manifest.verified else BackupStatus.COMPLETED.value
            self.store.store_manifest(manifest)
        except Exception as e:
            manifest.status = BackupStatus.FAILED.value
            manifest.error_message = str(e)
            self.store.store_manifest(manifest)
        return manifest

    def create_incremental_backup(self, since: Optional[float] = None) -> BackupManifest:
        if not self.enabled:
            return BackupManifest(backup_id="disabled", backup_type="incremental", status="skipped")
        since_ts = since or max(self._last_full_backup, self._last_incremental_backup)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup_id = f"incr_{ts}"
        backup_path = self.store.backup_dir / backup_id
        backup_path.mkdir(parents=True, exist_ok=True)
        manifest = BackupManifest(backup_id=backup_id, backup_type=BackupType.INCREMENTAL.value,
                                  status=BackupStatus.IN_PROGRESS.value, source_path=self.db_path,
                                  backup_path=str(backup_path), encrypted=bool(self.encryptor._key))
        self.store.store_manifest(manifest)
        try:
            if self.db_path and Path(self.db_path).exists():
                self._sqlite_wal_checkpoint(self.db_path)
                db_backup = backup_path / "database.sqlite"
                self._sqlite_backup(self.db_path, str(db_backup))
                if self.encryptor._key:
                    encrypted_path = backup_path / "database.sqlite.enc"
                    self.encryptor.encrypt_file(db_backup, encrypted_path)
                    db_backup.unlink()
            if self.config_dir and Path(self.config_dir).exists():
                config_backup = backup_path / "config"
                config_backup.mkdir(exist_ok=True)
                for f in Path(self.config_dir).rglob("*"):
                    if f.is_file() and f.stat().st_mtime > since_ts:
                        rel = f.relative_to(self.config_dir)
                        dst = config_backup / rel
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(f, dst)
            if self.audit_log_dir and Path(self.audit_log_dir).exists():
                audit_backup = backup_path / "audit_logs"
                audit_backup.mkdir(exist_ok=True)
                for f in Path(self.audit_log_dir).rglob("*"):
                    if f.is_file() and f.stat().st_mtime > since_ts:
                        rel = f.relative_to(self.audit_log_dir)
                        dst = audit_backup / rel
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(f, dst)
            manifest.size_bytes = self._dir_size(backup_path)
            manifest.checksum = self._compute_checksum(backup_path)
            manifest.status = BackupStatus.COMPLETED.value
            manifest.completed_at = time.time()
            self._last_incremental_backup = manifest.completed_at
            self.store.store_manifest(manifest)
        except Exception as e:
            manifest.status = BackupStatus.FAILED.value
            manifest.error_message = str(e)
            self.store.store_manifest(manifest)
        return manifest

    def create_config_backup(self) -> BackupManifest:
        if not self.enabled:
            return BackupManifest(backup_id="disabled", backup_type="config", status="skipped")
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup_id = f"config_{ts}"
        backup_path = self.store.backup_dir / backup_id
        backup_path.mkdir(parents=True, exist_ok=True)
        manifest = BackupManifest(backup_id=backup_id, backup_type=BackupType.CONFIG.value,
                                  status=BackupStatus.COMPLETED.value, source_path=self.config_dir,
                                  backup_path=str(backup_path), completed_at=time.time())
        try:
            if self.config_dir and Path(self.config_dir).exists():
                shutil.copytree(self.config_dir, backup_path / "config")
            manifest.size_bytes = self._dir_size(backup_path)
            manifest.checksum = self._compute_checksum(backup_path)
            self.store.store_manifest(manifest)
        except Exception as e:
            manifest.status = BackupStatus.FAILED.value
            manifest.error_message = str(e)
            self.store.store_manifest(manifest)
        return manifest

    def create_audit_log_backup(self) -> BackupManifest:
        if not self.enabled:
            return BackupManifest(backup_id="disabled", backup_type="audit_log", status="skipped")
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup_id = f"audit_{ts}"
        backup_path = self.store.backup_dir / backup_id
        backup_path.mkdir(parents=True, exist_ok=True)
        manifest = BackupManifest(backup_id=backup_id, backup_type=BackupType.AUDIT_LOG.value,
                                  status=BackupStatus.COMPLETED.value, source_path=self.audit_log_dir,
                                  backup_path=str(backup_path), completed_at=time.time())
        try:
            if self.audit_log_dir and Path(self.audit_log_dir).exists():
                shutil.copytree(self.audit_log_dir, backup_path / "audit_logs")
            manifest.size_bytes = self._dir_size(backup_path)
            manifest.checksum = self._compute_checksum(backup_path)
            self.store.store_manifest(manifest)
        except Exception as e:
            manifest.status = BackupStatus.FAILED.value
            manifest.error_message = str(e)
            self.store.store_manifest(manifest)
        return manifest

    def run_scheduled_backup(self, schedule: str = "daily") -> BackupManifest:
        if schedule == "daily":
            manifest = self.create_full_backup(verify=True)
            self.store.rotate()
            return manifest
        elif schedule == "hourly":
            return self.create_incremental_backup()
        else:
            raise ValueError(f"Unknown schedule: {schedule}")

    def _sqlite_backup(self, source_db: str, dest_path: str):
        src = sqlite3.connect(source_db)
        dst = sqlite3.connect(dest_path)
        with dst:
            src.backup(dst)
        src.close()
        dst.close()

    def _sqlite_wal_checkpoint(self, db_path: str):
        conn = sqlite3.connect(db_path)
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            conn.close()

    def _verify_backup(self, manifest: BackupManifest) -> bool:
        backup_path = Path(manifest.backup_path)
        try:
            if manifest.encrypted and self.encryptor._key:
                enc_path = backup_path / "database.sqlite.enc"
                if enc_path.exists():
                    decrypted = self.encryptor.decrypt(enc_path.read_bytes())
                    if not decrypted.startswith(b"SQLite format 3"):
                        return False
            else:
                db_path = backup_path / "database.sqlite"
                if db_path.exists():
                    conn = sqlite3.connect(str(db_path))
                    conn.execute("SELECT count(*) FROM sqlite_master")
                    conn.close()
            current_checksum = self._compute_checksum(backup_path)
            return current_checksum == manifest.checksum
        except Exception:
            return False

    def _compute_checksum(self, path: Path) -> str:
        hasher = hashlib.sha256()
        if path.is_file():
            hasher.update(path.read_bytes())
        elif path.is_dir():
            for f in sorted(path.rglob("*")):
                if f.is_file():
                    hasher.update(f.read_bytes())
        return hasher.hexdigest()

    def _dir_size(self, path: Path) -> int:
        total = 0
        for f in path.rglob("*"):
            if f.is_file():
                total += f.stat().st_size
        return total


_manager: Optional[BackupManager] = None

def get_backup_manager(**kwargs) -> BackupManager:
    global _manager
    if _manager is None:
        _manager = BackupManager(**kwargs)
    return _manager

def reset_backup_manager():
    global _manager
    _manager = None
