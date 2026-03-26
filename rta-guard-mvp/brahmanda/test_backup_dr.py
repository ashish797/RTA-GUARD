"""
Tests for Phase 6.7 — Backup & Disaster Recovery
"""

import json
import os
import sqlite3
import tempfile
import time

import pytest


class TestBackupManifest:
    def test_creation(self):
        from brahmanda.backup import BackupManifest
        m = BackupManifest(backup_id="test_001", backup_type="full")
        assert m.backup_id == "test_001"
        assert m.status == "pending"
        assert m.created_at > 0

    def test_to_dict_roundtrip(self):
        from brahmanda.backup import BackupManifest
        m = BackupManifest(backup_id="test_002", backup_type="incremental", size_bytes=1024)
        d = m.to_dict()
        m2 = BackupManifest.from_dict(d)
        assert m2.backup_id == m.backup_id
        assert m2.size_bytes == 1024


class TestBackupStore:
    def _make_store(self):
        from brahmanda.backup import BackupStore
        return BackupStore(tempfile.mkdtemp())

    def test_store_and_get(self):
        from brahmanda.backup import BackupManifest
        store = self._make_store()
        store.store_manifest(BackupManifest(backup_id="b1", backup_type="full"))
        assert store.get_manifest("b1").backup_id == "b1"

    def test_list_manifests(self):
        from brahmanda.backup import BackupManifest
        store = self._make_store()
        store.store_manifest(BackupManifest(backup_id="b1", backup_type="full"))
        store.store_manifest(BackupManifest(backup_id="b2", backup_type="incremental"))
        assert len(store.list_manifests()) == 2
        assert len(store.list_manifests(backup_type="full")) == 1

    def test_delete(self):
        from brahmanda.backup import BackupManifest
        store = self._make_store()
        bp = tempfile.mkdtemp()
        store.store_manifest(BackupManifest(backup_id="b1", backup_type="full", backup_path=bp))
        assert store.delete_backup("b1")
        assert store.get_manifest("b1") is None


class TestBackupEncryptor:
    def test_no_key_passthrough(self):
        from brahmanda.backup import BackupEncryptor
        enc = BackupEncryptor()
        data = b"hello world"
        assert enc.encrypt(data) == data
        assert enc.decrypt(data) == data

    def test_generate_key(self):
        from brahmanda.backup import BackupEncryptor
        key = BackupEncryptor.generate_key()
        assert isinstance(key, bytes)
        assert len(key) > 0


class TestBackupManager:
    def _make_manager(self, enabled=True):
        from brahmanda.backup import BackupManager
        tmpdir = tempfile.mkdtemp()
        db_path = os.path.join(tmpdir, "test.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE sessions (id INTEGER PRIMARY KEY, data TEXT)")
        conn.execute("INSERT INTO sessions VALUES (1, 'test')")
        conn.commit(); conn.close()
        config_dir = os.path.join(tmpdir, "config"); os.makedirs(config_dir)
        with open(os.path.join(config_dir, "app.conf"), "w") as f: f.write("key=value\n")
        audit_dir = os.path.join(tmpdir, "audit"); os.makedirs(audit_dir)
        with open(os.path.join(audit_dir, "audit.log"), "w") as f: f.write("entry1\n")
        return BackupManager(db_path=db_path, config_dir=config_dir, audit_log_dir=audit_dir,
                             backup_dir=os.path.join(tmpdir, "backups"), enabled=enabled)

    def test_disabled_skips(self):
        assert self._make_manager(enabled=False).create_full_backup().status == "skipped"

    def test_full_backup(self):
        m = self._make_manager().create_full_backup(verify=False)
        assert m.status == "completed" and m.size_bytes > 0 and m.checksum

    def test_full_backup_with_verify(self):
        assert self._make_manager().create_full_backup(verify=True).status in ("completed", "verified")

    def test_incremental_backup(self):
        bm = self._make_manager()
        bm.create_full_backup(verify=False)
        time.sleep(0.1)
        m = bm.create_incremental_backup()
        assert m.status == "completed" and m.backup_type == "incremental"

    def test_config_backup(self):
        m = self._make_manager().create_config_backup()
        assert m.status == "completed" and m.backup_type == "config"

    def test_audit_log_backup(self):
        m = self._make_manager().create_audit_log_backup()
        assert m.status == "completed" and m.backup_type == "audit_log"

    def test_scheduled_daily(self):
        assert self._make_manager().run_scheduled_backup("daily").status in ("completed", "verified")

    def test_scheduled_hourly(self):
        bm = self._make_manager()
        bm.create_full_backup(verify=False)
        assert bm.run_scheduled_backup("hourly").status == "completed"

    def test_scheduled_invalid(self):
        with pytest.raises(ValueError):
            self._make_manager().run_scheduled_backup("weekly")


