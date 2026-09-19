"use client";

import { CheckCircle2, ChevronLeft, ChevronRight, Download, FileText, Search, ShieldCheck, Trash2, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { PageHeader } from "@/components/page-header";
import { ResultDetail } from "@/components/result-detail";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import {
  deleteHistoryEntry,
  downloadHistoryReport,
  downloadHistoryZip,
  fetchHistory,
  fetchHistoryDetail,
  resolveApiUrl
} from "@/lib/api";
import { readSessionValue, storageKeys } from "@/lib/storage";
import type { HistoryDetail, HistoryItem, HistoryListPayload } from "@/lib/types";

const documentTypeFilters = [
  { value: "steg", label: "Facture STEG", query: "facture steg" },
  { value: "medical", label: "Analyse medicale", query: "analyse medicale" },
  { value: "receipt", label: "Ticket de caisse", query: "ticket" },
  { value: "supplier", label: "Facture fournisseur", query: "facture fournisseur" },
] as const;

function typeFilterQuery(typeFilter: string, search: string) {
  const selected = documentTypeFilters.find((item) => item.value === typeFilter)?.query ?? "";
  return selected || search.trim();
}

function isImageSource(filename: string) {
  return /\.(png|jpe?g|webp|gif|bmp|tiff?)$/i.test(filename);
}

function qualityLabel(score: number | null) {
  if (score === null || Number.isNaN(score)) {
    return "Score qualite N/A";
  }
  if (score < 50) {
    return `A verifier ${score.toFixed(1)}%`;
  }
  if (score < 75) {
    return `Correct ${score.toFixed(1)}%`;
  }
  return `Fiable ${score.toFixed(1)}%`;
}

function qualityClass(score: number | null) {
  if (score === null) {
    return "text-[#8d95ae]";
  }
  if (score < 50) {
    return "text-[#df4d64]";
  }
  if (score < 75) {
    return "text-[#b88607]";
  }
  return "text-[#2eb764]";
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
      cache: "no-store"
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
    <div className="flex h-14 w-16 shrink-0 items-center justify-center overflow-hidden rounded-xl border border-[rgba(139,147,172,0.14)] bg-[#eef2fb] dark:border-white/10 dark:bg-[#0b1020]">
      {previewUrl ? (
        <img alt={item.sourceFilename} className="h-full w-full object-cover" src={previewUrl} />
      ) : (
        <FileText className="h-6 w-6 text-[#7c4dff]" />
      )}
    </div>
  );
}

