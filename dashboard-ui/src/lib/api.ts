import type {
  Stats, GuardEvent, CheckResult, AgentInfo, DriftInfo, DriftComponents,
  AnomalyInfo, Tenant, TenantHealth, RBACRoles, UserRole, Webhook,
  EscalationStatus, EscalationConfig, SSOProvider, AuthStatus, LoginResponse,
  RateLimitStatus, SLAStatus, SLAStats, BrahmandaStatus, VerifyResult,
} from '@/types';

const API_BASE = import.meta.env.VITE_API_URL || '';

function getToken(): string | null {
  return localStorage.getItem('rta-guard-token');
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string>),
  };
  if (token) headers['Authorization'] = `Bearer ${token}`;

  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });

  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(body.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

// ─── Auth ──────────────────────────────────────────────────────────

export const authApi = {
  login: (username: string, password: string) =>
    request<LoginResponse>('/api/login', { method: 'POST', body: JSON.stringify({ username, password }) }),
  status: () => request<AuthStatus>('/api/auth/status'),
  ssoLogin: (tenantId = '', provider = '') =>
    request<{ login_url: string; tenant_id: string; provider_name: string }>(`/api/sso/login?tenant_id=${tenantId}&provider_name=${provider}`),
  ssoCallback: (code: string, state: string, provider: string) =>
    request<LoginResponse>('/api/sso/callback', { method: 'POST', body: JSON.stringify({ code, state, provider }) }),
  ssoProviders: (tenantId = '') =>
    request<{ providers: SSOProvider[]; total: number; configured: boolean }>(`/api/sso/providers?tenant_id=${tenantId}`),
  ssoCreateProvider: (data: { tenant_id: string; provider_name: string; client_id: string; client_secret: string; discovery_url: string }) =>
    request<{ status: string }>('/api/sso/providers', { method: 'POST', body: JSON.stringify(data) }),
  ssoDeleteProvider: (tenantId: string, providerName: string) =>
    request<{ status: string }>(`/api/sso/providers/${tenantId}/${providerName}`, { method: 'DELETE' }),
};

// ─── Core Guard ────────────────────────────────────────────────────

export const guardApi = {
  events: (sessionId?: string) => {
    const q = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : '';
    return request<{ events: GuardEvent[]; total: number }>(`/api/events${q}`);
  },
  killed: () => request<{ killed_sessions: string[]; total: number }>('/api/killed'),
  stats: () => request<Stats>('/api/stats'),
  check: (input: string, sessionId: string) =>
    request<CheckResult>('/api/check', { method: 'POST', body: JSON.stringify({ input, session_id: sessionId }) }),
  reset: (sessionId: string) =>
    request<{ status: string; session_id: string }>(`/api/reset/${sessionId}`, { method: 'POST' }),
};

// ─── Brahmanda ─────────────────────────────────────────────────────

export const brahmandaApi = {
  status: () => request<BrahmandaStatus>('/api/brahmanda/status'),
  verify: (claim: string, domain = '') =>
    request<VerifyResult>('/api/brahmanda/verify', { method: 'POST', body: JSON.stringify({ claim, domain }) }),
  pipelineVerify: (claim: string, domain = '') =>
    request<VerifyResult>('/api/brahmanda/pipeline/verify', { method: 'POST', body: JSON.stringify({ claim, domain }) }),
};

// ─── Tenants ───────────────────────────────────────────────────────

export const tenantsApi = {
  list: () => request<{ tenants: Tenant[]; total: number }>('/api/tenants'),
  get: (id: string) => request<Tenant>(`/api/tenants/${id}`),
  create: (name: string, tenantId: string) =>
    request<{ status: string; tenant: Tenant }>('/api/tenants', { method: 'POST', body: JSON.stringify({ name, tenant_id: tenantId }) }),
  delete: (id: string) => request<{ status: string }>(`/api/tenants/${id}`, { method: 'DELETE' }),
  health: (id: string) => request<TenantHealth>(`/api/tenants/${id}/health`),
};

// ─── RBAC ──────────────────────────────────────────────────────────

export const rbacApi = {
  roles: () => request<RBACRoles>('/api/rbac/roles'),
  assign: (userId: string, tenantId: string, role: string) =>
    request<{ status: string }>('/api/rbac/assign', { method: 'POST', body: JSON.stringify({ user_id: userId, tenant_id: tenantId, role }) }),
  revoke: (userId: string, tenantId: string) =>
    request<{ status: string }>('/api/rbac/revoke', { method: 'POST', body: JSON.stringify({ user_id: userId, tenant_id: tenantId }) }),
  userRole: (userId: string, tenantId: string) =>
    request<UserRole>(`/api/rbac/user/${userId}/tenant/${tenantId}`),
  tenantRoles: (tenantId: string) =>
    request<{ tenant_id: string; assignments: Array<Record<string, string>>; total: number }>(`/api/rbac/tenant/${tenantId}`),
};

// ─── Conscience ────────────────────────────────────────────────────

export const conscienceApi = {
  agents: () => request<{ agents: AgentInfo[]; total: number }>('/api/conscience/agents'),
  health: (agentId: string) => request<Record<string, any>>(`/api/conscience/health/${agentId}`),
  anomaly: (agentId: string) => request<AnomalyInfo>(`/api/conscience/anomaly/${agentId}`),
  drift: (agentId: string) => request<DriftInfo>(`/api/conscience/drift/${agentId}`),
  driftComponents: (agentId: string) => request<DriftComponents>(`/api/conscience/drift/components/${agentId}`),
  driftSession: (sessionId: string) => request<DriftInfo>(`/api/conscience/drift/session/${sessionId}`),
  driftRecord: (data: { agent_id: string; session_id: string; score: number; components: Record<string, number> }) =>
    request<{ status: string }>('/api/conscience/drift/record', { method: 'POST', body: JSON.stringify(data) }),
  sessions: (agentId?: string, userId?: string, limit = 50) => {
    const params = new URLSearchParams();
    if (agentId) params.set('agent_id', agentId);
    if (userId) params.set('user_id', userId);
    params.set('limit', String(limit));
    return request<{ sessions: Array<Record<string, any>>; total: number }>(`/api/conscience/sessions?${params}`);
  },
  users: () => request<{ users: Array<Record<string, any>>; total: number }>('/api/conscience/users'),
  tamas: (agentId: string) => request<Record<string, any>>(`/api/conscience/tamas/${agentId}`),
  temporal: (agentId: string) => request<Record<string, any>>(`/api/conscience/temporal/${agentId}`),
  userAnomaly: (userId: string) => request<Record<string, any>>(`/api/conscience/user/${userId}/anomaly`),
  userSignals: (userId: string) => request<Record<string, any>>(`/api/conscience/user/${userId}/signals`),
  userList: (tenantId = '') =>
    request<{ users: Array<Record<string, any>>; total: number }>(`/api/conscience/user-tracker/list?tenant_id=${tenantId}`),
};

// ─── Escalation ────────────────────────────────────────────────────

export const escalationApi = {
  evaluate: (agentId: string, sessionId = '', signals: Record<string, number> = {}) =>
    request<EscalationStatus>('/api/conscience/escalation/evaluate', {
      method: 'POST', body: JSON.stringify({ agent_id: agentId, session_id: sessionId, signals }),
    }),
  status: (agentId: string, sessionId = '') =>
    request<EscalationStatus>(`/api/conscience/escalation/${agentId}?session_id=${sessionId}`),
  history: (limit = 50) =>
    request<{ history: EscalationStatus[]; total: number }>(`/api/conscience/escalation/history?limit=${limit}`),
  config: () => request<EscalationConfig>('/api/conscience/escalation/config'),
};

// ─── Webhooks ──────────────────────────────────────────────────────

export const webhooksApi = {
  list: (tenantId?: string) => {
    const q = tenantId ? `?tenant_id=${tenantId}` : '';
    return request<{ webhooks: Webhook[]; total: number }>(`/api/webhooks${q}`);
  },
  get: (id: string) => request<Webhook>(`/api/webhooks/${id}`),
  create: (data: { url: string; events: string[]; tenant_id: string; description?: string }) =>
    request<{ status: string; webhook: Webhook }>('/api/webhooks', { method: 'POST', body: JSON.stringify(data) }),
  update: (id: string, data: Partial<Webhook>) =>
    request<{ status: string }>(`/api/webhooks/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  delete: (id: string) => request<{ status: string }>(`/api/webhooks/${id}`, { method: 'DELETE' }),
  test: (id: string) => request<{ status: string; webhook_id: string; event_id: string }>(`/api/webhooks/${id}/test`, { method: 'POST' }),
};

// ─── Reports ───────────────────────────────────────────────────────

export const reportsApi = {
  types: () => request<{ report_types: string[]; output_formats: string[] }>('/api/reports/types'),
  generate: (data: { report_type: string; tenant_id: string; start_date: string; end_date: string; output_format: string }) =>
    request<{ status: string; report: Record<string, any> }>('/api/reports/generate', { method: 'POST', body: JSON.stringify(data) }),
};

// ─── SLA & Rate Limiting ──────────────────────────────────────────

export const slaApi = {
  status: () => request<SLAStatus>('/api/sla/status'),
  metric: (name: string) => request<Record<string, any>>(`/api/sla/metrics/${name}`),
  breaches: (startDate?: string, endDate?: string, limit = 50) => {
    const params = new URLSearchParams();
    if (startDate) params.set('start_date', startDate);
    if (endDate) params.set('end_date', endDate);
    params.set('limit', String(limit));
    return request<{ breaches: Array<Record<string, any>>; total: number }>(`/api/sla/breaches?${params}`);
  },
  stats: () => request<SLAStats>('/api/sla/stats'),
  rateLimitStatus: (tenantId = '') =>
    request<RateLimitStatus>(`/api/rate-limit/status?tenant_id=${tenantId}`),
  rateLimitConfigure: (tenantId: string, rpm: number, burst: number) =>
    request<{ status: string }>('/api/rate-limit/configure', {
      method: 'POST', body: JSON.stringify({ tenant_id: tenantId, requests_per_minute: rpm, burst_size: burst }),
    }),
};
