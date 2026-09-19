"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  FileText,
  FolderKanban,
  History,
  LayoutDashboard,
  LogOut,
  Search,
  Settings,
  Sparkles,
  UserCircle2
} from "lucide-react";
import type { PropsWithChildren } from "react";

import { ThemeToggle } from "@/components/theme-toggle";
import { logoutApi } from "@/lib/api";
import { cn } from "@/lib/utils";

const navigation = [
  { href: "/dashboard", label: "Tableau de bord", icon: LayoutDashboard },
  { href: "/documents", label: "Documents", icon: FolderKanban },
  { href: "/extractions", label: "Extractions", icon: Sparkles },
  { href: "/history", label: "Historiques", icon: History },
  { href: "/settings", label: "Parametres", icon: Settings }
];

export function AppShell({ children }: PropsWithChildren) {
  const pathname = usePathname();
  const router = useRouter();
  const isAuthPage = pathname === "/login";
  const showTopSearch = pathname !== "/dashboard";

  const handleLogout = () => {
    logoutApi();
    router.replace("/login");
  };

  if (isAuthPage) {
    return (
      <div className="h-[100dvh] overflow-hidden bg-[#f7f9fc] text-[#1b2440]">
        {children}
      </div>
    );
  }

  return (
    <div className="min-h-[100dvh] bg-background px-3 py-3 text-foreground lg:px-4 lg:py-4">
      <div className="mx-auto flex h-[calc(100dvh-1.5rem)] max-w-[1680px] gap-5 lg:h-[calc(100dvh-2rem)]">
        <aside className="hidden h-full w-[112px] shrink-0 rounded-[22px] border border-[rgba(140,148,170,0.18)] bg-white px-3 py-4 shadow-[0_10px_36px_rgba(23,33,64,0.05)] dark:border-white/10 dark:bg-[#101625] xl:flex xl:flex-col">
          <div className="mb-8 flex items-center gap-2 px-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-[linear-gradient(145deg,#ffe0ef,#eef2ff)] text-[#7c4dff] dark:bg-[linear-gradient(145deg,#2a244d,#101625)]">
              <FileText className="h-4 w-4" />
            </div>
            <div>
              <div className="text-sm font-bold">DocIA</div>
            </div>
          </div>

          <nav className="flex-1 space-y-1.5">
            {navigation.map((item) => {
              const Icon = item.icon;
              const active = pathname === item.href;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={cn(
                    "group flex flex-col items-center gap-1 rounded-2xl border px-2 py-3 text-center text-[11px] font-medium transition",
                    active
                      ? "border-[#ccefd8] bg-[#eefcf3] text-[#2eb764] dark:border-[#1f6b41] dark:bg-[#11271d] dark:text-[#86f7b6]"
                      : "border-transparent text-[#74809f] hover:border-[rgba(140,148,170,0.18)] hover:bg-[#f8faff] hover:text-[#1b2440] dark:text-[#9ca6c6] dark:hover:bg-white/5 dark:hover:text-white"
                  )}
                >
                  <Icon className="h-4 w-4" />
                  {item.label}
                </Link>
              );
            })}
          </nav>

          <div className="mt-6 space-y-2">
            <Link
              href="/profile"
              className="block rounded-[18px] border border-[rgba(140,148,170,0.18)] bg-[#fbfcff] p-2.5 dark:border-white/10 dark:bg-[#0f1525]"
            >
              <div className="flex items-center gap-2">
                <div className="flex h-8 w-8 items-center justify-center rounded-full bg-[linear-gradient(145deg,#7c4dff,#61d79c)] text-white">
                  <UserCircle2 className="h-4 w-4" />
                </div>
                <div className="min-w-0">
                  <div className="truncate text-[11px] font-semibold">Profil</div>
                  <div className="truncate text-[10px] text-[#7a83a2]">Compte actif</div>
                </div>
              </div>
            </Link>
            <button
              type="button"
              onClick={handleLogout}
              className="flex w-full items-center justify-center gap-1.5 rounded-[16px] border border-[#ffd1d9] bg-[#fff8fa] px-2 py-2 text-[11px] font-semibold text-[#df4d64] transition hover:bg-[#ffeef2] dark:border-[#5a2632] dark:bg-[#1a1118] dark:text-[#ff8fa1]"
              title="Se deconnecter"
            >
              <LogOut className="h-3.5 w-3.5" />
              Deconnexion
            </button>
          </div>
        </aside>

        <main className="flex h-full min-h-0 flex-1 flex-col overflow-hidden rounded-[24px] border border-[rgba(140,148,170,0.16)] bg-white px-5 py-5 shadow-[0_12px_45px_rgba(23,33,64,0.05)] dark:border-white/10 dark:bg-[#101625]">
          <div className="mb-4 flex items-center justify-between gap-3 xl:hidden">
            <div className="flex items-center gap-2">
              <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-[linear-gradient(145deg,#ffe0ef,#eef2ff)] text-[#7c4dff] dark:bg-[linear-gradient(145deg,#2a244d,#101625)]">
                <FileText className="h-4 w-4" />
              </div>
              <div className="text-sm font-bold">DocIA</div>
            </div>
            <div className="flex items-center gap-2">
              <ThemeToggle />
              <button
                type="button"
                onClick={handleLogout}
                className="flex h-10 items-center gap-2 rounded-xl border border-[#ffd1d9] bg-[#fff8fa] px-3 text-[12px] font-semibold text-[#df4d64] dark:border-[#5a2632] dark:bg-[#1a1118] dark:text-[#ff8fa1]"
              >
                <LogOut className="h-4 w-4" />
                Deconnexion
              </button>
            </div>
          </div>
          <div className="mb-6 flex gap-3 overflow-x-auto xl:hidden">
            {navigation.map((item) => {
              const Icon = item.icon;
              const active = pathname === item.href;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={cn(
                    "flex shrink-0 items-center gap-2 rounded-xl border px-4 py-2 text-sm font-medium transition",
                    active
                      ? "border-[#ccefd8] bg-[#eefcf3] text-[#2eb764] dark:border-[#1f6b41] dark:bg-[#11271d] dark:text-[#86f7b6]"
                      : "border-[rgba(140,148,170,0.18)] bg-[#fbfcff] text-[#74809f] dark:border-white/10 dark:bg-[#0f1525] dark:text-[#9ca6c6]"
                  )}
                >
                  <Icon className="h-4 w-4" />
                  {item.label}
                </Link>
              );
            })}
          </div>
          <div
            className={cn(
              "mb-5 hidden items-center gap-4 xl:flex",
              showTopSearch ? "justify-between" : "justify-end"
            )}
          >
            {showTopSearch ? (
              <div className="flex h-10 w-full max-w-[280px] items-center gap-3 rounded-xl border border-[rgba(140,148,170,0.18)] bg-[#fbfcff] px-3 dark:border-white/10 dark:bg-[#0f1525]">
                <Search className="h-4 w-4 text-[#8b93ac]" />
                <input
                  className="w-full bg-transparent text-sm outline-none placeholder:text-[#9ca3ba]"
                  placeholder="Rechercher..."
                />
              </div>
            ) : null}
            <div className="flex items-center gap-2">
              <ThemeToggle />
            </div>
          </div>
          <div className="app-scroll flex-1 pr-1">{children}</div>
        </main>
      </div>
    </div>
  );
}