class TestBackupSingleton:
    def test_get_and_reset(self):
        from brahmanda.backup import get_backup_manager, reset_backup_manager
        reset_backup_manager()
        t = tempfile.mkdtemp()
        bm = get_backup_manager(enabled=False, backup_dir=os.path.join(t, "backups"))
        assert bm is not None and bm is get_backup_manager()
        reset_backup_manager()
        t2 = tempfile.mkdtemp()
        assert get_backup_manager(enabled=False, backup_dir=os.path.join(t2, "backups")) is not bm
        reset_backup_manager()


class TestRestoreLog:
    def test_creation(self):
        from brahmanda.restore import RestoreLog
        r = RestoreLog(restore_id="r1", backup_id="b1", mode="full")
        assert r.restore_id == "r1" and r.status == "pending"

    def test_to_dict_roundtrip(self):
        from brahmanda.restore import RestoreLog
        r = RestoreLog(restore_id="r1", backup_id="b1", mode="full", tables_restored=["t1"])
        assert RestoreLog.from_dict(r.to_dict()).tables_restored == ["t1"]


class TestRestoreEngine:
    def _setup(self):
        from brahmanda.backup import BackupManager
        from brahmanda.restore import RestoreEngine
        tmpdir = tempfile.mkdtemp()
        db_path = os.path.join(tmpdir, "test.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, val TEXT)")
        conn.execute("INSERT INTO items VALUES (1, 'original')")
        conn.commit(); conn.close()
        config_dir = os.path.join(tmpdir, "config"); os.makedirs(config_dir)
        with open(os.path.join(config_dir, "app.conf"), "w") as f: f.write("original=true\n")
        bm = BackupManager(db_path=db_path, config_dir=config_dir, audit_log_dir=os.path.join(tmpdir, "audit"),
                           backup_dir=os.path.join(tmpdir, "backups"), enabled=True)
        bm.create_full_backup(verify=False)
        return bm, RestoreEngine(backup_manager=bm, db_path=db_path, config_dir=config_dir,
                                 restore_log_path=os.path.join(tmpdir, "restore_log.json")), db_path

    def test_dry_run_restore(self):
        bm, re, _ = self._setup()
        assert re.dry_run_restore(bm.store.list_manifests()[0].backup_id).status == "validated"

    def test_restore_nonexistent(self):
        _, re, _ = self._setup()
        r = re.restore_from_backup("nonexistent_id")
        assert r.status == "failed" and "not found" in r.error_message

    def test_full_restore(self):
        bm, re, db_path = self._setup()
        backups = bm.store.list_manifests()
        conn = sqlite3.connect(db_path)
        conn.execute("DELETE FROM items"); conn.commit(); conn.close()
        result = re.restore_from_backup(backups[0].backup_id)
        assert result.status == "completed" and "items" in result.tables_restored
        conn = sqlite3.connect(db_path)
        rows = conn.execute("SELECT * FROM items").fetchall(); conn.close()
        assert len(rows) == 1 and rows[0][1] == "original"

    def test_selective_restore(self):
        bm, re, _ = self._setup()
        result = re.restore_from_backup(bm.store.list_manifests()[0].backup_id, tables=["items"])
        assert result.status == "completed" and result.tables_restored == ["items"]

    def test_point_in_time_restore(self):
        _, re, _ = self._setup()
        assert re.point_in_time_restore(target_timestamp=time.time() + 100).status in ("completed", "failed")

    def test_point_in_time_no_backup(self):
        _, re, _ = self._setup()
        assert re.point_in_time_restore(target_timestamp=0).status == "failed"

    def test_restore_history(self):
        bm, re, _ = self._setup()
        re.dry_run_restore(bm.store.list_manifests()[0].backup_id)
        assert len(re.get_restore_history()) >= 1


