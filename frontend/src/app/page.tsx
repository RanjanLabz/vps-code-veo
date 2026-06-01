"use client";

import {
  Activity,
  AlertCircle,
  AppWindow,
  ArrowRight,
  Bot,
  BrainCircuit,
  CheckCircle2,
  Clock3,
  Copy,
  ExternalLink,
  Image as ImageIcon,
  KeyRound,
  ListTodo,
  Loader2,
  Monitor,
  Network,
  Plus,
  PlayCircle,
  Radio,
  RefreshCcw,
  Route,
  Timer,
  Send,
  Server,
  Settings2,
  Trash2,
  Users,
} from "lucide-react";
import Link from "next/link";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { storedToken } from "@/lib/adminAuth";

type GenerationType = "text_to_image" | "image_to_image" | "text_to_video" | "image_to_video";

type FlowSetting = {
  model?: string;
  duration?: number;
  estimated_credits?: number;
  presets?: Record<string, unknown>;
};

type FlowSettings = Record<GenerationType, FlowSetting>;

type ModelOption = {
  model: string;
  duration?: number;
  estimated_credits?: number;
};

type ModelCatalog = Record<GenerationType, ModelOption[]>;

type Metrics = {
  total_jobs: number;
  completed_jobs: number;
  failed_jobs: number;
  active_jobs: number;
  global_queue_depth: number;
  requested_last_15m: number;
  requested_last_1h: number;
  avg_total_job_seconds?: number | null;
  avg_wait_seconds?: number | null;
  avg_global_queue_seconds?: number | null;
  avg_local_account_queue_seconds?: number | null;
  avg_queue_to_account_seconds?: number | null;
  avg_processing_seconds?: number | null;
  total_job_seconds: number;
  total_wait_seconds: number;
  total_global_queue_seconds: number;
  total_local_account_queue_seconds: number;
  total_queue_to_account_seconds: number;
  total_processing_seconds: number;
  free_account_slots: number;
  workers_online: number;
  workers_total: number;
  recommendations: string[];
  by_state: Record<string, number>;
  by_type: Record<string, number>;
};

type BrowserStatus = {
  running?: boolean;
  current_url?: string;
  auth_required?: boolean;
  flowkit?: {
    connected?: boolean;
    flow_key_present?: boolean;
    pending?: number;
  };
};

