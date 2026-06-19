"use client";

import { useRouter } from "next/navigation";
import {
  ArrowRight,
  Check,
  Eye,
  EyeOff,
  LockKeyhole,
  Mail,
  Plus,
  ShieldCheck,
  UserRound
} from "lucide-react";
import { FormEvent, useState } from "react";

import { loginApi } from "@/lib/api";

function authError(message: string) {
  try {
    const parsed = JSON.parse(message);
    return parsed.detail || message;
  } catch {
    return message;
  }
}

export default function LoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(true);
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      await loginApi({ username, password });
      router.push("/dashboard");
    } catch (err) {
      setError(authError(err instanceof Error ? err.message : "Connexion impossible."));
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="relative grid h-[100dvh] grid-rows-[auto_minmax(0,1fr)] overflow-hidden bg-[radial-gradient(circle_at_20%_0%,rgba(0,119,255,0.12),transparent_30%),linear-gradient(135deg,#f8fbff_0%,#ffffff_50%,#eef7ff_100%)] px-5 py-5 text-[#071a3d]">
      <div className="pointer-events-none absolute right-[8%] top-[23%] hidden text-[#bfeeff] opacity-65 lg:block">
        <ShieldCheck className="h-72 w-72 stroke-[1.1]" />
      </div>
      <div className="pointer-events-none absolute right-[14%] top-[45%] hidden h-8 w-8 rounded-lg text-[#ccefff] lg:flex">
        <Plus className="h-8 w-8" />
      </div>
      <div className="pointer-events-none absolute bottom-[15%] right-[9%] hidden grid-cols-4 gap-3 opacity-25 lg:grid">
        {Array.from({ length: 16 }).map((_, index) => (
          <span key={index} className="h-1.5 w-1.5 rounded-full bg-[#8fdcff]" />
        ))}
      </div>

      <div className="mx-auto flex w-full max-w-[1500px] items-center gap-3">
        <div className="flex h-12 w-12 items-center justify-center rounded-[18px] border-2 border-[#0078ff] bg-white text-[#0078ff] shadow-[0_12px_28px_rgba(0,120,255,0.16)]">
          <Plus className="h-8 w-8 stroke-[3]" />
        </div>
        <div>
          <div className="text-[28px] font-black tracking-[-0.02em] text-[#061739]">
            Docu<span className="text-[#0078ff]">AI</span>
          </div>
          <div className="text-[13px] font-medium text-[#66769a]">Extraction securisee des donnees documentaires</div>
        </div>
      </div>

      <div className="flex min-h-0 items-center justify-center">
      <section className="w-full max-w-[540px] rounded-[24px] border border-[#dbe6f5] bg-white/92 px-8 py-7 shadow-[0_24px_70px_rgba(32,57,101,0.13)] backdrop-blur">
        <div className="mb-5 text-center">
          <h1 className="text-[30px] font-black tracking-[-0.02em] text-[#071a3d]">Connexion</h1>
          <p className="mt-2 text-[14px] font-medium text-[#66769a]">Accedez a votre espace securise</p>
        </div>

        <form className="space-y-4" onSubmit={submit}>
          <div className="space-y-2">
            <label className="text-[13px] font-bold text-[#071a3d]" htmlFor="username">
              Identifiant ou e-mail
            </label>
            <div className="relative">
              <Mail className="pointer-events-none absolute left-4 top-1/2 h-5 w-5 -translate-y-1/2 text-[#7a8bad]" />
              <input
                id="username"
                autoComplete="username"
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                placeholder="admin"
                className="h-12 w-full rounded-xl border border-[#cfdbea] bg-white px-12 text-[15px] font-medium text-[#071a3d] outline-none transition placeholder:text-[#8b9aba] focus:border-[#0078ff] focus:ring-4 focus:ring-[#0078ff]/10"
                required
              />
            </div>
          </div>

          <div className="space-y-2">
            <label className="text-[13px] font-bold text-[#071a3d]" htmlFor="password">
              Mot de passe
            </label>
            <div className="relative">
              <LockKeyhole className="pointer-events-none absolute left-4 top-1/2 h-5 w-5 -translate-y-1/2 text-[#7a8bad]" />
              <input
                id="password"
                autoComplete="current-password"
                type={showPassword ? "text" : "password"}
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                className="h-12 w-full rounded-xl border border-[#cfdbea] bg-white px-12 pr-12 text-[15px] font-medium text-[#071a3d] outline-none transition placeholder:text-[#8b9aba] focus:border-[#0078ff] focus:ring-4 focus:ring-[#0078ff]/10"
                required
              />
              <button
                type="button"
                onClick={() => setShowPassword((current) => !current)}
                className="absolute right-4 top-1/2 flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-lg text-[#7a8bad] transition hover:bg-[#edf5ff] hover:text-[#0078ff]"
                aria-label={showPassword ? "Masquer le mot de passe" : "Afficher le mot de passe"}
              >
                {showPassword ? <EyeOff className="h-5 w-5" /> : <Eye className="h-5 w-5" />}
              </button>
            </div>
          </div>

          <div className="flex flex-wrap items-center justify-between gap-3 text-sm">
            <button
              type="button"
              onClick={() => setRemember((current) => !current)}
              className="flex items-center gap-2 font-medium text-[#607092]"
            >
              <span className={`flex h-5 w-5 items-center justify-center rounded-md border ${remember ? "border-[#17b8a6] bg-[#17b8a6] text-white" : "border-[#cfdbea] bg-white text-transparent"}`}>
                <Check className="h-3.5 w-3.5" />
              </span>
              Se souvenir de moi
            </button>
            <button type="button" className="font-bold text-[#0078ff]">
              Mot de passe oublie ?
            </button>
          </div>

          {error ? <div className="rounded-xl bg-[#fff4f5] px-4 py-3 text-sm font-semibold text-[#d92d4a]">{error}</div> : null}

          <button
            className="flex h-12 w-full items-center justify-center gap-3 rounded-xl bg-[linear-gradient(135deg,#0078ff,#005dea)] text-[16px] font-black text-white shadow-[0_18px_34px_rgba(0,104,255,0.28)] transition hover:brightness-105 disabled:cursor-not-allowed disabled:opacity-60"
            type="submit"
            disabled={loading}
          >
            <ArrowRight className="h-5 w-5" />
            {loading ? "Connexion..." : "Se connecter"}
          </button>
        </form>
      </section>
      </div>

      <div className="pointer-events-none absolute bottom-6 left-6 flex h-10 w-10 items-center justify-center rounded-full bg-[#0b1327] text-white shadow-lg">
        <UserRound className="h-5 w-5" />
      </div>
    </main>
  );
}
