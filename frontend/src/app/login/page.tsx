"use client";

import { FormEvent, Suspense, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useAuth } from "@/lib/AuthProvider";
import {
  authErrorMessage,
  confirmAccount,
  isAuthConfigured,
  isUnconfirmedError,
  resendCode,
  safeNext,
} from "@/lib/auth";

export default function LoginPage() {
  return (
    <Suspense fallback={<div className="mx-auto max-w-md text-[#627290]">Loading…</div>}>
      <LoginForm />
    </Suspense>
  );
}

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const next = safeNext(params.get("next"));
  const { login, refresh } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [needsCode, setNeedsCode] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  if (!isAuthConfigured()) {
    return (
      <div className="mx-auto max-w-md">
        <h1 className="serif text-4xl">Sign in</h1>
        <p className="card mt-6 p-6 text-sm text-[#627290]">
          Cognito is not configured yet. Add the user pool id and app client id to
          <code className="mx-1">frontend/.env.local</code> and restart Next.js. The README has the
          console checklist.
        </p>
      </div>
    );
  }

  async function goSignedIn() {
    const session = await refresh();
    if (!session) {
      await login(email.trim(), password);
    }
    router.replace(next);
    router.refresh();
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setMessage(null);
    try {
      if (needsCode) {
        await confirmAccount(email.trim(), code.trim());
        await goSignedIn();
        return;
      }
      await login(email.trim(), password);
      router.replace(next);
      router.refresh();
    } catch (err) {
      if (isUnconfirmedError(err)) {
        setNeedsCode(true);
        setMessage("Check your email for a confirmation code, then enter it here.");
      } else {
        setMessage(authErrorMessage(err));
      }
    } finally {
      setBusy(false);
    }
  }

  async function resend() {
    setBusy(true);
    setMessage(null);
    try {
      await resendCode(email.trim());
      setNeedsCode(true);
      setMessage("A new code is on the way.");
    } catch (err) {
      setMessage(authErrorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-md">
      <h1 className="serif text-4xl">Welcome back</h1>
      <p className="mt-2 text-[#627290]">Sign in to share a complaint or a neighbor note.</p>
      <form onSubmit={submit} className="card mt-8 grid gap-4 p-6">
        <label className="grid gap-1 text-sm">
          Email
          <input
            type="email"
            required
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="field"
          />
        </label>
        <label className="grid gap-1 text-sm">
          Password
          <input
            type="password"
            required
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="field"
          />
        </label>
        {needsCode && (
          <label className="grid gap-1 text-sm">
            Confirmation code
            <input
              required
              inputMode="numeric"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              className="field"
            />
          </label>
        )}
        <button disabled={busy} className="btn-primary px-5 py-3 disabled:opacity-40">
          {busy ? "Signing in…" : needsCode ? "Confirm and sign in" : "Sign in"}
        </button>
        <button type="button" disabled={busy || !email} onClick={resend} className="btn-soft px-5 py-3 text-sm">
          Email me a confirmation code
        </button>
        {message && <p className="text-sm text-[#d9546a]">{message}</p>}
      </form>
      <p className="mt-4 text-sm text-[#627290]">
        New here?{" "}
        <Link href={`/signup?next=${encodeURIComponent(next)}`} className="font-semibold text-[#031d4e]">
          Create an account
        </Link>
      </p>
    </div>
  );
}
