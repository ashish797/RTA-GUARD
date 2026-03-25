"""
RTA-GUARD — RBAC Tests (Phase 4.2)

Tests for Role-Based Access Control:
- Role assignment and revocation
- Permission checks (ADMIN has all, VIEWER limited)
- Multi-tenant role isolation
- Permission decorator enforcement
- Edge cases: unassigned user, invalid role, revocation
"""
import asyncio
import pytest
from brahmanda.rbac import (
    Role, Permission, RBACManager, RoleAssignment,
    get_role_permissions, get_all_permissions,
    reset_rbac_manager,
)


# ─── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def rbac_mgr():
    """Fresh in-memory RBAC manager."""
    manager = RBACManager(db_path=None)
    yield manager
    manager.close()


def _uid(prefix="u"):
    """Generate unique test ID."""
    import uuid
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


# ═══════════════════════════════════════════════════════════════════
# 1. Role & Permission Enums
# ═══════════════════════════════════════════════════════════════════


class TestRoleEnum:
    """Test Role enum values."""

    def test_admin_exists(self):
        assert Role.ADMIN.value == "admin"

    def test_operator_exists(self):
        assert Role.OPERATOR.value == "operator"

    def test_viewer_exists(self):
        assert Role.VIEWER.value == "viewer"

    def test_auditor_exists(self):
        assert Role.AUDITOR.value == "auditor"

    def test_all_roles(self):
        assert len(Role) == 4

    def test_role_from_string(self):
        assert Role("admin") == Role.ADMIN
        assert Role("viewer") == Role.VIEWER

    def test_invalid_role_raises(self):
        with pytest.raises(ValueError):
            Role("superadmin")


class TestPermissionEnum:
    """Test Permission enum values."""

    def test_create_rules(self):
        assert Permission.CREATE_RULES.value == "create_rules"

    def test_modify_rules(self):
        assert Permission.MODIFY_RULES.value == "modify_rules"

    def test_view_rules(self):
        assert Permission.VIEW_RULES.value == "view_rules"

    def test_view_logs(self):
        assert Permission.VIEW_LOGS.value == "view_logs"

    def test_manage_users(self):
        assert Permission.MANAGE_USERS.value == "manage_users"

    def test_manage_tenants(self):
        assert Permission.MANAGE_TENANTS.value == "manage_tenants"

    def test_view_reports(self):
        assert Permission.VIEW_REPORTS.value == "view_reports"

    def test_export_data(self):
        assert Permission.EXPORT_DATA.value == "export_data"

    def test_delete_data(self):
        assert Permission.DELETE_DATA.value == "delete_data"

    def test_all_permissions_count(self):
        assert len(Permission) == 9
        assert len(get_all_permissions()) == 9


# ═══════════════════════════════════════════════════════════════════
# 2. Role-Permission Mapping
# ═══════════════════════════════════════════════════════════════════


