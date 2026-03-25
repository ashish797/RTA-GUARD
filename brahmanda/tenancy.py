"""
RTA-GUARD — Multi-tenant Isolation (Phase 4.1)

Provides tenant-aware data isolation for all Brahmanda modules.
Each tenant gets its own isolated directory with separate SQLite databases.

Usage:
    # Single-tenant mode (backward compatible)
    monitor = ConscienceMonitor()  # uses shared data/conscience.db

    # Multi-tenant mode
    tenant_mgr = TenantManager(base_data_dir="data")
    ctx = tenant_mgr.create_tenant("acme-corp", name="Acme Corp")
    monitor = ConscienceMonitor(tenant_context=ctx)

    # Load existing tenant
    ctx = tenant_mgr.get_tenant("acme-corp")
    monitor = ConscienceMonitor(tenant_context=ctx)
"""
import os
import re
import json
import shutil
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

# ─── Tenant ID Validation ──────────────────────────────────────────

# Only allow alphanumeric, hyphens, underscores (3-64 chars)
_TENANT_ID_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{2,63}$")

# Reserved tenant IDs that cannot be used
_RESERVED_IDS = {"default", "shared", "legacy", "admin", "root", "system", "null", "none"}


def validate_tenant_id(tenant_id: str) -> None:
    """
    Validate a tenant ID for security and correctness.

    Raises ValueError on invalid IDs. Prevents path traversal and
    enforces consistent naming.
    """
    if not tenant_id or not isinstance(tenant_id, str):
        raise ValueError("tenant_id must be a non-empty string")
    tenant_id = tenant_id.strip()
    if tenant_id in _RESERVED_IDS:
        raise ValueError(f"tenant_id '{tenant_id}' is reserved")
    if not _TENANT_ID_PATTERN.match(tenant_id):
        raise ValueError(
            f"tenant_id '{tenant_id}' is invalid. Must be 3-64 chars, "
            "alphanumeric with hyphens/underscores, starting with alphanumeric"
        )
    # Extra path traversal check
    if ".." in tenant_id or "/" in tenant_id or "\\" in tenant_id:
        raise ValueError(f"tenant_id '{tenant_id}' contains path traversal characters")


# ─── Tenant Context ────────────────────────────────────────────────


@dataclass
class TenantContext:
    """
    Holds all context for a single tenant.

    Provides database paths and configuration for tenant-isolated operation.
    """
    tenant_id: str
    tenant_dir: str  # e.g., "data/tenants/acme-corp"
    name: str = ""   # Human-readable name
    config: Dict[str, Any] = field(default_factory=dict)
    created_at: str = ""

    @property
    def conscience_db_path(self) -> str:
        return os.path.join(self.tenant_dir, "conscience.db")

    @property
    def attribution_db_path(self) -> str:
        return os.path.join(self.tenant_dir, "attribution.db")

    @property
    def user_monitor_db_path(self) -> str:
        return os.path.join(self.tenant_dir, "user_monitor.db")

    @property
    def temporal_db_path(self) -> str:
        return os.path.join(self.tenant_dir, "temporal.db")

    def get_db_path(self, module: str) -> str:
        """Get the database path for a specific module."""
        db_map = {
            "conscience": self.conscience_db_path,
            "attribution": self.attribution_db_path,
            "user_monitor": self.user_monitor_db_path,
            "temporal": self.temporal_db_path,
        }
        if module not in db_map:
            raise ValueError(f"Unknown module '{module}'. Valid: {list(db_map.keys())}")
        return db_map[module]

    def to_dict(self) -> dict:
        return {
            "tenant_id": self.tenant_id,
            "name": self.name,
            "tenant_dir": self.tenant_dir,
            "config": self.config,
            "created_at": self.created_at,
        }


# ─── Tenant Manager ────────────────────────────────────────────────


