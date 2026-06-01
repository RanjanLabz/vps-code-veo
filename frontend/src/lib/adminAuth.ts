"use client";

export type AdminSession = {
  email: string;
  role: string;
  expires_at?: number;
};

const TOKEN_KEY = "flowkit_admin_token";

export function storedToken() {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY);
}

export function storeToken(token: string) {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
}

export async function loginWithPassword(email: string, password: string) {
  const response = await fetch("/api/admin/login", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!response.ok) throw new Error(await response.text());
  const data = (await response.json()) as { token: string; user: AdminSession };
  storeToken(data.token);
  return data.user;
}

export async function signupWithPassword(email: string, password: string, name: string) {
  const response = await fetch("/api/admin/signup", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ email, password, name }),
  });
  if (!response.ok) throw new Error(await response.text());
  return response.json() as Promise<{ status: string; message: string }>;
}

export async function currentAdminSession() {
  const token = storedToken();
  if (!token) return null;
  const response = await fetch("/api/admin/me", {
    headers: { authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  if (!response.ok) {
    clearToken();
    return null;
  }
  return response.json() as Promise<AdminSession>;
}

export async function changePassword(currentPassword: string, newPassword: string) {
  const token = storedToken();
  if (!token) throw new Error("Not signed in.");
  const response = await fetch("/api/admin/change-password", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
  });
  if (!response.ok) throw new Error(await response.text());
  return response.json() as Promise<{ ok: boolean; message: string }>;
}
