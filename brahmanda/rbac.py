"""
RTA-GUARD — Role-Based Access Control (Phase 4.2)

Provides tenant-scoped RBAC with 4 roles and 9 permissions.
Users can have different roles in different tenants (multi-tenant isolation).

Usage:
    rbac = get_rbac_manager()

    # Assign role
    rbac.assign_role("user-123", "acme-corp", Role.ADMIN, assigned_by="system")

    # Check permission
    rbac.has_permission("user-123", "acme-corp", Permission.MODIFY_RULES)  # True

    # Multi-tenant: different role per tenant
    rbac.assign_role("user-123", "beta-corp", Role.VIEWER, assigned_by="admin-1")
    rbac.has_permission("user-123", "beta-corp", Permission.MODIFY_RULES)  # False
"""
import os
import json
import logging
import sqlite3
from enum import Enum
from pathlib import Path
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional, Dict, Set, List, FrozenSet

logger = logging.getLogger(__name__)


# ─── Roles & Permissions ───────────────────────────────────────────


class Role(Enum):
    """Available roles in the RBAC system."""
    ADMIN = "admin"
    OPERATOR = "operator"
    VIEWER = "viewer"
    AUDITOR = "auditor"


class Permission(Enum):
    """Granular permissions for RTA-GUARD operations."""
    CREATE_RULES = "create_rules"
    MODIFY_RULES = "modify_rules"
    VIEW_RULES = "view_rules"
    VIEW_LOGS = "view_logs"
    MANAGE_USERS = "manage_users"
    MANAGE_TENANTS = "manage_tenants"
    VIEW_REPORTS = "view_reports"
    EXPORT_DATA = "export_data"
    DELETE_DATA = "delete_data"


# Role → Permissions mapping
_ROLE_PERMISSIONS: Dict[Role, FrozenSet[Permission]] = {
    Role.ADMIN: frozenset(Permission),  # All permissions
    Role.OPERATOR: frozenset({
        Permission.CREATE_RULES,
        Permission.MODIFY_RULES,
        Permission.VIEW_RULES,
        Permission.VIEW_LOGS,
    }),
    Role.VIEWER: frozenset({
        Permission.VIEW_RULES,
        Permission.VIEW_LOGS,
        Permission.VIEW_REPORTS,
    }),
    Role.AUDITOR: frozenset({
        Permission.VIEW_RULES,
        Permission.VIEW_LOGS,
        Permission.VIEW_REPORTS,
        Permission.EXPORT_DATA,
    }),
}


def get_role_permissions(role: Role) -> FrozenSet[Permission]:
    """Get the set of permissions for a given role."""
    return _ROLE_PERMISSIONS[role]


def get_all_permissions() -> FrozenSet[Permission]:
    """Get all available permissions."""
    return frozenset(Permission)


# ─── Role Assignment ───────────────────────────────────────────────


@dataclass
class RoleAssignment:
    """A user's role assignment within a specific tenant."""
    user_id: str
    tenant_id: str
    role: Role
    assigned_at: str  # ISO 8601
    assigned_by: str  # user_id or "system"

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "tenant_id": self.tenant_id,
            "role": self.role.value,
            "assigned_at": self.assigned_at,
            "assigned_by": self.assigned_by,
        }


# ─── RBAC Manager ──────────────────────────────────────────────────


