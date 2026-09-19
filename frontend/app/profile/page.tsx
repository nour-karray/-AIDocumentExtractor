"use client";

import { LogOut, ShieldCheck, UserCircle2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { fetchCurrentUser, logoutApi } from "@/lib/api";
import type { AuthMeResponse } from "@/lib/types";

export default function ProfilePage() {
  const router = useRouter();
  const [profile, setProfile] = useState<AuthMeResponse | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { fetchCurrentUser().then(setProfile).catch((err: Error) => setError(err.message)); }, []);
  const logout = () => { logoutApi(); router.replace("/login"); };
  return <div className="space-y-5">
    <PageHeader eyebrow="PROFIL" title="Profil utilisateur" description="Identite fournie par le backend DocIA." />
    <Card className="mx-auto max-w-2xl space-y-5">
      <div className="flex items-center gap-4"><div className="flex h-16 w-16 items-center justify-center rounded-full bg-[#edf1ff] text-[#7c4dff] dark:bg-[#211d3b]"><UserCircle2 className="h-8 w-8" /></div><div><div className="proto-title text-xl font-bold">{profile?.user.username ?? "Chargement..."}</div><div className="mt-1 text-sm text-[#7a83a2]">Mode : {profile?.mode ?? "—"}</div></div></div>
      {error ? <div className="text-sm text-[#df4d64]">{error}</div> : null}
      <div className="flex items-center gap-2 rounded-xl bg-[#eef9f0] p-3 text-sm text-[#23834c] dark:bg-[#11271d] dark:text-[#86f7b6]"><ShieldCheck className="h-4 w-4" />Aucun profil personnel fictif n'est conserve dans l'application.</div>
      <Button variant="danger" onClick={logout} className="gap-2"><LogOut className="h-4 w-4" /> Se deconnecter</Button>
    </Card>
  </div>;
}