class TestRolePermissionMapping:
    """Test role → permissions mapping."""

    def test_admin_has_all_permissions(self):
        perms = get_role_permissions(Role.ADMIN)
        assert perms == frozenset(Permission)

    def test_operator_permissions(self):
        perms = get_role_permissions(Role.OPERATOR)
        assert Permission.CREATE_RULES in perms
        assert Permission.MODIFY_RULES in perms
        assert Permission.VIEW_RULES in perms
        assert Permission.VIEW_LOGS in perms
        assert len(perms) == 4
        assert Permission.MANAGE_USERS not in perms
        assert Permission.MANAGE_TENANTS not in perms
        assert Permission.DELETE_DATA not in perms
        assert Permission.EXPORT_DATA not in perms

    def test_viewer_permissions(self):
        perms = get_role_permissions(Role.VIEWER)
        assert Permission.VIEW_RULES in perms
        assert Permission.VIEW_LOGS in perms
        assert Permission.VIEW_REPORTS in perms
        assert len(perms) == 3
        assert Permission.CREATE_RULES not in perms
        assert Permission.MODIFY_RULES not in perms
        assert Permission.DELETE_DATA not in perms
        assert Permission.MANAGE_USERS not in perms

    def test_auditor_permissions(self):
        perms = get_role_permissions(Role.AUDITOR)
        assert Permission.VIEW_RULES in perms
        assert Permission.VIEW_LOGS in perms
        assert Permission.VIEW_REPORTS in perms
        assert Permission.EXPORT_DATA in perms
        assert len(perms) == 4
        assert Permission.CREATE_RULES not in perms
        assert Permission.MODIFY_RULES not in perms
        assert Permission.DELETE_DATA not in perms

    def test_only_admin_has_manage_users(self):
        for role in [Role.OPERATOR, Role.VIEWER, Role.AUDITOR]:
            assert Permission.MANAGE_USERS not in get_role_permissions(role)
        assert Permission.MANAGE_USERS in get_role_permissions(Role.ADMIN)

    def test_only_admin_has_delete_data(self):
        for role in [Role.OPERATOR, Role.VIEWER, Role.AUDITOR]:
            assert Permission.DELETE_DATA not in get_role_permissions(role)

    def test_no_role_overlaps_modify_rules_except_admin_operator(self):
        for role in [Role.VIEWER, Role.AUDITOR]:
            assert Permission.MODIFY_RULES not in get_role_permissions(role)


# ═══════════════════════════════════════════════════════════════════
# 3. Role Assignment & Revocation
# ═══════════════════════════════════════════════════════════════════


class TestRoleAssignment:

    def test_assign_role(self, rbac_mgr):
        uid = _uid()
        tid = _uid("t")
        assignment = rbac_mgr.assign_role(uid, tid, Role.ADMIN, assigned_by="system")
        assert assignment.user_id == uid
        assert assignment.tenant_id == tid
        assert assignment.role == Role.ADMIN
        assert assignment.assigned_by == "system"
        assert assignment.assigned_at  # ISO timestamp

    def test_assign_replaces_existing(self, rbac_mgr):
        uid = _uid()
        tid = _uid("t")
        rbac_mgr.assign_role(uid, tid, Role.VIEWER, assigned_by="system")
        rbac_mgr.assign_role(uid, tid, Role.ADMIN, assigned_by="system")
        assert rbac_mgr.get_user_role(uid, tid) == Role.ADMIN
        assert len(rbac_mgr.list_role_assignments(tid)) == 1

    def test_assign_metadata(self, rbac_mgr):
        uid = _uid()
        tid = _uid("t")
        assignment = rbac_mgr.assign_role(uid, tid, Role.OPERATOR, assigned_by="admin-1")
        assert assignment.assigned_by == "admin-1"
        d = assignment.to_dict()
        assert d["user_id"] == uid
        assert d["tenant_id"] == tid
        assert d["role"] == "operator"
        assert d["assigned_by"] == "admin-1"

    def test_revoke_role(self, rbac_mgr):
        uid = _uid()
        tid = _uid("t")
        rbac_mgr.assign_role(uid, tid, Role.ADMIN, assigned_by="system")
        assert rbac_mgr.revoke_role(uid, tid) is True
        assert rbac_mgr.get_user_role(uid, tid) is None

    def test_revoke_nonexistent(self, rbac_mgr):
        assert rbac_mgr.revoke_role("no-user", "no-tenant") is False

    def test_revoke_preserves_other_tenants(self, rbac_mgr):
        uid = _uid()
        t1 = _uid("t")
        t2 = _uid("t")
        rbac_mgr.assign_role(uid, t1, Role.ADMIN, assigned_by="system")
        rbac_mgr.assign_role(uid, t2, Role.VIEWER, assigned_by="system")
        rbac_mgr.revoke_role(uid, t1)
        assert rbac_mgr.get_user_role(uid, t1) is None
        assert rbac_mgr.get_user_role(uid, t2) == Role.VIEWER

    def test_reassign_after_revoke(self, rbac_mgr):
        uid = _uid()
        tid = _uid("t")
        rbac_mgr.assign_role(uid, tid, Role.VIEWER, assigned_by="system")
        rbac_mgr.revoke_role(uid, tid)
        rbac_mgr.assign_role(uid, tid, Role.ADMIN, assigned_by="system")
        assert rbac_mgr.get_user_role(uid, tid) == Role.ADMIN