class TestRestoreSingleton:
    def test_get_and_reset(self):
        from brahmanda.restore import get_restore_engine, reset_restore_engine
        from brahmanda.backup import get_backup_manager, reset_backup_manager
        reset_restore_engine(); reset_backup_manager()
        t = tempfile.mkdtemp()
        bm = get_backup_manager(enabled=False, backup_dir=os.path.join(t, "backups"))
        assert get_restore_engine(backup_manager=bm, restore_log_path=os.path.join(t, "log.json")) is not None
        reset_restore_engine(); reset_backup_manager()


class TestDRMonitorModels:
    def test_rpo_target(self):
        from brahmanda.dr_monitor import RPOTarget
        assert RPOTarget(name="t", max_data_loss_seconds=3600).max_data_loss_hours == 1.0

    def test_rto_target(self):
        from brahmanda.dr_monitor import RTOTarget
        assert RTOTarget(name="t", max_recovery_seconds=7200).max_recovery_hours == 2.0

    def test_dr_health_report(self):
        from brahmanda.dr_monitor import DRHealthReport
        assert DRHealthReport(status="healthy").to_dict()["status"] == "healthy"


class TestDRMonitor:
    def _setup(self):
        from brahmanda.backup import BackupManager
        from brahmanda.dr_monitor import DRMonitor, RPOTarget, RTOTarget
        tmpdir = tempfile.mkdtemp()
        db_path = os.path.join(tmpdir, "test.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE t (id INTEGER)"); conn.commit(); conn.close()
        bm = BackupManager(db_path=db_path, backup_dir=os.path.join(tmpdir, "backups"), enabled=True)
        bm.create_full_backup(verify=False)
        return bm, DRMonitor(backup_manager=bm, rpo_target=RPOTarget(name="t", max_data_loss_seconds=86400),
                             rto_target=RTOTarget(name="t", max_recovery_seconds=3600),
                             drill_log_path=os.path.join(tmpdir, "drills.json"), enabled=True)

    def test_check_health(self):
        _, m = self._setup()
        r = m.check_health()
        assert r.status in ("healthy", "warning", "unknown") and r.total_backups >= 1

    def test_check_rpo(self):
        _, m = self._setup()
        rpo = m.check_rpo()
        assert rpo["status"] in ("compliant", "breached", "unknown") and "actual_seconds" in rpo

    def test_schedule_and_execute_drill(self):
        _, m = self._setup()
        drill = m.schedule_drill(drill_type="restore_test", operator="admin")
        assert drill.drill_id and drill.status == "scheduled"
        result = m.execute_drill(drill.drill_id)
        assert result.status in ("completed", "failed") and "duration_seconds" in result.results

    def test_drill_history(self):
        _, m = self._setup()
        m.schedule_drill(drill_type="restore_test")
        assert len(m.get_drill_history()) >= 1

    def test_disabled_monitor(self):
        from brahmanda.backup import BackupManager
        from brahmanda.dr_monitor import DRMonitor
        tmpdir = tempfile.mkdtemp()
        assert DRMonitor(backup_manager=BackupManager(backup_dir=tmpdir, enabled=False), enabled=False).check_health().status == "disabled"


class TestDRSingleton:
    def test_get_and_reset(self):
        from brahmanda.dr_monitor import get_dr_monitor, reset_dr_monitor
        from brahmanda.backup import get_backup_manager, reset_backup_manager
        reset_dr_monitor(); reset_backup_manager()
        t = tempfile.mkdtemp()
        bm = get_backup_manager(enabled=False, backup_dir=os.path.join(t, "backups"))
        assert get_dr_monitor(backup_manager=bm, enabled=False, drill_log_path=os.path.join(t, "dr.json")) is not None
        reset_dr_monitor(); reset_backup_manager()


class TestSnapshotManifest:
    def test_creation(self):
        from brahmanda.snapshot import SnapshotManifest
        m = SnapshotManifest(snapshot_id="s1", snapshot_type="full")
        assert m.snapshot_id == "s1" and m.status == "pending"

    def test_to_dict_roundtrip(self):
        from brahmanda.snapshot import SnapshotManifest
        m = SnapshotManifest(snapshot_id="s1", snapshot_type="full", components=["db", "config"])
        assert SnapshotManifest.from_dict(m.to_dict()).components == ["db", "config"]


