# RTA-GUARD — Disaster Recovery Plan

**Phase 6.7 — Backup & Disaster Recovery**
**Version:** 0.7.0
**Last Updated:** 2026-03-26

---

## Table of Contents

1. [Overview](#overview)
2. [RPO / RTO Targets](#rpo--rto-targets)
3. [Backup Schedule](#backup-schedule)
4. [Architecture](#architecture)
5. [Enabling Backups (Helm)](#enabling-backups-helm)
6. [Restore Procedures](#restore-procedures)
7. [DR Drill Instructions](#dr-drill-instructions)
8. [Monitoring & Alerting](#monitoring--alerting)
9. [Runbooks](#runbooks)
10. [Troubleshooting](#troubleshooting)

---

## Overview

RTA-GUARD's disaster recovery strategy is built on **encrypted, versioned backups** stored on durable persistent volumes. The system supports:

- **Full backups** — complete snapshots of the database, config, and audit logs
- **Incremental backups** — only changes since the last full/incremental backup
- **AES-256 encryption** — all backup archives encrypted at rest
- **Integrity verification** — SHA-256 checksums on every backup manifest
- **Automated retention** — configurable cleanup of backups older than N days

Backup is **opt-in** and disabled by default. Enable it via Helm values.

---

## RPO / RTO Targets

| Metric | Target | Notes |
|--------|--------|-------|
| **RPO** (Recovery Point Objective) | **≤ 6 hours** | Incremental backups run every 6 hours |
| **RTO** (Recovery Time Objective) | **≤ 30 minutes** | Time to restore from the latest full + incremental chain |
| **Full backup window** | **≤ 2 hours** | Daily full backup at 02:00 UTC |
| **Incremental window** | **≤ 15 minutes** | Every 6 hours (00:00, 06:00, 12:00, 18:00 UTC) |

For tighter RPO, adjust `backup.incrementalSchedule` in values.yaml (e.g., hourly).

---

## Backup Schedule

```
┌─────────────────────────────────────────────────────────┐
│  Time (UTC)   │  Type         │  Schedule               │
├───────────────┼───────────────┼─────────────────────────┤
│  02:00        │  FULL         │  0 2 * * *              │
│  00,06,12,18  │  INCREMENTAL  │  0 */6 * * *            │
└──────────────────────────────────────────────────────────┘
```

### What gets backed up

| Component | Full Backup | Incremental | Encrypted |
|-----------|:-----------:|:-----------:|:---------:|
| SQLite database | ✅ | ✅ (WAL/changes) | ✅ |
| Application config | ✅ | ❌ | ✅ |
| Audit logs | ✅ | ✅ (new entries) | ✅ |
| Encryption keys | ✅ | ❌ | ✅ |

---

## Architecture

```
                    ┌──────────────────┐
                    │  Kubernetes API  │
                    └────────┬─────────┘
                             │
                    ┌────────▼─────────┐
                    │   CronJob        │
                    │  backup-full     │──── Daily 02:00
                    │  backup-incr     │──── Every 6h
                    └────────┬─────────┘
                             │
                    ┌────────▼─────────┐
                    │  brahmanda.      │
                    │  backup module   │
                    └────────┬─────────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
        ┌──────────┐  ┌──────────┐  ┌──────────┐
        │ Encrypt  │  │ Checksum │  │ Manifest │
        │ (AES-256)│  │ (SHA-256)│  │ (JSON)   │
        └────┬─────┘  └────┬─────┘  └────┬─────┘
             └──────────────┼──────────────┘
                            ▼
                   ┌─────────────────┐
                   │   Backup PVC    │
                   │  (50Gi default) │
                   └─────────────────┘
```

---

## Enabling Backups (Helm)

### Minimal enable

```bash
helm install rta-guard ./helm/rta-guard \
  --set backup.enabled=true
```

### Production configuration

```bash
helm install rta-guard ./helm/rta-guard \
  --set backup.enabled=true \
  --set backup.fullSchedule="0 2 * * *" \
  --set backup.incrementalSchedule="0 */6 * * *" \
  --set backup.retentionDays=90 \
  --set backup.encryptionEnabled=true \
  --set backup.pvc.size=200Gi \
  --set backup.pvc.storageClass=fast-ssd
```

### values.yaml backup section

```yaml
backup:
  enabled: true                    # opt-in, disabled by default
  fullSchedule: "0 2 * * *"       # daily full at 2 AM
  incrementalSchedule: "0 */6 * * *"  # incremental every 6 hours
  retentionDays: 30               # keep backups for 30 days
  encryptionEnabled: true         # AES-256 encryption
  storagePath: "/data/backups"
  pvc:
    enabled: true
    storageClass: ""              # use cluster default
    accessModes: [ReadWriteOnce]
    size: 50Gi
  resources:
    requests:
      cpu: 250m
      memory: 256Mi
    limits:
      cpu: "1"
      memory: 1Gi
```

---

## Restore Procedures

### Prerequisites

- Access to the Kubernetes cluster
- `kubectl` configured with appropriate RBAC
- Backup PVC mounted and accessible
- Encryption key available (if backups are encrypted)

### Procedure 1: Full Restore (Database Failure)

**Scenario:** Primary SQLite database is corrupted or lost.

```bash
# 1. Identify the latest good backup
kubectl exec -it <pod> -- python -m brahmanda.backup list --storage-path /data/backups

# 2. Scale down the application (prevent writes during restore)
kubectl scale deployment rta-guard --replicas=0

# 3. Run the restore
kubectl exec -it <pod> -- python -m brahmanda.restore \
  --mode full \
  --backup-id <BACKUP_ID> \
  --storage-path /data/backups \
  --decrypt

# 4. Verify integrity
kubectl exec -it <pod> -- python -m brahmanda.restore verify \
  --backup-id <BACKUP_ID> \
  --storage-path /data/backups

# 5. Scale back up
kubectl scale deployment rta-guard --replicas=1

# 6. Validate application health
kubectl get pods -l app.kubernetes.io/name=rta-guard
kubectl logs -l app.kubernetes.io/name=rta-guard --tail=50
```

### Procedure 2: Point-in-Time Recovery

**Scenario:** Data corruption detected at a known time; need to restore to a specific backup.

```bash
# 1. List backups with timestamps
kubectl exec -it <pod> -- python -m brahmanda.backup list \
  --storage-path /data/backups --format json | jq '.[] | {id, type, created_at}'

# 2. Find the last good backup BEFORE the corruption event
#    (compare timestamps with the corruption detection time)

# 3. Restore using that backup ID
kubectl exec -it <pod> -- python -m brahmanda.restore \
  --mode full \
  --backup-id <BACKUP_ID> \
  --storage-path /data/backups \
  --decrypt

# 4. Then apply any incremental backups taken between the full and corruption
kubectl exec -it <pod> -- python -m brahmanda.restore \
  --mode selective \
  --backup-id <INCREMENTAL_ID> \
  --storage-path /data/backups \
  --decrypt
```

### Procedure 3: Selective Table Restore

**Scenario:** Only one table was corrupted; restore just that table.

```bash
kubectl exec -it <pod> -- python -m brahmanda.restore \
  --mode selective \
  --backup-id <BACKUP_ID> \
  --tables "violations,audit_log" \
  --storage-path /data/backups \
  --decrypt
```

### Procedure 4: Dry Run (Validation Only)

**Scenario:** Verify a backup is restorable without actually restoring.

```bash
kubectl exec -it <pod> -- python -m brahmanda.restore \
  --mode dry_run \
  --backup-id <BACKUP_ID> \
  --storage-path /data/backups \
  --decrypt
```

---

## DR Drill Instructions

Run a disaster recovery drill **at least quarterly** to validate the backup/restore pipeline.

### Pre-Drill Checklist

- [ ] Confirm backup CronJobs are running: `kubectl get cronjobs`
- [ ] Verify recent backups exist: list backups via CLI
- [ ] Ensure encryption key is accessible
- [ ] Notify the team (DR drill is non-destructive but causes brief downtime)
- [ ] Prepare a staging/test namespace (recommended)

### Drill Steps

| Step | Action | Expected Result | Pass/Fail |
|------|--------|-----------------|-----------|
| 1 | Run `list` command | Recent backups visible | |
| 2 | Run `dry_run` on latest backup | Integrity check passes | |
| 3 | Deploy a test instance from backup | App starts, data intact | |
| 4 | Run `selective` restore on one table | Table restored correctly | |
| 5 | Measure time from `scale down` to `scale up` | RTO ≤ 30 min | |
| 6 | Verify data loss window | RPO ≤ 6 hours | |
| 7 | Document findings | Report filed | |

### Post-Drill

- File a report with: drill date, participants, findings, issues
- Update this document if procedures changed
- Fix any issues found before the next quarter

---

## Monitoring & Alerting

### Key Metrics to Monitor

| Metric | Source | Alert Threshold |
|--------|--------|-----------------|
| Last successful full backup age | `brahmanda.dr_monitor` | > 26 hours |
| Last successful incremental age | `brahmanda.dr_monitor` | > 8 hours |
| Backup PVC usage | Kubernetes metrics | > 80% |
| Backup job failure count | CronJob status | > 0 consecutive |
| Backup verification status | `BackupManifest.verified` | `false` |

### Prometheus Alerts (example)

```yaml
groups:
  - name: rta-guard-backup
    rules:
      - alert: BackupFullStale
        expr: time() - rta_guard_last_full_backup_timestamp > 93600
        for: 10m
        labels:
          severity: critical
        annotations:
          summary: "Full backup is stale (>26h old)"

      - alert: BackupJobFailed
        expr: kube_cronjob_status_last_schedule_time{cronjob=~".*backup.*"} < time() - 86400
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "Backup CronJob hasn't succeeded recently"
```

---

## Runbooks

### Runbook 1: Backup Job Failing

1. Check CronJob events: `kubectl describe cronjob rta-guard-backup-full`
2. Check pod logs: `kubectl logs job/<job-name>`
3. Common causes:
   - **PVC full** → expand PVC or reduce retention
   - **Image pull error** → verify image tag exists
   - **Permission denied** → check securityContext / serviceAccount
   - **Encryption key missing** → verify secret is mounted
4. After fix, trigger a manual run:
   ```bash
   kubectl create job --from=cronjob/rta-guard-backup-full manual-backup-$(date +%s)
   ```

### Runbook 2: Restore Failing

1. Verify backup exists: `brahmanda.backup list`
2. Verify checksum: manifest should show `verified: true`
3. Check encryption key: must match the key used during backup
4. Run in dry-run mode first to isolate the issue
5. If database locked, ensure all app replicas are scaled to 0

### Runbook 3: Full Cluster Loss

1. Provision new Kubernetes cluster
2. Restore Helm release from values (use `helm get values` backup or GitOps repo)
3. Recreate PVC from off-cluster backup (if using Velero, CSI snapshots, etc.)
4. Run full restore procedure (Procedure 1)
5. Validate all services are healthy
6. Re-enable backup CronJobs

---

## Troubleshooting

### "backup encryption key not found"

Ensure the encryption secret exists:
```bash
kubectl get secret rta-guard-backup-encryption
```
If missing, create it:
```bash
kubectl create secret generic rta-guard-backup-encryption \
  --from-literal=key=$(openssl rand -hex 32)
```

### "no space left on device"

Check PVC usage:
```bash
kubectl exec -it <pod> -- df -h /data/backups
```
Options: expand PVC, reduce `retentionDays`, or move old backups to cold storage.

### "checksum mismatch"

The backup archive is corrupted. This could indicate:
- Storage corruption → check PVC health
- Incomplete write → check if the backup job was killed mid-run
- Tampering → investigate if the archive was modified externally

Use an older backup and re-run incremental after.

---

## Contact

For DR-related issues, contact the RTA-GUARD on-call team or open an issue in the project repository.
