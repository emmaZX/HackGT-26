"use client";

import { FormEvent, Suspense, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useAuth } from "@/lib/AuthProvider";
import { authErrorMessage, confirmAccount, isAuthConfigured, registerAccount, resendCode, safeNext } from "@/lib/auth";

export default function SignupPage() {
  return (
    <Suspense fallback={<div className="mx-auto max-w-md text-[#5a6d80]">Loading…</div>}>
      <SignupForm />
    </Suspense>
  );
}

function SignupForm() {
  const router = useRouter();
  const params = useSearchParams();
  const next = safeNext(params.get("next"));
  const { login, refresh } = useAuth();
  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [needsCode, setNeedsCode] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  if (!isAuthConfigured()) {
    return (
      <div className="mx-auto max-w-md">
        <h1 className="serif text-4xl">Create an account</h1>
        <p className="card mt-6 p-6 text-sm text-[#5a6d80]">
          Cognito is not configured yet. Add the user pool id and app client id to
          <code className="mx-1">frontend/.env.local</code> and restart Next.js.
        </p>
      </div>
    );
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setMessage(null);
    try {
      if (!needsCode) {
        const result = await registerAccount(displayName.trim(), email.trim(), password);
        if (result.nextStep.signUpStep === "CONFIRM_SIGN_UP") {
          setNeedsCode(true);
          setMessage("We sent a confirmation code to your email.");
          return;
        }
        await finishSignIn();
        return;
      }
      await confirmAccount(email.trim(), code.trim());
      await finishSignIn();
    } catch (err) {
      const name = typeof err === "object" && err && "name" in err ? String(err.name) : "";
      if (name === "UsernameExistsException") {
        setNeedsCode(true);
        setMessage("That email already has an account. Enter the confirmation code, or sign in if you already confirmed.");
      } else {
        setMessage(authErrorMessage(err));
      }
    } finally {
      setBusy(false);
    }
  }

  async function finishSignIn() {
    const session = await refresh();
    if (!session) {
      await login(email.trim(), password);
    }
    router.replace(next);
    router.refresh();
  }

  async function resend() {
    setBusy(true);
    setMessage(null);
    try {
      await resendCode(email.trim());
      setMessage("A new code is on the way.");
    } catch (err) {
      setMessage(authErrorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-md">
      <h1 className="serif text-4xl">Join the neighbors</h1>
      <p className="mt-2 text-[#5a6d80]">Create an account to share what happened with a product.</p>
      <form onSubmit={submit} className="card mt-8 grid gap-4 p-6">
        {!needsCode ? (
          <>
            <label className="grid gap-1 text-sm">
              What should we call you?
              <input
                required
                minLength={2}
                maxLength={80}
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                className="field"
              />
            </label>
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
                minLength={8}
                autoComplete="new-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="field"
              />
              <span className="text-xs text-[#5a6d80]">
                At least 8 characters, with upper, lower, a number, and a symbol.
              </span>
            </label>
          </>
        ) : (
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
          {busy ? "Working…" : needsCode ? "Confirm and sign in" : "Create account"}
        </button>
        {needsCode && (
          <button type="button" disabled={busy} onClick={resend} className="btn-soft px-5 py-3 text-sm">
            Resend code
          </button>
        )}
        {message && <p className="text-sm text-[#5a6d80]">{message}</p>}
      </form>
      <p className="mt-4 text-sm text-[#5a6d80]">
        Already have an account?{" "}
        <Link href={`/login?next=${encodeURIComponent(next)}`} className="font-semibold text-[#1a365d]">
          Sign in
        </Link>
      </p>
    </div>
  );
}
