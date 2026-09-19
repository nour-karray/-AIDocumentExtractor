"use client";

import { CalendarDays, ChevronLeft, ChevronRight, FileText, Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { fetchHistory, resolveApiUrl } from "@/lib/api";
import { readSessionValue, storageKeys } from "@/lib/storage";
import type { HistoryItem, HistoryListPayload } from "@/lib/types";

const historyTypeFilters = [
  { value: "steg", label: "Facture STEG", query: "facture steg" },
  { value: "medical", label: "Analyse medicale", query: "analyse medicale" },
  { value: "receipt", label: "Ticket de caisse", query: "ticket de caisse" },
  { value: "supplier", label: "Facture fournisseur", query: "facture fournisseur" },
] as const;

function typeFilterQuery(typeFilter: string) {
  return historyTypeFilters.find((item) => item.value === typeFilter)?.query ?? "";
}

function groupByDate(items: HistoryItem[]) {
  return items.reduce<Record<string, HistoryItem[]>>((acc, item) => {
    const key = item.savedDate ?? "Sans date";
    acc[key] = [...(acc[key] ?? []), item];
    return acc;
  }, {});
}

function isImageSource(filename: string) {
  return /\.(png|jpe?g|webp|gif|bmp|tiff?)$/i.test(filename);
}

function SourceThumbnail({ item }: { item: HistoryItem }) {
  const [previewUrl, setPreviewUrl] = useState("");

  useEffect(() => {
    if (!item.sourceUrl || !isImageSource(item.sourceFilename)) {
      setPreviewUrl("");
      return;
    }

    let alive = true;
    let objectUrl = "";
    const token = readSessionValue(storageKeys.authToken, "");

    fetch(resolveApiUrl(item.sourceUrl), {
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
      cache: "no-store",
    })
      .then((response) => {
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }
        return response.blob();
      })
      .then((blob) => {
        if (!alive) {
          return;
        }
        objectUrl = URL.createObjectURL(blob);
        setPreviewUrl(objectUrl);
      })
      .catch(() => {
        if (alive) {
          setPreviewUrl("");
        }
      });

    return () => {
      alive = false;
      if (objectUrl) {
        URL.revokeObjectURL(objectUrl);
      }
    };
  }, [item.sourceFilename, item.sourceUrl]);

  return (
    <div className="flex h-11 w-11 shrink-0 items-center justify-center overflow-hidden rounded-xl bg-[#eef2fb] dark:bg-[#0b1020]">
      {previewUrl ? (
        <img alt={item.sourceFilename} className="h-full w-full object-cover" src={previewUrl} />
      ) : (
        <FileText className="h-5 w-5 text-[#7c4dff]" />
      )}
    </div>
  );
}

