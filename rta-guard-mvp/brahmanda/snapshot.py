"""
RTA-GUARD — System Snapshots (Phase 6.7)
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
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)


class SnapshotType(Enum):
    FULL = "full"
    INCREMENTAL = "incremental"


class SnapshotStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    ARCHIVED = "archived"


@dataclass
class SnapshotManifest:
    snapshot_id: str
    snapshot_type: str
    status: str = "pending"
    created_at: float = 0.0
    completed_at: float = 0.0
    size_bytes: int = 0
    compressed_size_bytes: int = 0
    checksum: str = ""
    snapshot_path: str = ""
    components: List[str] = field(default_factory=list)
    parent_snapshot_id: str = ""
    file_hashes: Dict[str, str] = field(default_factory=dict)
    error_message: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = time.time()

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "SnapshotManifest":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class SnapshotStore:
    def __init__(self, snapshot_dir: str, max_snapshots: int = 50):
        self.snapshot_dir = Path(snapshot_dir)
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        self.max_snapshots = max_snapshots
        self._manifests: Dict[str, SnapshotManifest] = {}
        self._load_manifests()

    def _manifest_index_path(self) -> Path:
        return self.snapshot_dir / "snapshot_index.json"

    def _load_manifests(self):
        idx = self._manifest_index_path()
        if idx.exists():
            try:
                data = json.loads(idx.read_text())
                self._manifests = {k: SnapshotManifest.from_dict(v) for k, v in data.items()}
            except (json.JSONDecodeError, KeyError):
                self._manifests = {}

    def _save_manifests(self):
        data = {k: v.to_dict() for k, v in self._manifests.items()}
        self._manifest_index_path().write_text(json.dumps(data, indent=2))

    def store_manifest(self, manifest: SnapshotManifest):
        self._manifests[manifest.snapshot_id] = manifest
        self._save_manifests()

    def get_manifest(self, snapshot_id: str) -> Optional[SnapshotManifest]:
        return self._manifests.get(snapshot_id)

    def list_manifests(self, snapshot_type: Optional[str] = None) -> List[SnapshotManifest]:
        results = []
        for m in self._manifests.values():
            if snapshot_type and m.snapshot_type != snapshot_type:
                continue
            results.append(m)
        results.sort(key=lambda x: x.created_at, reverse=True)
        return results

    def delete_snapshot(self, snapshot_id: str) -> bool:
        manifest = self._manifests.pop(snapshot_id, None)
        if manifest:
            path = Path(manifest.snapshot_path)
            if path.exists() and path.is_dir():
                shutil.rmtree(path)
            self._save_manifests()
            return True
        return False

    def cleanup(self) -> int:
        all_snaps = sorted(self._manifests.values(), key=lambda s: s.created_at)
        deleted = 0
        while len(all_snaps) > self.max_snapshots:
            oldest = all_snaps.pop(0)
            self.delete_snapshot(oldest.snapshot_id)
            deleted += 1
        return deleted

    def archive_snapshot(self, snapshot_id: str, archive_dir: str) -> bool:
        manifest = self._manifests.get(snapshot_id)
        if not manifest:
            return False
        src_path = Path(manifest.snapshot_path)
        if not src_path.exists():
            return False
        archive_path = Path(archive_dir)
        archive_path.mkdir(parents=True, exist_ok=True)
        archive_file = archive_path / f"{snapshot_id}.tar.gz"
        import tarfile
        with tarfile.open(archive_file, "w:gz") as tar:
            tar.add(src_path, arcname=snapshot_id)
        manifest.status = SnapshotStatus.ARCHIVED.value
        manifest.compressed_size_bytes = archive_file.stat().st_size
        self._save_manifests()
        shutil.rmtree(src_path)
        return True


class SnapshotManager:
    def __init__(self, db_path: str = "", config_dir: str = "", state_dirs: Optional[List[str]] = None,
                 snapshot_dir: str = "/tmp/rta-guard/snapshots", archive_dir: str = "/tmp/rta-guard/snapshot-archive",
                 max_snapshots: int = 50, enabled: bool = False):
        self.enabled = enabled
        self.db_path = db_path
        self.config_dir = config_dir
        self.state_dirs = state_dirs or []
        self.archive_dir = archive_dir
        self.store = SnapshotStore(snapshot_dir, max_snapshots)
        self._last_full_snapshot_id: str = ""

    def create_full_snapshot(self) -> SnapshotManifest:
        if not self.enabled:
            return SnapshotManifest(snapshot_id="disabled", snapshot_type="full", status="skipped")
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        snapshot_id = f"full_snap_{ts}"
        snapshot_path = self.store.snapshot_dir / snapshot_id
        snapshot_path.mkdir(parents=True, exist_ok=True)
        manifest = SnapshotManifest(snapshot_id=snapshot_id, snapshot_type=SnapshotType.FULL.value,
                                    status=SnapshotStatus.IN_PROGRESS.value, snapshot_path=str(snapshot_path))
        self.store.store_manifest(manifest)
        try:
            components = []
            file_hashes: Dict[str, str] = {}
            if self.db_path and Path(self.db_path).exists():
                db_snap = snapshot_path / "database"
                db_snap.mkdir(exist_ok=True)
                self._snapshot_database(self.db_path, db_snap)
                components.append("database")
                self._collect_hashes(db_snap, file_hashes)
            if self.config_dir and Path(self.config_dir).exists():
                config_snap = snapshot_path / "config"
                shutil.copytree(self.config_dir, config_snap)
                components.append("config")
                self._collect_hashes(config_snap, file_hashes)
            for state_dir in self.state_dirs:
                if Path(state_dir).exists():
                    state_name = Path(state_dir).name
                    state_snap = snapshot_path / f"state_{state_name}"
                    shutil.copytree(state_dir, state_snap)
                    components.append(f"state_{state_name}")
                    self._collect_hashes(state_snap, file_hashes)
            manifest.components = components
            manifest.file_hashes = file_hashes
            manifest.size_bytes = self._dir_size(snapshot_path)
            manifest.checksum = self._compute_checksum(snapshot_path)
            manifest.status = SnapshotStatus.COMPLETED.value
            manifest.completed_at = time.time()
            self._last_full_snapshot_id = snapshot_id
            self.store.store_manifest(manifest)
            self.store.cleanup()
        except Exception as e:
            manifest.status = SnapshotStatus.FAILED.value
            manifest.error_message = str(e)
            self.store.store_manifest(manifest)
        return manifest

    def create_incremental_snapshot(self, parent_id: Optional[str] = None) -> SnapshotManifest:
        if not self.enabled:
            return SnapshotManifest(snapshot_id="disabled", snapshot_type="incremental", status="skipped")
        parent_id = parent_id or self._last_full_snapshot_id
        if not parent_id:
            return self.create_full_snapshot()
        parent = self.store.get_manifest(parent_id)
        if not parent:
            return self.create_full_snapshot()
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        snapshot_id = f"incr_snap_{ts}"
        snapshot_path = self.store.snapshot_dir / snapshot_id
        snapshot_path.mkdir(parents=True, exist_ok=True)
        manifest = SnapshotManifest(snapshot_id=snapshot_id, snapshot_type=SnapshotType.INCREMENTAL.value,
                                    status=SnapshotStatus.IN_PROGRESS.value, snapshot_path=str(snapshot_path),
                                    parent_snapshot_id=parent_id)
        self.store.store_manifest(manifest)
        try:
            components = []
            file_hashes: Dict[str, str] = {}
            parent_hashes = parent.file_hashes
            if self.db_path and Path(self.db_path).exists():
                db_mtime = Path(self.db_path).stat().st_mtime
                if db_mtime > parent.completed_at:
                    db_snap = snapshot_path / "database"
                    db_snap.mkdir(exist_ok=True)
                    self._snapshot_database(self.db_path, db_snap)
                    components.append("database")
                    self._collect_hashes(db_snap, file_hashes)
            if self.config_dir and Path(self.config_dir).exists():
                changed_files = self._find_changed_files(Path(self.config_dir), parent_hashes, parent.completed_at)
                if changed_files:
                    config_snap = snapshot_path / "config"
                    for f in changed_files:
                        rel = f.relative_to(self.config_dir)
                        dst = config_snap / rel
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(f, dst)
                    components.append("config")
                    self._collect_hashes(config_snap, file_hashes)
            for state_dir in self.state_dirs:
                if Path(state_dir).exists():
                    changed_files = self._find_changed_files(Path(state_dir), parent_hashes, parent.completed_at)
                    if changed_files:
                        state_name = Path(state_dir).name
                        state_snap = snapshot_path / f"state_{state_name}"
                        for f in changed_files:
                            rel = f.relative_to(state_dir)
                            dst = state_snap / rel
                            dst.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(f, dst)
                        components.append(f"state_{state_name}")
                        self._collect_hashes(state_snap, file_hashes)
            manifest.components = components
            manifest.file_hashes = file_hashes
            manifest.size_bytes = self._dir_size(snapshot_path)
            manifest.checksum = self._compute_checksum(snapshot_path)
            manifest.status = SnapshotStatus.COMPLETED.value
            manifest.completed_at = time.time()
            self.store.store_manifest(manifest)
        except Exception as e:
            manifest.status = SnapshotStatus.FAILED.value
            manifest.error_message = str(e)
            self.store.store_manifest(manifest)
        return manifest

    def deduplicate(self) -> int:
        content_hashes: Dict[str, List[str]] = {}
        for manifest in self.store.list_manifests():
            for file_path, file_hash in manifest.file_hashes.items():
                key = f"{manifest.snapshot_id}:{file_path}"
                content_hashes.setdefault(file_hash, []).append(key)
        duplicates = {h: paths for h, paths in content_hashes.items() if len(paths) > 1}
        return len(duplicates)

    def _snapshot_database(self, db_path: str, dest_dir: Path):
        dest_db = dest_dir / "database.sqlite"
        src = sqlite3.connect(db_path)
        dst = sqlite3.connect(str(dest_db))
        with dst:
            src.backup(dst)
        src.close()
        dst.close()

    def _find_changed_files(self, dir_path: Path, parent_hashes: Dict[str, str], since: float) -> List[Path]:
        changed = []
        for f in dir_path.rglob("*"):
            if f.is_file():
                rel = str(f.relative_to(dir_path))
                if self._file_hash(f) != parent_hashes.get(rel):
                    changed.append(f)
        return changed

    def _collect_hashes(self, dir_path: Path, hashes: Dict[str, str]):
        base = dir_path.parent
        for f in dir_path.rglob("*"):
            if f.is_file():
                hashes[str(f.relative_to(base))] = self._file_hash(f)

    def _file_hash(self, path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

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
        return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


_manager: Optional[SnapshotManager] = None

def get_snapshot_manager(**kwargs) -> SnapshotManager:
    global _manager
    if _manager is None:
        _manager = SnapshotManager(**kwargs)
    return _manager

def reset_snapshot_manager():
    global _manager
    _manager = None