# ═══════════════════════════════════════════════════════════════════
# 4. Permission Checks
# ═══════════════════════════════════════════════════════════════════


class TestPermissionChecks:

    def test_admin_has_all(self, rbac_mgr):
        uid = _uid()
        tid = _uid("t")
        rbac_mgr.assign_role(uid, tid, Role.ADMIN, assigned_by="system")
        for perm in Permission:
            assert rbac_mgr.has_permission(uid, tid, perm) is True

    def test_operator_limited(self, rbac_mgr):
        uid = _uid()
        tid = _uid("t")
        rbac_mgr.assign_role(uid, tid, Role.OPERATOR, assigned_by="system")
        assert rbac_mgr.has_permission(uid, tid, Permission.CREATE_RULES) is True
        assert rbac_mgr.has_permission(uid, tid, Permission.MODIFY_RULES) is True
        assert rbac_mgr.has_permission(uid, tid, Permission.VIEW_RULES) is True
        assert rbac_mgr.has_permission(uid, tid, Permission.VIEW_LOGS) is True
        assert rbac_mgr.has_permission(uid, tid, Permission.MANAGE_USERS) is False
        assert rbac_mgr.has_permission(uid, tid, Permission.DELETE_DATA) is False
        assert rbac_mgr.has_permission(uid, tid, Permission.EXPORT_DATA) is False

    def test_viewer_read_only(self, rbac_mgr):
        uid = _uid()
        tid = _uid("t")
        rbac_mgr.assign_role(uid, tid, Role.VIEWER, assigned_by="system")
        assert rbac_mgr.has_permission(uid, tid, Permission.VIEW_RULES) is True
        assert rbac_mgr.has_permission(uid, tid, Permission.VIEW_LOGS) is True
        assert rbac_mgr.has_permission(uid, tid, Permission.VIEW_REPORTS) is True
        assert rbac_mgr.has_permission(uid, tid, Permission.CREATE_RULES) is False
        assert rbac_mgr.has_permission(uid, tid, Permission.MODIFY_RULES) is False
        assert rbac_mgr.has_permission(uid, tid, Permission.DELETE_DATA) is False
        assert rbac_mgr.has_permission(uid, tid, Permission.MANAGE_USERS) is False

    def test_auditor_can_export(self, rbac_mgr):
        uid = _uid()
        tid = _uid("t")
        rbac_mgr.assign_role(uid, tid, Role.AUDITOR, assigned_by="system")
        assert rbac_mgr.has_permission(uid, tid, Permission.VIEW_RULES) is True
        assert rbac_mgr.has_permission(uid, tid, Permission.VIEW_LOGS) is True
        assert rbac_mgr.has_permission(uid, tid, Permission.VIEW_REPORTS) is True
        assert rbac_mgr.has_permission(uid, tid, Permission.EXPORT_DATA) is True
        assert rbac_mgr.has_permission(uid, tid, Permission.CREATE_RULES) is False
        assert rbac_mgr.has_permission(uid, tid, Permission.MODIFY_RULES) is False
        assert rbac_mgr.has_permission(uid, tid, Permission.DELETE_DATA) is False

    def test_unassigned_user_no_permissions(self, rbac_mgr):
        uid = _uid()
        tid = _uid("t")
        for perm in Permission:
            assert rbac_mgr.has_permission(uid, tid, perm) is False

    def test_get_user_permissions_returns_set(self, rbac_mgr):
        uid = _uid()
        tid = _uid("t")
        rbac_mgr.assign_role(uid, tid, Role.OPERATOR, assigned_by="system")
        perms = rbac_mgr.get_user_permissions(uid, tid)
        assert isinstance(perms, set)
        assert Permission.CREATE_RULES in perms
        assert Permission.MANAGE_USERS not in perms

    def test_get_user_permissions_empty_for_unassigned(self, rbac_mgr):
        uid = _uid()
        tid = _uid("t")
        assert rbac_mgr.get_user_permissions(uid, tid) == set()


