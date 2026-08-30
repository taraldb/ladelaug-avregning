import { NavLink, Navigate, Outlet, Route, Routes, useLocation } from "react-router-dom";
import { useAuth } from "./auth/AuthContext";
import AuditLog from "./pages/AuditLog";
import AuthAction from "./pages/AuthAction";
import Chargers from "./pages/Chargers";
import ForecastSettings from "./pages/ForecastSettings";
import Login from "./pages/Login";
import Members from "./pages/Members";
import MemberDetail from "./pages/MemberDetail";
import MyAccount from "./pages/MyAccount";
import SettlementDetail from "./pages/SettlementDetail";
import Settlements from "./pages/Settlements";
import SystemHealth from "./pages/SystemHealth";

function FullPageMessage({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-950 text-sm text-slate-400">
      {children}
    </div>
  );
}

export function RequireAuth({ children }: { children: React.ReactNode }) {
  const { user, isLoading } = useAuth();
  const location = useLocation();

  if (isLoading) {
    return <FullPageMessage>Laster …</FullPageMessage>;
  }
  if (!user) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  return <>{children}</>;
}

export function RequireAdmin() {
  const { user } = useAuth();
  if (user && user.role !== "admin") {
    return <Navigate to="/my-account" replace />;
  }
  return <Outlet />;
}

const navLinkClass = ({ isActive }: { isActive: boolean }) =>
  `rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
    isActive
      ? "bg-slate-100 text-slate-900"
      : "text-slate-300 hover:bg-slate-700/60 hover:text-slate-100"
  }`;

function Layout() {
  const { user, logout } = useAuth();
  const isAdmin = user?.role === "admin";
  const hasPortal = user?.role === "member" || user?.member_id != null;

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <header className="sticky top-0 z-10 border-b border-slate-800 bg-slate-900/70 backdrop-blur">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-4 sm:px-6 lg:px-8">
          <div className="flex items-center gap-4">
            <span className="text-sm font-semibold tracking-tight">
              Ladelaug avregning
            </span>
            <nav className="flex gap-1 rounded-lg bg-slate-800/60 p-1">
              {isAdmin && (
                <>
                  <NavLink to="/members" className={navLinkClass}>
                    Medlemmer
                  </NavLink>
                  <NavLink to="/chargers" className={navLinkClass}>
                    Ladere
                  </NavLink>
                  <NavLink to="/settlements" className={navLinkClass}>
                    Avregninger
                  </NavLink>
                  <NavLink to="/audit" className={navLinkClass}>
                    Revisjonslogg
                  </NavLink>
                  <NavLink to="/forecast" className={navLinkClass}>
                    Prognose
                  </NavLink>
                  <NavLink to="/system" className={navLinkClass}>
                    System
                  </NavLink>
                </>
              )}
              {!isAdmin && hasPortal && (
                <NavLink to="/my-account" className={navLinkClass}>
                  Min konto
                </NavLink>
              )}
            </nav>
          </div>
          <div className="flex items-center gap-3 text-xs text-slate-400">
            <span>{user?.email}</span>
            <button
              type="button"
              onClick={() => void logout()}
              className="rounded-md border border-slate-700 px-2.5 py-1 text-slate-300 hover:bg-slate-800"
            >
              Logg ut
            </button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-8 sm:px-6 lg:px-8">
        <Outlet />
      </main>
    </div>
  );
}

function HomeRedirect() {
  const { user } = useAuth();
  return <Navigate to={user?.role === "admin" ? "/members" : "/my-account"} replace />;
}

export default function AppRouter() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/auth/magic-link" element={<AuthAction mode="magic-link" />} />
      <Route path="/auth/reset" element={<AuthAction mode="reset" />} />
      <Route
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route index element={<HomeRedirect />} />
        <Route path="/my-account" element={<MyAccount />} />
        <Route element={<RequireAdmin />}>
          <Route path="/members" element={<Members />} />
          <Route path="/members/:id" element={<MemberDetail />} />
          <Route path="/chargers" element={<Chargers />} />
          <Route path="/settlements" element={<Settlements />} />
          <Route path="/settlements/:id" element={<SettlementDetail />} />
          <Route path="/audit" element={<AuditLog />} />
          <Route path="/forecast" element={<ForecastSettings />} />
          <Route path="/system" element={<SystemHealth />} />
        </Route>
        <Route path="*" element={<HomeRedirect />} />
      </Route>
    </Routes>
  );
}
