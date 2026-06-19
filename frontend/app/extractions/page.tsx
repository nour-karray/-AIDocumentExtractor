"use client";

import {
  Check,
  CloudUpload,
  FileStack,
  Info,
  LoaderCircle,
  Plus
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { fetchMeta, uploadExtractions } from "@/lib/api";
import {
  readStoredValue,
  storageKeys,
  writeStoredValue,
} from "@/lib/storage";
import type { ExtractionBatchPayload, MetaPayload } from "@/lib/types";
import type { DragEvent } from "react";

const localConfig = {
  label: "Pipeline IA local",
  provider: "Ollama",
  defaultHost: "http://127.0.0.1:11434",
  defaultModel: "qwen2.5:7b-instruct",
} as const;

const fallbackMethods = [
  { value: "local", label: "Pipeline IA local (Docling + PaddleOCR + Qwen2.5)" },
] as const;

const ACCEPTED_EXTENSIONS = new Set(["jpg", "jpeg", "png", "tif", "tiff", "pdf"]);

const modeVisuals: Record<string, { title: string; hint: string }> = {
  auto: { title: "Auto", hint: "Detection intelligente" },
  medical: { title: "Analyse medicale", hint: "Labo & comptes rendus" },
  steg: { title: "Facture STEG", hint: "Electricite & facture" },
  supplier: { title: "Facture fournisseur", hint: "B2B generique" },
  receipt: { title: "Ticket de caisse", hint: "Recu & ticket" },
};

function isSupportedFile(file: File) {
  const extension = file.name.split(".").pop()?.toLowerCase() ?? "";
  return ACCEPTED_EXTENSIONS.has(extension) || file.type.startsWith("image/") || file.type === "application/pdf";
}

function resolveAllowedMethods(meta: MetaPayload) {
  return meta.methods;
}

function resolveInitialMethod(meta: MetaPayload) {
  if (resolveAllowedMethods(meta).some((item) => item.value === "local")) {
    return "local";
  }
  return resolveAllowedMethods(meta)[0]?.value ?? "local";
}

function resolveStoredMethod(meta: MetaPayload) {
  const allowedMethods = resolveAllowedMethods(meta);
  const storedMethod =
    readStoredValue(storageKeys.defaultMethod, "") ||
    readStoredValue(storageKeys.aiProvider, "");

  if (storedMethod && allowedMethods.some((item) => item.value === storedMethod)) {
    return storedMethod;
  }

  return resolveInitialMethod(meta);
}

export default function ExtractionsPage() {
  const router = useRouter();
  const [meta, setMeta] = useState<MetaPayload | null>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [mode, setMode] = useState("auto");
  const [method, setMethod] = useState("local");
  const [ollamaHost, setOllamaHost] = useState<string>(localConfig.defaultHost);
  const [localModel, setLocalModel] = useState<string>(localConfig.defaultModel);
  const [geminiApiKey, setGeminiApiKey] = useState("");
  const [geminiModel, setGeminiModel] = useState("");
  const [previewUrl, setPreviewUrl] = useState("");
  const [dragActive, setDragActive] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [result, setResult] = useState<ExtractionBatchPayload | null>(null);

  useEffect(() => {
    fetchMeta()
      .then((payload) => {
        setMeta(payload);
        setOllamaHost(readStoredValue(storageKeys.ollamaHost, payload.defaultOllamaHost ?? localConfig.defaultHost));
        setLocalModel(readStoredValue(storageKeys.localModel, payload.defaultLocalModel ?? localConfig.defaultModel));
        setGeminiModel(payload.defaultGeminiModel);
        const initialMethod = resolveStoredMethod(payload);
        setMethod(initialMethod);
        writeStoredValue(storageKeys.defaultMethod, initialMethod);
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : "Backend DocuAI non joignable.");
      });
  }, []);

  const availableMethods = useMemo(
    () => (meta ? resolveAllowedMethods(meta) : []),
    [meta]
  );

  const extractionOptions = availableMethods.length ? availableMethods : fallbackMethods;

  const localPipelineIncomplete =
    method === "local" && meta?.localPipeline && !meta.localPipeline.available;
  const methodHelp = localPipelineIncomplete
    ? "Pipeline IA local incomplet : installe Docling, PaddleOCR et lance Ollama/Qwen2.5. OCR local classique reste disponible pour comparer ou depanner."
    : method === "local"
      ? "Mode par defaut : pretraitement, Docling, controle qualite, fallback PaddleOCR si besoin, puis extraction JSON par Qwen2.5 local via Ollama."
      : method === "ocr"
        ? "OCR local classique sans Qwen. Utile seulement pour comparer ou depanner."
        : "Ancien moteur conserve : Gemini API pour les documents complexes, avec une cle dans .env ou saisie ici pour la session.";

  useEffect(() => {
    if (!meta) {
      return;
    }

    if (availableMethods.length && !availableMethods.some((item) => item.value === method)) {
      const fallback = resolveInitialMethod(meta);
      setMethod(fallback);
      setInfo("La methode precedente n'est plus active. Extraction a bascule sur le moteur disponible.");
      return;
    }

    setInfo(
      method === "local" && meta?.localPipeline && !meta.localPipeline.available
        ? "Mode local par defaut selectionne. Installe Docling, PaddleOCR et lance Ollama/Qwen2.5 pour activer toute l'architecture hybride."
        : ""
    );
  }, [availableMethods, meta, method]);

  const previewFile = files[0] ?? null;
  const previewKind = previewFile
    ? previewFile.type === "application/pdf" || previewFile.name.toLowerCase().endsWith(".pdf")
      ? "pdf"
      : previewFile.type.startsWith("image/")
        ? "image"
        : "other"
    : "empty";

  useEffect(() => {
    if (!previewFile) {
      setPreviewUrl("");
      return;
    }

    const nextUrl = URL.createObjectURL(previewFile);
    setPreviewUrl(nextUrl);
    return () => URL.revokeObjectURL(nextUrl);
  }, [previewFile]);

  const handleSelectedFiles = (selected: File[]) => {
    const supported = selected.filter(isSupportedFile);
    if (!supported.length) {
      setError("Format non supporte. Utilise JPG, PNG, TIFF ou PDF.");
      return;
    }
    setFiles(supported);
    setResult(null);
    setError("");
  };

  const handleFileChange = (selected: FileList | null) => {
    if (!selected) {
      return;
    }
    handleSelectedFiles(Array.from(selected));
  };

  const handleDrop = (event: DragEvent<HTMLLabelElement>) => {
    event.preventDefault();
    event.stopPropagation();
    setDragActive(false);
    handleSelectedFiles(Array.from(event.dataTransfer.files));
  };

  const handleDrag = (event: DragEvent<HTMLLabelElement>, active: boolean) => {
    event.preventDefault();
    event.stopPropagation();
    setDragActive(active);
  };

  const runExtraction = async () => {
    if (!files.length) {
      setError("Ajoute au moins un document avant de lancer l'extraction.");
      return;
    }

    setLoading(true);
    setError("");

    const form = new FormData();
    const origins = files.map((file) => {
      const relative = (file as File & { webkitRelativePath?: string }).webkitRelativePath;
      return relative ? relative.split("/").slice(0, -1).join("/") || "upload" : "upload";
    });

    files.forEach((file) => {
      form.append("files", file, file.name);
    });
    form.append("mode", mode);
    form.append("method", method);
    form.append("geminiApiKey", geminiApiKey);
    form.append("geminiModel", geminiModel);
    form.append("ollamaHost", ollamaHost);
    form.append("localModel", localModel);
    form.append("retries", "5");
    form.append("retryDelay", "2");
    form.append("originsJson", JSON.stringify(origins));

    try {
      const response = await uploadExtractions(form);
      setResult(response);
      const firstError = response.items.find((item) => item.status === "error")?.error;
      if (response.summary.errorCount > 0) {
        setError(
          response.summary.okCount > 0
            ? `${response.summary.errorCount} fichier(s) en erreur. Consulte le resume ci-dessous.`
            : firstError || "Extraction impossible. Verifie la configuration du pipeline local."
        );
      } else {
        setError("");
      }
      writeStoredValue(storageKeys.lastExtraction, JSON.stringify(response));
      writeStoredValue(storageKeys.aiProvider, method);
      writeStoredValue(storageKeys.ollamaHost, ollamaHost);
      writeStoredValue(storageKeys.localModel, localModel);
      writeStoredValue(storageKeys.defaultMethod, method);
      if (response.latestSuccess?.historyEntryKey) {
        router.push(`/documents?entry=${response.latestSuccess.historyEntryKey}`);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erreur extraction a verifier.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="2. EXTRACTION (Nouvelle extraction)"
        title="Nouvelle extraction"
        description="Importe tes documents, puis lance le pipeline IA local Docling + PaddleOCR + Qwen2.5 par defaut."
      />

      <div className="flex flex-wrap items-center gap-4 rounded-[18px] border border-[rgba(139,147,172,0.14)] bg-[#fbfcff] px-4 py-3 text-[12px] text-[#5e6888] dark:border-white/10 dark:bg-[#0f1525] dark:text-[#b1bcda]">
        {["Importer", "Configurer", "Traiter", "Resultats"].map((step, index) => (
          <div key={step} className="flex items-center gap-3">
            <span
              className={`flex h-6 w-6 items-center justify-center rounded-full border text-[11px] font-bold ${
                index === 0
                  ? "border-[#89d9ac] bg-[#edf9f1] text-[#2eb764] dark:border-[#1f6b41] dark:bg-[#11271d] dark:text-[#86f7b6]"
                  : "border-[rgba(139,147,172,0.18)] bg-white text-[#8d95ae] dark:border-white/10 dark:bg-[#101625] dark:text-[#9ca6c6]"
              }`}
            >
              {index + 1}
            </span>
            <span className="font-semibold">{step}</span>
            {index < 3 ? <span className="text-[#ccd2e3]"> </span> : null}
          </div>
        ))}
      </div>

      <div className="grid gap-4 xl:grid-cols-[1.06fr,0.64fr]">
        <div className="space-y-4">
          <Card>
            <div className="mb-4 proto-title text-[15px] font-bold text-[#1b2440] dark:text-white">
              Importer vos documents
            </div>
            <div className="mb-4 text-[12px] text-[#8d95ae]">
              Glissez-deposez vos fichiers ici ou parcourez.
            </div>
            <label
              onDragEnter={(event) => handleDrag(event, true)}
              onDragOver={(event) => handleDrag(event, true)}
              onDragLeave={(event) => handleDrag(event, false)}
              onDrop={handleDrop}
              className={`flex min-h-[240px] cursor-pointer flex-col items-center justify-center gap-4 rounded-[18px] border border-dashed px-6 py-8 text-center transition ${
                dragActive
                  ? "border-[#7c4dff] bg-[#f4efff] shadow-[0_14px_28px_rgba(124,77,255,0.12)] dark:border-[#9277ff] dark:bg-[#15172b]"
                  : "border-[rgba(124,77,255,0.28)] bg-[#fcfbff] dark:border-[#4a3f78] dark:bg-[#0f1525]"
              }`}
            >
              <div className="flex h-14 w-14 items-center justify-center rounded-full border border-[rgba(139,147,172,0.16)] bg-white text-[#7c4dff] dark:border-white/10 dark:bg-[#121829]">
                <CloudUpload className="h-7 w-7" />
              </div>
              <div>
                <div className="proto-title text-[18px] font-bold text-[#1b2440] dark:text-white">
                  Glissez vos fichiers ici
                </div>
                <div className="mt-1 text-[12px] text-[#8d95ae]">ou</div>
              </div>
              <input
                className="hidden"
                type="file"
                accept=".jpg,.jpeg,.png,.tif,.tiff,.pdf"
                multiple
                onChange={(event) => handleFileChange(event.target.files)}
              />
              <span className="inline-flex h-10 items-center rounded-xl bg-gradient-to-r from-[#7c4dff] to-[#6d43f0] px-4 text-sm font-semibold text-white">
                Parcourir les fichiers
              </span>
            </label>

            {previewFile ? (
              <div className="mt-5 overflow-hidden rounded-[18px] border border-[rgba(139,147,172,0.14)] bg-[#fbfcff] dark:border-white/10 dark:bg-[#0f1525]">
                <div className="flex items-center justify-between gap-3 border-b border-[rgba(139,147,172,0.12)] px-4 py-3 dark:border-white/10">
                  <div className="min-w-0">
                    <div className="text-[12px] font-semibold text-[#687292]">Apercu du document</div>
                    <div className="truncate text-[12px] text-[#1b2440] dark:text-white">{previewFile.name}</div>
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    <Badge tone="purple">
                      {previewKind === "pdf" ? "PDF" : previewKind === "image" ? "Image" : "Fichier"}
                    </Badge>
                    <Button onClick={runExtraction} disabled={loading || !files.length} size="sm" className="min-w-[165px]">
                      <span>{loading ? "Traitement..." : "Lancer l'extraction"}</span>
                      {loading ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
                    </Button>
                  </div>
                </div>

                {previewUrl && previewKind === "pdf" ? (
                  <iframe
                    className="h-[560px] w-full bg-white"
                    src={previewUrl}
                    title={`Apercu ${previewFile.name}`}
                  />
                ) : null}

                {previewUrl && previewKind === "image" ? (
                  <div className="flex max-h-[560px] items-start justify-center overflow-auto bg-[#f5f7fb] p-3 dark:bg-[#0b1020]">
                    <img
                      alt={`Apercu ${previewFile.name}`}
                      className="max-h-[520px] max-w-full rounded-xl border border-[rgba(139,147,172,0.14)] bg-white object-contain dark:border-white/10"
                      src={previewUrl}
                    />
                  </div>
                ) : null}

                {previewKind === "other" ? (
                  <div className="px-4 py-6 text-[12px] text-[#8d95ae]">
                    Ce type de fichier est charge, mais l'apercu navigateur n'est pas disponible.
                  </div>
                ) : null}
              </div>
            ) : null}

            <div className="mt-5">
              <div className="mb-3 text-[12px] font-semibold text-[#687292]">Type de documents</div>
              <div className="grid gap-3 sm:grid-cols-5">
                {meta?.modes.map((item) => {
                  const visual = modeVisuals[item.value] ?? { title: item.label, hint: "" };
                  const active = mode === item.value;
                  return (
                    <button
                      key={item.value}
                      type="button"
                      onClick={() => setMode(item.value)}
                      className={`rounded-[16px] border p-3 text-left transition ${
                        active
                          ? "border-[#89d9ac] bg-[#edf9f1] shadow-[0_8px_20px_rgba(46,183,100,0.1)] dark:border-[#1f6b41] dark:bg-[#11271d]"
                          : "border-[rgba(139,147,172,0.14)] bg-white hover:bg-[#fafbff] dark:border-white/10 dark:bg-[#121829] dark:hover:bg-[#141c2e]"
                      }`}
                    >
                      <div className="proto-title text-[13px] font-bold text-[#1b2440] dark:text-white">
                        {visual.title}
                      </div>
                      <div className="mt-1 text-[11px] text-[#8d95ae]">{visual.hint}</div>
                    </button>
                  );
                })}
              </div>
            </div>
          </Card>

          <Card>
            <div className="mb-3 flex items-center gap-2 text-[13px] font-semibold text-[#1b2440] dark:text-white">
              <Info className="h-4 w-4 text-[#7c4dff]" />
              Informations
            </div>
            <ul className="space-y-2 text-[12px] text-[#6b7594] dark:text-[#b1bcda]">
              <li>Formats supportes : JPG, PNG, PDF</li>
              <li>Taille max : 20 Mo par fichier</li>
              <li>Pipeline principal : Docling + PaddleOCR fallback + Qwen2.5 local</li>
            </ul>
          </Card>
        </div>

        <div className="space-y-4">
          <Card className="space-y-4">
            <div className="proto-title text-[15px] font-bold text-[#1b2440] dark:text-white">
              Configuration
            </div>

            <div className="space-y-2">
              <div className="text-[12px] font-semibold text-[#687292]">Methode d'extraction</div>
              <Select
                value={method}
                onChange={(event) => {
                  const nextValue = event.target.value;
                  setMethod(nextValue);
                  writeStoredValue(storageKeys.aiProvider, nextValue);
                  writeStoredValue(storageKeys.defaultMethod, nextValue);
                }}
              >
                {extractionOptions.map((item) => (
                  <option key={item.value} value={item.value}>
                    {item.label}
                  </option>
                ))}
              </Select>
              <div className={`rounded-xl px-3 py-2 text-[11px] ${
                localPipelineIncomplete
                  ? "bg-[#fff7e6] text-[#b26b00] dark:bg-[#2c210e] dark:text-[#ffd08a]"
                  : "bg-[#eef9f0] text-[#2eb764] dark:bg-[#11271d] dark:text-[#86f7b6]"
              }`}>
                {methodHelp}
              </div>
            </div>

            <div className="space-y-2">
              <div className="text-[12px] font-semibold text-[#687292]">Langue du document</div>
              <Select defaultValue="Francais">
                <option>Francais</option>
                <option>Anglais</option>
                <option>Arabe</option>
              </Select>
            </div>

            {method === "gemini" ? (
              <div className="space-y-3">
                <div className="space-y-2">
                  <div className="text-[12px] font-semibold text-[#687292]">Modele Gemini</div>
                  <Input
                    value={geminiModel}
                    onChange={(event) => setGeminiModel(event.target.value)}
                    placeholder={meta?.defaultGeminiModel ?? "gemini-2.5-flash"}
                  />
                  <div className="text-[12px] font-semibold text-[#687292]">Cle API Gemini</div>
                  <Input
                    type="password"
                    value={geminiApiKey}
                    onChange={(event) => setGeminiApiKey(event.target.value)}
                    placeholder={meta?.geminiConfigured ? "Cle deja configuree dans .env" : "GEMINI_API_KEY"}
                  />
                </div>
                <div className="rounded-[16px] border border-[rgba(139,147,172,0.14)] bg-[#fbfcff] p-3 text-[12px] text-[#6b7594] dark:border-white/10 dark:bg-[#0f1525] dark:text-[#b1bcda]">
                  <div className="mb-1 font-semibold text-[#1b2440] dark:text-white">Gemini API</div>
                  <div>Mode API conserve pour comparer avec le pipeline local ou traiter des documents complexes.</div>
                  <div className="mt-2">
                    Etat backend : cle Gemini {meta?.geminiConfigured ? "configuree dans .env" : "non configuree"}.
                  </div>
                </div>
              </div>
            ) : null}

            {method === "ocr" ? (
              <div className="rounded-[16px] border border-[rgba(139,147,172,0.14)] bg-[#fbfcff] p-3 text-[12px] text-[#6b7594] dark:border-white/10 dark:bg-[#0f1525] dark:text-[#b1bcda]">
                <div className="mb-1 font-semibold text-[#1b2440] dark:text-white">OCR local classique</div>
                <div>Mode sans Qwen conserve uniquement pour depanner ou comparer. Le moteur principal reste Docling + PaddleOCR + Qwen2.5.</div>
              </div>
            ) : null}

            {method === "local" ? (
            <div className="space-y-3">
              <div className="rounded-[16px] border border-[rgba(139,147,172,0.14)] bg-[#fbfcff] p-3 text-[12px] text-[#6b7594] dark:border-white/10 dark:bg-[#0f1525] dark:text-[#b1bcda]">
                <div className="mb-1 font-semibold text-[#1b2440] dark:text-white">{localConfig.label}</div>
                <div>Pipeline actif : document vers pretraitement, Docling, controle qualite, fallback PaddleOCR si besoin, puis JSON extrait par Qwen2.5 via Ollama.</div>
                <div className="mt-2">
                  Etat backend : Docling {meta?.localPipeline?.doclingAvailable ? "pret" : "non installe"} / PaddleOCR {meta?.localPipeline?.paddleocrAvailable ? "pret" : "non installe"} / Ollama {meta?.localPipeline?.ollamaAvailable ? "pret" : "non joignable"}.
                </div>
              </div>
            </div>
            ) : null}
          </Card>

          <Card className="space-y-3">
            <div className="flex items-center justify-between">
              <div className="text-[12px] font-semibold text-[#687292]">Fichiers charges</div>
              <Badge tone="purple">{files.length}</Badge>
            </div>
            <div className="space-y-2">
              {files.length ? (
                files.map((file) => (
                  <div
                    key={`${file.name}-${file.size}`}
                    className="flex items-center justify-between rounded-xl border border-[rgba(139,147,172,0.12)] bg-[#fbfcff] px-3 py-2 dark:border-white/10 dark:bg-[#0f1525]"
                  >
                    <div className="flex items-center gap-2">
                      <FileStack className="h-4 w-4 text-[#7c4dff]" />
                      <span className="text-[12px] font-medium text-[#1b2440] dark:text-white">
                        {file.name}
                      </span>
                    </div>
                    <span className="text-[11px] text-[#8d95ae]">{(file.size / 1024).toFixed(0)} Ko</span>
                  </div>
                ))
              ) : (
                <div className="text-[12px] text-[#8d95ae]">Aucun document charge.</div>
              )}
            </div>
            <Button onClick={runExtraction} className="w-full justify-between" disabled={loading || !files.length}>
              <span>{loading ? "Traitement..." : "Lancer l'extraction"}</span>
              {loading ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
            </Button>
            {error ? <div className="text-[12px] text-[#df4d64]">{error}</div> : null}
            {info ? <div className="text-[12px] text-[#b88607]">{info}</div> : null}
            {result ? (
              <div className="rounded-[16px] border border-[rgba(139,147,172,0.14)] bg-[#fbfcff] p-3 dark:border-white/10 dark:bg-[#0f1525]">
                <div className="mb-2 flex items-center justify-between">
                  <div className="text-[12px] font-semibold text-[#1b2440] dark:text-white">Resume batch</div>
                  <Badge tone={result.summary.errorCount ? "warning" : "success"}>
                    {result.summary.okCount}/{result.summary.total}
                  </Badge>
                </div>
                <div className="space-y-2">
                  {result.items.map((item) => (
                    <div key={`${item.filename}-${item.status}`} className="flex items-start justify-between gap-3 text-[12px]">
                      <div>
                        <div className="font-medium text-[#1b2440] dark:text-white">{item.filename}</div>
                        <div className="text-[#8d95ae]">{item.summary.headline}</div>
                      </div>
                      {item.status === "ok" ? (
                        <Check className="h-4 w-4 text-[#2eb764]" />
                      ) : (
                        <span className="text-[#df4d64]">!</span>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            ) : null}
          </Card>
        </div>
      </div>
    </div>
  );
}
