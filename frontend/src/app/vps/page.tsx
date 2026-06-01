"use client";

import {
  AlertCircle,
  ArrowLeft,
  CheckCircle2,
  Loader2,
  Network,
  Plus,
  RefreshCcw,
  Server,
  Trash2,
} from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { FormEvent, Suspense, useEffect, useMemo, useState } from "react";
import { storedToken } from "@/lib/adminAuth";

type Worker = {
  id: string;
  base_url: string;
  enabled: boolean;
  max_jobs: number;
  status?: {
    online: boolean;
    accounts_total: number;
    accounts_busy: number;
    accounts_ready: number;
    active_jobs: number;
    queue_size: number;
    cpu: number;
    ram: number;
    health_score: number;
    error?: string;
    raw_health?: {
      browser_status?: Record<string, BrowserStatus>;
      extension_status?: { manifest_present?: boolean };
    };
  };
};

type BrowserStatus = {
  pid?: number;
  running?: boolean;
  display?: string;
  vnc_port?: number;
  debug_port?: number;
  current_url?: string;
  auth_required?: boolean;
  flowkit?: {
    connected?: boolean;
    flow_key_present?: boolean;
    pending?: number;
  };
};

type Account = {
  id: string;
  status: string;
  profile_path?: string;
  proxy_enabled?: boolean;
  proxy_url?: string | null;
  jobs_running: number;
  health_score: number;
  browser_pid?: number | null;
  remote_debugging_port?: number | null;
  display?: string | null;
  vnc_port?: number | null;
  vnc_web_port?: number | null;
  vnc_web_url?: string | null;
  flowkit_ws_port?: number | null;
  settings?: {
    max_concurrent_jobs?: number;
    tags?: string[];
  };
};

const API = "/api/orchestrator";
const DEFAULT_PUBLIC_VPS_HOST = process.env.NEXT_PUBLIC_DEFAULT_VPS_HOST || "your-worker.example.com";

function cls(...items: Array<string | false | null | undefined>) {
  return items.filter(Boolean).join(" ");
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const token = storedToken();
  const response = await fetch(`${API}${path}`, {
    ...init,
    headers: {
      "content-type": "application/json",
      ...(token ? { authorization: `Bearer ${token}` } : {}),
      ...(init?.headers || {}),
    },
    cache: "no-store",
  });
  if (!response.ok) throw new Error(await response.text());
  return response.json() as Promise<T>;
}