# ═══════════════════════════════════════════════════════════════════
# 5. Multi-Tenant Isolation
# ═══════════════════════════════════════════════════════════════════


class TestMultiTenantIsolation:

    def test_different_roles_different_tenants(self, rbac_mgr):
        uid = _uid()
        t1 = _uid("t")
        t2 = _uid("t")
        rbac_mgr.assign_role(uid, t1, Role.ADMIN, assigned_by="system")
        rbac_mgr.assign_role(uid, t2, Role.VIEWER, assigned_by="system")

        assert rbac_mgr.has_permission(uid, t1, Permission.MODIFY_RULES) is True
        assert rbac_mgr.has_permission(uid, t2, Permission.MODIFY_RULES) is False

    def test_revoke_in_one_tenant_not_other(self, rbac_mgr):
        uid = _uid()
        t1 = _uid("t")
        t2 = _uid("t")
        rbac_mgr.assign_role(uid, t1, Role.ADMIN, assigned_by="system")
        rbac_mgr.assign_role(uid, t2, Role.VIEWER, assigned_by="system")
        rbac_mgr.revoke_role(uid, t1)
        assert rbac_mgr.get_user_role(uid, t1) is None
        assert rbac_mgr.get_user_role(uid, t2) == Role.VIEWER

    def test_list_user_tenants(self, rbac_mgr):
        uid = _uid()
        rbac_mgr.assign_role(uid, "tenant-a", Role.ADMIN, assigned_by="system")
        rbac_mgr.assign_role(uid, "tenant-b", Role.VIEWER, assigned_by="system")
        rbac_mgr.assign_role(uid, "tenant-c", Role.AUDITOR, assigned_by="system")

        tenants = rbac_mgr.list_user_tenants(uid)
        assert set(tenants) == {"tenant-a", "tenant-b", "tenant-c"}

    def test_list_role_assignments_per_tenant(self, rbac_mgr):
        t1 = _uid("t")
        t2 = _uid("t")
        u1 = _uid()
        u2 = _uid()
        rbac_mgr.assign_role(u1, t1, Role.ADMIN, assigned_by="system")
        rbac_mgr.assign_role(u2, t1, Role.VIEWER, assigned_by=u1)
        rbac_mgr.assign_role(u1, t2, Role.OPERATOR, assigned_by="system")

        t1_assignments = rbac_mgr.list_role_assignments(t1)
        assert len(t1_assignments) == 2
        user_ids = {a.user_id for a in t1_assignments}
        assert user_ids == {u1, u2}

        t2_assignments = rbac_mgr.list_role_assignments(t2)
        assert len(t2_assignments) == 1
        assert t2_assignments[0].role == Role.OPERATOR

    def test_no_cross_tenant_permission_leak(self, rbac_mgr):
        uid = _uid()
        t_alpha = _uid("t")
        t_beta = _uid("t")
        rbac_mgr.assign_role(uid, t_alpha, Role.ADMIN, assigned_by="system")
        # No assignment in t_beta
        assert rbac_mgr.has_permission(uid, t_beta, Permission.DELETE_DATA) is False
        assert rbac_mgr.has_permission(uid, t_beta, Permission.VIEW_RULES) is False


# ═══════════════════════════════════════════════════════════════════
# 6. Management Operations
# ═══════════════════════════════════════════════════════════════════


