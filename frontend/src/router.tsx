import { NavLink, Navigate, Outlet, Route, Routes, useLocation } from "react-router-dom";
import { useAuth } from "./auth/AuthContext";
import AuditLog from "./pages/AuditLog";
import AuthAction from "./pages/AuthAction";
import Chargers from "./pages/Chargers";
import ForecastSettings from "./pages/ForecastSettings";
import Login from "./pages/Login";
import Members from "./pages/Members";
import MemberDetail from "./pages/MemberDetail";
import Movements from "./pages/Movements";
import MyAccount from "./pages/MyAccount";
import SettlementDetail from "./pages/SettlementDetail";
import Settlements from "./pages/Settlements";
import SystemHealth from "./pages/SystemHealth";
import Users from "./pages/Users";
import { ROUTES, SYSTEM_TAB_PATHS } from "./routes";

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
    return <Navigate to={ROUTES.login} replace state={{ from: location.pathname }} />;
  }
  return <>{children}</>;
}

export function RequireAdmin() {
  const { user } = useAuth();
  if (user && user.role !== "admin") {
    return <Navigate to={ROUTES.home} replace />;
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
  const { pathname } = useLocation();
  const isAdmin = user?.role === "admin";
  const hasPortal = user?.role === "member" || user?.member_id != null;

  // /brukere and /ladere live under System (configuration) — keep that tab lit.
  const systemActive = SYSTEM_TAB_PATHS.some(
    (p) => pathname === p || pathname.startsWith(`${p}/`),
  );

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
                  <NavLink to={ROUTES.members} className={navLinkClass}>
                    Medlemmer
                  </NavLink>
                  <NavLink to={ROUTES.settlements} className={navLinkClass}>
                    Avregninger
                  </NavLink>
                  <NavLink to={ROUTES.movements} className={navLinkClass}>
                    Bevegelser
                  </NavLink>
                  <NavLink to={ROUTES.audit} className={navLinkClass}>
                    Revisjonslogg
                  </NavLink>
                  <NavLink to={ROUTES.forecast} className={navLinkClass}>
                    Prognose
                  </NavLink>
                  <NavLink
                    to={ROUTES.system}
                    className={() => navLinkClass({ isActive: systemActive })}
                  >
                    System
                  </NavLink>
                </>
              )}
              {!isAdmin && hasPortal && (
                <NavLink to={ROUTES.home} end className={navLinkClass}>
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

/** The site root: a member's "min side", an admin's members list. */
function HomeOrAccount() {
  const { user } = useAuth();
  if (user?.role === "admin") {
    return <Navigate to={ROUTES.members} replace />;
  }
  return <MyAccount />;
}

export default function AppRouter() {
  return (
    <Routes>
      <Route path={ROUTES.login} element={<Login />} />
      <Route path="/auth/magic-link" element={<AuthAction mode="magic-link" />} />
      <Route path="/auth/reset" element={<AuthAction mode="reset" />} />
      <Route
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route index element={<HomeOrAccount />} />
        <Route element={<RequireAdmin />}>
          <Route path={ROUTES.members} element={<Members />} />
          <Route path={ROUTES.memberDetail(":id")} element={<MemberDetail />} />
          <Route path={ROUTES.users} element={<Users />} />
          <Route path={ROUTES.chargers} element={<Chargers />} />
          <Route path={ROUTES.settlements} element={<Settlements />} />
          <Route path={ROUTES.settlementDetail(":id")} element={<SettlementDetail />} />
          <Route path={ROUTES.movements} element={<Movements />} />
          <Route path={ROUTES.audit} element={<AuditLog />} />
          <Route path={ROUTES.forecast} element={<ForecastSettings />} />
          <Route path={ROUTES.system} element={<SystemHealth />} />
        </Route>
        <Route path="*" element={<Navigate to={ROUTES.home} replace />} />
      </Route>
    </Routes>
  );
}
