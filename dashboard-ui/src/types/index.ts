/* eslint-disable @typescript-eslint/no-explicit-any */

// ─── API Response Types ────────────────────────────────────────────

export interface GuardEvent {
  session_id: string;
  input_text: string;
  decision: 'pass' | 'warn' | 'kill';
  violation_type: string | null;
  timestamp: string | null;
  details: Record<string, any> | null;
}

export interface Stats {
  total_events: number;
  total_kills: number;
  total_warnings: number;
  total_passes: number;
  active_killed_sessions: number;
  violation_types: Record<string, number>;
}

export interface CheckResult {
  allowed: boolean;
  session_id: string;
  event: GuardEvent | null;
  message: string | null;
  error: string | null;
}

export interface AgentInfo {
  agent_id: string;
  health?: string;
  drift_score?: number;
  sessions_count?: number;
  last_active?: string;
  [key: string]: any;
}

export interface DriftInfo {
  agent_id: string;
  score: number;
  level: string;
  components: Record<string, number>;
  overall_score?: number;
}

export interface DriftComponents {
  agent_id: string;
  components: Record<string, number>;
  overall_score: number;
  level: string;
}

export interface AnomalyInfo {
  agent_id: string;
  is_anomalous: boolean;
  anomaly_type: string;
  detail: string;
}

export interface Tenant {
  tenant_id: string;
  name: string;
  created_at?: string;
  [key: string]: any;
}

export interface TenantHealth {
  tenant_id: string;
  databases: Record<string, { status: string; [key: string]: any }>;
}

export interface RBACRoles {
  roles: Record<string, string[]>;
  all_permissions: string[];
}

export interface UserRole {
  user_id: string;
  tenant_id: string;
  role: string | null;
  permissions: string[];
}

export interface Webhook {
  webhook_id: string;
  url: string;
  events: string[];
  tenant_id: string;
  active: boolean;
  description: string;
  created_at: string | null;
}

export interface EscalationStatus {
  level: string;
  reasons: string[];
  signal_scores: Record<string, number>;
  aggregate_score: number;
  triggered_rules: string[];
}

export interface EscalationConfig {
  levels: Record<string, any>;
  thresholds: Record<string, number>;
}

export interface SSOProvider {
  provider_name: string;
  tenant_id: string;
  client_id: string;
  discovery_url: string;
  [key: string]: any;
}

export interface AuthStatus {
  enabled: boolean;
  token_set: boolean;
}

export interface LoginResponse {
  session_id: string;
  expires_in: number;
  tenant_id: string | null;
  role: string | null;
}

export interface RateLimitStatus {
  tenant_id: string;
  requests_per_minute: number;
  burst_size: number;
  current_usage?: number;
}

export interface SLAStatus {
  uptime: number;
  response_time_p50: number;
  response_time_p99: number;
  kill_rate: number;
}

export interface SLAStats {
  total_requests: number;
  total_breaches: number;
  breach_rate: number;
  avg_response_time: number;
}

export interface BrahmandaStatus {
  backend: string;
  fact_count: number;
  qdrant_url: string | null;
}

export interface VerifyResult {
  verified: boolean;
  confidence: number;
  domain: string;
  contradictions: Array<Record<string, any>>;
}

export interface WSMessage {
  session_id: string;
  input_text: string;
  decision: 'pass' | 'warn' | 'kill';
  violation_type: string | null;
  timestamp: string;
  details: Record<string, any> | null;
}