class TestManagement:

    def test_list_role_assignments_empty(self, rbac_mgr):
        assert rbac_mgr.list_role_assignments("no-tenant") == []

    def test_delete_tenant_roles(self, rbac_mgr):
        t1 = _uid("t")
        t2 = _uid("t")
        u1 = _uid()
        u2 = _uid()
        rbac_mgr.assign_role(u1, t1, Role.ADMIN, assigned_by="system")
        rbac_mgr.assign_role(u2, t1, Role.VIEWER, assigned_by="system")
        rbac_mgr.assign_role(u1, t2, Role.OPERATOR, assigned_by="system")

        count = rbac_mgr.delete_tenant_roles(t1)
        assert count == 2
        assert rbac_mgr.list_role_assignments(t1) == []
        # t2 unaffected
        assert rbac_mgr.get_user_role(u1, t2) == Role.OPERATOR

    def test_delete_tenant_roles_nonexistent(self, rbac_mgr):
        assert rbac_mgr.delete_tenant_roles("nope") == 0


# ═══════════════════════════════════════════════════════════════════
# 7. Edge Cases
# ═══════════════════════════════════════════════════════════════════


class TestEdgeCases:

    def test_same_user_same_tenant_replacement(self, rbac_mgr):
        uid = _uid()
        tid = _uid("t")
        rbac_mgr.assign_role(uid, tid, Role.VIEWER, assigned_by="system")
        rbac_mgr.assign_role(uid, tid, Role.OPERATOR, assigned_by="admin")
        assert rbac_mgr.get_user_role(uid, tid) == Role.OPERATOR
        assert len(rbac_mgr.list_role_assignments(tid)) == 1

    def test_revoke_then_check(self, rbac_mgr):
        uid = _uid()
        tid = _uid("t")
        rbac_mgr.assign_role(uid, tid, Role.ADMIN, assigned_by="system")
        assert rbac_mgr.has_permission(uid, tid, Permission.DELETE_DATA) is True
        rbac_mgr.revoke_role(uid, tid)
        assert rbac_mgr.has_permission(uid, tid, Permission.DELETE_DATA) is False
        assert rbac_mgr.has_permission(uid, tid, Permission.VIEW_RULES) is False

    def test_multiple_users_same_tenant(self, rbac_mgr):
        tid = _uid("t")
        u1 = _uid()
        u2 = _uid()
        u3 = _uid()
        rbac_mgr.assign_role(u1, tid, Role.ADMIN, assigned_by="system")
        rbac_mgr.assign_role(u2, tid, Role.VIEWER, assigned_by=u1)
        rbac_mgr.assign_role(u3, tid, Role.AUDITOR, assigned_by=u1)

        assert rbac_mgr.has_permission(u1, tid, Permission.DELETE_DATA) is True
        assert rbac_mgr.has_permission(u2, tid, Permission.VIEW_RULES) is True
        assert rbac_mgr.has_permission(u2, tid, Permission.DELETE_DATA) is False
        assert rbac_mgr.has_permission(u3, tid, Permission.EXPORT_DATA) is True

    def test_assigned_by_tracked(self, rbac_mgr):
        tid = _uid("t")
        u1 = _uid()
        u2 = _uid()
        rbac_mgr.assign_role(u1, tid, Role.ADMIN, assigned_by="system")
        rbac_mgr.assign_role(u2, tid, Role.VIEWER, assigned_by=u1)

        assignments = rbac_mgr.list_role_assignments(tid)
        by_user = {a.user_id: a for a in assignments}
        assert by_user[u1].assigned_by == "system"
        assert by_user[u2].assigned_by == u1

    def test_many_users_same_tenant(self, rbac_mgr):
        tid = _uid("t")
        users = [_uid() for _ in range(20)]
        for i, uid in enumerate(users):
            role = list(Role)[i % len(Role)]
            rbac_mgr.assign_role(uid, tid, role, assigned_by="system")
        assert len(rbac_mgr.list_role_assignments(tid)) == 20

    def test_many_tenants_same_user(self, rbac_mgr):
        uid = _uid()
        tenants = [_uid("t") for _ in range(10)]
        for tid in tenants:
            rbac_mgr.assign_role(uid, tid, Role.ADMIN, assigned_by="system")
        assert set(rbac_mgr.list_user_tenants(uid)) == set(tenants)