type Worker = {
  id: string;
  base_url: string;
  enabled: boolean;
  max_jobs: number;
  weight: number;
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

type CapacitySnapshot = {
  vps_id: string;
  enabled: boolean;
  online: boolean;
  accounts_ready?: number;
  accounts_busy?: number;
  capacity_remaining: number;
  queue_size?: number;
  active_jobs?: number;
  cpu?: number;
  ram?: number;
  health_score?: number;
  reason: string;
};

type JobProgress = {
  phase: string;
  percent: number;
  percent_source: "estimated" | "native";
  veo_native_percent?: number | null;
  veo_native_percent_available?: boolean;
  message: string;
  elapsed_seconds: number;
  queue_position?: number | null;
  estimated_queue_seconds?: number | null;
  eta_seconds?: number | null;
  updated_at?: string;
  user_visible?: boolean;
};

type Job = {
  id: string;
  prompt: string;
  generation_type: GenerationType;
  flow_settings: FlowSetting;
  production_defaults_used: boolean;
  preferred_worker_id?: string | null;
  preferred_account_id?: string | null;
  assigned_worker_id?: string | null;
  worker_job_id?: string | null;
  state: string;
  retries: number;
  max_retries: number;
  created_at: string;
  assigned_at?: string | null;
  completed_at?: string | null;
  last_error?: string | null;
  routing_status?: string;
  progress?: JobProgress;
  capacity_snapshot?: CapacitySnapshot[];
  payload?: {
    worker_result?: WorkerResult;
    [key: string]: unknown;
  };
  timeline?: Record<string, string>;
  live_worker_job?: WorkerResult;
};

type EventTone = "done" | "active" | "waiting" | "failed" | "blocked";

type FlowEvent = {
  title: string;
  detail: string;
  tone: EventTone;
  icon: React.ReactNode;
  at?: string | null;
};

type WorkerResult = {
  id?: string;
  state?: string;
  account_id?: string | null;
  assigned_account_id?: string | null;
  retries?: number;
  max_retries?: number;
  output_urls?: string[];
  outputs?: string[];
  last_error?: string | null;
  browser_url?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  timeline?: Record<string, string>;
  payload?: {
    flowkit_result?: {
      project_id?: string;
      image_media_id?: string;
      video_media_id?: string;
    };
  };
};

type AdminUser = {
  email: string;
  name?: string;
  status: "approved" | "pending" | "blocked";
  role?: string;
  super_admin?: boolean;
  last_seen_at?: string;
  updated_at?: string;
};

const API = "/api/orchestrator";
const DEFAULT_WORKER_PUBLIC_BASE = process.env.NEXT_PUBLIC_WORKER_PUBLIC_BASE || "";

const GENERATION_TYPES: Array<{ value: GenerationType; label: string }> = [
  { value: "text_to_image", label: "Text to Image" },
  { value: "image_to_image", label: "Image to Image" },
  { value: "text_to_video", label: "Text to Video" },
  { value: "image_to_video", label: "Image to Video" },
];

const EMPTY_SETTINGS: FlowSettings = {
  text_to_image: {},
  image_to_image: {},
  text_to_video: {},
  image_to_video: {},
};

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

async function adminApi<T>(path: string, init?: RequestInit): Promise<T> {
  const token = storedToken();
  const response = await fetch(`/api/admin${path}`, {
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

function browserStatuses(worker: Worker): BrowserStatus[] {
  return Object.values(worker.status?.raw_health?.browser_status || {});
}

function flowkitConnectedCount(worker: Worker) {
  return browserStatuses(worker).filter((status) => status.flowkit?.connected).length;
}

function authRequiredCount(worker: Worker) {
  return browserStatuses(worker).filter((status) => status.auth_required).length;
}

function workerResult(job: Job): WorkerResult | undefined {
  return job.live_worker_job || job.payload?.worker_result;
}

function outputUrls(result?: WorkerResult) {
  return result?.output_urls || result?.outputs || [];
}

function modelOptionLabel(option: ModelOption) {
  const parts = [option.model];
  if (option.duration) parts.push(`${option.duration}s`);
  if (option.estimated_credits !== undefined) parts.push(`${option.estimated_credits} points`);
  return parts.join(" | ");
}

function modelOptionKey(option: ModelOption) {
  return `${option.model}::${option.duration ?? ""}::${option.estimated_credits ?? ""}`;
}

function currentModelKey(setting: FlowSetting) {
  return modelOptionKey({
    model: setting.model || "",
    duration: setting.duration,
    estimated_credits: setting.estimated_credits,
  });
}

function isVideoOutput(job: Job, url: string) {
  return job.generation_type.includes("video") || /\.(mp4|webm|mov)(\?|$)/i.test(url) || url.includes("/video/");
}

function outputUrlForBrowser(url: string) {
  if (url.startsWith("/media/")) return `${DEFAULT_WORKER_PUBLIC_BASE}${url}`;
  return url;
}

function parseTime(value?: string | null) {
  if (!value) return null;
  const time = new Date(value).getTime();
  return Number.isFinite(time) ? time : null;
}

function durationLabel(ms: number) {
  const total = Math.max(0, Math.floor(ms / 1000));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  if (hours > 0) return `${hours}h ${minutes}m`;
  if (minutes > 0) return `${minutes}m ${seconds}s`;
  return `${seconds}s`;
}

function timeLabel(value?: string | null) {
  const parsed = parseTime(value);
  if (!parsed) return "time pending";
  return new Intl.DateTimeFormat(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(parsed);
}

function jobStartedAt(job: Job) {
  const local = workerResult(job);
  return parseTime(local?.started_at) || parseTime(job.assigned_at) || parseTime(job.created_at) || Date.now();
}

function jobQueuedAt(job: Job) {
  return parseTime(job.created_at) || Date.now();
}

function jobVerdict(job: Job) {
  const local = workerResult(job);
  const urls = outputUrls(local);
  if (job.state === "COMPLETED" && urls.length > 0) return { label: "OUTPUT READY", tone: "green" as const };
  if (job.state === "COMPLETED") return { label: "COMPLETED, NO OUTPUT", tone: "amber" as const };
  if (job.state === "FAILED" || job.state === "TIMEOUT") return { label: job.state, tone: "red" as const };
  if (local?.state) return { label: `WORKER ${local.state}`, tone: "amber" as const };
  return { label: job.state, tone: "amber" as const };
}

function eventToneClass(tone: EventTone) {
  if (tone === "done") return "border-emerald-200 bg-emerald-50 text-emerald-800";
  if (tone === "active") return "border-blue-200 bg-blue-50 text-blue-800";
  if (tone === "failed") return "border-red-200 bg-red-50 text-red-800";
  if (tone === "blocked") return "border-amber-200 bg-amber-50 text-amber-900";
  return "border-slate-200 bg-slate-50 text-slate-600";
}

function eventDotClass(tone: EventTone) {
  if (tone === "done") return "bg-emerald-500";
  if (tone === "active") return "bg-blue-500";
  if (tone === "failed") return "bg-red-500";
  if (tone === "blocked") return "bg-amber-500";
  return "bg-slate-300";
}

function jobEvents(job: Job): FlowEvent[] {
  const local = workerResult(job);
  const globalTimeline = job.timeline || {};
  const localTimeline = local?.timeline || {};
  const urls = outputUrls(local);
  const terminalFailed = job.state === "FAILED" || job.state === "TIMEOUT";
  const completed = job.state === "COMPLETED";
  const assigned = Boolean(job.assigned_worker_id);
  const localAccepted = Boolean(job.worker_job_id || local?.id);
  const account = local?.account_id || local?.assigned_account_id || job.preferred_account_id || "";
  const hasAccount = Boolean(account);
  const browser = local?.browser_url || "";
  const localState = local?.state || "";
  const authError = `${job.last_error || ""} ${local?.last_error || ""}`.toLowerCase().includes("login") || `${job.last_error || ""} ${local?.last_error || ""}`.toLowerCase().includes("auth");

  const events: FlowEvent[] = [
    {
      title: "API request",
      detail: job.prompt,
      tone: "done",
      icon: <Send size={16} />,
      at: globalTimeline.api_received || job.created_at,
    },
    {
      title: "Global queue",
      detail: job.assigned_worker_id ? "Job left the global queue" : job.routing_status === "waiting_for_vps" ? "Waiting for a VPS/account slot" : "Queued for scheduler",
      tone: job.assigned_worker_id ? "done" : terminalFailed ? "failed" : "active",
      icon: <Network size={16} />,
      at: globalTimeline.global_queued || job.created_at,
    },
    {
      title: "VPS routing",
      detail: job.assigned_worker_id || job.capacity_snapshot?.map((item) => `${item.vps_id}: ${item.reason}`).join(" | ") || "Not assigned yet",
      tone: assigned ? "done" : terminalFailed ? "failed" : "waiting",
      icon: <Server size={16} />,
      at: globalTimeline.vps_selected || job.assigned_at,
    },
    {
      title: "Local worker queue",
      detail: job.worker_job_id || local?.id || "Waiting for selected VPS to accept",
      tone: localAccepted ? "done" : assigned ? "active" : "waiting",
      icon: <Route size={16} />,
      at: globalTimeline.worker_accepted || localTimeline.local_queued,
    },
    {
      title: "Account selection",
      detail: account || "Waiting for local account scheduler",
      tone: hasAccount ? "done" : localAccepted ? "active" : "waiting",
      icon: <Bot size={16} />,
      at: localTimeline.account_selected,
    },
    {
      title: "Browser + FlowKit",
      detail: browser || (authError ? "Google login/auth action required in VNC" : "Waiting for Chrome/FlowKit session"),
      tone: authError ? "blocked" : browser ? "done" : hasAccount ? "active" : "waiting",
      icon: authError ? <KeyRound size={16} /> : <AppWindow size={16} />,
      at: localTimeline.browser_ready || localTimeline.flowkit_request_started || localTimeline.browser_recovery_started,
    },
    {
      title: "Google Flow execution",
      detail: localState ? `Worker state: ${localState}` : completed ? "Generation completed" : terminalFailed ? job.last_error || local?.last_error || "Execution failed" : "Waiting for Flow response",
      tone: completed ? "done" : terminalFailed ? "failed" : hasAccount ? "active" : "waiting",
      icon: <BrainCircuit size={16} />,
      at: localTimeline.executor_started || localTimeline.prompt_submitted || local?.started_at,
    },
    {
      title: "Output",
      detail: urls.length > 0 ? `${urls.length} output URL${urls.length === 1 ? "" : "s"} returned` : completed ? "Completed but no output URL returned" : "No output yet",
      tone: urls.length > 0 ? "done" : completed ? "blocked" : terminalFailed ? "failed" : "waiting",
      icon: <ImageIcon size={16} />,
      at: localTimeline.output_detected || localTimeline.local_completed || globalTimeline.global_completed || job.completed_at,
    },
  ];

  return events;
}

function eventDelta(events: FlowEvent[], index: number) {
  const current = parseTime(events[index]?.at);
  if (!current) return null;
  for (let prev = index - 1; prev >= 0; prev -= 1) {
    const previous = parseTime(events[prev]?.at);
    if (previous) return durationLabel(current - previous);
  }
  return null;
}

async function copyText(text: string) {
  await navigator.clipboard.writeText(text);
}

export default function Home() {
  const [workers, setWorkers] = useState<Worker[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [flowSettings, setFlowSettings] = useState<FlowSettings>(EMPTY_SETTINGS);
  const [modelCatalog, setModelCatalog] = useState<ModelCatalog>({
    text_to_image: [],
    image_to_image: [],
    text_to_video: [],
    image_to_video: [],
  });
  const [adminUsers, setAdminUsers] = useState<AdminUser[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [now, setNow] = useState(() => Date.now());

  const [workerId, setWorkerId] = useState("vps-1");
  const [workerUrl, setWorkerUrl] = useState("");
  const [workerMaxJobs, setWorkerMaxJobs] = useState(10);
  const [workerWeight, setWorkerWeight] = useState(100);
  const [workerEnabled, setWorkerEnabled] = useState(true);

  const [generationType, setGenerationType] = useState<GenerationType>("text_to_image");
  const [prompt, setPrompt] = useState("cinematic Tokyo rain street");
  const [preferredWorkerId, setPreferredWorkerId] = useState("");
  const [preferredAccountId, setPreferredAccountId] = useState("");
  const [resetPasswords, setResetPasswords] = useState<Record<string, string>>({});

  const selectedGlobalSetting = flowSettings[generationType] || {};

  const fleet = useMemo(() => {
    const online = workers.filter((worker) => worker.status?.online).length;
    const accounts = workers.reduce((sum, worker) => sum + (worker.status?.accounts_total || 0), 0);
    const freeSlots = workers.reduce((sum, worker) => sum + (worker.status?.accounts_ready || 0), 0);
    const localQueues = workers.reduce((sum, worker) => sum + (worker.status?.queue_size || 0), 0);
    const flowkit = workers.reduce((sum, worker) => sum + flowkitConnectedCount(worker), 0);
    const authNeeded = workers.reduce((sum, worker) => sum + authRequiredCount(worker), 0);
    return { online, accounts, freeSlots, localQueues, flowkit, authNeeded };
  }, [workers]);

  const globalQueued = jobs.filter((job) => ["QUEUED", "RETRYING"].includes(job.state) && !job.assigned_worker_id).length;
  const activeDispatches = jobs.filter((job) => ["ASSIGNED", "PROCESSING", "RETRYING"].includes(job.state)).length;
  const activeJob = jobs.find((job) => ["ASSIGNED", "PROCESSING", "RETRYING"].includes(job.state));
  const queueJobs = jobs.filter((job) => ["QUEUED", "RETRYING"].includes(job.state) && !job.assigned_worker_id);

  async function refresh(silent = false) {
    if (!silent) setBusy("Refreshing");
    try {
      const [nextWorkers, nextJobs, nextSettings, nextMetrics, nextCatalog, nextAdminUsers] = await Promise.all([
        api<Worker[]>("/workers"),
        api<Job[]>("/jobs?limit=50"),
        api<FlowSettings>("/flow-settings"),
        api<Metrics>("/metrics"),
        api<ModelCatalog>("/flow-models"),
        adminApi<{ users: AdminUser[] }>("/access").then((value) => value.users).catch(() => []),
      ]);
      setWorkers(nextWorkers);
      setJobs(nextJobs);
      setFlowSettings({ ...EMPTY_SETTINGS, ...nextSettings });
      setModelCatalog(nextCatalog);
      setMetrics(nextMetrics);
      setAdminUsers(nextAdminUsers);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load orchestrator");
    } finally {
      setBusy(null);
    }
  }

  useEffect(() => {
    const boot = window.setTimeout(() => refresh(), 0);
    const id = window.setInterval(() => refresh(true), 10000);
    const clock = window.setInterval(() => setNow(Date.now()), 1000);
    return () => {
      window.clearTimeout(boot);
      window.clearInterval(id);
      window.clearInterval(clock);
    };
  }, []);

  function editWorker(worker: Worker) {
    setWorkerId(worker.id);
    setWorkerUrl(worker.base_url);
    setWorkerMaxJobs(worker.max_jobs);
    setWorkerWeight(worker.weight);
    setWorkerEnabled(worker.enabled);
    setNotice(`Editing ${worker.id}`);
  }

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

  async function saveWorker(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await run("VPS saved", () =>
      api("/workers", {
        method: "POST",
        body: JSON.stringify({
          id: workerId.trim(),
          base_url: workerUrl.trim(),
          max_jobs: workerMaxJobs,
          weight: workerWeight,
          enabled: workerEnabled,
        }),
      }),
    );
  }

  async function toggleWorker(worker: Worker) {
    await run(worker.enabled ? "VPS disabled" : "VPS enabled", () =>
      api("/workers", {
        method: "POST",
        body: JSON.stringify({
          id: worker.id,
          base_url: worker.base_url,
          max_jobs: worker.max_jobs,
          weight: worker.weight,
          enabled: !worker.enabled,
        }),
      }),
    );
  }

  async function deleteWorker(worker: Worker) {
    await run("VPS removed", () => api(`/workers/${encodeURIComponent(worker.id)}`, { method: "DELETE" }));
  }

  async function submitGeneration(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const body: Record<string, unknown> = {
      prompt,
      metadata: { source: "admin-test-panel" },
    };
    if (preferredWorkerId) body.preferred_worker_id = preferredWorkerId;
    if (preferredAccountId.trim()) body.preferred_account_id = preferredAccountId.trim();
    await run("Generation queued", () =>
      api(`/generate/${generationType.replaceAll("_", "-")}`, {
        method: "POST",
        body: JSON.stringify(body),
      }),
    );
  }

  async function updateFlowModel(type: GenerationType, key: string) {
    const selected = modelCatalog[type].find((option) => modelOptionKey(option) === key);
    if (!selected) return;
    await run("Flow model updated", () =>
      api("/flow-settings", {
        method: "PATCH",
        body: JSON.stringify({
          [type]: {
            model: selected.model,
            duration: selected.duration ?? null,
            estimated_credits: selected.estimated_credits ?? 0,
          },
        }),
      }),
    );
  }

  async function updateAdminAccess(email: string, status: AdminUser["status"]) {
    await run(`Admin ${status}`, () =>
      adminApi("/access", {
        method: "POST",
        body: JSON.stringify({ email, status, role: status === "approved" ? "admin" : "viewer" }),
      }),
    );
  }

  async function resetAdminPassword(email: string) {
    const password = resetPasswords[email] || "";
    if (password.length < 8) {
      setError("Reset password must be at least 8 characters.");
      return;
    }
    await run("Admin password reset", () =>
      adminApi("/access/reset-password", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      }),
    );
    setResetPasswords((current) => ({ ...current, [email]: "" }));
  }

  return (
    <main className="min-h-screen bg-[#f6f7f9] text-slate-950">
      <div className="mx-auto flex min-h-screen w-full max-w-[1500px] flex-col px-4 py-4 sm:px-6 lg:px-8">
        <header className="flex flex-col gap-4 border-b border-slate-200 pb-4 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex items-center gap-3">
            <div className="flex size-11 items-center justify-center rounded-lg bg-slate-950 text-white">
              <Network size={22} />
            </div>
            <div>
              <h1 className="text-2xl font-semibold tracking-normal">Flow Orchestrator</h1>
              <p className="text-sm text-slate-500">Multi-VPS fleet, FlowKit account workers, global queue routing, and internal generation tests.</p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Status ok={fleet.online > 0} label={`${fleet.online}/${workers.length} VPS online`} />
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

        <section className="mt-5 grid gap-3 md:grid-cols-4">
          <Metric icon={<Server size={18} />} label="VPS online" value={`${fleet.online}/${workers.length}`} />
          <Metric icon={<Users size={18} />} label="Free account slots" value={`${fleet.freeSlots}/${fleet.accounts}`} />
          <Metric icon={<Clock3 size={18} />} label="Global queued" value={String(globalQueued)} />
          <Metric icon={<Route size={18} />} label="Active dispatches" value={String(activeDispatches)} />
        </section>

        <div className="mt-5 grid gap-5 xl:grid-cols-[420px_minmax(0,1fr)]">
          <aside className="grid content-start gap-5">
            <Panel title="Add or Update VPS">
              <form className="grid gap-3" onSubmit={saveWorker}>
                <Field label="VPS ID">
                  <input className="input" value={workerId} onChange={(event) => setWorkerId(event.target.value)} placeholder="vps-2" />
                </Field>
                <Field label="VPS worker API URL">
                  <input className="input" value={workerUrl} onChange={(event) => setWorkerUrl(event.target.value)} placeholder="http://vps-ip:8080" />
                </Field>
                <div className="grid gap-3 sm:grid-cols-2">
                  <Field label="Max VPS jobs">
                    <input className="input" type="number" min={1} max={100} value={workerMaxJobs} onChange={(event) => setWorkerMaxJobs(Number(event.target.value))} />
                  </Field>
                  <Field label="Routing weight">
                    <input className="input" type="number" min={1} max={1000} value={workerWeight} onChange={(event) => setWorkerWeight(Number(event.target.value))} />
                  </Field>
                </div>
                <label className="flex items-center justify-between rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm">
                  <span className="font-medium text-slate-700">Enabled for global scheduler</span>
                  <input type="checkbox" checked={workerEnabled} onChange={(event) => setWorkerEnabled(event.target.checked)} />
                </label>
                <button className="primary-button" disabled={Boolean(busy)}>
                  {busy === "VPS saved" ? <Loader2 size={17} className="animate-spin" /> : <Plus size={17} />}
                  Save VPS node
                </button>
              </form>
            </Panel>

            <Panel title="Admin Access">
              <div className="grid gap-3">
                <div className="rounded-lg border border-slate-200 bg-white p-3 text-sm text-slate-600">
                  Email/password sign-in is required. New users appear here as pending after signup.
                </div>
                {adminUsers.length === 0 ? (
                  <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm text-slate-500">No access records yet.</div>
                ) : (
                  adminUsers.map((user) => (
                    <div key={user.email} className="rounded-lg border border-slate-200 bg-white p-3">
                      <div className="truncate text-sm font-semibold text-slate-950">{user.email}</div>
                      <div className="mt-1 flex flex-wrap gap-2 text-xs text-slate-500">
                        <span className={cls("rounded-md px-2 py-0.5 font-semibold", user.status === "approved" ? "bg-emerald-50 text-emerald-700" : user.status === "blocked" ? "bg-red-50 text-red-700" : "bg-amber-50 text-amber-700")}>
                          {user.status}
                        </span>
                        {user.super_admin ? <span>super admin</span> : <span>{user.role || "viewer"}</span>}
                      </div>
                      {!user.super_admin && (
                        <div className="mt-3 grid gap-2">
                          <div className="grid grid-cols-3 gap-2">
                            <button className="command-button h-9 justify-center" onClick={() => updateAdminAccess(user.email, "approved")} disabled={Boolean(busy)}>
                              Approve
                            </button>
                            <button className="command-button h-9 justify-center" onClick={() => updateAdminAccess(user.email, "pending")} disabled={Boolean(busy)}>
                              Pending
                            </button>
                            <button className="command-button h-9 justify-center text-red-700" onClick={() => updateAdminAccess(user.email, "blocked")} disabled={Boolean(busy)}>
                              Block
                            </button>
                          </div>
                          <div className="grid gap-2 sm:grid-cols-[1fr_auto]">
                            <input
                              className="input h-9"
                              type="password"
                              placeholder="New password"
                              value={resetPasswords[user.email] || ""}
                              onChange={(event) => setResetPasswords((current) => ({ ...current, [user.email]: event.target.value }))}
                            />
                            <button className="command-button h-9 justify-center" onClick={() => resetAdminPassword(user.email)} disabled={Boolean(busy)}>
                              Reset
                            </button>
                          </div>
                        </div>
                      )}
                    </div>
                  ))
                )}
              </div>
            </Panel>

            <Panel title="Flow Model Policy">
              <div className="grid gap-3">
                {GENERATION_TYPES.map((item) => {
                  const setting = flowSettings[item.value] || {};
                  const options = modelCatalog[item.value] || [];
                  return (
                    <Field key={item.value} label={item.label}>
                      <select
                        className="input"
                        value={currentModelKey(setting)}
                        onChange={(event) => updateFlowModel(item.value, event.target.value)}
                        disabled={Boolean(busy) || options.length === 0}
                      >
                        {setting.model && !options.some((option) => modelOptionKey(option) === currentModelKey(setting)) && (
                          <option value={currentModelKey(setting)}>
                            {setting.model}{setting.duration ? ` | ${setting.duration}s` : ""}{setting.estimated_credits !== undefined ? ` | ${setting.estimated_credits} points` : ""}
                          </option>
                        )}
                        {options.map((option) => (
                          <option key={modelOptionKey(option)} value={modelOptionKey(option)}>
                            {modelOptionLabel(option)}
                          </option>
                        ))}
                      </select>
                    </Field>
                  );
                })}
                <div className="rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-xs leading-5 text-blue-900">
                  These are production defaults used by API jobs. Tests do not override them; change the policy here before sending jobs.
                </div>
              </div>
            </Panel>

            <Panel title="Generation Test">
              <form className="grid gap-3" onSubmit={submitGeneration}>
                <Field label="API type">
                  <select className="input" value={generationType} onChange={(event) => setGenerationType(event.target.value as GenerationType)}>
                    {GENERATION_TYPES.map((item) => (
                      <option key={item.value} value={item.value}>{item.label}</option>
                    ))}
                  </select>
                </Field>
                <Field label="Production default">
                  <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm font-semibold text-emerald-800">
                    {selectedGlobalSetting.model || "No model set"}{selectedGlobalSetting.duration ? ` | ${selectedGlobalSetting.duration}s` : ""}{selectedGlobalSetting.estimated_credits !== undefined ? ` | ${selectedGlobalSetting.estimated_credits} points` : ""}
                  </div>
                </Field>
                <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs leading-5 text-slate-600">
                  This page sends a normal production-style API request. Model selection comes from configured Flow settings, so tests cannot silently override the model.
                </div>
                <Field label="Prompt">
                  <textarea className="input min-h-24 py-2" value={prompt} onChange={(event) => setPrompt(event.target.value)} />
                </Field>
                <Field label="Preferred VPS for test only">
                  <select className="input" value={preferredWorkerId} onChange={(event) => setPreferredWorkerId(event.target.value)}>
                    <option value="">Auto route across all VPS</option>
                    {workers.map((worker) => (
                      <option key={worker.id} value={worker.id}>{worker.id}</option>
                    ))}
                  </select>
                </Field>
                <Field label="Preferred account for test only">
                  <input className="input" value={preferredAccountId} onChange={(event) => setPreferredAccountId(event.target.value)} placeholder="leave blank for account scheduler" />
                </Field>
                <button className="primary-button" disabled={Boolean(busy) || !prompt.trim()}>
                  {busy === "Generation queued" ? <Loader2 size={17} className="animate-spin" /> : <Send size={17} />}
                  Queue through global scheduler
                </button>
              </form>
            </Panel>
          </aside>

          <section className="grid content-start gap-5">
            <Panel title="Capacity Metrics">
              <MetricsBoard metrics={metrics} />
            </Panel>

            <Panel title="API Docs">
              <ApiDocs selectedType={generationType} />
            </Panel>

            <Panel title="VPS Fleet">
              <div className="mb-4 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-800">
                User API requests enter the global queue first. The scheduler checks every VPS, chooses a healthy VPS with free account capacity, then the selected VPS chooses the account. Use the VPS page to add or remove accounts inside that node.
              </div>
              {workers.length === 0 ? (
                <Empty text="No VPS nodes are registered yet. Add the first VPS worker from the form on the left." />
              ) : (
                <div className="grid gap-3 xl:grid-cols-2">
                  {workers.map((worker) => (
                    <WorkerCard
                      key={worker.id}
                      worker={worker}
                      busy={Boolean(busy)}
                      onEdit={() => editWorker(worker)}
                      onToggle={() => toggleWorker(worker)}
                      onDelete={() => deleteWorker(worker)}
                    />
                  ))}
                </div>
              )}
            </Panel>

            <Panel title="Now Processing">
              <OperationsBoard activeJob={activeJob} queueJobs={queueJobs} now={now} />
            </Panel>

            <Panel title="Live Event Map">
              <SystemEventMap jobs={jobs} fleet={fleet} />
            </Panel>

            <Panel title="Global Queue">
              <div className="grid gap-3">
                {jobs.length === 0 && <Empty text="No jobs found in the global queue." />}
                {jobs.slice(0, 12).map((job) => (
                  <JobCard key={job.id} job={job} />
                ))}
              </div>
            </Panel>
          </section>
        </div>
      </div>
    </main>
  );
}

function WorkerCard({
  worker,
  busy,
  onEdit,
  onToggle,
  onDelete,
}: {
  worker: Worker;
  busy: boolean;
  onEdit: () => void;
  onToggle: () => void;
  onDelete: () => void;
}) {
  const status = worker.status;
  const connected = flowkitConnectedCount(worker);
  const authNeeded = authRequiredCount(worker);
  const capacityRemaining = Math.min(status?.accounts_ready ?? 0, Math.max(0, worker.max_jobs - (status?.active_jobs ?? 0)));
  return (
    <article className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <button className="min-w-0 text-left" type="button" onClick={onEdit}>
          <div className="flex flex-wrap items-center gap-2">
            <span className="break-all text-base font-semibold">{worker.id}</span>
            <StatusPill ok={Boolean(status?.online)} label={status?.online ? "online" : "offline"} />
            <StatusPill ok={worker.enabled} label={worker.enabled ? "enabled" : "disabled"} />
          </div>
          <p className="mt-1 break-all text-xs text-slate-500">{worker.base_url}</p>
        </button>
        <Link className="command-button shrink-0" href={`/vps?id=${encodeURIComponent(worker.id)}`}>
          <Server size={16} />
          Open VPS page
        </Link>
      </div>

      <div className="mt-4 grid gap-2 text-xs sm:grid-cols-3">
        <Info label="Accounts" value={`${status?.accounts_ready ?? 0} ready / ${status?.accounts_total ?? 0} total`} compact />
        <Info label="Free slots" value={String(capacityRemaining)} compact />
        <Info label="Busy accounts" value={String(status?.accounts_busy ?? 0)} compact />
        <Info label="Local queue" value={String(status?.queue_size ?? 0)} compact />
        <Info label="FlowKit connected" value={`${connected}/${status?.accounts_total ?? 0}`} compact />
        <Info label="Auth needed" value={String(authNeeded)} compact warning={authNeeded > 0} />
        <Info label="Active jobs" value={`${status?.active_jobs ?? 0}/${worker.max_jobs}`} compact />
        <Info label="CPU" value={`${Math.round(status?.cpu ?? 0)}%`} compact warning={(status?.cpu ?? 0) >= 92} />
        <Info label="RAM" value={`${Math.round(status?.ram ?? 0)}%`} compact warning={(status?.ram ?? 0) >= 92} />
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        <button type="button" className="command-button" onClick={onEdit} disabled={busy}>
          <Settings2 size={16} />
          Edit VPS
        </button>
        <button type="button" className="command-button" onClick={onToggle} disabled={busy}>
          {worker.enabled ? "Disable" : "Enable"}
        </button>
        <button type="button" className="command-button text-red-600 hover:border-red-200 hover:bg-red-50" onClick={onDelete} disabled={busy}>
          <Trash2 size={16} />
          Remove
        </button>
      </div>
      {status?.error && <p className="mt-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">{status.error}</p>}
    </article>
  );
}

function MetricsBoard({ metrics }: { metrics: Metrics | null }) {
  if (!metrics) return <Empty text="Metrics are loading from the orchestrator." />;
  const pressure =
    metrics.global_queue_depth > 0 && metrics.free_account_slots === 0
      ? "Queue blocked: no free account slots"
      : metrics.global_queue_depth > metrics.free_account_slots
        ? "Queue pressure rising"
        : "Capacity looks healthy";
  return (
    <div className="grid gap-4">
      <div className="grid gap-3 md:grid-cols-4">
        <Metric icon={<ListTodo size={18} />} label="Total jobs" value={String(metrics.total_jobs)} />
        <Metric icon={<Clock3 size={18} />} label="Avg queue to account" value={secondsMetric(metrics.avg_queue_to_account_seconds ?? metrics.avg_wait_seconds)} />
        <Metric icon={<Timer size={18} />} label="Avg total time" value={secondsMetric(metrics.avg_total_job_seconds)} />
        <Metric icon={<Users size={18} />} label="Free slots" value={String(metrics.free_account_slots)} />
      </div>
      <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <div className="text-sm font-semibold">Throughput and queue pressure</div>
              <p className="mt-1 text-xs text-slate-500">{pressure}</p>
            </div>
            <span className="rounded-lg bg-slate-100 px-3 py-2 text-xs font-semibold text-slate-700">
              {metrics.requested_last_15m} requests / 15m
            </span>
          </div>
          <div className="mt-4 grid gap-2 sm:grid-cols-3">
            <Info label="Requested last hour" value={String(metrics.requested_last_1h)} compact />
            <Info label="Queue depth" value={String(metrics.global_queue_depth)} compact warning={metrics.global_queue_depth > 0} />
            <Info label="Active jobs" value={String(metrics.active_jobs)} compact />
            <Info label="Completed" value={String(metrics.completed_jobs)} compact />
            <Info label="Failed" value={String(metrics.failed_jobs)} compact warning={metrics.failed_jobs > metrics.completed_jobs && metrics.failed_jobs > 0} />
            <Info label="Global queue to VPS" value={secondsMetric(metrics.avg_global_queue_seconds)} compact />
            <Info label="Local queue to account" value={secondsMetric(metrics.avg_local_account_queue_seconds)} compact />
            <Info label="Avg processing" value={secondsMetric(metrics.avg_processing_seconds)} compact />
            <Info label="Total job time" value={secondsMetric(metrics.total_job_seconds)} compact />
            <Info label="Total queue time" value={secondsMetric(metrics.total_queue_to_account_seconds || metrics.total_wait_seconds)} compact />
            <Info label="Workers online" value={`${metrics.workers_online}/${metrics.workers_total}`} compact />
          </div>
        </div>
        <div className="rounded-lg border border-slate-200 bg-slate-50 p-4">
          <div className="text-sm font-semibold">Scale guidance</div>
          {metrics.recommendations.length === 0 ? (
            <p className="mt-3 text-sm text-slate-500">No urgent scaling signal yet. Watch average wait time and queue depth as traffic grows.</p>
          ) : (
            <div className="mt-3 grid gap-2">
              {metrics.recommendations.map((item) => (
                <div key={item} className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs font-medium text-amber-900">
                  {item}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function ApiDocs({ selectedType }: { selectedType: GenerationType }) {
  const path = `/api/orchestrator/generate/${selectedType.replaceAll("_", "-")}`;
  const directPath = `${process.env.NEXT_PUBLIC_ORCHESTRATOR_PUBLIC_URL || "https://your-orchestrator.example.com"}/generate/${selectedType.replaceAll("_", "-")}`;
  const statusPath = "/api/orchestrator/jobs/{job_id}";
  const directStatusPath = `${process.env.NEXT_PUBLIC_ORCHESTRATOR_PUBLIC_URL || "https://your-orchestrator.example.com"}/jobs/{job_id}`;
  const body = `{\n  "prompt": "cinematic Tokyo rain street"\n}`;
  const curl = `curl -X POST ${directPath} \\\n  -H "content-type: application/json" \\\n  -d '${body.replaceAll("\n", "")}'`;
  const statusCurl = `curl ${directStatusPath}`;
  const submitResponse = `{
  "id": "gjob_...",
  "state": "QUEUED",
  "generation_type": "${selectedType}",
  "flow_settings": {
    "model": "veo-3.1-fast",
    "duration": 8,
    "estimated_credits": 160
  }
}`;
  const progressResponse = `{
  "id": "gjob_...",
  "state": "PROCESSING",
  "routing_status": "local_job_visible",
  "assigned_worker_id": "vps-1",
  "worker_job_id": "job_...",
  "live_worker_job": {
    "state": "PROCESSING",
    "account_id": "account@example.com",
    "output_urls": []
  },
  "progress": {
    "phase": "generating",
    "percent": 64,
    "percent_source": "estimated",
    "veo_native_percent_available": false,
    "message": "FlowKit/Google Flow generation is running.",
    "queue_position": null,
    "estimated_queue_seconds": null,
    "eta_seconds": 180,
    "elapsed_seconds": 240
  }
}`;
  return (
    <div className="grid gap-4">
      <div className="rounded-lg border border-slate-200 bg-slate-50 p-4">
        <div className="flex flex-col gap-2 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <div className="text-sm font-semibold">Production Integration Flow</div>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">
              Your app sends a generation request, stores the returned job id, then polls job status every 2-5 seconds. The response tells users where the job is, how long it has waited, estimated ETA, output URLs, and the exact failure if something blocks.
            </p>
          </div>
          <a className="command-button h-9" href={`${process.env.NEXT_PUBLIC_ORCHESTRATOR_PUBLIC_URL || "https://your-orchestrator.example.com"}/docs`} target="_blank" rel="noreferrer">
            <ExternalLink size={15} />
            Open FastAPI docs
          </a>
        </div>
        <div className="mt-4 grid gap-2 md:grid-cols-4">
          <Info label="1. Submit" value="POST /generate/*" compact />
          <Info label="2. Store" value="job id" compact />
          <Info label="3. Poll" value="GET /jobs/{id}" compact />
          <Info label="4. Render" value="progress + outputs" compact />
        </div>
      </div>

      <div className="grid gap-3 xl:grid-cols-2">
        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <div className="text-sm font-semibold">Submit Job</div>
          <p className="mt-2 text-sm text-slate-600">Use the localhost path from this admin app, or call the orchestrator directly from your backend.</p>
          <div className="mt-3 grid gap-2">
            <CodeLine label="Admin proxy" value={path} />
            <CodeLine label="Direct API" value={directPath} />
          </div>
          <div className="mt-3 flex items-center justify-between gap-2">
            <div className="text-xs font-semibold uppercase text-slate-500">Example curl</div>
            <button className="command-button h-8" type="button" onClick={() => copyText(curl)}>
              <Copy size={14} />
              Copy
            </button>
          </div>
          <pre className="mt-2 max-h-44 overflow-auto rounded-lg bg-slate-950 p-3 text-xs text-slate-100">{curl}</pre>
        </div>

        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <div className="text-sm font-semibold">Poll Job Status</div>
          <p className="mt-2 text-sm text-slate-600">Poll this endpoint until the job reaches `COMPLETED`, `FAILED`, or `TIMEOUT`.</p>
          <div className="mt-3 grid gap-2">
            <CodeLine label="Admin proxy" value={statusPath} />
            <CodeLine label="Direct API" value={directStatusPath} />
          </div>
          <div className="mt-3 flex items-center justify-between gap-2">
            <div className="text-xs font-semibold uppercase text-slate-500">Example curl</div>
            <button className="command-button h-8" type="button" onClick={() => copyText(statusCurl)}>
              <Copy size={14} />
              Copy
            </button>
          </div>
          <pre className="mt-2 max-h-44 overflow-auto rounded-lg bg-slate-950 p-3 text-xs text-slate-100">{statusCurl}</pre>
        </div>
      </div>

      <div className="grid gap-3 xl:grid-cols-2">
        <DocBlock
          title="Submit Response"
          body="The first response is only an acceptance receipt. Do not expect output here. Save `id` and start polling."
          code={submitResponse}
        />
        <DocBlock
          title="Status Response"
          body="This is the main response for your app UI. Use `progress`, `routing_status`, `live_worker_job`, and `output_urls`."
          code={progressResponse}
        />
      </div>

      <div className="grid gap-3 xl:grid-cols-3">
        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <div className="text-sm font-semibold">Progress Contract</div>
          <div className="mt-3 grid gap-2 text-sm text-slate-600">
            <DocRow name="phase" value="queued, vps_selected, local_queue, account_selected, generating, outputs_ready, completed, retrying, failed" />
            <DocRow name="percent" value="0-100 user-facing progress" />
            <DocRow name="percent_source" value="estimated for now" />
            <DocRow name="eta_seconds" value="estimated seconds until done" />
            <DocRow name="elapsed_seconds" value="total time since API received" />
            <DocRow name="message" value="safe user-facing status text" />
          </div>
        </div>

        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <div className="text-sm font-semibold">Queue Time</div>
          <p className="mt-2 text-sm leading-6 text-slate-600">
            `estimated_queue_seconds` means expected time until a free account accepts the job. It is not video generation time. `eta_seconds` includes queue wait plus expected processing time.
          </p>
          <div className="mt-3 grid gap-2 text-sm text-slate-600">
            <DocRow name="queue_position" value="position in global queue" />
            <DocRow name="estimated_queue_seconds" value="time to account slot" />
            <DocRow name="avg_queue_to_account_seconds" value="available from /metrics" />
          </div>
        </div>

        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <div className="text-sm font-semibold">Veo Percentage</div>
          <p className="mt-2 text-sm leading-6 text-slate-600">
            Google Flow/FlowKit is not currently returning a native Veo percentage. The API exposes this honestly as `veo_native_percent_available: false`; use `progress.percent` for UI.
          </p>
          <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-800">
            If FlowKit later exposes native progress, keep the same app UI and switch when `percent_source` becomes `native`.
          </div>
        </div>
      </div>

      <div className="grid gap-3 xl:grid-cols-2">
        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <div className="text-sm font-semibold">Job States</div>
          <div className="mt-3 grid gap-2 text-sm text-slate-600">
            <DocRow name="QUEUED" value="waiting in global orchestrator queue" />
            <DocRow name="ASSIGNED" value="VPS selected, dispatch in progress" />
            <DocRow name="PROCESSING" value="worker accepted, local execution running" />
            <DocRow name="RETRYING" value="temporary failure, retry delay active" />
            <DocRow name="COMPLETED" value="output_urls should be available" />
            <DocRow name="FAILED / TIMEOUT" value="show last_error and support retry" />
          </div>
        </div>

        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <div className="text-sm font-semibold">Output Handling</div>
          <p className="mt-2 text-sm leading-6 text-slate-600">
            For images, output URLs may be Google Flow image links. For videos, the worker can return `/media/videos/file.mp4`; convert relative URLs to the worker base URL before rendering.
          </p>
          <pre className="mt-3 max-h-40 overflow-auto rounded-lg bg-slate-950 p-3 text-xs text-slate-100">{`const outputUrl =
  url.startsWith("/media/")
    ? WORKER_PUBLIC_BASE + url
    : url;`}</pre>
        </div>
      </div>

      <div className="flex items-center justify-between gap-2">
        <div className="rounded-lg border border-blue-200 bg-blue-50 p-4 text-sm leading-6 text-blue-900">
          Model policy: production requests do not need to pass a model. The orchestrator applies the configured Flow setting for the API type. Use `flow_override` only for internal testing, not normal user traffic.
        </div>
      </div>
    </div>
  );
}

function CodeLine({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid gap-1">
      <div className="text-[11px] font-semibold uppercase text-slate-400">{label}</div>
      <div className="break-all rounded-lg bg-slate-950 px-3 py-2 font-mono text-xs text-slate-100">{value}</div>
    </div>
  );
}

function DocBlock({ title, body, code }: { title: string; body: string; code: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="text-sm font-semibold">{title}</div>
      <p className="mt-2 text-sm leading-6 text-slate-600">{body}</p>
      <pre className="mt-3 max-h-80 overflow-auto rounded-lg bg-slate-950 p-3 text-xs text-slate-100">{code}</pre>
    </div>
  );
}

function DocRow({ name, value }: { name: string; value: string }) {
  return (
    <div className="rounded-lg bg-slate-50 px-3 py-2">
      <div className="font-mono text-xs font-semibold text-slate-900">{name}</div>
      <div className="mt-1 text-xs leading-5 text-slate-500">{value}</div>
    </div>
  );
}

function secondsMetric(value?: number | null) {
  if (value === null || value === undefined) return "n/a";
  return durationLabel(value * 1000);
}

function etaLabel(value?: number | null) {
  if (value === null || value === undefined) return "calculating";
  return durationLabel(value * 1000);
}

function progressLabel(progress?: JobProgress) {
  if (!progress) return "Progress calculating";
  const source = progress.veo_native_percent_available ? "Veo reported" : "estimated";
  return `${progress.percent}% ${source}`;
}

function JobCard({ job }: { job: Job }) {
  const local = workerResult(job);
  const urls = outputUrls(local);
  const firstUrl = urls[0] ? outputUrlForBrowser(urls[0]) : "";
  const verdict = jobVerdict(job);
  const events = jobEvents(job);
  const model = job.flow_settings?.model || "model pending";
  const points = job.flow_settings?.estimated_credits;
  const whyWaiting = job.capacity_snapshot?.map((item) => `${item.vps_id}: ${item.reason}`).join(" | ");
  const detail =
    job.last_error ||
    local?.last_error ||
    whyWaiting ||
    (job.state === "COMPLETED" && urls.length === 0 ? "The worker marked this job completed but returned no output_urls. Check worker logs and FlowKit response payload." : null);
  return (
    <article className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex flex-col gap-2 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className={cls("rounded-md px-2 py-1 text-xs font-semibold", verdict.tone === "green" ? "bg-emerald-50 text-emerald-700" : verdict.tone === "red" ? "bg-red-50 text-red-700" : "bg-amber-50 text-amber-700")}>{verdict.label}</span>
            <span className="text-xs font-semibold text-slate-500">{job.generation_type.replaceAll("_", " ")}</span>
            <span className="text-xs text-slate-400">{job.id}</span>
          </div>
          <p className="mt-2 break-words text-sm font-medium text-slate-800">{job.prompt}</p>
          <p className="mt-1 text-xs text-slate-500">{model}{job.flow_settings?.duration ? ` | ${job.flow_settings.duration}s` : ""}{points !== undefined ? ` | ${points} points` : ""}</p>
        </div>
        <span className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs font-semibold text-slate-600">
          {job.production_defaults_used ? "global model" : "test override"}
        </span>
      </div>
      {job.progress && (
        <div className="mt-3 rounded-lg border border-slate-200 bg-slate-50 p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <div className="text-xs font-semibold uppercase text-slate-500">User-facing status</div>
              <div className="mt-1 text-sm font-semibold text-slate-800">{job.progress.message}</div>
            </div>
            <div className="text-right text-xs font-semibold text-slate-500">
              <div>{progressLabel(job.progress)}</div>
              <div>ETA {etaLabel(job.progress.eta_seconds)}</div>
            </div>
          </div>
          <div className="mt-3 h-2 overflow-hidden rounded-full bg-slate-200">
            <div className="h-full rounded-full bg-blue-600 transition-all" style={{ width: `${Math.max(0, Math.min(100, job.progress.percent))}%` }} />
          </div>
          <div className="mt-2 grid gap-2 text-xs sm:grid-cols-3">
            <Info label="Queue position" value={job.progress.queue_position ? `#${job.progress.queue_position}` : "not queued"} compact />
            <Info label="Expected queue wait" value={etaLabel(job.progress.estimated_queue_seconds)} compact />
            <Info label="Elapsed" value={etaLabel(job.progress.elapsed_seconds)} compact />
          </div>
        </div>
      )}
      <div className="mt-3 grid gap-2 text-xs sm:grid-cols-2 lg:grid-cols-4">
        <Info label="Routing" value={job.routing_status || "pending"} compact />
        <Info label="VPS" value={job.assigned_worker_id || "pending"} compact />
        <Info label="Account" value={local?.account_id || local?.assigned_account_id || job.preferred_account_id || "pending"} compact warning={job.state === "COMPLETED" && !local?.account_id && !local?.assigned_account_id} />
        <Info label="Local job" value={job.worker_job_id || local?.id || "pending"} compact />
        <Info label="Global retries" value={`${job.retries}/${job.max_retries}`} compact />
        <Info label="Local retries" value={local ? `${local.retries ?? 0}/${local.max_retries ?? 0}` : "pending"} compact />
        <Info label="Browser" value={local?.browser_url || "pending"} compact />
        <Info label="Outputs" value={String(urls.length)} compact warning={job.state === "COMPLETED" && urls.length === 0} />
        <Info label="FlowKit project" value={local?.payload?.flowkit_result?.project_id || "pending"} compact />
        <Info label="Media ID" value={local?.payload?.flowkit_result?.image_media_id || local?.payload?.flowkit_result?.video_media_id || "pending"} compact />
        <Info label="Worker state" value={local?.state || "pending"} compact />
      </div>
      <EventRail events={events} />
      {urls.length > 0 && (
        <div className="mt-3 grid gap-3 md:grid-cols-[180px_minmax(0,1fr)]">
          {isVideoOutput(job, urls[0]) ? (
            <video className="h-32 w-full overflow-hidden rounded-lg border border-slate-200 bg-black object-cover" src={firstUrl} controls muted playsInline />
          ) : (
            <a className="block overflow-hidden rounded-lg border border-slate-200 bg-slate-50" href={firstUrl} target="_blank" rel="noreferrer" title="Open generated output">
              {urls[0].includes("/image/") || !job.generation_type.includes("video") ? (
              // eslint-disable-next-line @next/next/no-img-element
                <img className="h-32 w-full object-cover" src={urls[0]} alt="Generated output preview" />
              ) : (
                <div className="flex h-32 items-center justify-center text-slate-500"><ImageIcon size={28} /></div>
              )}
            </a>
          )}
          <div className="grid content-start gap-2">
            <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm font-semibold text-emerald-800">Real output URL returned by worker</div>
            {urls.map((url, index) => (
              <div key={url} className="flex min-w-0 items-center gap-2 rounded-lg bg-slate-50 px-3 py-2">
                <span className="shrink-0 text-xs font-semibold text-slate-400">#{index + 1}</span>
                <a className="min-w-0 flex-1 truncate text-sm font-medium text-blue-700 hover:underline" href={outputUrlForBrowser(url)} target="_blank" rel="noreferrer">{outputUrlForBrowser(url)}</a>
                <button className="icon-button shrink-0" type="button" title="Copy output URL" onClick={() => copyText(outputUrlForBrowser(url))}>
                  <Copy size={15} />
                </button>
                <a className="icon-button shrink-0" href={outputUrlForBrowser(url)} target="_blank" rel="noreferrer" title="Open output">
                  <ExternalLink size={15} />
                </a>
              </div>
            ))}
          </div>
        </div>
      )}
      {detail && (
        <div className={cls("mt-3 rounded-lg border px-3 py-2 text-xs", job.state === "COMPLETED" && urls.length > 0 ? "border-slate-200 bg-slate-50 text-slate-700" : "border-amber-200 bg-amber-50 text-amber-800")}>
          <div className="font-semibold">Debug detail</div>
          <pre className="mt-1 max-h-28 overflow-auto whitespace-pre-wrap break-words font-mono text-[11px]">{detail}</pre>
        </div>
      )}
    </article>
  );
}

function SystemEventMap({
  jobs,
  fleet,
}: {
  jobs: Job[];
  fleet: { online: number; accounts: number; freeSlots: number; localQueues: number; flowkit: number; authNeeded: number };
}) {
  const latest = jobs[0];
  const events = latest ? jobEvents(latest) : [];
  const activeIndex = events.findIndex((event) => event.tone === "active" || event.tone === "blocked" || event.tone === "failed");
  const current = activeIndex >= 0 ? events[activeIndex] : events[events.length - 1];
  return (
    <div className="grid gap-4">
      <div className="grid gap-3 md:grid-cols-3">
        <MiniSignal icon={<Radio size={16} />} label="Fleet" value={`${fleet.online} VPS online`} />
        <MiniSignal icon={<Users size={16} />} label="Accounts" value={`${fleet.freeSlots}/${fleet.accounts} slots free`} />
        <MiniSignal icon={<Monitor size={16} />} label="FlowKit" value={`${fleet.flowkit} connected`} warning={fleet.authNeeded > 0} />
      </div>
      {!latest ? (
        <Empty text="Send a test job and this area will show the live path it takes through the system." />
      ) : (
        <div className="rounded-lg border border-slate-200 bg-slate-950 p-4 text-white">
          <div className="flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
            <div>
              <div className="flex items-center gap-2 text-sm font-semibold text-slate-200">
                <Activity size={16} />
                Latest job path
              </div>
              <p className="mt-1 line-clamp-2 text-sm text-slate-400">{latest.prompt}</p>
            </div>
            <div className={cls("rounded-lg px-3 py-2 text-xs font-semibold", current?.tone === "failed" ? "bg-red-500/20 text-red-100" : current?.tone === "blocked" ? "bg-amber-500/20 text-amber-100" : current?.tone === "active" ? "bg-blue-500/20 text-blue-100" : "bg-emerald-500/20 text-emerald-100")}>
              {current?.title || "Waiting"}
            </div>
          </div>
          <div className="mt-4 grid gap-2 lg:grid-cols-8">
            {events.map((event, index) => {
              const delta = eventDelta(events, index);
              return (
              <div key={`${event.title}-${index}`} className="relative">
                {index < events.length - 1 && <div className="absolute left-[calc(100%-8px)] top-5 z-0 hidden h-px w-4 bg-slate-700 lg:block" />}
                <div className={cls("relative z-10 grid min-h-28 gap-2 rounded-lg border p-3", darkEventClass(event.tone))}>
                  <div className="flex items-center justify-between">
                    <span className="flex size-8 items-center justify-center rounded-lg bg-white/10">{event.icon}</span>
                    {index < events.length - 1 && <ArrowRight size={14} className="text-slate-500 lg:hidden" />}
                  </div>
                  <div>
                    <div className="text-xs font-semibold">{event.title}</div>
                    <div className="mt-1 text-[10px] font-semibold opacity-70">{timeLabel(event.at)}{delta ? ` | +${delta}` : ""}</div>
                    <p className="mt-1 line-clamp-3 text-[11px] leading-4 opacity-80">{event.detail}</p>
                  </div>
                </div>
              </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

function OperationsBoard({ activeJob, queueJobs, now }: { activeJob?: Job; queueJobs: Job[]; now: number }) {
  const activeLocal = activeJob ? workerResult(activeJob) : undefined;
  const activeEvents = activeJob ? jobEvents(activeJob) : [];
  const activeStep = activeEvents.find((event) => event.tone === "active" || event.tone === "blocked" || event.tone === "failed") || activeEvents[activeEvents.length - 1];
  const activeOutputs = outputUrls(activeLocal);
  return (
    <div className="grid gap-4">
      <div className="rounded-lg border border-slate-200 bg-slate-950 p-4 text-white">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-200">
            <PlayCircle size={17} />
            Active job slot
          </div>
          {activeJob && (
            <span className="inline-flex items-center gap-2 rounded-lg bg-white/10 px-3 py-1.5 text-xs font-semibold">
              <Timer size={14} />
              {durationLabel(now - jobStartedAt(activeJob))}
            </span>
          )}
        </div>

        {!activeJob ? (
          <div className="mt-4 rounded-lg border border-dashed border-slate-700 bg-slate-900 px-4 py-8 text-center text-sm text-slate-400">
            No job is currently being processed.
          </div>
        ) : (
          <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1fr)_260px]">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <span className="rounded-md bg-blue-500/20 px-2 py-1 text-xs font-semibold text-blue-100">{activeJob.state}</span>
                <span className="text-xs text-slate-400">{activeJob.generation_type.replaceAll("_", " ")}</span>
                <span className="truncate text-xs text-slate-500">{activeJob.id}</span>
              </div>
              <p className="mt-3 break-words text-lg font-semibold leading-6">{activeJob.prompt}</p>
              <p className="mt-2 text-sm text-slate-400">
                {activeJob.flow_settings?.model || "model pending"}
                {activeJob.flow_settings?.duration ? ` | ${activeJob.flow_settings.duration}s` : ""}
                {activeJob.flow_settings?.estimated_credits !== undefined ? ` | ${activeJob.flow_settings.estimated_credits} points` : ""}
              </p>
              <div className="mt-4 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
                <DarkInfo label="Current step" value={activeStep?.title || "Waiting"} tone={activeStep?.tone} />
                <DarkInfo label="Progress" value={activeJob.progress ? progressLabel(activeJob.progress) : "calculating"} tone="active" />
                <DarkInfo label="ETA" value={etaLabel(activeJob.progress?.eta_seconds)} />
                <DarkInfo label="VPS" value={activeJob.assigned_worker_id || "pending"} />
                <DarkInfo label="Account" value={activeLocal?.account_id || activeLocal?.assigned_account_id || activeJob.preferred_account_id || "pending"} />
                <DarkInfo label="Outputs" value={String(activeOutputs.length)} tone={activeOutputs.length ? "done" : undefined} />
              </div>
              {activeJob.progress && (
                <div className="mt-4 h-2 overflow-hidden rounded-full bg-slate-800">
                  <div className="h-full rounded-full bg-blue-400 transition-all" style={{ width: `${Math.max(0, Math.min(100, activeJob.progress.percent))}%` }} />
                </div>
              )}
            </div>
            <div className="rounded-lg border border-slate-800 bg-slate-900 p-3">
              <div className="text-xs font-semibold uppercase text-slate-500">Live progress</div>
              <div className="mt-3 grid gap-2">
                {activeEvents.map((event) => (
                  <div key={event.title} className="flex items-start gap-2">
                    <span className={cls("mt-1 size-2 shrink-0 rounded-full", eventDotClass(event.tone))} />
                    <div className="min-w-0">
                      <div className={cls("text-xs font-semibold", event.tone === "waiting" ? "text-slate-500" : "text-slate-200")}>{event.title}</div>
                      <div className="mt-0.5 text-[10px] font-semibold text-slate-600">{timeLabel(event.at)}</div>
                      <p className="line-clamp-2 text-[11px] leading-4 text-slate-500">{event.detail}</p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>

      <div className="rounded-lg border border-slate-200 bg-white">
        <div className="flex items-center justify-between border-b border-slate-100 px-3 py-2">
          <div className="flex items-center gap-2 text-sm font-semibold">
            <ListTodo size={16} />
            Waiting queue
          </div>
          <span className="rounded-md bg-slate-100 px-2 py-1 text-xs font-semibold text-slate-600">{queueJobs.length} waiting</span>
        </div>
        {queueJobs.length === 0 ? (
          <div className="px-4 py-6 text-center text-sm text-slate-500">Global queue is empty.</div>
        ) : (
          <div className="divide-y divide-slate-100">
            {queueJobs.slice(0, 8).map((job, index) => {
              const waitMs = now - jobQueuedAt(job);
              const reason = job.capacity_snapshot?.map((item) => `${item.vps_id}: ${item.reason}`).join(" | ") || job.routing_status || "Waiting for scheduler";
              return (
                <div key={job.id} className="grid gap-2 px-3 py-3 md:grid-cols-[52px_minmax(0,1fr)_150px] md:items-center">
                  <div className="flex items-center gap-2 text-xs font-semibold text-slate-400">
                    <span className="flex size-7 items-center justify-center rounded-lg bg-slate-100 text-slate-700">{index + 1}</span>
                  </div>
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="rounded-md bg-amber-50 px-2 py-1 text-[11px] font-semibold text-amber-700">{job.state}</span>
                      <span className="text-xs font-medium text-slate-500">{job.generation_type.replaceAll("_", " ")}</span>
                    </div>
                    <p className="mt-1 truncate text-sm font-semibold text-slate-800">{job.prompt}</p>
                    <p className="mt-1 truncate text-xs text-slate-500">{reason}</p>
                    {job.progress && <p className="mt-1 truncate text-xs font-medium text-blue-700">ETA {etaLabel(job.progress.eta_seconds)} | queue {etaLabel(job.progress.estimated_queue_seconds)}</p>}
                  </div>
                  <div className="inline-flex items-center gap-2 rounded-lg bg-slate-50 px-3 py-2 text-xs font-semibold text-slate-700">
                    <Timer size={14} />
                    {durationLabel(waitMs)}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

function DarkInfo({ label, value, tone }: { label: string; value: string; tone?: EventTone }) {
  return (
    <div className={cls("rounded-lg border px-3 py-2", tone === "blocked" ? "border-amber-400/30 bg-amber-400/10" : tone === "failed" ? "border-red-400/30 bg-red-400/10" : tone === "done" ? "border-emerald-400/30 bg-emerald-400/10" : "border-slate-800 bg-slate-900")}>
      <div className="text-[11px] font-semibold uppercase text-slate-500">{label}</div>
      <div className="mt-1 break-all text-sm font-semibold text-slate-100">{value}</div>
    </div>
  );
}

function darkEventClass(tone: EventTone) {
  if (tone === "done") return "border-emerald-400/30 bg-emerald-400/10 text-emerald-50";
  if (tone === "active") return "border-blue-400/40 bg-blue-400/10 text-blue-50 shadow-[0_0_0_1px_rgba(96,165,250,0.2)]";
  if (tone === "failed") return "border-red-400/40 bg-red-400/10 text-red-50";
  if (tone === "blocked") return "border-amber-300/50 bg-amber-300/10 text-amber-50";
  return "border-slate-700 bg-slate-900 text-slate-300";
}

function EventRail({ events }: { events: FlowEvent[] }) {
  return (
    <div className="mt-4 rounded-lg border border-slate-200 bg-slate-50 p-3">
      <div className="mb-3 flex items-center gap-2 text-xs font-semibold uppercase text-slate-500">
        <Activity size={14} />
        Event trace
      </div>
      <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-4">
        {events.map((event, index) => {
          const delta = eventDelta(events, index);
          return (
          <div key={`${event.title}-${index}`} className={cls("rounded-lg border p-3", eventToneClass(event.tone))}>
            <div className="flex items-center gap-2">
              <span className={cls("size-2 rounded-full", eventDotClass(event.tone))} />
              <span className="flex size-7 items-center justify-center rounded-md bg-white/70">{event.icon}</span>
              <span className="text-xs font-semibold">{event.title}</span>
            </div>
            <div className="mt-2 text-[10px] font-semibold opacity-70">{timeLabel(event.at)}{delta ? ` | +${delta}` : ""}</div>
            <p className="mt-2 line-clamp-3 text-[11px] leading-4 opacity-80">{event.detail}</p>
          </div>
          );
        })}
      </div>
    </div>
  );
}

function MiniSignal({ icon, label, value, warning }: { icon: React.ReactNode; label: string; value: string; warning?: boolean }) {
  return (
    <div className={cls("rounded-lg border px-3 py-2", warning ? "border-amber-200 bg-amber-50" : "border-slate-200 bg-white")}>
      <div className={cls("flex items-center gap-2 text-[11px] font-semibold uppercase", warning ? "text-amber-600" : "text-slate-400")}>{icon}{label}</div>
      <div className={cls("mt-1 text-sm font-semibold", warning ? "text-amber-900" : "text-slate-800")}>{value}</div>
    </div>
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

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <label className="grid gap-1.5 text-sm"><span className="font-medium text-slate-700">{label}</span>{children}</label>;
}

function Metric({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex items-center gap-2 text-xs font-semibold uppercase text-slate-400">{icon}{label}</div>
      <div className="mt-2 text-2xl font-semibold text-slate-900">{value}</div>
    </div>
  );
}

function Info({ label, value, compact, warning }: { label: string; value: string; compact?: boolean; warning?: boolean }) {
  return (
    <div className={cls("rounded-lg", warning ? "bg-amber-50" : "bg-slate-50", compact ? "px-3 py-2" : "p-3")}>
      <div className={cls("text-[11px] font-medium uppercase", warning ? "text-amber-500" : "text-slate-400")}>{label}</div>
      <div className={cls("mt-1 break-all text-sm font-semibold", warning ? "text-amber-800" : "text-slate-800")}>{value}</div>
    </div>
  );
}

function Status({ ok, label }: { ok: boolean; label: string }) {
  return <span className={cls("inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-sm font-medium", ok ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-red-200 bg-red-50 text-red-700")}>{ok ? <CheckCircle2 size={16} /> : <AlertCircle size={16} />}{label}</span>;
}

function StatusPill({ ok, label }: { ok: boolean; label: string }) {
  return <span className={cls("rounded-md px-2 py-1 text-xs font-semibold", ok ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-600")}>{label}</span>;
}

function Empty({ text }: { text: string }) {
  return <div className="rounded-lg border border-dashed border-slate-200 bg-slate-50 px-6 py-10 text-center text-sm text-slate-500">{text}</div>;
}
