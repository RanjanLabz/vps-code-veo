const DEFAULT_ORCHESTRATOR_URL = "https://flowkit-global-orchestrator.onrender.com";
const DEFAULT_ADMIN_EMAIL = "runjawon@gmail.com";
const SESSION_TTL_SECONDS = 60 * 60 * 12;
const PASSWORD_HASH_ITERATIONS = 100000;

const encoder = new TextEncoder();

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function normalizeEmail(email) {
  return String(email || "").trim().toLowerCase();
}

function userKey(email) {
  return `user:${normalizeEmail(email)}`;
}

function tokenFromRequest(request) {
  const authorization = request.headers.get("authorization") || "";
  const match = authorization.match(/^Bearer\s+(.+)$/i);
  return match?.[1] || null;
}

function base64Url(bytes) {
  const view = new Uint8Array(bytes);
  let binary = "";
  for (let i = 0; i < view.length; i += 0x8000) {
    binary += String.fromCharCode(...view.subarray(i, i + 0x8000));
  }
  return btoa(binary).replaceAll("+", "-").replaceAll("/", "_").replaceAll("=", "");
}

function fromBase64Url(value) {
  const padded = value.replaceAll("-", "+").replaceAll("_", "/").padEnd(Math.ceil(value.length / 4) * 4, "=");
  const binary = atob(padded);
  return Uint8Array.from(binary, (char) => char.charCodeAt(0));
}