function VpsPageContent() {
  const searchParams = useSearchParams();
  const vpsId = searchParams.get("id") || "";
  const [workers, setWorkers] = useState<Worker[]>([]);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [newAccountId, setNewAccountId] = useState("acc-1");
  const [newAccountConcurrency, setNewAccountConcurrency] = useState(1);
  const [newAccountProxyEnabled, setNewAccountProxyEnabled] = useState(false);
  const [newAccountProxyUrl, setNewAccountProxyUrl] = useState("");
  const [removeProfileOnDelete, setRemoveProfileOnDelete] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const worker = useMemo(() => workers.find((item) => item.id === vpsId) || null, [workers, vpsId]);
  const browserStatus = worker?.status?.raw_health?.browser_status || {};
  const publicHost = useMemo(() => publicHostForWorker(worker), [worker]);

  async function refresh(silent = false) {
    if (!silent) setBusy("Refreshing");
    try {
      const [nextWorkers, nextAccounts] = await Promise.all([
        api<Worker[]>("/workers"),
        api<Account[]>(`/workers/${encodeURIComponent(vpsId)}/accounts`),
      ]);
      setWorkers(nextWorkers);
      setAccounts(nextAccounts);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load VPS");
    } finally {
      setBusy(null);
    }
  }

  useEffect(() => {
    const boot = window.setTimeout(() => refresh(), 0);
    const id = window.setInterval(() => refresh(true), 10000);
    return () => {
      window.clearTimeout(boot);
      window.clearInterval(id);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [vpsId]);

  async function run(label: string, action: () => Promise<unknown>) {
    setBusy(label);
    setNotice(null);
    setError(null);
    try {
      await action();
      setNotice(label);
      await refresh(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Action failed");
    } finally {
      setBusy(null);
    }
  }

  async function addAccount(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await run("Account created", () =>
      api(`/workers/${encodeURIComponent(vpsId)}/accounts`, {
        method: "POST",
        body: JSON.stringify({
          id: newAccountId.trim() || undefined,
          proxy_enabled: newAccountProxyEnabled,
          proxy_url: newAccountProxyEnabled ? newAccountProxyUrl || null : null,
          settings: { max_concurrent_jobs: newAccountConcurrency },
        }),
      }),
    );
  }

  async function accountAction(account: Account, action: "start" | "stop" | "restart" | "recover") {
    await run(`Account ${action}`, () =>
      api(`/workers/${encodeURIComponent(vpsId)}/accounts/${encodeURIComponent(account.id)}/${action}`, { method: "POST" }),
    );
  }

  async function deleteAccount(account: Account) {
    await run("Account removed", () =>
      api(`/workers/${encodeURIComponent(vpsId)}/accounts/${encodeURIComponent(account.id)}?remove_profile=${removeProfileOnDelete}`, {
        method: "DELETE",
      }),
    );
  }

  async function updateAccount(account: Account, patch: { maxConcurrentJobs: number; proxyEnabled: boolean; proxyUrl: string }) {
    await run("Account updated", async () => {
      await api(`/workers/${encodeURIComponent(vpsId)}/accounts/${encodeURIComponent(account.id)}/settings`, {
        method: "PATCH",
        body: JSON.stringify({ max_concurrent_jobs: patch.maxConcurrentJobs }),
      });
      await api(`/workers/${encodeURIComponent(vpsId)}/accounts/${encodeURIComponent(account.id)}/proxy`, {
        method: "PATCH",
        body: JSON.stringify({
          proxy_enabled: patch.proxyEnabled,
          proxy_url: patch.proxyEnabled ? patch.proxyUrl || null : null,
        }),
      });
    });
  }

  return (
    <main className="min-h-screen bg-[#f6f7f9] text-slate-950">
      <div className="mx-auto flex min-h-screen w-full max-w-[1400px] flex-col px-4 py-4 sm:px-6 lg:px-8">
        <header className="flex flex-col gap-4 border-b border-slate-200 pb-4 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex items-center gap-3">
            <Link className="icon-button" href="/" title="Back to overview">
              <ArrowLeft size={17} />
            </Link>
            <div className="flex size-11 items-center justify-center rounded-lg bg-slate-950 text-white">
              <Server size={22} />
            </div>
            <div>
              <h1 className="text-2xl font-semibold tracking-normal">{vpsId}</h1>
              <p className="break-all text-sm text-slate-500">{worker?.base_url || "Loading VPS worker..."}</p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Status ok={Boolean(worker?.status?.online)} label={worker?.status?.online ? "VPS online" : "VPS offline"} />
            <button className="icon-button" onClick={() => refresh()} disabled={Boolean(busy)} title="Refresh">
              <RefreshCcw size={17} className={busy === "Refreshing" ? "animate-spin" : ""} />
            </button>
          </div>
        </header>

        {(notice || error) && (
          <div className={cls("mt-4 flex items-center gap-2 rounded-lg border px-3 py-2 text-sm", error ? "border-red-200 bg-red-50 text-red-700" : "border-emerald-200 bg-emerald-50 text-emerald-700")}>
            {error ? <AlertCircle size={16} /> : <CheckCircle2 size={16} />}
            <span className="line-clamp-2">{error || notice}</span>
          </div>
        )}

        <section className="mt-5 grid gap-4 md:grid-cols-4">
          <Info label="Accounts" value={`${worker?.status?.accounts_ready ?? 0} ready / ${worker?.status?.accounts_total ?? accounts.length} total`} />
          <Info label="Jobs" value={`${worker?.status?.active_jobs ?? 0} active / max ${worker?.max_jobs ?? 0}`} />
          <Info label="CPU" value={`${Math.round(worker?.status?.cpu ?? 0)}%`} />
          <Info label="RAM" value={`${Math.round(worker?.status?.ram ?? 0)}%`} />
        </section>

        <div className="mt-5 grid gap-5 xl:grid-cols-[420px_minmax(0,1fr)]">
          <aside className="grid content-start gap-5">
            <Panel title="Add Account">
              <form className="grid gap-3" onSubmit={addAccount}>
                <Field label="Account ID">
                  <input className="input" value={newAccountId} onChange={(event) => setNewAccountId(event.target.value)} placeholder="account email or acc-3" />
                </Field>
                <Field label="Max concurrent jobs">
                  <input className="input" type="number" min={1} max={10} value={newAccountConcurrency} onChange={(event) => setNewAccountConcurrency(Number(event.target.value))} />
                </Field>
                <label className="flex items-center justify-between rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm">
                  <span className="font-medium text-slate-700">Use proxy</span>
                  <input type="checkbox" checked={newAccountProxyEnabled} onChange={(event) => setNewAccountProxyEnabled(event.target.checked)} />
                </label>
                {newAccountProxyEnabled && (
                  <Field label="Proxy URL">
                    <input className="input" value={newAccountProxyUrl} onChange={(event) => setNewAccountProxyUrl(event.target.value)} placeholder="http://user:pass@host:8080" />
                  </Field>
                )}
                <button className="primary-button" disabled={Boolean(busy)}>
                  {busy ? <Loader2 size={17} className="animate-spin" /> : <Plus size={17} />}
                  Add account
                </button>
              </form>
            </Panel>

            <Panel title="Remove Behavior">
              <label className="flex items-center justify-between rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
                <span className="font-medium">Delete Chrome profile data when removing account</span>
                <input type="checkbox" checked={removeProfileOnDelete} onChange={(event) => setRemoveProfileOnDelete(event.target.checked)} />
              </label>
            </Panel>
          </aside>

          <section className="grid content-start gap-3">
            {accounts.length === 0 && <Empty text="No accounts returned for this VPS." />}
            {accounts.map((account) => (
              <AccountCard
                key={account.id}
                account={account}
                runtime={browserStatus[account.id] || {}}
                publicHost={publicHost}
                busy={Boolean(busy)}
                onAction={(action) => accountAction(account, action)}
                onDelete={() => deleteAccount(account)}
                onSave={(patch) => updateAccount(account, patch)}
              />
            ))}
          </section>
        </div>
      </div>
    </main>
  );
}

export default function VpsPage() {
  return (
    <Suspense fallback={<main className="min-h-screen bg-slate-50 p-8 text-slate-950">Loading VPS...</main>}>
      <VpsPageContent />
    </Suspense>
  );
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border border-slate-200 bg-white shadow-sm">
      <div className="border-b border-slate-100 px-4 py-3 text-sm font-semibold">{title}</div>
      <div className="p-4">{children}</div>
    </section>
  );
}

function AccountCard({
  account,
  runtime,
  publicHost,
  busy,
  onAction,
  onDelete,
  onSave,
}: {
  account: Account;
  runtime: BrowserStatus;
  publicHost: string;
  busy: boolean;
  onAction: (action: "start" | "stop" | "restart" | "recover") => void;
  onDelete: () => void;
  onSave: (patch: { maxConcurrentJobs: number; proxyEnabled: boolean; proxyUrl: string }) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [maxConcurrentJobs, setMaxConcurrentJobs] = useState(account.settings?.max_concurrent_jobs ?? 1);
  const [proxyEnabled, setProxyEnabled] = useState(Boolean(account.proxy_enabled));
  const [proxyUrl, setProxyUrl] = useState(account.proxy_url || "");
  const vncUrl =
    account.vnc_web_url && !account.vnc_web_url.includes("127.0.0.1")
      ? account.vnc_web_url
      : account.vnc_web_port
        ? `http://${publicHost}:${account.vnc_web_port}/vnc.html?autoconnect=1&resize=remote`
        : null;
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="break-all font-semibold">{account.id}</span>
            <span className={cls("rounded-md px-2 py-1 text-xs font-medium", account.status === "READY" ? "bg-emerald-50 text-emerald-700" : "bg-amber-50 text-amber-700")}>{account.status}</span>
            <span className={cls("rounded-md px-2 py-1 text-xs font-medium", runtime.flowkit?.connected ? "bg-blue-50 text-blue-700" : "bg-slate-100 text-slate-600")}>FlowKit {runtime.flowkit?.connected ? "connected" : "unknown"}</span>
            {runtime.auth_required && <span className="rounded-md bg-red-50 px-2 py-1 text-xs font-medium text-red-700">login needed</span>}
          </div>
          <p className="mt-1 break-all text-xs text-slate-500">{account.profile_path || "profile path unavailable"}</p>
        </div>
        {vncUrl && (
          <a className="command-button" href={vncUrl} target="_blank" rel="noreferrer">
            <Network size={16} />
            Open VNC
          </a>
        )}
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        <button type="button" className="command-button" disabled={busy} onClick={() => setEditing(!editing)}>{editing ? "Cancel edit" : "Edit settings"}</button>
        <button type="button" className="command-button" disabled={busy} onClick={() => onAction("start")}>Start</button>
        <button type="button" className="command-button" disabled={busy} onClick={() => onAction("stop")}>Stop</button>
        <button type="button" className="command-button" disabled={busy} onClick={() => onAction("restart")}>Restart</button>
        <button type="button" className="command-button" disabled={busy} onClick={() => onAction("recover")}>Recover</button>
        <button type="button" className="command-button text-red-600 hover:border-red-200 hover:bg-red-50" disabled={busy} onClick={onDelete}>
          <Trash2 size={16} />
          Remove account
        </button>
      </div>
      {editing && (
        <div className="mt-3 grid gap-3 rounded-lg border border-slate-200 bg-slate-50 p-3">
          <div className="grid gap-2 md:grid-cols-[160px_1fr]">
            <Field label="Max jobs">
              <input className="input" type="number" min={1} max={10} value={maxConcurrentJobs} onChange={(event) => setMaxConcurrentJobs(Number(event.target.value))} />
            </Field>
            <Field label="Proxy URL">
              <input className="input" value={proxyUrl} onChange={(event) => setProxyUrl(event.target.value)} disabled={!proxyEnabled} placeholder="http://user:pass@host:8080" />
            </Field>
          </div>
          <label className="flex items-center justify-between rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm">
            <span className="font-medium text-slate-700">Proxy enabled</span>
            <input type="checkbox" checked={proxyEnabled} onChange={(event) => setProxyEnabled(event.target.checked)} />
          </label>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              className="primary-button"
              disabled={busy}
              onClick={() => {
                onSave({ maxConcurrentJobs, proxyEnabled, proxyUrl });
                setEditing(false);
              }}
            >
              Save account settings
            </button>
            <button
              type="button"
              className="command-button"
              disabled={busy}
              onClick={() => {
                setMaxConcurrentJobs(account.settings?.max_concurrent_jobs ?? 1);
                setProxyEnabled(Boolean(account.proxy_enabled));
                setProxyUrl(account.proxy_url || "");
                setEditing(false);
              }}
            >
              Cancel
            </button>
          </div>
        </div>
      )}
      <div className="mt-3 grid gap-2 text-xs text-slate-600 sm:grid-cols-2 lg:grid-cols-4">
        <Info label="Health" value={String(account.health_score)} compact />
        <Info label="Running jobs" value={`${account.jobs_running}/${account.settings?.max_concurrent_jobs ?? 1}`} compact />
        <Info label="Display" value={account.display || runtime.display || "-"} compact />
        <Info label="Chrome PID" value={String(account.browser_pid ?? runtime.pid ?? "-")} compact />
        <Info label="VNC port" value={String(account.vnc_port ?? runtime.vnc_port ?? "-")} compact />
        <Info label="noVNC port" value={String(account.vnc_web_port ?? "-")} compact />
        <Info label="Debug port" value={String(account.remote_debugging_port ?? runtime.debug_port ?? "-")} compact />
        <Info label="Proxy" value={account.proxy_enabled ? account.proxy_url || "enabled" : "off"} compact />
        <Info label="Current URL" value={runtime.current_url || "-"} compact />
        <Info label="Flow token" value={runtime.flowkit?.flow_key_present ? "present" : "missing"} compact />
      </div>
    </div>
  );
}

function publicHostForWorker(worker: Worker | null) {
  try {
    const host = new URL(worker?.base_url || "").hostname;
    if (host && host !== "127.0.0.1" && host !== "localhost") return host;
  } catch {
    return DEFAULT_PUBLIC_VPS_HOST;
  }
  return DEFAULT_PUBLIC_VPS_HOST;
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <label className="grid gap-1.5 text-sm"><span className="font-medium text-slate-700">{label}</span>{children}</label>;
}

function Info({ label, value, compact }: { label: string; value: string; compact?: boolean }) {
  return (
    <div className={cls("rounded-lg bg-slate-50", compact ? "px-3 py-2" : "p-3")}>
      <div className="text-[11px] font-medium uppercase text-slate-400">{label}</div>
      <div className="mt-1 break-all text-sm font-semibold text-slate-800">{value}</div>
    </div>
  );
}

function Status({ ok, label }: { ok: boolean; label: string }) {
  return <span className={cls("inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-sm font-medium", ok ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-red-200 bg-red-50 text-red-700")}>{ok ? <CheckCircle2 size={16} /> : <AlertCircle size={16} />}{label}</span>;
}

function Empty({ text }: { text: string }) {
  return <div className="rounded-lg border border-dashed border-slate-200 bg-slate-50 px-6 py-10 text-center text-sm text-slate-500">{text}</div>;
}
