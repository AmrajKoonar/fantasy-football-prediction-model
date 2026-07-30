"use client";

import { createClient, type SupabaseClient, type User } from "@supabase/supabase-js";

let singleton: SupabaseClient | null = null;

export function supabaseConfigured(): boolean {
  return Boolean(
    process.env.NEXT_PUBLIC_SUPABASE_URL && process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY,
  );
}

export function getSupabase(): SupabaseClient {
  if (!supabaseConfigured()) {
    throw new Error("Supabase environment variables are not configured.");
  }
  singleton ??= createClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY!,
    {
      auth: {
        persistSession: true,
        autoRefreshToken: true,
        detectSessionInUrl: true,
      },
    },
  );
  return singleton;
}

export async function ensureAnonymousUser(): Promise<User> {
  const client = getSupabase();
  const existing = await client.auth.getUser();
  if (existing.data.user) return existing.data.user;
  const signedIn = await client.auth.signInAnonymously();
  if (signedIn.error || !signedIn.data.user) {
    throw signedIn.error ?? new Error("Anonymous sign-in failed.");
  }
  return signedIn.data.user;
}

export function getDisplayName(): string {
  if (typeof window === "undefined") return "Guest";
  const stored = window.localStorage.getItem("fantasy-analytics-display-name");
  if (stored) return stored;
  const generated = `Guest ${Math.floor(1000 + Math.random() * 9000)}`;
  window.localStorage.setItem("fantasy-analytics-display-name", generated);
  return generated;
}

export function setDisplayName(name: string) {
  window.localStorage.setItem("fantasy-analytics-display-name", name.trim().slice(0, 30));
}