# ═══════════════════════════════════════════════════════════════════
# 8. Permission Decorator Simulation
# ═══════════════════════════════════════════════════════════════════


class TestPermissionDecorator:
    """Test the permission-checking pattern used by dashboard."""

    def test_admin_can_do_everything(self, rbac_mgr):
        uid = _uid()
        tid = _uid("t")
        rbac_mgr.assign_role(uid, tid, Role.ADMIN, assigned_by="system")

        # Simulate decorated endpoint check
        for perm in Permission:
            assert rbac_mgr.has_permission(uid, tid, perm) is True

    def test_viewer_blocked_from_write(self, rbac_mgr):
        uid = _uid()
        tid = _uid("t")
        rbac_mgr.assign_role(uid, tid, Role.VIEWER, assigned_by="system")

        assert rbac_mgr.has_permission(uid, tid, Permission.VIEW_RULES) is True
        assert rbac_mgr.has_permission(uid, tid, Permission.DELETE_DATA) is False

    def test_unassigned_blocked(self, rbac_mgr):
        uid = _uid()
        tid = _uid("t")
        for perm in Permission:
            assert rbac_mgr.has_permission(uid, tid, perm) is False

    def test_tenant_scoped_different_permissions(self, rbac_mgr):
        uid = _uid()
        ta = _uid("t")
        tb = _uid("t")
        rbac_mgr.assign_role(uid, ta, Role.ADMIN, assigned_by="system")
        rbac_mgr.assign_role(uid, tb, Role.VIEWER, assigned_by="system")

        assert rbac_mgr.has_permission(uid, ta, Permission.DELETE_DATA) is True
        assert rbac_mgr.has_permission(uid, tb, Permission.DELETE_DATA) is False


# ═══════════════════════════════════════════════════════════════════
# 9. Invalid Inputs
# ═══════════════════════════════════════════════════════════════════


class TestInvalidInputs:

    def test_invalid_role_raises(self):
        with pytest.raises(ValueError):
            Role("superadmin")

    def test_invalid_permission_raises(self):
        with pytest.raises(ValueError):
            Permission("world_domination")


# ═══════════════════════════════════════════════════════════════════
# 10. Global Manager
# ═══════════════════════════════════════════════════════════════════


class TestGlobalManager:

    def teardown_method(self):
        reset_rbac_manager()

    def test_get_rbac_manager_returns_same_instance(self):
        from brahmanda.rbac import get_rbac_manager
        m1 = get_rbac_manager(db_path=None)
        m2 = get_rbac_manager(db_path=None)
        assert m1 is m2

    def test_reset_creates_new_instance(self):
        from brahmanda.rbac import get_rbac_manager
        m1 = get_rbac_manager(db_path=None)
        reset_rbac_manager()
        m2 = get_rbac_manager(db_path=None)
        assert m1 is not m2


# ═══════════════════════════════════════════════════════════════════
# 11. Backward Compatibility
# ═══════════════════════════════════════════════════════════════════


class TestBackwardCompatibility:

    def test_unconfigured_rbac_no_permissions(self, rbac_mgr):
        """Without assignments, user has no permissions."""
        assert rbac_mgr.has_permission("anyone", "any-tenant", Permission.VIEW_RULES) is False

    def test_role_assignment_dict(self, rbac_mgr):
        uid = _uid()
        tid = _uid("t")
        assignment = rbac_mgr.assign_role(uid, tid, Role.VIEWER, assigned_by="admin")
        d = assignment.to_dict()
        assert d["user_id"] == uid
        assert d["tenant_id"] == tid
        assert d["role"] == "viewer"
        assert d["assigned_by"] == "admin"
        assert "assigned_at" in d
