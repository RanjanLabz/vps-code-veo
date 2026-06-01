"use client";

import { LogOut, ShieldCheck, UserCheck } from "lucide-react";
import { FormEvent, ReactNode, useEffect, useState } from "react";
import {
  AdminSession,
  changePassword,
  clearToken,
  currentAdminSession,
  loginWithPassword,
  signupWithPassword,
} from "@/lib/adminAuth";

export function AuthGate({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<AdminSession | null>(null);
  const [loading, setLoading] = useState(true);
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [showChangePassword, setShowChangePassword] = useState(false);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    currentAdminSession()
      .then(setSession)
      .finally(() => setLoading(false));
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      if (mode === "signup") {
        const result = await signupWithPassword(email, password, name);
        setNotice(result.message || "Signup request saved. Wait for admin approval.");
        setMode("login");
        setPassword("");
        return;
      }
      setSession(await loginWithPassword(email, password));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Authentication failed.");
    } finally {
      setBusy(false);
    }
  }

  function logout() {
    clearToken();
    setSession(null);
    setPassword("");
  }

  async function submitPasswordChange(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const result = await changePassword(currentPassword, newPassword);
      setNotice(result.message || "Password changed.");
      setCurrentPassword("");
      setNewPassword("");
      setShowChangePassword(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to change password.");
    } finally {
      setBusy(false);
    }
  }

  if (loading) {
    return (
      <main className="auth-shell">
        <section className="auth-panel">
          <ShieldCheck size={34} />
          <h1>Checking admin session</h1>
          <p>Verifying your local admin session.</p>
        </section>
      </main>
    );
  }

  if (!session) {
    return (
      <main className="auth-shell">
        <form className="auth-panel" onSubmit={submit}>
          <ShieldCheck size={34} />
          <h1>{mode === "login" ? "FlowKit Admin" : "Request admin access"}</h1>
          <p>
            {mode === "login"
              ? "Sign in with your approved admin email and password."
              : "Create an account request. A super admin must approve it before you can use the panel."}
          </p>
          {mode === "signup" && (
            <label className="grid gap-1 text-sm font-medium text-slate-700">
              Name
              <input className="input" value={name} onChange={(event) => setName(event.target.value)} placeholder="Your name" />
            </label>
          )}
          <label className="grid gap-1 text-sm font-medium text-slate-700">
            Email
            <input className="input" type="email" value={email} onChange={(event) => setEmail(event.target.value)} required />
          </label>
          <label className="grid gap-1 text-sm font-medium text-slate-700">
            Password
            <input className="input" type="password" value={password} onChange={(event) => setPassword(event.target.value)} required minLength={8} />
          </label>
          {notice ? <div className="auth-success">{notice}</div> : null}
          {error ? <div className="auth-error">{error}</div> : null}
          <button className="primary-button w-full" disabled={busy}>
            <UserCheck size={18} />
            {mode === "login" ? "Sign in" : "Request access"}
          </button>
          <button
            className="command-button w-full justify-center"
            type="button"
            onClick={() => {
              setMode(mode === "login" ? "signup" : "login");
              setError(null);
              setNotice(null);
            }}
          >
            {mode === "login" ? "Create access request" : "Back to sign in"}
          </button>
        </form>
      </main>
    );
  }

  return (
    <>
      <div className="auth-bar">
        <span>{session.email}</span>
        <strong>{session.role === "super_admin" ? "Super admin" : session.role || "Admin"}</strong>
        <button className="command-button h-8" onClick={() => setShowChangePassword((value) => !value)}>
          Change password
        </button>
        <button className="command-button h-8" onClick={logout}>
          <LogOut size={15} />
          Sign out
        </button>
      </div>
      {showChangePassword && (
        <div className="auth-password-panel">
          <form className="grid gap-3" onSubmit={submitPasswordChange}>
            <label className="grid gap-1 text-sm font-medium text-slate-700">
              Current password
              <input className="input" type="password" value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} required />
            </label>
            <label className="grid gap-1 text-sm font-medium text-slate-700">
              New password
              <input className="input" type="password" value={newPassword} onChange={(event) => setNewPassword(event.target.value)} required minLength={8} />
            </label>
            {notice ? <div className="auth-success">{notice}</div> : null}
            {error ? <div className="auth-error">{error}</div> : null}
            <button className="primary-button" disabled={busy}>Save password</button>
          </form>
        </div>
      )}
      {children}
    </>
  );
}
