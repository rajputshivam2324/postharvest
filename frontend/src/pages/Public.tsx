import { useEffect, useState, type FormEvent } from 'react';
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom';
import {
  ArrowRight,
  Eye,
  EyeOff,
  Leaf,
  Radio,
  Thermometer,
  Layers,
  Bell,
  ClipboardCheck,
  Send,
  ShieldCheck,
} from 'lucide-react';
import { Brand, Notice, Safety } from '../components/ui';
import { useAuth } from '../auth';
import { safeDestination } from '../api/client';

/** The public landing page is a separate static page (public/site, built with the design kit). */
export function Landing() {
  useEffect(() => {
    window.location.replace('/site/index.html');
  }, []);
  return (
    <p className="not-found">
      Opening Harvest… <a href="/site/index.html">Continue to the Harvest home page</a>
    </p>
  );
}

export function Login() {
  const auth = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [show, setShow] = useState(false);
  if (auth.user) return <Navigate to={safeDestination(location.state?.from)} replace />;
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    setBusy(true);
    setError('');
    try {
      await auth.login(String(data.get('user_id')).trim(), String(data.get('password')));
      form.reset();
      navigate(safeDestination(location.state?.from), { replace: true });
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Unable to sign in. Please try again.');
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="login-page">
      <div className="login-story">
        <Brand />
        <div>
          <h1>
            A closer look
            <br />
            at what matters.
          </h1>
          <p>
            Your batches. Your evidence.
            <br />
            Your next considered decision.
          </p>
          <Leaf size={100} strokeWidth={1} />
        </div>
        <Safety />
      </div>
      <main className="login-main">
        <Link className="text-link back-home" to="/">
          Back to Harvest
        </Link>
        <div className="login-form">
          <h1>Welcome back.</h1>
          <p>Sign in to your monitoring workspace.</p>
          {error && <Notice danger>{error}</Notice>}
          <form onSubmit={submit}>
            <label>
              User ID
              <input
                name="user_id"
                autoComplete="username"
                required
                maxLength={80}
                pattern="[a-zA-Z0-9_.@\-]+"
                placeholder="Your assigned user ID"
              />
            </label>
            <label>
              Password
              <div className="password-input">
                <input
                  name="password"
                  type={show ? 'text' : 'password'}
                  autoComplete="current-password"
                  required
                  maxLength={128}
                  placeholder="Your password"
                />
                <button
                  type="button"
                  onClick={() => setShow(!show)}
                  aria-label={show ? 'Hide password' : 'Show password'}
                >
                  {show ? <EyeOff size={18} /> : <Eye size={18} />}
                </button>
              </div>
            </label>
            <button className="button primary large" disabled={busy}>
              {busy ? 'Signing in…' : 'Sign in'}
              <ArrowRight size={18} />
            </button>
          </form>
          <p className="login-help">
            New here?{' '}
            <Link className="text-link" to="/signup">
              Create an account
            </Link>
            <br />
            Your session ends when you reload or close this page.
          </p>
        </div>
      </main>
    </div>
  );
}

export function Signup() {
  const auth = useAuth();
  const navigate = useNavigate();
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [role, setRole] = useState<'operator' | 'vendor'>('vendor');
  if (auth.user) return <Navigate to="/app" replace />;
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    if (data.get('password') !== data.get('confirm_password')) {
      setError('Passwords do not match.');
      return;
    }
    setError('');
    setBusy(true);
    try {
      await auth.signup(String(data.get('user_id')).trim(), String(data.get('password')), role);
      form.reset();
      navigate('/app', { replace: true });
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Unable to create your account. Please try again.');
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="login-page">
      <div className="login-story">
        <Brand />
        <div>
          <h1>
            Your harvest.
            <br />A shared perspective.
          </h1>
          <p>
            Connect evidence with the people
            <br />
            who make the decisions.
          </p>
          <Leaf size={100} strokeWidth={1} />
        </div>
        <Safety />
      </div>
      <main className="login-main">
        <Link className="text-link back-home" to="/">
          Back to Harvest
        </Link>
        <div className="login-form">
          <h1>Create your account.</h1>
          <p>Choose the access that fits your work.</p>
          {error && <Notice danger>{error}</Notice>}
          <form onSubmit={submit}>
            <label>
              User ID
              <input
                aria-label="User ID"
                name="user_id"
                autoComplete="username"
                required
                maxLength={80}
                pattern="[a-zA-Z0-9_.@\-]+"
                placeholder="Letters, numbers, dots, or hyphens"
              />
            </label>
            <label>
              Account role
              <select
                aria-label="Account role"
                name="role"
                value={role}
                onChange={(e) => setRole(e.target.value as typeof role)}
              >
                <option value="vendor">Vendor</option>
                <option value="operator">Operator</option>
              </select>
              <span className="field-hint">
                {role === 'vendor'
                  ? 'Read-only access to batches an administrator assigns to your account.'
                  : 'Shared access to warehouse batches, observations, assessments and alerts.'}
              </span>
            </label>
            <label>
              Password
              <input
                aria-label="Password"
                name="password"
                type="password"
                autoComplete="new-password"
                required
                minLength={12}
                maxLength={128}
                placeholder="At least 12 characters"
              />
            </label>
            <label>
              Confirm password
              <input
                aria-label="Confirm password"
                name="confirm_password"
                type="password"
                autoComplete="new-password"
                required
                minLength={12}
                maxLength={128}
              />
            </label>
            <button className="button primary large" disabled={busy}>
              {busy ? 'Creating account…' : 'Create account'}
              <ArrowRight size={18} />
            </button>
          </form>
          <p className="login-help">
            Already have an account?{' '}
            <Link className="text-link" to="/login">
              Sign in
            </Link>
            <br />
            Administrator accounts are provisioned separately.
          </p>
        </div>
      </main>
    </div>
  );
}