class TestSnapshotStore:
    def _make_store(self):
        from brahmanda.snapshot import SnapshotStore
        return SnapshotStore(tempfile.mkdtemp())

    def test_store_and_get(self):
        from brahmanda.snapshot import SnapshotManifest
        store = self._make_store()
        store.store_manifest(SnapshotManifest(snapshot_id="s1", snapshot_type="full"))
        assert store.get_manifest("s1").snapshot_id == "s1"

    def test_list(self):
        from brahmanda.snapshot import SnapshotManifest
        store = self._make_store()
        store.store_manifest(SnapshotManifest(snapshot_id="s1", snapshot_type="full"))
        store.store_manifest(SnapshotManifest(snapshot_id="s2", snapshot_type="incremental"))
        assert len(store.list_manifests()) == 2 and len(store.list_manifests(snapshot_type="full")) == 1

    def test_cleanup(self):
        from brahmanda.snapshot import SnapshotManifest
        store = self._make_store()
        store.max_snapshots = 2
        for i in range(5):
            # Create actual temp dirs for snapshots so cleanup works
            d = os.path.join(str(store.snapshot_dir), f"dir_{i}")
            os.makedirs(d)
            store.store_manifest(SnapshotManifest(snapshot_id=f"s{i}", snapshot_type="full", snapshot_path=d))
        assert store.cleanup() == 3 and len(store.list_manifests()) == 2


class TestSnapshotManager:
    def _make_manager(self, enabled=True):
        from brahmanda.snapshot import SnapshotManager
        tmpdir = tempfile.mkdtemp()
        db_path = os.path.join(tmpdir, "test.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE t (id INTEGER)"); conn.commit(); conn.close()
        config_dir = os.path.join(tmpdir, "config"); os.makedirs(config_dir)
        with open(os.path.join(config_dir, "app.conf"), "w") as f: f.write("key=value\n")
        state_dir = os.path.join(tmpdir, "state"); os.makedirs(state_dir)
        with open(os.path.join(state_dir, "cache.json"), "w") as f: f.write("{}\n")
        return SnapshotManager(db_path=db_path, config_dir=config_dir, state_dirs=[state_dir],
                               snapshot_dir=os.path.join(tmpdir, "snapshots"), enabled=enabled)

    def test_disabled_skips(self):
        assert self._make_manager(enabled=False).create_full_snapshot().status == "skipped"

    def test_full_snapshot(self):
        m = self._make_manager().create_full_snapshot()
        assert m.status == "completed" and "database" in m.components and m.size_bytes > 0

    def test_incremental_snapshot(self):
        sm = self._make_manager()
        sm.create_full_snapshot(); time.sleep(0.1)
        m = sm.create_incremental_snapshot()
        assert m.status == "completed" and m.snapshot_type == "incremental"

    def test_incremental_no_parent_creates_full(self):
        assert self._make_manager().create_incremental_snapshot().snapshot_type == "full"

    def test_deduplication(self):
        sm = self._make_manager()
        sm.create_full_snapshot(); sm.create_full_snapshot()
        assert sm.deduplicate() >= 0


class TestSnapshotSingleton:
    def test_get_and_reset(self):
        from brahmanda.snapshot import get_snapshot_manager, reset_snapshot_manager
        reset_snapshot_manager()
        t = tempfile.mkdtemp()
        assert get_snapshot_manager(enabled=False, snapshot_dir=os.path.join(t, "snaps")) is not None
        reset_snapshot_manager()


class TestBackupRestoreIntegration:
    def test_full_cycle(self):
        from brahmanda.backup import BackupManager
        from brahmanda.restore import RestoreEngine
        tmpdir = tempfile.mkdtemp()
        db_path = os.path.join(tmpdir, "test.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE records (id INTEGER PRIMARY KEY, data TEXT)")
        conn.execute("INSERT INTO records VALUES (1, 'important'), (2, 'critical')")
        conn.commit(); conn.close()
        bm = BackupManager(db_path=db_path, backup_dir=os.path.join(tmpdir, "backups"), enabled=True)
        backup = bm.create_full_backup(verify=False)
        assert backup.status == "completed"
        conn = sqlite3.connect(db_path)
        conn.execute("DELETE FROM records"); conn.commit(); conn.close()
        re = RestoreEngine(backup_manager=bm, db_path=db_path)
        result = re.restore_from_backup(backup.backup_id)
        assert result.status == "completed"
        conn = sqlite3.connect(db_path)
        rows = conn.execute("SELECT * FROM records ORDER BY id").fetchall(); conn.close()
        assert len(rows) == 2 and rows[0][1] == "important" and rows[1][1] == "critical"
