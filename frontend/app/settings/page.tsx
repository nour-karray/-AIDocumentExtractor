"use client";

import { Server, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";
import { PageHeader } from "@/components/page-header";
import { Card } from "@/components/ui/card";
import { fetchMeta, fetchModels } from "@/lib/api";
import type { MetaPayload, ModelsPayload } from "@/lib/types";

export default function SettingsPage() {
  const [meta, setMeta] = useState<MetaPayload | null>(null);
  const [models, setModels] = useState<ModelsPayload | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { Promise.all([fetchMeta(), fetchModels()]).then(([m, r]) => { setMeta(m); setModels(r); }).catch((err: Error) => setError(err.message)); }, []);
  return <div className="space-y-5">
    <PageHeader eyebrow="PARAMETRES" title="Configuration" description="Etat en lecture seule de la configuration serveur." />
    {error ? <Card className="text-[#df4d64]">{error}</Card> : null}
    <div className="grid gap-4 lg:grid-cols-2">
      <Card className="space-y-3"><div className="flex items-center gap-2 font-semibold"><Server className="h-4 w-4 text-[#7c4dff]" />Runtime</div><div className="text-sm text-[#66708e]">API : {meta?.apiVersion ?? "Chargement..."}</div><div className="text-sm text-[#66708e]">Gemini : {models?.runtime.geminiConfigured ? "configure" : "non configure"}</div><div className="text-sm text-[#66708e]">Ollama : {models?.runtime.ollamaConfigured ? "disponible" : "indisponible"}</div><div className="text-sm text-[#66708e]">OCR : {models?.runtime.tesseractConfigured ? "configure" : "non configure"}</div></Card>
      <Card className="space-y-3"><div className="flex items-center gap-2 font-semibold"><ShieldCheck className="h-4 w-4 text-[#2eb764]" />Securite</div><p className="text-sm text-[#66708e]">Les cles API, secrets JWT, hotes et modeles sont configures cote serveur. Ils ne sont ni saisis ni stockes dans le navigateur.</p><p className="text-sm text-[#66708e]">Authentification : {meta?.auth?.enabled ? "activee" : "desactivee"}</p></Card>
    </div>
  </div>;
}