export default function HistoryPage() {
  const [search, setSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [selectedDate, setSelectedDate] = useState("");
  const [page, setPage] = useState(1);
  const [list, setList] = useState<HistoryListPayload | null>(null);
  const [selectedKey, setSelectedKey] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    const params = new URLSearchParams({
      page: String(page),
      pageSize: "8",
    });
    const normalizedSearch = search.trim();
    const selectedTypeQuery = typeFilterQuery(typeFilter);
    if (normalizedSearch) {
      params.set("search", normalizedSearch);
    }
    if (selectedTypeQuery) {
      params.set("typeQuery", selectedTypeQuery);
    }
    if (selectedDate) {
      params.set("dateFrom", selectedDate);
      params.set("dateTo", selectedDate);
    }
    fetchHistory(params)
      .then((payload) => {
        setError("");
        setList(payload);
        setSelectedKey((current) => {
          const selectedStillVisible = payload.items.some((item) => item.entryKey === current);
          if (payload.items[0] && (!current || !selectedStillVisible)) {
            return payload.items[0].entryKey;
          }
          return selectedStillVisible ? current : "";
        });
      })
      .catch((err: Error) => setError(err.message));
  }, [page, search, typeFilter, selectedDate]);

  const grouped = useMemo(() => groupByDate(list?.items ?? []), [list]);

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="5. HISTORIQUES"
        title="Historique des extractions"
        description="Chronologie des documents traites avec filtre rapide et acces detaille."
      />

      <Card className="space-y-4">
        <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
          <div className="flex flex-1 flex-wrap items-center gap-3">
            <div className="relative w-full max-w-[320px]">
              <Search className="pointer-events-none absolute left-3 top-3 h-4 w-4 text-[#99a1bb]" />
              <Input
                value={search}
                onChange={(event) => {
                  setSearch(event.target.value);
                  setPage(1);
                }}
                placeholder="Rechercher dans l'historique..."
                className="pl-9"
              />
            </div>
            <Select
              value={typeFilter}
              onChange={(event) => {
                setTypeFilter(event.target.value);
                setPage(1);
              }}
              className="max-w-[220px]"
            >
              <option value="">Tous les types</option>
              {historyTypeFilters.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </Select>
          </div>
          <div className="flex flex-wrap items-center gap-2 xl:justify-end">
            <div className="flex min-h-10 items-center gap-2 rounded-xl border border-[rgba(139,147,172,0.16)] bg-[#fbfcff] px-3 py-2 text-[12px] text-[#6b7594] dark:border-white/10 dark:bg-[#0f1525] dark:text-[#b1bcda]">
              <CalendarDays className="h-4 w-4 shrink-0 text-[#7c4dff]" />
              <Select
                value={selectedDate}
                onChange={(event) => {
                  setSelectedDate(event.target.value);
                  setPage(1);
                }}
                aria-label="Filtrer par date"
                className="h-8 min-w-[190px] rounded-lg bg-white text-[12px] dark:bg-[#121829]"
              >
                <option value="">Toutes les dates</option>
                {(list?.filters.availableDates ?? []).map((item) => (
                  <option key={item.value} value={item.value}>
                    {item.label}
                  </option>
                ))}
              </Select>
            </div>
          </div>
        </div>

        {error ? <div className="text-sm text-[#df4d64]">{error}</div> : null}

        {!list ? (
          <div className="text-sm text-[#7a83a2]">Chargement de l'historique...</div>
        ) : (
          <div className="grid gap-4 xl:grid-cols-[0.7fr,1.3fr]">
            <div className="rounded-[18px] border border-[rgba(139,147,172,0.14)] bg-[#fbfcff] p-4 dark:border-white/10 dark:bg-[#0f1525]">
              <div className="space-y-5">
                {Object.entries(grouped).map(([date, items]) => (
                  <div key={date} className="grid grid-cols-[18px,1fr] gap-3">
                    <div className="flex flex-col items-center">
                      <span className="mt-1 h-2.5 w-2.5 rounded-full bg-[#7c4dff]" />
                      <span className="mt-2 h-full w-px bg-[#e6eaf5] dark:bg-white/10" />
                    </div>
                    <div>
                      <div className="mb-2 text-[12px] font-semibold text-[#1b2440] dark:text-white">
                        {date}
                      </div>
                      <div className="space-y-2">
                        {items.map((item) => (
                          <button
                            key={item.entryKey}
                            type="button"
                            onClick={() => setSelectedKey(item.entryKey)}
                            className={`grid w-full grid-cols-[44px,minmax(0,1fr)] items-center gap-3 rounded-[14px] border px-3 py-2 text-left text-[12px] transition ${
                              selectedKey === item.entryKey
                                ? "border-[#d6ccff] bg-[#f5f0ff] dark:border-[#47328c] dark:bg-[#1c1734]"
                                : "border-[rgba(139,147,172,0.1)] bg-white hover:bg-[#fafbff] dark:border-white/10 dark:bg-[#121829] dark:hover:bg-[#151c30]"
                            }`}
                          >
                            <SourceThumbnail item={item} />
                            <div className="min-w-0">
                              <div className="truncate font-medium text-[#1b2440] dark:text-white">
                                {item.sourceFilename}
                              </div>
                              <div className="mt-1 truncate text-[#8d95ae]">{item.kindLabel}</div>
                            </div>
                          </button>
                        ))}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div className="rounded-[18px] border border-[rgba(139,147,172,0.14)] bg-white p-4 dark:border-white/10 dark:bg-[#121829]">
              <div className="space-y-2">
                {(list.items ?? []).map((item) => (
                  <button
                    key={item.entryKey}
                    type="button"
                    onClick={() => setSelectedKey(item.entryKey)}
                    className={`grid w-full grid-cols-[130px,1fr,120px,70px] items-center gap-3 rounded-[14px] px-3 py-3 text-left text-[12px] transition ${
                      selectedKey === item.entryKey
                        ? "bg-[#f7f4ff]"
                        : "hover:bg-[#fafbff] dark:hover:bg-white/5"
                    }`}
                  >
                    <div className="text-[#8d95ae]">{item.savedDate ?? "N/A"}</div>
                    <div className="min-w-0">
                      <div className="truncate font-medium text-[#1b2440] dark:text-white">
                        {item.sourceFilename}
                      </div>
                      <div className="truncate text-[#8d95ae]">{item.kindLabel}</div>
                    </div>
                    <div className="truncate text-[#606b89] dark:text-[#b1bcda]">{item.method}</div>
                    <div className="text-right">
                      <Badge tone={item.status === "ok" ? "success" : "danger"}>
                        {item.status === "ok" ? "Succes" : "Erreur"}
                      </Badge>
                    </div>
                  </button>
                ))}
              </div>
            </div>
          </div>
        )}

        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="text-[12px] text-[#8d95ae]">
            Page {list?.pagination.page ?? 1} / {list?.pagination.totalPages ?? 1}
          </div>
          <div className="flex items-center gap-2 text-[12px] text-[#8d95ae]">
            <button
              type="button"
              onClick={() => setPage((current) => Math.max(1, current - 1))}
              disabled={!list || list.pagination.page <= 1}
              className="flex h-8 w-8 items-center justify-center rounded-lg border border-[rgba(139,147,172,0.18)] bg-white transition hover:bg-[#f6f8ff] disabled:cursor-not-allowed disabled:opacity-45 dark:border-white/10 dark:bg-[#0f1525] dark:hover:bg-white/5"
              title="Page precedente"
            >
              <ChevronLeft className="h-4 w-4" />
            </button>
            <span>{list?.pagination.total ?? 0} extraction(s)</span>
            <button
              type="button"
              onClick={() =>
                setPage((current) => Math.min(list?.pagination.totalPages ?? 1, current + 1))
              }
              disabled={!list || list.pagination.page >= list.pagination.totalPages}
              className="flex h-8 w-8 items-center justify-center rounded-lg border border-[rgba(139,147,172,0.18)] bg-white transition hover:bg-[#f6f8ff] disabled:cursor-not-allowed disabled:opacity-45 dark:border-white/10 dark:bg-[#0f1525] dark:hover:bg-white/5"
              title="Page suivante"
            >
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>
        </div>
      </Card>
    </div>
  );
}