class TenantManager:
    """
    Manages tenant lifecycle: creation, loading, deletion, and listing.

    Enforces isolation by giving each tenant its own directory with
    separate SQLite database files.

    Args:
        base_data_dir: Root data directory. Tenant dirs created under
                       {base_data_dir}/tenants/{tenant_id}/
    """

    TENANTS_DIR_NAME = "tenants"
    METADATA_FILE = "tenant.json"

    def __init__(self, base_data_dir: str = "data"):
        self._base_data_dir = base_data_dir
        self._tenants_dir = os.path.join(base_data_dir, self.TENANTS_DIR_NAME)
        self._tenants: Dict[str, TenantContext] = {}
        self._load_existing_tenants()

    @property
    def base_data_dir(self) -> str:
        return self._base_data_dir

    @property
    def tenants_dir(self) -> str:
        return self._tenants_dir

    def _load_existing_tenants(self) -> None:
        """Scan the tenants directory and load existing tenant contexts."""
        if not os.path.isdir(self._tenants_dir):
            return
        for entry in os.listdir(self._tenants_dir):
            tenant_path = os.path.join(self._tenants_dir, entry)
            meta_path = os.path.join(tenant_path, self.METADATA_FILE)
            if os.path.isdir(tenant_path) and os.path.isfile(meta_path):
                try:
                    with open(meta_path, "r") as f:
                        meta = json.load(f)
                    ctx = TenantContext(
                        tenant_id=meta["tenant_id"],
                        name=meta.get("name", entry),
                        tenant_dir=tenant_path,
                        config=meta.get("config", {}),
                        created_at=meta.get("created_at", ""),
                    )
                    self._tenants[ctx.tenant_id] = ctx
                    logger.info(f"Loaded tenant: {ctx.tenant_id}")
                except (json.JSONDecodeError, KeyError) as e:
                    logger.warning(f"Skipping invalid tenant metadata at {meta_path}: {e}")

    def create_tenant(
        self,
        tenant_id: str,
        name: str = "",
        config: Optional[Dict[str, Any]] = None,
    ) -> TenantContext:
        """
        Create a new tenant with isolated directory and databases.

        Args:
            tenant_id: Unique identifier (3-64 chars, alphanumeric/hyphens/underscores)
            name: Human-readable name
            config: Optional configuration dict

        Returns:
            TenantContext for the new tenant

        Raises:
            ValueError: If tenant_id is invalid or already exists
        """
        from datetime import datetime, timezone

        validate_tenant_id(tenant_id)

        if tenant_id in self._tenants:
            raise ValueError(f"Tenant '{tenant_id}' already exists")

        tenant_dir = os.path.join(self._tenants_dir, tenant_id)
        os.makedirs(tenant_dir, exist_ok=True)

        now = datetime.now(timezone.utc).isoformat()
        ctx = TenantContext(
            tenant_id=tenant_id,
            name=name or tenant_id,
            tenant_dir=tenant_dir,
            config=config or {},
            created_at=now,
        )

        # Save metadata
        meta_path = os.path.join(tenant_dir, self.METADATA_FILE)
        with open(meta_path, "w") as f:
            json.dump(ctx.to_dict(), f, indent=2)

        self._tenants[tenant_id] = ctx
        logger.info(f"Created tenant: {tenant_id} at {tenant_dir}")
        return ctx

    def get_tenant(self, tenant_id: str) -> TenantContext:
        """
        Get an existing tenant context.

        Args:
            tenant_id: The tenant identifier

        Returns:
            TenantContext

        Raises:
            ValueError: If tenant does not exist
        """
        validate_tenant_id(tenant_id)
        if tenant_id not in self._tenants:
            raise ValueError(f"Tenant '{tenant_id}' not found")
        return self._tenants[tenant_id]

    def delete_tenant(self, tenant_id: str, force: bool = False) -> None:
        """
        Delete a tenant and all its data.

        Args:
            tenant_id: The tenant identifier
            force: If True, remove files even if dir doesn't exist

        Raises:
            ValueError: If tenant does not exist
        """
        validate_tenant_id(tenant_id)
        if tenant_id not in self._tenants:
            raise ValueError(f"Tenant '{tenant_id}' not found")

        ctx = self._tenants[tenant_id]
        tenant_dir = ctx.tenant_dir

        if os.path.isdir(tenant_dir):
            shutil.rmtree(tenant_dir)
            logger.info(f"Deleted tenant directory: {tenant_dir}")

        del self._tenants[tenant_id]

    def list_tenants(self) -> List[Dict[str, Any]]:
        """
        List all tenants with metadata.

        Returns:
            List of tenant dicts
        """
        return [ctx.to_dict() for ctx in self._tenants.values()]

    def tenant_exists(self, tenant_id: str) -> bool:
        """Check if a tenant exists."""
        return tenant_id in self._tenants

    def get_or_create_tenant(
        self,
        tenant_id: str,
        name: str = "",
        config: Optional[Dict[str, Any]] = None,
    ) -> TenantContext:
        """Get existing tenant or create if it doesn't exist."""
        if self.tenant_exists(tenant_id):
            return self._tenants[tenant_id]
        return self.create_tenant(tenant_id, name=name, config=config)


# ─── Legacy / Default Tenant ───────────────────────────────────────

# For backward compatibility: when no tenant_id is provided, use the
# shared legacy paths (data/conscience.db, etc.)
_LEGACY_DATA_DIR = "data"


def get_legacy_context() -> Optional[None]:
    """
    Returns None to signal legacy/single-tenant mode.

    Modules check: if tenant_context is None, use legacy paths.
    """
    return None


# ─── Global Tenant Manager ─────────────────────────────────────────

_manager: Optional[TenantManager] = None


def get_tenant_manager(base_data_dir: str = "data") -> TenantManager:
    """Get or create the global TenantManager instance."""
    global _manager
    if _manager is None:
        _manager = TenantManager(base_data_dir=base_data_dir)
    return _manager


def reset_tenant_manager() -> None:
    """Reset the global TenantManager (for testing)."""
    global _manager
    _manager = None
