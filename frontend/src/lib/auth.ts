import { Amplify } from "aws-amplify";
import {
  autoSignIn,
  confirmSignUp,
  fetchAuthSession,
  fetchUserAttributes,
  getCurrentUser,
  resendSignUpCode,
  signIn,
  signOut,
  signUp,
} from "aws-amplify/auth";

export type SessionUser = {
  sub: string;
  email: string;
  displayName: string;
};

let configured = false;

export function isAuthConfigured() {
  return Boolean(
    process.env.NEXT_PUBLIC_COGNITO_USER_POOL_ID && process.env.NEXT_PUBLIC_COGNITO_APP_CLIENT_ID,
  );
}

export function configureAuth() {
  if (!isAuthConfigured() || typeof window === "undefined") return false;
  // Always re-apply env-based pool/client so .env.local fixes take effect after restart
  // without a hard full reload of the JS module state mid-session.
  Amplify.configure({
    Auth: {
      Cognito: {
        userPoolId: process.env.NEXT_PUBLIC_COGNITO_USER_POOL_ID!,
        userPoolClientId: process.env.NEXT_PUBLIC_COGNITO_APP_CLIENT_ID!,
        loginWith: { email: true },
      },
    },
  });
  configured = true;
  return true;
}

export function safeNext(value: string | null | undefined) {
if (!value || !value.startsWith("/") || value.startsWith("//")) return "/";  return value;
}

export function isUnconfirmedError(err: unknown) {
  return errorName(err) === "UserNotConfirmedException";
}

export async function getIdToken() {
  if (!configureAuth()) return null;
  try {
    let session = await fetchAuthSession();
    if (!session.tokens?.idToken) {
      session = await fetchAuthSession({ forceRefresh: true });
    }
    return session.tokens?.idToken?.toString() ?? null;
  } catch {
    return null;
  }
}

function userFromClaims(
  payload: Record<string, unknown>,
  attrs: Record<string, string> = {},
): SessionUser | null {
  const sub = payload.sub;
  if (!sub) return null;
  const email = attrs.email || String(payload.email || payload["cognito:username"] || "");
  return {
    sub: String(sub),
    email,
    displayName:
      attrs.name ||
      attrs.preferred_username ||
      String(payload.name || payload.preferred_username || "") ||
      email.split("@")[0] ||
      "Neighbor",
  };
}

export async function currentUser(): Promise<SessionUser | null> {
  if (!configureAuth()) return null;
  try {
    await getCurrentUser();
    const session = await fetchAuthSession();
    const payload = (session.tokens?.idToken?.payload || {}) as Record<string, unknown>;
    let attrs: Record<string, string> = {};
    try {
      const raw = await fetchUserAttributes();
      attrs = Object.fromEntries(Object.entries(raw).filter((entry): entry is [string, string] => Boolean(entry[1])));
    } catch {
      // Token claims are enough if Cognito hides some attributes.
    }
    return userFromClaims(payload, attrs);
  } catch {
    return null;
  }
}

function preferredUsername(displayName: string, email: string) {
  const cleaned = (displayName || email.split("@")[0] || "neighbor")
    .trim()
    .replace(/\s+/g, "_")
    .replace(/[^\w.\-']/g, "")
    .slice(0, 80);
  return cleaned || "neighbor";
}

export async function registerAccount(displayName: string, email: string, password: string) {
  configureAuth();
  const username = preferredUsername(displayName, email);
  const attempts: Record<string, string>[] = [
    { email, preferred_username: username, name: displayName },
    { email, preferred_username: username },
    { email, name: displayName },
    { email },
  ];
  let lastError: unknown;
  for (const userAttributes of attempts) {
    try {
      return await signUp({
        username: email,
        password,
        options: { userAttributes, autoSignIn: true },
      });
    } catch (err) {
      lastError = err;
      if (errorName(err) !== "InvalidParameterException") throw err;
    }
  }
  throw lastError;
}

export async function confirmAccount(email: string, code: string) {
  configureAuth();
  const result = await confirmSignUp({ username: email, confirmationCode: code });
  if (result.nextStep.signUpStep === "COMPLETE_AUTO_SIGN_IN") {
    await autoSignIn();
  }
  return result;
}

export async function resendCode(email: string) {
  configureAuth();
  return resendSignUpCode({ username: email });
}

export async function loginAccount(email: string, password: string) {
  configureAuth();
  try {
    await getCurrentUser();
    await signOut();
  } catch {
    // No existing session.
  }
  const result = await signIn({ username: email, password });
  if (result.nextStep.signInStep === "CONFIRM_SIGN_UP") {
    const err = new Error("Please confirm your email first.");
    err.name = "UserNotConfirmedException";
    throw err;
  }
  if (result.nextStep.signInStep !== "DONE") {
    throw new Error(`Sign-in needs another step (${result.nextStep.signInStep}).`);
  }
  return result;
}

export async function logoutAccount() {
  if (!configureAuth()) return;
  await signOut();
}

function errorName(err: unknown) {
  return typeof err === "object" && err && "name" in err ? String(err.name) : "";
}

export function authErrorMessage(err: unknown) {
  const name = errorName(err);
  const map: Record<string, string> = {
    NotAuthorizedException: "Email or password is not right.",
    UserNotFoundException: "No account exists for that email yet. Create one first.",
    UsernameExistsException: "An account with that email already exists. Sign in, or confirm the email if you just signed up.",
    UserNotConfirmedException: "Please confirm your email first. Check your inbox for the code.",
    CodeMismatchException: "That confirmation code is not right.",
    ExpiredCodeException: "That code expired. Request a new one.",
    InvalidPasswordException: "Use 8+ characters with upper, lower, a number, and a symbol.",
    InvalidParameterException:
      err instanceof Error && err.message
        ? err.message
        : "Cognito rejected an attribute. If the pool requires preferred_username, use that instead of name.",
    LimitExceededException: "Too many attempts. Wait a minute and try again.",
    UserAlreadyAuthenticatedException: "You are already signed in. Refresh the page.",
  };
  if (map[name]) return map[name];
  return err instanceof Error ? err.message : "Something went wrong";
}
