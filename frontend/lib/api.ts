import type {
  AuthLoginPayload,
  AuthLoginResponse,
  AuthMeResponse,
  DashboardPayload,
  ExtractionBatchPayload,
  HistoryDetail,
  HistoryListPayload,
  MetaPayload,
  ModelsPayload
} from "@/lib/types";
import {
  readSessionValue,
  removeSessionValue,
  storageKeys,
  writeSessionValue,
} from "@/lib/storage";

const defaultApiBase = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

export function getApiBaseUrl() {
  return defaultApiBase.replace(/\/$/, "");
}

export function resolveApiUrl(path: string) {
  return `${getApiBaseUrl()}${path}`;
}

function getAuthToken() {
  return readSessionValue(storageKeys.authToken, "");
}

function buildHeaders(headers?: HeadersInit, includeJson = false) {
  const next = new Headers(headers);
  if (includeJson) {
    next.set("Content-Type", "application/json");
  }
  const token = getAuthToken();
  if (token) {
    next.set("Authorization", `Bearer ${token}`);
  }
  return next;
}

function networkErrorMessage(err: unknown) {
  if (err instanceof DOMException && err.name === "AbortError") {
    return "Requete interrompue: le backend met trop de temps a repondre.";
  }
  if (err instanceof TypeError) {
    return "Backend DocIA non joignable. Lance run_api.ps1 puis recharge la page.";
  }
  return err instanceof Error ? err.message : "Erreur reseau a verifier.";
}

async function readErrorMessage(response: Response) {
  const text = await response.text();
  if (!text) {
    return `HTTP ${response.status}`;
  }
  try {
    const payload = JSON.parse(text) as { detail?: unknown; error?: unknown; message?: unknown };
    const detail = payload.detail ?? payload.error ?? payload.message;
    if (typeof detail === "string" && detail.trim()) {
      return detail;
    }
    if (Array.isArray(detail)) {
      return detail.map((item) => String(item?.msg ?? item)).join(" / ");
    }
  } catch {
    // Keep the raw response body below.
  }
  return text;
}

async function readJson<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(resolveApiUrl(path), {
      ...init,
      headers: buildHeaders(init?.headers, true),
      cache: "no-store"
    });
  } catch (err) {
    throw new Error(networkErrorMessage(err));
  }
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }
  return (await response.json()) as T;
}

export function fetchMeta() {
  return readJson<MetaPayload>("/api/meta");
}

export async function loginApi(payload: AuthLoginPayload) {
  const response = await readJson<AuthLoginResponse>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify(payload)
  });
  writeSessionValue(storageKeys.authToken, response.accessToken);
  return response;
}

export function logoutApi() {
  removeSessionValue(storageKeys.authToken);
}

export function fetchCurrentUser() {
  return readJson<AuthMeResponse>("/api/auth/me");
}

export function fetchDashboard() {
  return readJson<DashboardPayload>("/api/dashboard");
}

export function fetchHistory(params: URLSearchParams) {
  return readJson<HistoryListPayload>(`/api/history?${params.toString()}`);
}

export function fetchHistoryDetail(entryKey: string) {
  return readJson<HistoryDetail>(`/api/history/${entryKey}`);
}

export function deleteHistoryEntry(entryKey: string) {
  return readJson<{ status: string; message: string }>(`/api/history/${entryKey}`, {
    method: "DELETE"
  });
}

function safeDownloadStem(name: string) {
  return (name.split(/[\\/]/).pop() ?? "document")
    .replace(/\.[^.]+$/, "")
    .replace(/[^\w-]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 80) || "document";
}

function filenameFromContentDisposition(value: string | null, fallback: string) {
  if (!value) {
    return fallback;
  }
  const utf8Match = value.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf8Match?.[1]) {
    try {
      return decodeURIComponent(utf8Match[1].trim());
    } catch {
      return utf8Match[1].trim();
    }
  }
  const match = value.match(/filename="?([^";]+)"?/i);
  return match?.[1]?.trim() || fallback;
}

async function downloadBinary(path: string, fallbackFilename: string) {
  const response = await fetch(resolveApiUrl(path), {
    headers: buildHeaders(),
    cache: "no-store"
  });
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }
  const blob = await response.blob();
  const objectUrl = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = objectUrl;
  link.download = filenameFromContentDisposition(
    response.headers.get("Content-Disposition"),
    fallbackFilename
  );
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
}

export function downloadHistoryReport(entryKey: string, sourceFilename = "document") {
  return downloadBinary(
    `/api/history/${entryKey}/report.pdf`,
    `DOCIA_${safeDownloadStem(sourceFilename)}.pdf`
  );
}

export function downloadHistoryZip(entryKeys: string[]) {
  const params = new URLSearchParams();
  entryKeys.forEach((entryKey) => params.append("entryKey", entryKey));
  return downloadBinary(`/api/history/export/zip?${params.toString()}`, "documents_export.zip");
}

export function fetchLatestResult() {
  return readJson<{ item: HistoryDetail | null }>("/api/results/latest");
}

export function fetchModels() {
  return readJson<ModelsPayload>("/api/models");
}

export async function uploadExtractions(
  formData: FormData
): Promise<ExtractionBatchPayload> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 150_000);
  try {
    let response: Response;
    try {
      response = await fetch(resolveApiUrl("/api/extractions"), {
        method: "POST",
        headers: buildHeaders(),
        body: formData,
        signal: controller.signal
      });
    } catch (err) {
      throw new Error(networkErrorMessage(err));
    }
    if (!response.ok) {
      throw new Error(await readErrorMessage(response));
    }
    return (await response.json()) as ExtractionBatchPayload;
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new Error(
        "Extraction arretee: le traitement a pris trop de temps. Verifie Ollama/Qwen, ou teste avec OCR local classique pour obtenir un resultat plus rapide."
      );
    }
    throw err;
  } finally {
    clearTimeout(timeoutId);
  }
}
