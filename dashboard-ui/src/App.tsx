import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthProvider, useAuth } from '@/context/AuthContext';
import { Layout } from '@/components/layout/Layout';
import { LoadingSpinner } from '@/components/Loading';
import type { ReactNode } from 'react';

import LoginPage from '@/pages/Login';
import Dashboard from '@/pages/Dashboard';
import EventsPage from '@/pages/Events';
import SessionsPage from '@/pages/Sessions';
import CheckPage from '@/pages/Check';
import ConsciencePage from '@/pages/Conscience';
import DriftPage from '@/pages/Drift';
import EscalationPage from '@/pages/Escalation';
import TenantsPage from '@/pages/Tenants';
import RBACPage from '@/pages/RBAC';
import WebhooksPage from '@/pages/Webhooks';
import BrahmandaPage from '@/pages/Brahmanda';
import ReportsPage from '@/pages/Reports';
import SLAPage from '@/pages/SLA';
import SettingsPage from '@/pages/Settings';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
      staleTime: 5000,
    },
  },
});

function ProtectedRoute({ children }: { children: ReactNode }) {
  const { isAuthenticated, isLoading } = useAuth();
  if (isLoading) return <div className="min-h-screen flex items-center justify-center"><LoadingSpinner /></div>;
  if (!isAuthenticated) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/" element={<ProtectedRoute><Layout /></ProtectedRoute>}>
        <Route index element={<Dashboard />} />
        <Route path="events" element={<EventsPage />} />
        <Route path="sessions" element={<SessionsPage />} />
        <Route path="check" element={<CheckPage />} />
        <Route path="conscience" element={<ConsciencePage />} />
        <Route path="drift" element={<DriftPage />} />
        <Route path="escalation" element={<EscalationPage />} />
        <Route path="tenants" element={<TenantsPage />} />
        <Route path="rbac" element={<RBACPage />} />
        <Route path="webhooks" element={<WebhooksPage />} />
        <Route path="brahmanda" element={<BrahmandaPage />} />
        <Route path="reports" element={<ReportsPage />} />
        <Route path="sla" element={<SLAPage />} />
        <Route path="settings" element={<SettingsPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <AppRoutes />
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
