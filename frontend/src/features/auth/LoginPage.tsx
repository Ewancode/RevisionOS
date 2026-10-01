import { useNavigate } from "@tanstack/react-router";
import { useState, type FormEvent } from "react";

import { Button, ErrorText, Field } from "@/components/ui";

import { useLogin } from "./session";

export function LoginPage() {
  const login = useLogin();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault();
    try {
      await login.mutateAsync({ email, password });
      await navigate({ to: "/" });
    } catch {
      setPassword("");
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center px-4">
      <form
        onSubmit={submit}
        className="flex w-full max-w-sm flex-col gap-4 rounded-lg border border-border bg-surface p-6"
        aria-labelledby="login-heading"
      >
        <h1 id="login-heading" className="text-xl font-semibold">
          Sign in to Revision OS
        </h1>
        <Field
          label="Email"
          type="email"
          autoComplete="username"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
        <Field
          label="Password"
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        <ErrorText error={login.error} />
        <Button type="submit" variant="primary" disabled={login.isPending}>
          {login.isPending ? "Signing in…" : "Sign in"}
        </Button>
      </form>
    </main>
  );
}
