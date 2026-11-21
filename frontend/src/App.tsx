import { useState } from 'react';
import { Navigate, NavLink, Outlet, Route, Routes, useLocation } from 'react-router-dom';
import {
  Activity,
  Bell,
  ClipboardList,
  LayoutDashboard,
  Layers,
  ListOrdered,
  LogOut,
  Menu,
  Settings,
  Sparkles,
  X,
} from 'lucide-react';
import { useAuth } from './auth';
import { Brand, Safety } from './components/ui';
import { ChatPanel } from './components/Chat';
import { Landing, Login, Signup } from './pages/Public';
import { Batches, Overview, Priorities, Alerts } from './pages/Operations';
import { BatchDetail } from './pages/BatchDetail';
import { Devices, SettingsPage } from './pages/Setup';

function Shell() {
  const { user, logout } = useAuth();
  const location = useLocation();
  const [open, setOpen] = useState(false);
  const [chat, setChat] = useState(false);
  if (!user)
    return <Navigate to="/login" state={{ from: location.pathname + location.search }} replace />;
  const batchId = location.pathname.match(/^\/app\/batches\/([^/]+)/)?.[1];
  const nav = [
    ['/app', LayoutDashboard, 'Overview'],
    ['/app/batches', Layers, 'Batches'],
    ['/app/devices', Activity, 'Devices'],
    ['/app/priorities', ListOrdered, 'Priorities'],
    ['/app/alerts', Bell, 'Alerts'],
    ['/app/settings', Settings, 'Settings'],
  ] as const;
  return (
    <div className="app-layout">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <aside className={`sidebar ${open ? 'open' : ''}`}>
        <div className="sidebar-top">
          <Brand />
          <button
            className="mobile-only icon-button"
            onClick={() => setOpen(false)}
            aria-label="Close navigation"
          >
            <X size={20} />
          </button>
        </div>
        <p className="workspace-label">Monitoring workspace</p>
        <nav aria-label="Application navigation">
          {nav.map(([path, Icon, title]) => (
            <NavLink key={path} to={path} end={path === '/app'} onClick={() => setOpen(false)}>
              <Icon size={19} />
              {title}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="pilot-tag">
            <LeafMark />
            <span>
              Tomato pilot<small>Evidence before action</small>
            </span>
          </div>
          <div className="user-row">
            <span className="avatar">{user.user_id.slice(0, 2).toUpperCase()}</span>
            <div>
              <strong>{user.user_id}</strong>
              <small>{user.role}</small>
            </div>
            <button className="icon-button" onClick={logout} aria-label="Sign out">
              <LogOut size={18} />
            </button>
          </div>
        </div>
      </aside>
      {open && (
        <button
          className="nav-scrim"
          onClick={() => setOpen(false)}
          aria-label="Close navigation"
        />
      )}
      <div className="app-body">
        <header className="app-topbar">
          <div>
            <button
              className="mobile-only icon-button"
              onClick={() => setOpen(!open)}
              aria-label="Open navigation"
              aria-expanded={open}
            >
              <Menu size={21} />
            </button>
            <span>
              Workspace <span className="crumb">/</span>{' '}
              {location.pathname === '/app'
                ? 'Overview'
                : location.pathname.split('/')[2]?.replace(/^./, (x) => x.toUpperCase())}
            </span>
          </div>
          <div className="topbar-actions">
            <button
              className="button secondary ask-button"
              onClick={() => setChat(!chat)}
              aria-expanded={chat}
            >
              <Sparkles size={16} /> Ask your data
            </button>
            <span className="role-label">
              {user.role === 'vendor' ? 'Read-only access' : 'Operator review required'}
            </span>
          </div>
        </header>
        <main id="main" className="app-main">
          <Outlet />
        </main>
        <Safety />
      </div>
      {chat && <ChatPanel batchId={batchId} close={() => setChat(false)} />}
    </div>
  );
}
function LeafMark() {
  return <ClipboardList size={21} />;
}
export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/login" element={<Login />} />
      <Route path="/signup" element={<Signup />} />
      <Route path="/app" element={<Shell />}>
        <Route index element={<Overview />} />
        <Route path="batches" element={<Batches />} />
        <Route path="batches/:id" element={<BatchDetail />} />
        <Route path="devices" element={<Devices />} />
        <Route path="priorities" element={<Priorities />} />
        <Route path="alerts" element={<Alerts />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route
          path="*"
          element={
            <div>
              <h1>Page not found</h1>
              <NavLink to="/app">Return to Overview</NavLink>
            </div>
          }
        />
      </Route>
      <Route
        path="*"
        element={
          <div className="not-found">
            <Brand />
            <h1>Page not found</h1>
            <NavLink to="/">Return home</NavLink>
          </div>
        }
      />
    </Routes>
  );
}