async function hmacKey(secret) {
  return crypto.subtle.importKey("raw", encoder.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign", "verify"]);
}

async function signSession(payload, env) {
  const secret = env.SESSION_SECRET || env.ORCHESTRATOR_API_KEY;
  if (!secret) throw new Error("SESSION_SECRET is not configured.");
  const body = base64Url(encoder.encode(JSON.stringify(payload)));
  const signature = await crypto.subtle.sign("HMAC", await hmacKey(secret), encoder.encode(body));
  return `${body}.${base64Url(signature)}`;
}

async function verifySessionToken(token, env) {
  const secret = env.SESSION_SECRET || env.ORCHESTRATOR_API_KEY;
  if (!secret) throw new Error("SESSION_SECRET is not configured.");
  const [body, signature] = String(token || "").split(".");
  if (!body || !signature) throw new Error("Invalid admin session.");
  const valid = await crypto.subtle.verify("HMAC", await hmacKey(secret), fromBase64Url(signature), encoder.encode(body));
  if (!valid) throw new Error("Invalid admin session.");
  const payload = JSON.parse(new TextDecoder().decode(fromBase64Url(body)));
  if (!payload.exp || Date.now() > payload.exp * 1000) throw new Error("Admin session expired.");
  return payload;
}

async function hashPassword(password, saltBase64) {
  const salt = saltBase64 ? fromBase64Url(saltBase64) : crypto.getRandomValues(new Uint8Array(16));
  const key = await crypto.subtle.importKey("raw", encoder.encode(password), "PBKDF2", false, ["deriveBits"]);
  const bits = await crypto.subtle.deriveBits(
    { name: "PBKDF2", salt, iterations: PASSWORD_HASH_ITERATIONS, hash: "SHA-256" },
    key,
    256,
  );
  return { salt: base64Url(salt), hash: base64Url(bits) };
}

async function verifyPassword(password, record) {
  if (!record?.password_salt || !record?.password_hash) return false;
  const next = await hashPassword(password, record.password_salt);
  return next.hash === record.password_hash;
}

async function setRecordPassword(record, password) {
  const passwordHash = await hashPassword(password);
  return {
    ...record,
    password_hash: passwordHash.hash,
    password_salt: passwordHash.salt,
    updated_at: new Date().toISOString(),
  };
}

async function getUser(env, email) {
  if (!env.ADMIN_USERS) return null;
  return env.ADMIN_USERS.get(userKey(email), "json");
}

async function saveUser(env, record) {
  if (!env.ADMIN_USERS) throw new Error("ADMIN_USERS KV binding is not configured.");
  await env.ADMIN_USERS.put(userKey(record.email), JSON.stringify(record));
}

async function getSession(request, env) {
  const token = tokenFromRequest(request);
  if (!token) throw new Error("Missing admin session.");
  const session = await verifySessionToken(token, env);
  const email = normalizeEmail(session.email);
  const superAdminEmail = normalizeEmail(env.ADMIN_EMAIL || DEFAULT_ADMIN_EMAIL);
  if (email === superAdminEmail) return { email, role: "super_admin", super_admin: true };
  const record = await getUser(env, email);
  if (!record || record.status !== "approved") throw new Error("Admin account is not approved.");
  return { email, role: record.role || "admin", super_admin: false };
}

async function requireApprovedAdmin(request, env) {
  try {
    return { session: await getSession(request, env) };
  } catch (error) {
    return { response: json({ error: error.message || "Unauthorized" }, 401) };
  }
}

async function requireSuperAdmin(request, env) {
  const auth = await requireApprovedAdmin(request, env);
  if (auth.response) return auth;
  if (!auth.session.super_admin) return { ...auth, response: json({ error: "Super admin access required." }, 403) };
  return auth;
}

async function proxyOrchestrator(request, env) {
  const auth = await requireApprovedAdmin(request, env);
  if (auth.response) return auth.response;

  const baseUrl = env.ORCHESTRATOR_API_URL || DEFAULT_ORCHESTRATOR_URL;
  const requestUrl = new URL(request.url);
  const upstreamPath = requestUrl.pathname.replace(/^\/api\/orchestrator\/?/, "");
  const upstream = new URL(upstreamPath, baseUrl.endsWith("/") ? baseUrl : `${baseUrl}/`);
  upstream.search = requestUrl.search;

  const headers = new Headers();
  const contentType = request.headers.get("content-type");
  const accept = request.headers.get("accept");
  if (contentType) headers.set("content-type", contentType);
  if (accept) headers.set("accept", accept);
  if (env.ORCHESTRATOR_API_KEY) headers.set("x-api-key", env.ORCHESTRATOR_API_KEY);

  return fetch(upstream.toString(), {
    method: request.method,
    headers,
    body: ["GET", "HEAD"].includes(request.method) ? undefined : request.body,
  });
}

async function listAccessRecords(env) {
  if (!env.ADMIN_USERS) return [];
  const entries = await env.ADMIN_USERS.list({ prefix: "user:" });
  const records = await Promise.all(entries.keys.map((item) => env.ADMIN_USERS.get(item.name, "json")));
  return records
    .filter(Boolean)
    .map(({ password_hash, password_salt, ...record }) => record)
    .sort((a, b) => a.email.localeCompare(b.email));
}

async function handleSignup(request, env) {
  let body;
  try {
    body = await request.json();
  } catch (error) {
    return json({ error: `Invalid signup JSON: ${error.message}` }, 400);
  }
  const email = normalizeEmail(body.email);
  const password = String(body.password || "");
  const name = String(body.name || "").trim();
  if (!email || password.length < 8) return json({ error: "Email and 8+ character password are required." }, 400);
  const superAdminEmail = normalizeEmail(env.ADMIN_EMAIL || DEFAULT_ADMIN_EMAIL);
  let existing;
  try {
    existing = await getUser(env, email);
  } catch (error) {
    return json({ error: `Unable to read admin user store: ${error.message}` }, 500);
  }
  if (existing) return json({ status: existing.status, message: "Account request already exists." });
  let passwordHash;
  try {
    passwordHash = await hashPassword(password);
  } catch (error) {
    return json({ error: `Unable to hash password: ${error.message}` }, 500);
  }
  const record = {
    email,
    name,
    status: email === superAdminEmail ? "approved" : "pending",
    role: email === superAdminEmail ? "super_admin" : "admin",
    super_admin: email === superAdminEmail,
    password_hash: passwordHash.hash,
    password_salt: passwordHash.salt,
    created_at: new Date().toISOString(),
  };
  try {
    await saveUser(env, record);
  } catch (error) {
    return json({ error: `Unable to save admin user: ${error.message}` }, 500);
  }
  return json({
    status: record.status,
    message: record.status === "approved" ? "Super admin account created. You can sign in now." : "Signup request saved. Wait for admin approval.",
  });
}

async function handleLogin(request, env) {
  let body;
  try {
    body = await request.json();
  } catch (error) {
    return json({ error: `Invalid login JSON: ${error.message}` }, 400);
  }
  const email = normalizeEmail(body.email);
  const password = String(body.password || "");
  const superAdminEmail = normalizeEmail(env.ADMIN_EMAIL || DEFAULT_ADMIN_EMAIL);

  let record;
  try {
    record = await getUser(env, email);
  } catch (error) {
    return json({ error: `Unable to read admin user store: ${error.message}` }, 500);
  }
  if (email === superAdminEmail && env.ADMIN_PASSWORD && password === env.ADMIN_PASSWORD) {
    let passwordHash;
    try {
      passwordHash = await hashPassword(password);
    } catch (error) {
      return json({ error: `Unable to hash super admin password: ${error.message}` }, 500);
    }
    record = {
      ...(record || {}),
      email,
      name: record?.name || "Super admin",
      status: "approved",
      role: "super_admin",
      super_admin: true,
      password_hash: passwordHash.hash,
      password_salt: passwordHash.salt,
      created_at: record?.created_at || new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };
    if (env.ADMIN_USERS) {
      try {
        await saveUser(env, record);
      } catch (error) {
        return json({ error: `Unable to save super admin account: ${error.message}` }, 500);
      }
    }
  }

  let passwordOk = false;
  try {
    passwordOk = Boolean(record && (await verifyPassword(password, record)));
  } catch (error) {
    return json({ error: `Unable to verify password: ${error.message}` }, 500);
  }
  if (!record || !passwordOk) return json({ error: "Invalid email or password." }, 401);
  if (record.status !== "approved") return json({ error: `Account is ${record.status}.` }, 403);

  const exp = Math.floor(Date.now() / 1000) + SESSION_TTL_SECONDS;
  const user = { email: record.email, role: record.role || "admin", super_admin: Boolean(record.super_admin), expires_at: exp };
  let token;
  try {
    token = await signSession({ ...user, exp }, env);
  } catch (error) {
    return json({ error: `Unable to sign admin session: ${error.message}` }, 500);
  }
  return json({ token, user });
}

async function handleAdminApi(request, env) {
  const url = new URL(request.url);
  if (url.pathname === "/api/admin/diagnostics") {
    return json({
      ok: true,
      has_admin_users_binding: Boolean(env.ADMIN_USERS),
      has_admin_email: Boolean(env.ADMIN_EMAIL || DEFAULT_ADMIN_EMAIL),
      has_admin_password: Boolean(env.ADMIN_PASSWORD),
      has_session_secret: Boolean(env.SESSION_SECRET || env.ORCHESTRATOR_API_KEY),
      has_orchestrator_api_key: Boolean(env.ORCHESTRATOR_API_KEY),
    });
  }
  if (url.pathname === "/api/admin/signup" && request.method === "POST") return handleSignup(request, env);
  if (url.pathname === "/api/admin/login" && request.method === "POST") return handleLogin(request, env);

  if (url.pathname === "/api/admin/change-password" && request.method === "POST") {
    const auth = await requireApprovedAdmin(request, env);
    if (auth.response) return auth.response;
    if (!env.ADMIN_USERS) return json({ error: "ADMIN_USERS KV binding is not configured." }, 500);
    const body = await request.json();
    const currentPassword = String(body.current_password || "");
    const newPassword = String(body.new_password || "");
    if (newPassword.length < 8) return json({ error: "New password must be at least 8 characters." }, 400);
    const record = await getUser(env, auth.session.email);
    if (!record || !(await verifyPassword(currentPassword, record))) return json({ error: "Current password is incorrect." }, 401);
    await saveUser(env, await setRecordPassword(record, newPassword));
    return json({ ok: true, message: "Password changed." });
  }

  if (url.pathname === "/api/admin/me") {
    const auth = await requireApprovedAdmin(request, env);
    if (auth.response) return auth.response;
    return json(auth.session);
  }

  if (url.pathname === "/api/admin/access" && request.method === "GET") {
    const auth = await requireSuperAdmin(request, env);
    if (auth.response) return auth.response;
    return json({ users: await listAccessRecords(env) });
  }

  if (url.pathname === "/api/admin/access" && request.method === "POST") {
    const auth = await requireSuperAdmin(request, env);
    if (auth.response) return auth.response;
    const body = await request.json();
    const email = normalizeEmail(body.email);
    const status = String(body.status || "pending").toLowerCase();
    if (!email || !["approved", "pending", "blocked"].includes(status)) return json({ error: "Invalid access update." }, 400);
    const existing = (await getUser(env, email)) || { email, created_at: new Date().toISOString() };
    const record = {
      ...existing,
      email,
      status,
      role: body.role || existing.role || "admin",
      updated_at: new Date().toISOString(),
      updated_by: auth.session.email,
    };
    if (email === normalizeEmail(env.ADMIN_EMAIL || DEFAULT_ADMIN_EMAIL)) {
      record.status = "approved";
      record.role = "super_admin";
      record.super_admin = true;
    }
    await saveUser(env, record);
    const { password_hash, password_salt, ...safeRecord } = record;
    return json(safeRecord);
  }

  if (url.pathname === "/api/admin/access/reset-password" && request.method === "POST") {
    const auth = await requireSuperAdmin(request, env);
    if (auth.response) return auth.response;
    if (!env.ADMIN_USERS) return json({ error: "ADMIN_USERS KV binding is not configured." }, 500);
    const body = await request.json();
    const email = normalizeEmail(body.email);
    const password = String(body.password || "");
    if (!email || password.length < 8) return json({ error: "Email and 8+ character password are required." }, 400);
    const existing = await getUser(env, email);
    if (!existing) return json({ error: "Admin user not found." }, 404);
    const record = await setRecordPassword(existing, password);
    record.updated_by = auth.session.email;
    await saveUser(env, record);
    const { password_hash, password_salt, ...safeRecord } = record;
    return json(safeRecord);
  }

  return json({ error: "Not found" }, 404);
}

export default {
  async fetch(request, env) {
    try {
      const url = new URL(request.url);
      if (url.pathname.startsWith("/api/admin")) return await handleAdminApi(request, env);
      if (url.pathname.startsWith("/api/orchestrator")) return await proxyOrchestrator(request, env);
      return env.ASSETS.fetch(request);
    } catch (error) {
      return json({ error: error.message || "Worker error" }, 500);
    }
  },
};
