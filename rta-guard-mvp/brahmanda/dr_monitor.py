"""
RTA-GUARD — Disaster Recovery Monitoring (Phase 6.7)
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional, List, Dict, Any, Callable

from brahmanda.backup import BackupManager, BackupStatus

logger = logging.getLogger(__name__)


class DRStatus(Enum):
    HEALTHY = "healthy"
    WARNING = "warning"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


class DrillStatus(Enum):
    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class RPOTarget:
    name: str
    max_data_loss_seconds: float
    description: str = ""

    @property
    def max_data_loss_hours(self) -> float:
        return self.max_data_loss_seconds / 3600


@dataclass
class RTOTarget:
    name: str
    max_recovery_seconds: float
    description: str = ""

    @property
    def max_recovery_hours(self) -> float:
        return self.max_recovery_seconds / 3600


@dataclass
class DRHealthReport:
    status: str = "unknown"
    last_full_backup_age_seconds: float = 0.0
    last_incremental_backup_age_seconds: float = 0.0
    total_backups: int = 0
    failed_backups_24h: int = 0
    rpo_status: str = "unknown"
    rto_status: str = "unknown"
    rpo_actual_seconds: float = 0.0
    warnings: List[str] = field(default_factory=list)
    timestamp: float = 0.0

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = time.time()

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DRDrill:
    drill_id: str
    scheduled_at: float = 0.0
    started_at: float = 0.0
    completed_at: float = 0.0
    status: str = "scheduled"
    drill_type: str = "restore_test"
    notes: str = ""
    results: Dict[str, Any] = field(default_factory=dict)
    operator: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "DRDrill":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class DRMonitor:
    def __init__(self, backup_manager: BackupManager, rpo_target: Optional[RPOTarget] = None,
                 rto_target: Optional[RTOTarget] = None,
                 alert_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None,
                 drill_log_path: str = "/tmp/rta-guard/dr_drills.json", enabled: bool = False):
        self.enabled = enabled
        self.backup_manager = backup_manager
        self.rpo_target = rpo_target or RPOTarget(name="default", max_data_loss_seconds=86400)
        self.rto_target = rto_target or RTOTarget(name="default", max_recovery_seconds=3600)
        self.alert_callback = alert_callback
        self.drill_log_path = Path(drill_log_path)
        self._drills: List[DRDrill] = []
        self._load_drills()

    def _load_drills(self):
        if self.drill_log_path.exists():
            try:
                data = json.loads(self.drill_log_path.read_text())
                self._drills = [DRDrill.from_dict(d) for d in data]
            except (json.JSONDecodeError, KeyError):
                self._drills = []

    def _save_drills(self):
        self.drill_log_path.parent.mkdir(parents=True, exist_ok=True)
        data = [d.to_dict() for d in self._drills]
        self.drill_log_path.write_text(json.dumps(data, indent=2))

    def _alert(self, severity: str, message: str, details: Optional[Dict] = None):
        logger.warning("DR Alert [%s]: %s", severity, message)
        if self.alert_callback:
            try:
                self.alert_callback(severity, {"message": message, **(details or {})})
            except Exception as e:
                logger.error("Alert callback failed: %s", e)

    def check_health(self) -> DRHealthReport:
        if not self.enabled:
            return DRHealthReport(status="disabled")
        report = DRHealthReport()
        now = time.time()
        all_backups = self.backup_manager.store.list_manifests()
        report.total_backups = len(all_backups)
        full_backups = [b for b in all_backups if b.backup_type == "full" and b.status in ("completed", "verified")]
        if full_backups:
            latest_full = max(full_backups, key=lambda b: b.completed_at)
            report.last_full_backup_age_seconds = now - latest_full.completed_at
        else:
            report.warnings.append("No completed full backups found")
        incr_backups = [b for b in all_backups if b.backup_type == "incremental" and b.status in ("completed", "verified")]
        if incr_backups:
            latest_incr = max(incr_backups, key=lambda b: b.completed_at)
            report.last_incremental_backup_age_seconds = now - latest_incr.completed_at
        cutoff_24h = now - 86400
        failed_24h = [b for b in all_backups if b.status == "failed" and b.created_at >= cutoff_24h]
        report.failed_backups_24h = len(failed_24h)
        if full_backups:
            data_loss = report.last_full_backup_age_seconds
            report.rpo_actual_seconds = data_loss
            if data_loss <= self.rpo_target.max_data_loss_seconds:
                report.rpo_status = "compliant"
            else:
                report.rpo_status = "breached"
                report.warnings.append(f"RPO breached: {data_loss/3600:.1f}h vs {self.rpo_target.max_data_loss_hours:.1f}h target")
                self._alert("critical", "RPO target breached", {"actual_hours": data_loss / 3600, "target_hours": self.rpo_target.max_data_loss_hours})
        else:
            report.rpo_status = "unknown"
            report.warnings.append("Cannot determine RPO: no backups available")
        report.rto_status = "unknown"
        if report.rpo_status == "breached" or report.failed_backups_24h > 3:
            report.status = DRStatus.CRITICAL.value
        elif report.warnings or report.failed_backups_24h > 0:
            report.status = DRStatus.WARNING.value
        elif report.rpo_status == "compliant":
            report.status = DRStatus.HEALTHY.value
        else:
            report.status = DRStatus.UNKNOWN.value
        return report

    def check_rpo(self) -> Dict[str, Any]:
        all_backups = self.backup_manager.store.list_manifests()
        full_backups = [b for b in all_backups if b.backup_type == "full" and b.status in ("completed", "verified")]
        if not full_backups:
            return {"status": "unknown", "reason": "no backups"}
        latest = max(full_backups, key=lambda b: b.completed_at)
        data_loss = time.time() - latest.completed_at
        return {
            "status": "compliant" if data_loss <= self.rpo_target.max_data_loss_seconds else "breached",
            "actual_seconds": data_loss, "target_seconds": self.rpo_target.max_data_loss_seconds,
            "last_backup": latest.backup_id,
            "last_backup_time": datetime.fromtimestamp(latest.completed_at, tz=timezone.utc).isoformat(),
        }

    def schedule_drill(self, drill_type: str = "restore_test", scheduled_at: Optional[float] = None,
                       operator: str = "", notes: str = "") -> DRDrill:
        drill_id = f"drill_{int(time.time())}"
        drill = DRDrill(drill_id=drill_id, scheduled_at=scheduled_at or time.time(),
                        drill_type=drill_type, operator=operator, notes=notes)
        self._drills.append(drill)
        self._save_drills()
        return drill

    def execute_drill(self, drill_id: str) -> DRDrill:
        drill = next((d for d in self._drills if d.drill_id == drill_id), None)
        if not drill:
            raise ValueError(f"Drill {drill_id} not found")
        drill.status = DrillStatus.IN_PROGRESS.value
        drill.started_at = time.time()
        self._save_drills()
        try:
            if drill.drill_type == "restore_test":
                backups = self.backup_manager.store.list_manifests()
                completed = [b for b in backups if b.status in ("completed", "verified")]
                if completed:
                    latest = max(completed, key=lambda b: b.completed_at)
                    drill.results["backup_tested"] = latest.backup_id
                    drill.results["backup_verified"] = latest.verified
                    drill.results["success"] = True
                else:
                    drill.results["success"] = False
                    drill.results["reason"] = "No completed backups to test"
            else:
                drill.results["success"] = True
                drill.results["note"] = f"{drill.drill_type} drill is a placeholder"
            drill.status = DrillStatus.COMPLETED.value
            drill.completed_at = time.time()
            drill.results["duration_seconds"] = drill.completed_at - drill.started_at
        except Exception as e:
            drill.status = DrillStatus.FAILED.value
            drill.completed_at = time.time()
            drill.results["error"] = str(e)
        self._save_drills()
        return drill

    def get_drill_history(self, limit: int = 20) -> List[DRDrill]:
        return sorted(self._drills, key=lambda d: d.scheduled_at, reverse=True)[:limit]


_monitor: Optional[DRMonitor] = None

def get_dr_monitor(**kwargs) -> DRMonitor:
    global _monitor
    if _monitor is None:
        _monitor = DRMonitor(**kwargs)
    return _monitor

def reset_dr_monitor():
    global _monitor
    _monitor = None