export default function DocumentsPage() {
  const [requestedEntryKey, setRequestedEntryKey] = useState("");
  const [search, setSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [page, setPage] = useState(1);
  const [data, setData] = useState<HistoryListPayload | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [selectedEntryKeys, setSelectedEntryKeys] = useState<string[]>([]);
  const [focusedEntryKey, setFocusedEntryKey] = useState("");
  const [focusedDetail, setFocusedDetail] = useState<HistoryDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    const params = new URLSearchParams(window.location.search);
    setRequestedEntryKey(params.get("entry") ?? "");
  }, []);

  useEffect(() => {
    const params = new URLSearchParams({ page: String(page), pageSize: "12" });
    const query = typeFilterQuery(typeFilter, search);
    if (query) {
      params.set("typeQuery", query);
    }

    fetchHistory(params)
      .then((payload) => {
        setData(payload);
        if (payload.pagination.page !== page) {
          setPage(payload.pagination.page);
        }
        setSelectedEntryKeys((current) =>
          current.filter((entryKey) => payload.items.some((item) => item.entryKey === entryKey))
        );

        if (focusedEntryKey && !payload.items.some((item) => item.entryKey === focusedEntryKey)) {
          setFocusedEntryKey("");
          setFocusedDetail(null);
          setDetailError("");
        }
      })
      .catch((err: Error) => setError(err.message));
  }, [focusedEntryKey, page, refreshKey, search, typeFilter]);

  const visibleEntryKeys = useMemo(
    () => data?.items.map((item) => item.entryKey) ?? [],
    [data]
  );

  const allVisibleSelected =
    visibleEntryKeys.length > 0 && visibleEntryKeys.every((entryKey) => selectedEntryKeys.includes(entryKey));

  const selectedItems =
    data?.items.filter((item) => selectedEntryKeys.includes(item.entryKey)) ?? [];
  const selectedTypeLabel =
    documentTypeFilters.find((item) => item.value === typeFilter)?.label ?? "Tous les types";

  const toggleEntry = (entryKey: string) => {
    setSelectedEntryKeys((current) =>
      current.includes(entryKey)
        ? current.filter((item) => item !== entryKey)
        : [...current, entryKey]
    );
    setNotice("");
  };

  const toggleAllVisible = () => {
    if (!visibleEntryKeys.length) {
      return;
    }

    setSelectedEntryKeys((current) => {
      if (allVisibleSelected) {
        return current.filter((entryKey) => !visibleEntryKeys.includes(entryKey));
      }
      return Array.from(new Set([...current, ...visibleEntryKeys]));
    });
    setNotice("");
  };

  const openDocumentDetail = (entryKey: string) => {
    setFocusedEntryKey(entryKey);
    setDetailLoading(true);
    setDetailError("");
    setFocusedDetail(null);
    fetchHistoryDetail(entryKey)
      .then(setFocusedDetail)
      .catch((err: Error) => {
        setFocusedDetail(null);
        setDetailError(err.message);
      })
      .finally(() => setDetailLoading(false));
  };

  useEffect(() => {
    if (!requestedEntryKey || requestedEntryKey === focusedEntryKey) {
      return;
    }
    openDocumentDetail(requestedEntryKey);
  }, [focusedEntryKey, requestedEntryKey]);

  const closeDocumentDetail = () => {
    setFocusedEntryKey("");
    setFocusedDetail(null);
    setDetailError("");
    setDetailLoading(false);
    setRequestedEntryKey("");

    if (typeof window !== "undefined") {
      const url = new URL(window.location.href);
      url.searchParams.delete("entry");
      window.history.replaceState({}, "", url.pathname + url.search);
    }
  };

  const isDetailModalOpen =
    Boolean(focusedEntryKey) || detailLoading || Boolean(focusedDetail) || Boolean(detailError);

  useEffect(() => {
    if (!isDetailModalOpen || typeof window === "undefined") {
      return;
    }

    const previousOverflow = document.body.style.overflow;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        closeDocumentDetail();
      }
    };

    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [isDetailModalOpen]);

  const sourceFilenameForEntry = (entryKey: string) =>
    data?.items.find((item) => item.entryKey === entryKey)?.sourceFilename ??
    (focusedDetail?.entryKey === entryKey ? focusedDetail.sourceFilename : "document");

  const exportSelectedDocuments = async () => {
    if (selectedEntryKeys.length > 1) {
      try {
        await downloadHistoryZip(selectedEntryKeys);
        setNotice(`${selectedEntryKeys.length} document(s) exporte(s) en ZIP.`);
      } catch (err) {
        setNotice(err instanceof Error ? err.message : "Export ZIP impossible.");
      }
      return;
    }

    const singleEntryKey = selectedEntryKeys[0] ?? focusedEntryKey;
    if (singleEntryKey) {
      try {
        await downloadHistoryReport(singleEntryKey, sourceFilenameForEntry(singleEntryKey));
        setNotice("Le rapport PDF du document selectionne a ete telecharge.");
      } catch (err) {
        setNotice(err instanceof Error ? err.message : "Export PDF impossible.");
      }
      return;
    }

    setNotice("Clique sur un document pour afficher son detail, ou coche plusieurs documents pour un export ZIP.");
  };

  const exportFocusedDocument = async () => {
    if (!focusedEntryKey) {
      setNotice("Clique d'abord sur un document pour afficher son detail.");
      return;
    }

    try {
      await downloadHistoryReport(focusedEntryKey, sourceFilenameForEntry(focusedEntryKey));
      setNotice("Le rapport PDF du document affiche a ete telecharge.");
    } catch (err) {
      setNotice(err instanceof Error ? err.message : "Export PDF impossible.");
    }
  };

  const trashSelectedDocuments = async () => {
    if (!selectedEntryKeys.length) {
      setNotice("Coche un ou plusieurs documents a supprimer.");
      return;
    }

    try {
      for (const entryKey of selectedEntryKeys) {
        await deleteHistoryEntry(entryKey);
      }
      const deletedCount = selectedEntryKeys.length;
      setSelectedEntryKeys([]);
      if (selectedEntryKeys.includes(focusedEntryKey)) {
        closeDocumentDetail();
      }
      setNotice(
        deletedCount > 1
          ? `${deletedCount} documents deplaces vers la corbeille.`
          : "Document deplace vers la corbeille."
      );
      setRefreshKey((current) => current + 1);
    } catch (err) {
      setNotice(err instanceof Error ? err.message : "Suppression impossible.");
    }
  };

  const trashFocusedDocument = async () => {
    if (!focusedEntryKey) {
      setNotice("Clique d'abord sur un document pour afficher son detail.");
      return;
    }

    try {
      const response = await deleteHistoryEntry(focusedEntryKey);
      setSelectedEntryKeys((current) => current.filter((entryKey) => entryKey !== focusedEntryKey));
      closeDocumentDetail();
      setNotice(response.message);
      setRefreshKey((current) => current + 1);
    } catch (err) {
      setNotice(err instanceof Error ? err.message : "Mise en corbeille impossible.");
    }
  };

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="4. DOCUMENTS (Liste des documents)"
        title="Documents"
        description="Consulte, filtre et exporte la liste complete des documents deja traites."
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
                  setNotice("");
                }}
                placeholder="Rechercher par type..."
                className="pl-9"
              />
            </div>
            <Select
              className="max-w-[220px]"
              value={typeFilter}
              onChange={(event) => {
                setTypeFilter(event.target.value);
                setPage(1);
                setNotice("");
              }}
            >
              <option value="">Tous les types</option>
              {documentTypeFilters.map((kind) => (
                <option key={kind.value} value={kind.value}>
                  {kind.label}
                </option>
              ))}
            </Select>
          </div>
          <div className="flex flex-wrap items-center gap-2 xl:justify-end">
            <Button
              variant="danger"
              className="gap-2"
              onClick={trashSelectedDocuments}
              disabled={!selectedEntryKeys.length}
            >
              <Trash2 className="h-4 w-4" />
              {selectedEntryKeys.length > 1 ? "Supprimer la selection" : "Supprimer"}
            </Button>
            <Button variant="success" className="gap-2" onClick={exportSelectedDocuments}>
              <Download className="h-4 w-4" />
              {selectedEntryKeys.length > 1
                ? "Exporter la selection"
                : focusedEntryKey || selectedEntryKeys.length === 1
                  ? "Exporter le document"
                  : "Exporter"}
            </Button>
          </div>
        </div>

        {error ? (
          <div className="text-sm text-[#df4d64]">{error}</div>
        ) : !data ? (
          <div className="text-sm text-[#7a83a2]">Chargement des documents...</div>
        ) : (
          <>
            <div className="flex flex-wrap items-center justify-between gap-2 text-[12px] text-[#7a83a2] dark:text-[#aeb7d2]">
              <span>
                {selectedItems.length
                  ? `${selectedItems.length} document(s) selectionne(s)`
                  : "Recherche par type uniquement : Facture STEG, Analyse medicale, Ticket de caisse ou Facture fournisseur."}
              </span>
              <span>
                Type filtre : {selectedTypeLabel}
              </span>
            </div>

            <div className="space-y-2">
              <div className="grid grid-cols-[auto,70px,minmax(0,1fr),auto,auto] items-center gap-3 px-2 text-[11px] font-semibold uppercase tracking-[0.08em] text-[#8d95ae]">
                <button
                  type="button"
                  onClick={toggleAllVisible}
                  className="mt-0.5 flex h-4 w-4 items-center justify-center rounded border border-[rgba(139,147,172,0.28)]"
                  title={allVisibleSelected ? "Tout deselectionner" : "Tout selectionner"}
                >
                  {allVisibleSelected ? <span className="h-2 w-2 rounded-sm bg-[#7c4dff]" /> : null}
                </button>
                <span />
                <span>Document</span>
                <span className="hidden xl:block">Date</span>
                <span className="text-right">Statut</span>
              </div>

              {data.items.map((item) => {
                const checked = selectedEntryKeys.includes(item.entryKey);
                const focused = focusedEntryKey === item.entryKey;

                return (
                  <div
                    key={item.entryKey}
                    role="button"
                    tabIndex={0}
                    onClick={() => openDocumentDetail(item.entryKey)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        openDocumentDetail(item.entryKey);
                      }
                    }}
                    className={`grid w-full grid-cols-[auto,70px,minmax(0,1fr),auto,auto] items-center gap-3 rounded-[18px] border px-3 py-3 text-left transition ${
                      focused
                        ? "border-[#cfdcff] bg-[#eef4ff] shadow-[0_8px_24px_rgba(81,108,201,0.08)] dark:border-[#29406f] dark:bg-[#132038]"
                        : checked
                          ? "border-[#e1d5ff] bg-[#f6f2ff] dark:border-[#453071] dark:bg-[#1a1630]"
                          : "border-[rgba(139,147,172,0.12)] bg-[#fbfcff] hover:bg-[#fafbff] dark:border-white/10 dark:bg-[#0f1525] dark:hover:bg-white/5"
                    }`}
                  >
                    <div onClick={(event) => event.stopPropagation()}>
                      <button
                        type="button"
                        onClick={() => toggleEntry(item.entryKey)}
                        className={`flex h-5 w-5 items-center justify-center rounded border transition ${
                          checked
                            ? "border-[#7c4dff] bg-[#7c4dff]"
                            : "border-[rgba(139,147,172,0.28)] bg-white dark:bg-transparent"
                        }`}
                        title={checked ? "Deselectionner" : "Selectionner"}
                      >
                        {checked ? <span className="h-2 w-2 rounded-full bg-white" /> : null}
                      </button>
                    </div>

                    <SourceThumbnail item={item} />

                    <div className="min-w-0">
                      <div className="truncate font-semibold text-[#1b2440] dark:text-white">
                        {item.sourceFilename}
                      </div>
                      <div className="mt-1 flex flex-wrap items-center gap-2 text-[12px] text-[#606b89] dark:text-[#b1bcda]">
                        <span className="truncate">{item.kindLabel}</span>
                        <Badge tone={item.method.includes("Gemini") ? "purple" : "default"}>
                          {item.method}
                        </Badge>
                        <span
                          className={`font-semibold ${qualityClass(item.qualityScore)}`}
                          title="Score qualite: indique si les champs importants ont ete bien detectes."
                        >
                          {qualityLabel(item.qualityScore)}
                        </span>
                      </div>
                    </div>

                    <div className="hidden text-[12px] text-[#606b89] dark:text-[#b1bcda] xl:block">
                      {item.savedDate ?? "N/A"}
                    </div>

                    <div className="flex justify-end">
                      <Badge tone={item.status === "ok" ? "success" : "danger"}>
                        {item.status === "ok" ? "Succes" : "Erreur"}
                      </Badge>
                    </div>
                  </div>
                );
              })}
            </div>

            <div className="flex flex-wrap items-center justify-end gap-2 text-[12px] text-[#8d95ae]">
              <button
                type="button"
                onClick={() => setPage((current) => Math.max(1, current - 1))}
                disabled={data.pagination.page <= 1}
                className="flex h-8 w-8 items-center justify-center rounded-lg border border-[rgba(139,147,172,0.18)] bg-white transition hover:bg-[#f6f8ff] disabled:cursor-not-allowed disabled:opacity-45 dark:border-white/10 dark:bg-[#0f1525] dark:hover:bg-white/5"
                title="Page precedente"
              >
                <ChevronLeft className="h-4 w-4" />
              </button>
              <span className="flex h-8 min-w-8 items-center justify-center rounded-lg bg-[#f3efff] px-2 font-semibold text-[#7c4dff]">
                {data.pagination.page}
              </span>
              <span>/ {data.pagination.totalPages}</span>
              <button
                type="button"
                onClick={() =>
                  setPage((current) => Math.min(data.pagination.totalPages, current + 1))
                }
                disabled={data.pagination.page >= data.pagination.totalPages}
                className="flex h-8 w-8 items-center justify-center rounded-lg border border-[rgba(139,147,172,0.18)] bg-white transition hover:bg-[#f6f8ff] disabled:cursor-not-allowed disabled:opacity-45 dark:border-white/10 dark:bg-[#0f1525] dark:hover:bg-white/5"
                title="Page suivante"
              >
                <ChevronRight className="h-4 w-4" />
              </button>
              <span className="ml-2">{data.pagination.total} document(s)</span>
            </div>
            {notice ? <div className="text-[12px] text-[#7455f2] dark:text-[#c7b7ff]">{notice}</div> : null}
          </>
        )}
      </Card>

      {isDetailModalOpen ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-[rgba(12,18,32,0.58)] px-4 py-6 backdrop-blur-[5px]"
          onClick={closeDocumentDetail}
        >
          <div
            className="max-h-[92vh] w-full max-w-[1380px] overflow-auto rounded-[26px] border border-[rgba(139,147,172,0.18)] bg-white p-4 shadow-[0_28px_90px_rgba(8,14,28,0.32)] dark:border-white/10 dark:bg-[#101625] md:p-5"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
              <div className="flex min-w-0 items-start gap-3">
                <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-[#f1ebff] text-[#7c4dff] shadow-[0_10px_24px_rgba(124,77,255,0.12)] dark:bg-[#21183a]">
                  <FileText className="h-5 w-5" />
                </div>
                <div className="min-w-0">
                  <div className="text-[20px] font-bold text-[#071a3d] dark:text-white">
                    Detail du document
                  </div>
                  <div className="mt-1 text-[12px] text-[#7a83a2] dark:text-[#aeb7d2]">
                    Consulte le contenu extrait et les informations du document.
                  </div>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <Button variant="danger" size="sm" className="gap-2 rounded-xl" onClick={trashFocusedDocument}>
                  <Trash2 className="h-4 w-4" />
                  Supprimer
                </Button>
                <Button variant="success" size="sm" className="gap-2 rounded-xl" onClick={exportFocusedDocument}>
                  <Download className="h-4 w-4" />
                  Exporter ce document
                </Button>
                <button
                  type="button"
                  onClick={closeDocumentDetail}
                  className="flex h-10 w-10 items-center justify-center rounded-2xl border border-[rgba(139,147,172,0.18)] bg-[#fbfcff] text-[#5f6888] transition hover:bg-[#f3f6ff] dark:border-white/10 dark:bg-[#0f1525] dark:text-[#b7c1de] dark:hover:bg-[#151c30]"
                  title="Fermer"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>
            </div>

            {detailError ? (
              <div className="rounded-[16px] border border-[rgba(223,77,100,0.18)] bg-[#fff5f7] px-4 py-3 text-sm text-[#df4d64] dark:border-[rgba(223,77,100,0.32)] dark:bg-[#2b1520]">
                {detailError}
              </div>
            ) : detailLoading ? (
              <Card>Chargement du detail du document...</Card>
            ) : focusedDetail ? (
              <>
                <div className="mb-4 grid gap-3 md:grid-cols-2 xl:grid-cols-[1.25fr,1.25fr,0.75fr]">
                  <div className="flex min-w-0 items-center gap-3 rounded-[16px] border border-[rgba(139,147,172,0.14)] bg-[#fbfcff] px-4 py-3 text-[12px] shadow-[0_10px_28px_rgba(19,29,61,0.035)] dark:border-white/10 dark:bg-[#0f1525]">
                    <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl bg-[#f1ebff] text-[#7c4dff] dark:bg-[#21183a]">
                      <FileText className="h-5 w-5" />
                    </div>
                    <div className="min-w-0">
                      <div className="font-semibold text-[#8d95ae]">Document</div>
                      <div className="mt-1 truncate font-semibold text-[#1b2440] dark:text-white">
                        {focusedDetail.sourceFilename}
                      </div>
                    </div>
                  </div>
                  <div className="flex min-w-0 items-center gap-3 rounded-[16px] border border-[rgba(139,147,172,0.14)] bg-[#fbfcff] px-4 py-3 text-[12px] shadow-[0_10px_28px_rgba(19,29,61,0.035)] dark:border-white/10 dark:bg-[#0f1525]">
                    <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl bg-[#edf3ff] text-[#3f6df6] dark:bg-[#182642]">
                      <ShieldCheck className="h-5 w-5" />
                    </div>
                    <div className="min-w-0">
                      <div className="font-semibold text-[#8d95ae]">Type detecte</div>
                      <div className="mt-1 truncate font-semibold text-[#1b2440] dark:text-white">
                        {focusedDetail.kindLabel}
                      </div>
                    </div>
                  </div>
                  <div className="flex min-w-0 items-center justify-between gap-3 rounded-[16px] border border-[rgba(139,147,172,0.14)] bg-[#fbfcff] px-4 py-3 text-[12px] shadow-[0_10px_28px_rgba(19,29,61,0.035)] dark:border-white/10 dark:bg-[#0f1525]">
                    <div className="min-w-0">
                      <div className="font-semibold text-[#8d95ae]">Statut</div>
                      <div className="mt-1">
                        <Badge tone={focusedDetail.status === "ok" ? "success" : "danger"}>
                          {focusedDetail.status === "ok" ? "Succes" : "Erreur"}
                        </Badge>
                      </div>
                    </div>
                    <CheckCircle2 className={`h-5 w-5 ${focusedDetail.status === "ok" ? "text-[#30c56f]" : "text-[#df4d64]"}`} />
                  </div>
                </div>
                <ResultDetail detail={focusedDetail} layout="stacked" />
              </>
            ) : (
              <Card>Aucun detail affiche pour le moment.</Card>
            )}
          </div>
        </div>
      ) : null}
    </div>
  );
}