class RBACManager:
    """
    Manages role-based access control with tenant scoping.

    Storage: SQLite table `role_assignments` in a per-manager DB file,
    or in-memory for testing.

    Args:
        db_path: Path to SQLite DB file. None = in-memory.
    """

    def __init__(self, db_path: Optional[str] = None):
        self._db_path = db_path
        if db_path:
            os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self._conn = sqlite3.connect(db_path or ":memory:")
        self._conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self) -> None:
        """Initialize the role_assignments table."""
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS role_assignments (
                user_id TEXT NOT NULL,
                tenant_id TEXT NOT NULL,
                role TEXT NOT NULL,
                assigned_at TEXT NOT NULL,
                assigned_by TEXT NOT NULL DEFAULT 'system',
                PRIMARY KEY (user_id, tenant_id)
            );
            CREATE INDEX IF NOT EXISTS idx_ra_tenant ON role_assignments(tenant_id);
            CREATE INDEX IF NOT EXISTS idx_ra_user ON role_assignments(user_id);
        """)
        self._conn.commit()

    def assign_role(
        self,
        user_id: str,
        tenant_id: str,
        role: Role,
        assigned_by: str = "system",
    ) -> RoleAssignment:
        """
        Assign a role to a user within a tenant.

        If the user already has a role in this tenant, it is replaced.
        A user can have different roles in different tenants.

        Args:
            user_id: The user identifier
            tenant_id: The tenant identifier
            role: The role to assign
            assigned_by: Who is making the assignment

        Returns:
            The RoleAssignment record
        """
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute("""
            INSERT OR REPLACE INTO role_assignments (user_id, tenant_id, role, assigned_at, assigned_by)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, tenant_id, role.value, now, assigned_by))
        self._conn.commit()

        assignment = RoleAssignment(
            user_id=user_id,
            tenant_id=tenant_id,
            role=role,
            assigned_at=now,
            assigned_by=assigned_by,
        )
        logger.info(f"Assigned role {role.value} to {user_id} in {tenant_id} by {assigned_by}")
        return assignment

    def revoke_role(self, user_id: str, tenant_id: str) -> bool:
        """
        Revoke a user's role in a tenant.

        Args:
            user_id: The user identifier
            tenant_id: The tenant identifier

        Returns:
            True if a role was revoked, False if user had no role
        """
        cursor = self._conn.execute(
            "DELETE FROM role_assignments WHERE user_id = ? AND tenant_id = ?",
            (user_id, tenant_id),
        )
        self._conn.commit()
        revoked = cursor.rowcount > 0
        if revoked:
            logger.info(f"Revoked role for {user_id} in {tenant_id}")
        return revoked

    def get_user_role(self, user_id: str, tenant_id: str) -> Optional[Role]:
        """
        Get a user's role in a specific tenant.

        Returns:
            The Role if assigned, None otherwise
        """
        row = self._conn.execute(
            "SELECT role FROM role_assignments WHERE user_id = ? AND tenant_id = ?",
            (user_id, tenant_id),
        ).fetchone()
        if row:
            return Role(row["role"])
        return None

    def get_user_permissions(self, user_id: str, tenant_id: str) -> Set[Permission]:
        """
        Get all permissions for a user in a specific tenant.

        Returns:
            Set of Permission. Empty set if user has no role.
        """
        role = self.get_user_role(user_id, tenant_id)
        if role is None:
            return set()
        return set(get_role_permissions(role))

    def has_permission(self, user_id: str, tenant_id: str, permission: Permission) -> bool:
        """
        Check if a user has a specific permission in a tenant.

        Args:
            user_id: The user identifier
            tenant_id: The tenant identifier
            permission: The permission to check

        Returns:
            True if user has the permission, False otherwise
        """
        permissions = self.get_user_permissions(user_id, tenant_id)
        return permission in permissions

    def list_role_assignments(self, tenant_id: str) -> List[RoleAssignment]:
        """
        List all role assignments for a tenant.

        Args:
            tenant_id: The tenant identifier

        Returns:
            List of RoleAssignment records
        """
        rows = self._conn.execute(
            "SELECT user_id, tenant_id, role, assigned_at, assigned_by FROM role_assignments WHERE tenant_id = ?",
            (tenant_id,),
        ).fetchall()
        return [
            RoleAssignment(
                user_id=row["user_id"],
                tenant_id=row["tenant_id"],
                role=Role(row["role"]),
                assigned_at=row["assigned_at"],
                assigned_by=row["assigned_by"],
            )
            for row in rows
        ]

    def list_user_tenants(self, user_id: str) -> List[str]:
        """
        List all tenants where a user has a role assignment.

        Returns:
            List of tenant_id strings
        """
        rows = self._conn.execute(
            "SELECT tenant_id FROM role_assignments WHERE user_id = ?",
            (user_id,),
        ).fetchall()
        return [row["tenant_id"] for row in rows]

    def delete_tenant_roles(self, tenant_id: str) -> int:
        """
        Delete all role assignments for a tenant.

        Args:
            tenant_id: The tenant identifier

        Returns:
            Number of assignments deleted
        """
        cursor = self._conn.execute(
            "DELETE FROM role_assignments WHERE tenant_id = ?",
            (tenant_id,),
        )
        self._conn.commit()
        return cursor.rowcount

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()


# ─── Global RBAC Manager ───────────────────────────────────────────

_manager: Optional[RBACManager] = None


def get_rbac_manager(db_path: Optional[str] = None) -> RBACManager:
    """
    Get or create the global RBACManager instance.

    Args:
        db_path: Path to SQLite DB. Default: data/rbac.db
    """
    global _manager
    if _manager is None:
        path = db_path or os.path.join(os.getenv("RTA_DATA_DIR", "data"), "rbac.db")
        _manager = RBACManager(db_path=path)
    return _manager


def reset_rbac_manager() -> None:
    """Reset the global RBACManager (for testing)."""
    global _manager
    if _manager is not None:
        _manager.close()
    _manager = None


# ─── FastAPI Permission Decorators ─────────────────────────────────

def require_permission(perm: Permission):
    """FastAPI dependency that checks if user has a specific permission."""
    def _check_permission(request, tenant_id: str = None):
        mgr = get_rbac_manager()
        # In a real implementation, extract user_id from JWT
        user_id = getattr(request, 'state', {}).get('user_id', 'anonymous')
        if not mgr.has_permission(user_id, tenant_id or '__default__', perm):
            from fastapi import HTTPException
            raise HTTPException(status_code=403, detail=f"Missing permission: {perm.value}")
        return True
    return _check_permission


def require_role(role: Role):
    """FastAPI dependency that checks if user has a specific role."""
    def _check_role(request, tenant_id: str = None):
        mgr = get_rbac_manager()
        user_id = getattr(request, 'state', {}).get('user_id', 'anonymous')
        user_role = mgr.get_role(user_id, tenant_id or '__default__')
        if user_role != role:
            from fastapi import HTTPException
            raise HTTPException(status_code=403, detail=f"Required role: {role.value}")
        return True
    return _check_role
