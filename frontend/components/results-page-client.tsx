"use client";

import { Download, FileSearch } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";

import { PageHeader } from "@/components/page-header";
import { ResultDetail } from "@/components/result-detail";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { fetchHistoryDetail, fetchLatestResult, resolveApiUrl } from "@/lib/api";
import { readStoredValue, storageKeys } from "@/lib/storage";
import type { ExtractionBatchPayload, HistoryDetail } from "@/lib/types";

export function ResultsPageClient() {
  const searchParams = useSearchParams();
  const entryKey = searchParams.get("entry");
  const [detail, setDetail] = useState<HistoryDetail | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (entryKey) {
      fetchHistoryDetail(entryKey)
        .then(setDetail)
        .catch((err: Error) => setError(err.message));
      return;
    }

    const stored = readStoredValue(storageKeys.lastExtraction, "");
    if (stored) {
      try {
        const parsed = JSON.parse(stored) as ExtractionBatchPayload;
        if (parsed.latestSuccess?.historyEntryKey) {
          fetchHistoryDetail(parsed.latestSuccess.historyEntryKey)
            .then(setDetail)
            .catch((err: Error) => setError(err.message));
          return;
        }
      } catch {
        // Ignore corrupted local storage and fallback to latest history entry.
      }
    }

    fetchLatestResult()
      .then((payload) => setDetail(payload.item))
      .catch((err: Error) => setError(err.message));
  }, [entryKey]);

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="3. DETAIL DU DOCUMENT"
        title={detail?.sourceFilename ?? "Detail du document"}
        description="Cette page montre un document traite, les champs extraits automatiquement et le JSON technique genere par l'extraction."
      />

      {error ? (
        <Card className="text-[#df4d64]">{error}</Card>
      ) : (
        <>
          {detail ? (
            <Card className="space-y-4">
              <div className="flex items-center justify-between text-[12px]">
                <Link href="/documents" className="font-semibold text-[#6f5df6]">
                  Retour aux documents
                </Link>
                <div className="flex flex-wrap gap-2">
                  <a href={resolveApiUrl(detail.reportUrl)} target="_blank" rel="noreferrer">
                    <Button variant="secondary" size="sm" className="gap-2">
                      <Download className="h-4 w-4" />
                      Rapport PDF
                    </Button>
                  </a>
                  {detail.sourceAvailable ? (
                    <a href={resolveApiUrl(detail.sourceUrl)} target="_blank" rel="noreferrer">
                      <Button size="sm" className="gap-2">
                        <FileSearch className="h-4 w-4" />
                        Fichier source
                      </Button>
                    </a>
                  ) : null}
                </div>
              </div>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <div className="proto-title text-[24px] font-bold text-[#1b2440] dark:text-white">
                    {detail.sourceFilename}
                  </div>
                  <div className="mt-1 text-[12px] text-[#8d95ae]">
                    {detail.kindLabel} - {detail.method} - {detail.savedDate ?? "Date a verifier"}
                  </div>
                </div>
                <Badge tone={detail.status === "ok" ? "success" : "danger"}>
                  {detail.status === "ok" ? "Succes" : "Erreur"}
                </Badge>
              </div>

              <div className="grid gap-3 md:grid-cols-3">
                <div className="rounded-[16px] border border-[rgba(139,147,172,0.14)] bg-[#fbfcff] px-4 py-3 text-[12px] dark:border-white/10 dark:bg-[#0f1525]">
                  <div className="font-semibold text-[#8d95ae]">Type detecte</div>
                  <div className="mt-1 text-[#1b2440] dark:text-white">{detail.kindLabel}</div>
                </div>
                <div className="rounded-[16px] border border-[rgba(139,147,172,0.14)] bg-[#fbfcff] px-4 py-3 text-[12px] dark:border-white/10 dark:bg-[#0f1525]">
                  <div className="font-semibold text-[#8d95ae]">Methode utilisee</div>
                  <div className="mt-1 text-[#1b2440] dark:text-white">{detail.method}</div>
                </div>
                <div className="rounded-[16px] border border-[rgba(139,147,172,0.14)] bg-[#fbfcff] px-4 py-3 text-[12px] dark:border-white/10 dark:bg-[#0f1525]">
                  <div className="font-semibold text-[#8d95ae]">Date d'extraction</div>
                  <div className="mt-1 text-[#1b2440] dark:text-white">{detail.savedDate ?? "Date a verifier"}</div>
                </div>
              </div>

              <div className="rounded-[16px] border border-[rgba(139,147,172,0.14)] bg-[#fbfcff] px-4 py-3 text-[12px] text-[#66708e] dark:border-white/10 dark:bg-[#0f1525] dark:text-[#b1bcda]">
                <div className="font-semibold text-[#1b2440] dark:text-white">Que contient cette page ?</div>
                <div className="mt-2">Document original : le fichier envoye ou son apercu.</div>
                <div className="mt-1">Champs extraits : les informations lues automatiquement par le systeme.</div>
                <div className="mt-1">JSON technique : la structure complete generee pour export ou traitement.</div>
              </div>
            </Card>
          ) : null}
          <ResultDetail detail={detail} />
        </>
      )}
    </div>
  );
}
