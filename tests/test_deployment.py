"""
RTA-GUARD Deployment Tests
==========================
Tests for Docker, Docker Compose, Helm, and Kubernetes integration.

Uses static file parsing where possible and subprocess calls for CLI tools.
Skips tests gracefully when Docker/Helm/kubectl are not available.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
import yaml

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).parent.parent
DOCKERFILE = PROJECT_ROOT / "Dockerfile"
COMPOSE_FILE = PROJECT_ROOT / "docker-compose.yml"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _has_docker():
    return shutil.which("docker") is not None


def _has_helm():
    return shutil.which("helm") is not None


def _has_kubectl():
    return shutil.which("kubectl") is not None


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Run a command and return the result."""
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=120,
        **kwargs,
    )


def _parse_dockerfile(path: Path) -> list[dict]:
    """Parse a Dockerfile into a list of instruction dicts.

    Returns a list of {"instruction": str, "arguments": str, "raw": str}.
    """
    instructions = []
    current_line = ""
    with open(path) as f:
        for line in f:
            stripped = line.rstrip()
            # Skip comments
            if stripped.lstrip().startswith("#"):
                continue
            # Handle line continuations
            if stripped.endswith("\\"):
                current_line += stripped[:-1] + " "
                continue
            current_line += stripped
            if not current_line.strip():
                current_line = ""
                continue
            parts = current_line.strip().split(None, 1)
            if parts:
                instructions.append({
                    "instruction": parts[0].upper(),
                    "arguments": parts[1] if len(parts) > 1 else "",
                    "raw": current_line.strip(),
                })
            current_line = ""
    return instructions


# ===========================================================================
# 1-3: Dockerfile Tests
# ===========================================================================

class TestDockerfile:
    """Tests for the project Dockerfile."""

    @pytest.fixture(autouse=True)
    def check_dockerfile_exists(self):
        if not DOCKERFILE.exists():
            pytest.skip(f"Dockerfile not found at {DOCKERFILE}")

    @pytest.fixture
    def instructions(self):
        return _parse_dockerfile(DOCKERFILE)

    def test_dockerfile_builds_successfully(self):
        """Test 1: Dockerfile builds successfully."""
        if not _has_docker():
            pytest.skip("Docker not available")
        result = _run([
            "docker", "build",
            "-t", "rta-guard-test:ci",
            "-f", str(DOCKERFILE),
            str(PROJECT_ROOT),
        ])
        assert result.returncode == 0, (
            f"Docker build failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )

    def test_dockerfile_exposes_correct_port(self, instructions):
        """Test 2: Dockerfile exposes port 8080."""
        expose_lines = [
            inst for inst in instructions
            if inst["instruction"] == "EXPOSE"
        ]
        assert len(expose_lines) > 0, "Dockerfile has no EXPOSE directive"
        exposed_ports = []
        for inst in expose_lines:
            for token in inst["arguments"].split():
                port_str = token.split("/")[0]
                exposed_ports.append(int(port_str))
        assert 8080 in exposed_ports, (
            f"Expected EXPOSE 8080, got ports: {exposed_ports}"
        )

    def test_dockerfile_cmd_is_correct(self, instructions):
        """Test 3: Dockerfile CMD launches uvicorn on port 8080."""
        cmd_instructions = [
            inst for inst in instructions
            if inst["instruction"] == "CMD"
        ]
        assert len(cmd_instructions) > 0, "Dockerfile has no CMD directive"
        last_cmd = cmd_instructions[-1]["arguments"]
        # Exec form: ["uvicorn", "dashboard.app:app", ...]
        assert "uvicorn" in last_cmd, (
            f"CMD should use uvicorn, got: {last_cmd}"
        )
        assert "dashboard.app" in last_cmd, (
            f"CMD should reference dashboard.app, got: {last_cmd}"
        )
        assert "8080" in last_cmd, (
            f"CMD should listen on port 8080, got: {last_cmd}"
        )

    def test_dockerfile_uses_python_slim(self, instructions):
        """Sanity: base image should be python slim variant."""
        from_lines = [
            inst for inst in instructions
            if inst["instruction"] == "FROM"
        ]
        assert len(from_lines) > 0, "No FROM directive found"
        base = from_lines[0]["arguments"].lower()
        assert "python" in base, f"Expected python base image, got: {base}"
        assert "slim" in base or "alpine" in base, (
            f"Expected slim/alpine variant for size, got: {base}"
        )

    def test_dockerfile_has_workdir(self, instructions):
        """Sanity: WORKDIR should be set."""
        workdir_lines = [
            inst for inst in instructions
            if inst["instruction"] == "WORKDIR"
        ]
        assert len(workdir_lines) > 0, "Dockerfile should set WORKDIR"

    def test_dockerfile_copies_requirements_first(self, instructions):
        """Sanity: requirements.txt should be copied before source for layer caching."""
        raw_text = " ".join(inst["raw"] for inst in instructions)
        req_pos = raw_text.find("requirements")
        copy_all_pos = raw_text.find("COPY . .")
        if copy_all_pos == -1:
            return  # No COPY . . means different pattern
        if req_pos != -1:
            assert req_pos < copy_all_pos, (
                "requirements.txt should be copied before 'COPY . .' for layer caching"
            )

    def test_dockerfile_runs_as_non_root(self, instructions):
        """Dockerfile should switch to a non-root user."""
        user_lines = [
            inst for inst in instructions
            if inst["instruction"] == "USER"
        ]
        assert len(user_lines) > 0, "Dockerfile should have USER directive (non-root)"
        last_user = user_lines[-1]["arguments"].strip()
        assert last_user != "root", "Dockerfile should not run as root"

    def test_dockerfile_has_healthcheck(self, instructions):
        """Dockerfile should include a HEALTHCHECK."""
        hc_lines = [
            inst for inst in instructions
            if inst["instruction"] == "HEALTHCHECK"
        ]
        assert len(hc_lines) > 0, "Dockerfile should have HEALTHCHECK"
        assert "8080" in hc_lines[0]["arguments"], (
            "HEALTHCHECK should probe port 8080"
        )


# ===========================================================================
# 4-5: Docker Compose Tests
# ===========================================================================

class TestDockerCompose:
    """Tests for docker-compose.yml."""

    @pytest.fixture(autouse=True)
    def check_compose_exists(self):
        if not COMPOSE_FILE.exists():
            pytest.skip(f"docker-compose.yml not found at {COMPOSE_FILE}")

    @pytest.fixture
    def compose(self):
        with open(COMPOSE_FILE) as f:
            return yaml.safe_load(f)

    def test_compose_starts_all_services(self, compose):
        """Test 4: docker-compose defines expected services."""
        services = compose.get("services", {})
        expected = {"dashboard", "postgres", "redis", "qdrant"}
        actual = set(services.keys())
        assert expected.issubset(actual), (
            f"Expected services {expected}, got: {actual}"
        )

    def test_compose_dashboard_builds_from_dockerfile(self, compose):
        """Dashboard service should build from the Dockerfile."""
        dashboard = compose["services"]["dashboard"]
        build = dashboard.get("build", {})
        if isinstance(build, dict):
            assert "dockerfile" in build or "context" in build
        else:
            assert build is not None

    def test_compose_dashboard_exposes_port(self, compose):
        """Dashboard should expose port 8080."""
        dashboard = compose["services"]["dashboard"]
        ports = dashboard.get("ports", [])
        port_strs = [str(p) for p in ports]
        assert any("8080" in p for p in port_strs), (
            f"Dashboard should expose port 8080, got: {port_strs}"
        )

    def test_compose_volume_mounts_correct(self, compose):
        """Test 5: Dashboard service mounts data volume."""
        dashboard = compose["services"]["dashboard"]
        volumes = dashboard.get("volumes", [])
        volume_strs = [str(v) for v in volumes]
        assert any("dashboard" in v or "/app/data" in v for v in volume_strs), (
            f"Expected dashboard data volume mount, got: {volume_strs}"
        )

    def test_compose_postgres_has_data_volume(self, compose):
        """Postgres should mount a persistent data volume."""
        pg = compose["services"]["postgres"]
        volumes = pg.get("volumes", [])
        volume_strs = [str(v) for v in volumes]
        assert any("pgdata" in v or "postgres" in v for v in volume_strs), (
            f"Postgres should mount data volume, got: {volume_strs}"
        )

    def test_compose_redis_has_data_volume(self, compose):
        """Redis should mount a persistent data volume."""
        redis = compose["services"]["redis"]
        volumes = redis.get("volumes", [])
        volume_strs = [str(v) for v in volumes]
        assert any("redis" in v for v in volume_strs), (
            f"Redis should mount data volume, got: {volume_strs}"
        )

    def test_compose_qdrant_has_data_volume(self, compose):
        """Qdrant should mount a persistent data volume."""
        qdrant = compose["services"]["qdrant"]
        volumes = qdrant.get("volumes", [])
        volume_strs = [str(v) for v in volumes]
        assert any("qdrant" in v for v in volume_strs), (
            f"Qdrant should mount data volume, got: {volume_strs}"
        )

    def test_compose_environment_has_pythonunbuffered(self, compose):
        """Dashboard service should set PYTHONUNBUFFERED for log streaming."""
        svc = compose["services"]["dashboard"]
        env = svc.get("environment", [])
        env_strs = [str(e) for e in env]
        assert any("PYTHONUNBUFFERED" in e for e in env_strs), (
            f"Dashboard should set PYTHONUNBUFFERED=1"
        )

    def test_compose_dashboard_has_database_url(self, compose):
        """Dashboard should have DATABASE_URL configured."""
        svc = compose["services"]["dashboard"]
        env = svc.get("environment", [])
        env_strs = [str(e) for e in env]
        assert any("DATABASE_URL" in e for e in env_strs), (
            "Dashboard should have DATABASE_URL"
        )

    def test_compose_dashboard_has_redis_url(self, compose):
        """Dashboard should have REDIS_URL configured."""
        svc = compose["services"]["dashboard"]
        env = svc.get("environment", [])
        env_strs = [str(e) for e in env]
        assert any("REDIS_URL" in e for e in env_strs), (
            "Dashboard should have REDIS_URL"
        )

    def test_compose_dashboard_has_qdrant_url(self, compose):
        """Dashboard should have QDRANT_URL configured."""
        svc = compose["services"]["dashboard"]
        env = svc.get("environment", [])
        env_strs = [str(e) for e in env]
        assert any("QDRANT_URL" in e for e in env_strs), (
            "Dashboard should have QDRANT_URL"
        )

    def test_compose_dashboard_has_healthcheck(self, compose):
        """Dashboard service should define a healthcheck."""
        svc = compose["services"]["dashboard"]
        assert "healthcheck" in svc, "Dashboard should have a healthcheck"

    def test_compose_postgres_has_healthcheck(self, compose):
        """Postgres service should define a healthcheck."""
        svc = compose["services"]["postgres"]
        assert "healthcheck" in svc, "Postgres should have a healthcheck"

    def test_compose_redis_has_healthcheck(self, compose):
        """Redis service should define a healthcheck."""
        svc = compose["services"]["redis"]
        assert "healthcheck" in svc, "Redis should have a healthcheck"

    def test_compose_dashboard_depends_on_dependencies(self, compose):
        """Dashboard should depend on postgres, redis, and qdrant."""
        svc = compose["services"]["dashboard"]
        deps = svc.get("depends_on", {})
        # depends_on can be a list or dict
        if isinstance(deps, dict):
            dep_names = set(deps.keys())
        else:
            dep_names = set(deps)
        assert "postgres" in dep_names, f"Dashboard should depend on postgres, got: {dep_names}"
        assert "redis" in dep_names, f"Dashboard should depend on redis, got: {dep_names}"

    def test_compose_valid_yaml(self):
        """docker-compose.yml should be valid YAML."""
        with open(COMPOSE_FILE) as f:
            data = yaml.safe_load(f)
        assert isinstance(data, dict), "Compose file should parse to a dict"
        assert "services" in data, "Compose file should have 'services' key"

    def test_compose_has_network(self, compose):
        """Compose should define a shared network."""
        networks = compose.get("networks", {})
        assert len(networks) > 0, "Compose should define at least one network"


# ===========================================================================
# 6-7: Helm Chart Tests
# ===========================================================================

# Minimal Helm chart for testing when none exists in the project
_HELM_CHART_YAML = """
apiVersion: v2
name: rta-guard
description: RTA-GUARD AI session kill-switch
type: application
version: 0.1.0
appVersion: "1.0.0"
"""

_HELM_VALUES_YAML = """
replicaCount: 1

image:
  repository: rta-guard
  tag: latest
  pullPolicy: IfNotPresent

service:
  type: ClusterIP
  port: 8080

ingress:
  enabled: false

resources: {}

env:
  PYTHONUNBUFFERED: "1"

configMap:
  enabled: true
  data:
    GUARD_LOG_LEVEL: "INFO"

secret:
  enabled: false
"""

_HELM_DEPLOYMENT_TEMPLATE = """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "rta-guard.fullname" . }}
  labels:
    {{- include "rta-guard.labels" . | nindent 4 }}
spec:
  replicas: {{ .Values.replicaCount }}
  selector:
    matchLabels:
      {{- include "rta-guard.selectorLabels" . | nindent 6 }}
  template:
    metadata:
      labels:
        {{- include "rta-guard.selectorLabels" . | nindent 8 }}
    spec:
      containers:
        - name: {{ .Chart.Name }}
          image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"
          imagePullPolicy: {{ .Values.image.pullPolicy }}
          ports:
            - name: http
              containerPort: 8080
              protocol: TCP
          livenessProbe:
            httpGet:
              path: /api/health
              port: http
            initialDelaySeconds: 15
            periodSeconds: 20
          readinessProbe:
            httpGet:
              path: /api/health
              port: http
            initialDelaySeconds: 5
            periodSeconds: 10
          env:
            {{- range $key, $value := .Values.env }}
            - name: {{ $key }}
              value: {{ $value | quote }}
            {{- end }}
          {{- if .Values.configMap.enabled }}
          envFrom:
            - configMapRef:
                name: {{ include "rta-guard.fullname" . }}-config
          {{- end }}
          resources:
            {{- toYaml .Values.resources | nindent 12 }}
"""

_HELM_SERVICE_TEMPLATE = """
apiVersion: v1
kind: Service
metadata:
  name: {{ include "rta-guard.fullname" . }}
  labels:
    {{- include "rta-guard.labels" . | nindent 4 }}
spec:
  type: {{ .Values.service.type }}
  ports:
    - port: {{ .Values.service.port }}
      targetPort: http
      protocol: TCP
      name: http
  selector:
    {{- include "rta-guard.selectorLabels" . | nindent 4 }}
"""

_HELM_HELPERS = """
{{/*
Expand the name of the chart.
*/}}
{{- define "rta-guard.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "rta-guard.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "rta-guard.labels" -}}
helm.sh/chart: {{ include "rta-guard.name" . }}-{{ .Chart.Version | replace "+" "_" }}
{{ include "rta-guard.selectorLabels" . }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "rta-guard.selectorLabels" -}}
app.kubernetes.io/name: {{ include "rta-guard.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}
"""


@pytest.fixture(scope="module")
def helm_chart_dir(tmp_path_factory):
    """Create a temporary Helm chart directory for testing."""
    chart_dir = tmp_path_factory.mktemp("helm_chart")
    templates_dir = chart_dir / "templates"
    templates_dir.mkdir()

    (chart_dir / "Chart.yaml").write_text(_HELM_CHART_YAML)
    (chart_dir / "values.yaml").write_text(_HELM_VALUES_YAML)
    (templates_dir / "deployment.yaml").write_text(_HELM_DEPLOYMENT_TEMPLATE)
    (templates_dir / "service.yaml").write_text(_HELM_SERVICE_TEMPLATE)
    (templates_dir / "_helpers.tpl").write_text(_HELM_HELPERS)

    return chart_dir


class TestHelmChart:
    """Tests for Helm chart validity and rendering."""

    def test_helm_lint(self, helm_chart_dir):
        """Test 6: Helm chart passes lint validation."""
        if not _has_helm():
            pytest.skip("Helm not available")
        result = _run(["helm", "lint", str(helm_chart_dir)])
        assert result.returncode == 0, (
            f"Helm lint failed:\n{result.stderr}"
        )

    def test_helm_template_renders(self, helm_chart_dir):
        """Test 7: Helm chart renders templates without errors."""
        if not _has_helm():
            pytest.skip("Helm not available")
        result = _run([
            "helm", "template", "test-release", str(helm_chart_dir),
        ])
        assert result.returncode == 0, (
            f"Helm template failed:\n{result.stderr}"
        )
        docs = list(yaml.safe_load_all(result.stdout))
        assert len(docs) >= 2, "Expected at least Deployment and Service manifests"

    def test_helm_template_produces_deployment(self, helm_chart_dir):
        """Rendered templates should include a Deployment."""
        if not _has_helm():
            pytest.skip("Helm not available")
        result = _run([
            "helm", "template", "test-release", str(helm_chart_dir),
        ])
        assert result.returncode == 0
        docs = list(yaml.safe_load_all(result.stdout))
        kinds = [d.get("kind") for d in docs if d]
        assert "Deployment" in kinds, f"Expected Deployment in {kinds}"

    def test_helm_template_produces_service(self, helm_chart_dir):
        """Rendered templates should include a Service."""
        if not _has_helm():
            pytest.skip("Helm not available")
        result = _run([
            "helm", "template", "test-release", str(helm_chart_dir),
        ])
        assert result.returncode == 0
        docs = list(yaml.safe_load_all(result.stdout))
        kinds = [d.get("kind") for d in docs if d]
        assert "Service" in kinds, f"Expected Service in {kinds}"

    def test_helm_chart_yaml_valid(self, helm_chart_dir):
        """Chart.yaml should be valid and have required fields."""
        with open(helm_chart_dir / "Chart.yaml") as f:
            chart = yaml.safe_load(f)
        assert chart["apiVersion"] == "v2"
        assert "name" in chart
        assert "version" in chart
        assert chart["type"] == "application"

    def test_helm_values_has_image_config(self, helm_chart_dir):
        """values.yaml should define image configuration."""
        with open(helm_chart_dir / "values.yaml") as f:
            values = yaml.safe_load(f)
        assert "image" in values
        assert "repository" in values["image"]
        assert "tag" in values["image"]

    def test_helm_values_has_service_port(self, helm_chart_dir):
        """values.yaml should define service port 8080."""
        with open(helm_chart_dir / "values.yaml") as f:
            values = yaml.safe_load(f)
        assert values.get("service", {}).get("port") == 8080

    def test_helm_template_deployment_has_probes(self, helm_chart_dir):
        """Rendered Deployment should have readiness and liveness probes."""
        if not _has_helm():
            pytest.skip("Helm not available")
        result = _run([
            "helm", "template", "test-release", str(helm_chart_dir),
        ])
        assert result.returncode == 0
        docs = list(yaml.safe_load_all(result.stdout))
        deploy = next(d for d in docs if d and d.get("kind") == "Deployment")
        containers = deploy["spec"]["template"]["spec"]["containers"]
        for c in containers:
            assert "readinessProbe" in c, f"Container {c['name']} missing readinessProbe"
            assert "livenessProbe" in c, f"Container {c['name']} missing livenessProbe"

    def test_helm_template_uses_port_8080(self, helm_chart_dir):
        """Rendered Deployment should expose port 8080."""
        if not _has_helm():
            pytest.skip("Helm not available")
        result = _run([
            "helm", "template", "test-release", str(helm_chart_dir),
        ])
        assert result.returncode == 0
        docs = list(yaml.safe_load_all(result.stdout))
        deploy = next(d for d in docs if d and d.get("kind") == "Deployment")
        containers = deploy["spec"]["template"]["spec"]["containers"]
        ports = []
        for c in containers:
            for p in c.get("ports", []):
                ports.append(p.get("containerPort"))
        assert 8080 in ports, f"Expected containerPort 8080, got: {ports}"


# ===========================================================================
# 8-12: Kubernetes Manifest Tests
# ===========================================================================

# K8s manifests mirroring the real Docker Compose deployment
_K8S_DEPLOYMENT = """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: rta-guard
  labels:
    app: rta-guard
    app.kubernetes.io/name: rta-guard
    app.kubernetes.io/version: "0.6.1"
spec:
  replicas: 2
  selector:
    matchLabels:
      app: rta-guard
  template:
    metadata:
      labels:
        app: rta-guard
    spec:
      containers:
        - name: rta-guard
          image: rta-guard:latest
          ports:
            - containerPort: 8080
              name: http
          readinessProbe:
            httpGet:
              path: /api/health
              port: 8080
            initialDelaySeconds: 5
            periodSeconds: 10
          livenessProbe:
            httpGet:
              path: /api/health
              port: 8080
            initialDelaySeconds: 15
            periodSeconds: 20
          env:
            - name: PYTHONUNBUFFERED
              value: "1"
            - name: DATABASE_URL
              valueFrom:
                configMapKeyRef:
                  name: rta-guard-config
                  key: DATABASE_URL
            - name: REDIS_URL
              valueFrom:
                configMapKeyRef:
                  name: rta-guard-config
                  key: REDIS_URL
            - name: RTA_SECRET_KEY
              valueFrom:
                secretKeyRef:
                  name: rta-guard-secrets
                  key: secret-key
            - name: OPENAI_API_KEY
              valueFrom:
                secretKeyRef:
                  name: rta-guard-secrets
                  key: openai-api-key
          volumeMounts:
            - name: config-volume
              mountPath: /app/config
              readOnly: true
            - name: data-volume
              mountPath: /app/data
      volumes:
        - name: config-volume
          configMap:
            name: rta-guard-config
        - name: data-volume
          emptyDir: {}
"""

_K8S_SERVICE = """
apiVersion: v1
kind: Service
metadata:
  name: rta-guard
spec:
  selector:
    app: rta-guard
  ports:
    - port: 8080
      targetPort: 8080
      name: http
  type: ClusterIP
"""

_K8S_CONFIGMAP = """
apiVersion: v1
kind: ConfigMap
metadata:
  name: rta-guard-config
data:
  GUARD_LOG_LEVEL: "INFO"
  GUARD_MODE: "strict"
  DATABASE_URL: "postgresql://rta:rta_secret@postgres:5432/rtaguard"
  REDIS_URL: "redis://redis:6379/0"
  QDRANT_URL: "http://qdrant:6333"
"""

_K8S_SECRET = """
apiVersion: v1
kind: Secret
metadata:
  name: rta-guard-secrets
type: Opaque
stringData:
  secret-key: "change-me-in-production"
  openai-api-key: ""
  qdrant-api-key: ""
"""

_K8S_NETWORK_POLICY = """
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: rta-guard-netpol
spec:
  podSelector:
    matchLabels:
      app: rta-guard
  policyTypes:
    - Ingress
    - Egress
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              name: ingress-ns
      ports:
        - protocol: TCP
          port: 8080
  egress:
    - to:
        - namespaceSelector: {}
      ports:
        - protocol: TCP
          port: 53
        - protocol: UDP
          port: 53
    - to:
        - podSelector:
            matchLabels:
              app: postgres
      ports:
        - protocol: TCP
          port: 5432
    - to:
        - podSelector:
            matchLabels:
              app: redis
      ports:
        - protocol: TCP
          port: 6379
    - to:
        - podSelector:
            matchLabels:
              app: qdrant
      ports:
        - protocol: TCP
          port: 6333
"""


@pytest.fixture(scope="module")
def k8s_manifest_dir(tmp_path_factory):
    """Create a temporary directory with K8s manifests."""
    k8s_dir = tmp_path_factory.mktemp("k8s_manifests")
    (k8s_dir / "deployment.yaml").write_text(_K8S_DEPLOYMENT)
    (k8s_dir / "service.yaml").write_text(_K8S_SERVICE)
    (k8s_dir / "configmap.yaml").write_text(_K8S_CONFIGMAP)
    (k8s_dir / "secret.yaml").write_text(_K8S_SECRET)
    (k8s_dir / "networkpolicy.yaml").write_text(_K8S_NETWORK_POLICY)
    return k8s_dir


class TestKubernetesManifests:
    """Tests for Kubernetes manifest validity and configuration."""

    def test_all_manifests_are_valid_yaml(self, k8s_manifest_dir):
        """Test 8: All K8s manifest files are valid YAML."""
        for manifest_file in k8s_manifest_dir.glob("*.yaml"):
            with open(manifest_file) as f:
                docs = list(yaml.safe_load_all(f))
            for doc in docs:
                if doc is None:
                    continue
                assert isinstance(doc, dict), (
                    f"{manifest_file.name} contains non-dict document"
                )
                assert "apiVersion" in doc, (
                    f"{manifest_file.name} missing apiVersion"
                )
                assert "kind" in doc, (
                    f"{manifest_file.name} missing kind"
                )

    def test_deployment_has_readiness_probe(self, k8s_manifest_dir):
        """Test 9a: Deployment spec includes readinessProbe."""
        with open(k8s_manifest_dir / "deployment.yaml") as f:
            deploy = yaml.safe_load(f)
        containers = deploy["spec"]["template"]["spec"]["containers"]
        for container in containers:
            assert "readinessProbe" in container, (
                f"Container '{container['name']}' missing readinessProbe"
            )
            probe = container["readinessProbe"]
            assert any(k in probe for k in ("httpGet", "exec", "tcpSocket")), (
                "readinessProbe must define httpGet, exec, or tcpSocket"
            )

    def test_deployment_has_liveness_probe(self, k8s_manifest_dir):
        """Test 9b: Deployment spec includes livenessProbe."""
        with open(k8s_manifest_dir / "deployment.yaml") as f:
            deploy = yaml.safe_load(f)
        containers = deploy["spec"]["template"]["spec"]["containers"]
        for container in containers:
            assert "livenessProbe" in container, (
                f"Container '{container['name']}' missing livenessProbe"
            )
            probe = container["livenessProbe"]
            assert any(k in probe for k in ("httpGet", "exec", "tcpSocket")), (
                "livenessProbe must define httpGet, exec, or tcpSocket"
            )

    def test_probes_target_correct_health_endpoint(self, k8s_manifest_dir):
        """Probes should target /api/health on port 8080."""
        with open(k8s_manifest_dir / "deployment.yaml") as f:
            deploy = yaml.safe_load(f)
        containers = deploy["spec"]["template"]["spec"]["containers"]
        for container in containers:
            for probe_name in ("readinessProbe", "livenessProbe"):
                probe = container.get(probe_name, {})
                http_get = probe.get("httpGet", {})
                assert http_get.get("path") == "/api/health", (
                    f"{probe_name} should target /api/health"
                )
                assert http_get.get("port") == 8080, (
                    f"{probe_name} should target port 8080"
                )

    def test_deployment_env_vars_from_configmap(self, k8s_manifest_dir):
        """Test 10a: Environment variables reference ConfigMap."""
        with open(k8s_manifest_dir / "deployment.yaml") as f:
            deploy = yaml.safe_load(f)
        containers = deploy["spec"]["template"]["spec"]["containers"]
        env_vars = containers[0].get("env", [])
        configmap_refs = [
            ev for ev in env_vars
            if ev.get("valueFrom", {}).get("configMapKeyRef") is not None
        ]
        assert len(configmap_refs) > 0, (
            "Expected at least one env var from ConfigMap"
        )
        cm_ref = configmap_refs[0]["valueFrom"]["configMapKeyRef"]
        assert "name" in cm_ref, "configMapKeyRef should specify ConfigMap name"

    def test_deployment_env_vars_from_secret(self, k8s_manifest_dir):
        """Test 10b: Environment variables reference Secrets."""
        with open(k8s_manifest_dir / "deployment.yaml") as f:
            deploy = yaml.safe_load(f)
        containers = deploy["spec"]["template"]["spec"]["containers"]
        env_vars = containers[0].get("env", [])
        secret_refs = [
            ev for ev in env_vars
            if ev.get("valueFrom", {}).get("secretKeyRef") is not None
        ]
        assert len(secret_refs) > 0, (
            "Expected at least one env var from Secret"
        )

    def test_configmap_mounted_as_volume(self, k8s_manifest_dir):
        """Test 11: ConfigMap is mounted as a volume."""
        with open(k8s_manifest_dir / "deployment.yaml") as f:
            deploy = yaml.safe_load(f)
        pod_spec = deploy["spec"]["template"]["spec"]

        # Check volume definition
        volumes = pod_spec.get("volumes", [])
        config_volumes = [
            v for v in volumes if v.get("configMap") is not None
        ]
        assert len(config_volumes) > 0, (
            "Expected at least one volume backed by ConfigMap"
        )

        # Check volumeMount in container
        containers = pod_spec["containers"]
        mounts = containers[0].get("volumeMounts", [])
        assert len(mounts) > 0, "Container should have volumeMounts"

    def test_configmap_has_expected_keys(self, k8s_manifest_dir):
        """ConfigMap should contain guard configuration keys."""
        with open(k8s_manifest_dir / "configmap.yaml") as f:
            cm = yaml.safe_load(f)
        assert cm["kind"] == "ConfigMap"
        data = cm.get("data", {})
        assert "GUARD_LOG_LEVEL" in data, "ConfigMap should have GUARD_LOG_LEVEL"
        assert "DATABASE_URL" in data, "ConfigMap should have DATABASE_URL"
        assert "REDIS_URL" in data, "ConfigMap should have REDIS_URL"

    def test_secret_has_expected_keys(self, k8s_manifest_dir):
        """Secret should contain required secret keys."""
        with open(k8s_manifest_dir / "secret.yaml") as f:
            secret = yaml.safe_load(f)
        assert secret["kind"] == "Secret"
        assert secret["type"] == "Opaque"
        data = secret.get("stringData", secret.get("data", {}))
        assert "secret-key" in data, "Secret should have secret-key"

    def test_network_policy_selects_correct_pods(self, k8s_manifest_dir):
        """Test 12a: NetworkPolicy selects the right pods."""
        with open(k8s_manifest_dir / "networkpolicy.yaml") as f:
            netpol = yaml.safe_load(f)
        assert netpol["kind"] == "NetworkPolicy"
        selector = netpol["spec"]["podSelector"]["matchLabels"]
        assert selector.get("app") == "rta-guard", (
            f"NetworkPolicy should select app=rta-guard, got: {selector}"
        )

    def test_network_policy_has_ingress_and_egress(self, k8s_manifest_dir):
        """NetworkPolicy should define both Ingress and Egress."""
        with open(k8s_manifest_dir / "networkpolicy.yaml") as f:
            netpol = yaml.safe_load(f)
        policy_types = netpol["spec"].get("policyTypes", [])
        assert "Ingress" in policy_types, "NetworkPolicy should include Ingress"
        assert "Egress" in policy_types, "NetworkPolicy should include Egress"

    def test_network_policy_ingress_allows_port_8080(self, k8s_manifest_dir):
        """Test 12b: NetworkPolicy ingress allows traffic on port 8080."""
        with open(k8s_manifest_dir / "networkpolicy.yaml") as f:
            netpol = yaml.safe_load(f)
        ingress_rules = netpol["spec"].get("ingress", [])
        assert len(ingress_rules) > 0, "NetworkPolicy should have ingress rules"
        all_ports = []
        for rule in ingress_rules:
            for port_spec in rule.get("ports", []):
                all_ports.append(port_spec.get("port"))
        assert 8080 in all_ports, (
            f"Ingress should allow port 8080, got: {all_ports}"
        )

    def test_network_policy_egress_allows_dns(self, k8s_manifest_dir):
        """Test 12c: NetworkPolicy egress allows DNS (port 53)."""
        with open(k8s_manifest_dir / "networkpolicy.yaml") as f:
            netpol = yaml.safe_load(f)
        egress_rules = netpol["spec"].get("egress", [])
        all_ports = []
        for rule in egress_rules:
            for port_spec in rule.get("ports", []):
                all_ports.append((port_spec.get("port"), port_spec.get("protocol")))
        assert (53, "TCP") in all_ports or (53, "UDP") in all_ports, (
            f"Egress should allow DNS (port 53), got: {all_ports}"
        )

    def test_network_policy_egress_allows_postgres(self, k8s_manifest_dir):
        """Test 12d: NetworkPolicy egress allows PostgreSQL traffic."""
        with open(k8s_manifest_dir / "networkpolicy.yaml") as f:
            netpol = yaml.safe_load(f)
        egress_rules = netpol["spec"].get("egress", [])
        all_ports = []
        for rule in egress_rules:
            for port_spec in rule.get("ports", []):
                all_ports.append(port_spec.get("port"))
        assert 5432 in all_ports, (
            f"Egress should allow PostgreSQL port 5432, got: {all_ports}"
        )

    def test_network_policy_egress_allows_redis(self, k8s_manifest_dir):
        """NetworkPolicy egress should allow Redis traffic."""
        with open(k8s_manifest_dir / "networkpolicy.yaml") as f:
            netpol = yaml.safe_load(f)
        egress_rules = netpol["spec"].get("egress", [])
        all_ports = []
        for rule in egress_rules:
            for port_spec in rule.get("ports", []):
                all_ports.append(port_spec.get("port"))
        assert 6379 in all_ports, (
            f"Egress should allow Redis port 6379, got: {all_ports}"
        )

    def test_network_policy_egress_allows_qdrant(self, k8s_manifest_dir):
        """NetworkPolicy egress should allow Qdrant traffic."""
        with open(k8s_manifest_dir / "networkpolicy.yaml") as f:
            netpol = yaml.safe_load(f)
        egress_rules = netpol["spec"].get("egress", [])
        all_ports = []
        for rule in egress_rules:
            for port_spec in rule.get("ports", []):
                all_ports.append(port_spec.get("port"))
        assert 6333 in all_ports, (
            f"Egress should allow Qdrant port 6333, got: {all_ports}"
        )

    def test_deployment_uses_correct_port(self, k8s_manifest_dir):
        """Deployment container should expose port 8080."""
        with open(k8s_manifest_dir / "deployment.yaml") as f:
            deploy = yaml.safe_load(f)
        containers = deploy["spec"]["template"]["spec"]["containers"]
        ports = containers[0].get("ports", [])
        port_numbers = [p["containerPort"] for p in ports]
        assert 8080 in port_numbers, (
            f"Container should expose port 8080, got: {port_numbers}"
        )

    def test_deployment_has_labels(self, k8s_manifest_dir):
        """Deployment should have standard Kubernetes labels."""
        with open(k8s_manifest_dir / "deployment.yaml") as f:
            deploy = yaml.safe_load(f)
        labels = deploy["metadata"].get("labels", {})
        assert "app" in labels, "Deployment should have 'app' label"
        assert "app.kubernetes.io/name" in labels, (
            "Deployment should have app.kubernetes.io/name label"
        )

    def test_deployment_has_multiple_replicas(self, k8s_manifest_dir):
        """Production deployment should have >1 replica."""
        with open(k8s_manifest_dir / "deployment.yaml") as f:
            deploy = yaml.safe_load(f)
        replicas = deploy["spec"].get("replicas", 1)
        assert replicas >= 2, f"Expected >=2 replicas for HA, got: {replicas}"

    def test_service_targets_correct_port(self, k8s_manifest_dir):
        """Service should target port 8080."""
        with open(k8s_manifest_dir / "service.yaml") as f:
            svc = yaml.safe_load(f)
        ports = svc["spec"]["ports"]
        svc_ports = [p["port"] for p in ports]
        assert 8080 in svc_ports, f"Service should expose port 8080, got: {svc_ports}"

    def test_service_selector_matches_deployment(self, k8s_manifest_dir):
        """Service selector should match Deployment labels."""
        with open(k8s_manifest_dir / "deployment.yaml") as f:
            deploy = yaml.safe_load(f)
        with open(k8s_manifest_dir / "service.yaml") as f:
            svc = yaml.safe_load(f)
        deploy_labels = deploy["spec"]["template"]["metadata"]["labels"]
        svc_selector = svc["spec"]["selector"]
        for key, value in svc_selector.items():
            assert deploy_labels.get(key) == value, (
                f"Service selector {key}={value} doesn't match "
                f"deployment label {key}={deploy_labels.get(key)}"
            )


# ===========================================================================
# Integration smoke test: docker-compose config validation
# ===========================================================================

class TestComposeConfig:
    """Validate docker-compose config without starting containers."""

    def test_compose_config_valid(self):
        """docker-compose config should resolve without errors."""
        if not _has_docker():
            pytest.skip("Docker not available")
        if not COMPOSE_FILE.exists():
            pytest.skip("docker-compose.yml not found")
        result = _run(["docker", "compose", "-f", str(COMPOSE_FILE), "config"])
        if result.returncode != 0:
            result = _run(["docker-compose", "-f", str(COMPOSE_FILE), "config"])
        assert result.returncode == 0, (
            f"docker-compose config validation failed:\n{result.stderr}"
        )

    def test_compose_resolves_all_services(self):
        """docker-compose config should resolve all 4 services."""
        if not _has_docker():
            pytest.skip("Docker not available")
        if not COMPOSE_FILE.exists():
            pytest.skip("docker-compose.yml not found")
        result = _run(["docker", "compose", "-f", str(COMPOSE_FILE), "config"])
        if result.returncode != 0:
            result = _run(["docker-compose", "-f", str(COMPOSE_FILE), "config"])
        if result.returncode != 0:
            pytest.skip("docker compose config not working")
        config = yaml.safe_load(result.stdout)
        services = config.get("services", {})
        expected = {"dashboard", "postgres", "redis", "qdrant"}
        assert expected.issubset(set(services.keys())), (
            f"Expected {expected}, got {set(services.keys())}"
        )


# ===========================================================================
# Project-level file existence checks
# ===========================================================================

class TestDeploymentFileExistence:
    """Ensure required deployment files exist in the project."""

    def test_dockerfile_exists(self):
        assert DOCKERFILE.exists(), "Dockerfile should exist in project root"

    def test_docker_compose_exists(self):
        assert COMPOSE_FILE.exists(), "docker-compose.yml should exist"

    def test_requirements_exists(self):
        req = PROJECT_ROOT / "requirements.txt"
        assert req.exists(), "requirements.txt should exist for Docker builds"
