export const storageKeys = {
  theme: "docuai-theme",
  uiSettings: "docuai-ui-settings",
  geminiKey: "docuai-gemini-key",
  geminiModel: "docuai-gemini-model",
  aiProvider: "docuai-ai-provider",
  openaiKey: "docuai-openai-key",
  openaiModel: "docuai-openai-model",
  anthropicKey: "docuai-anthropic-key",
  anthropicModel: "docuai-anthropic-model",
  ollamaHost: "docuai-ollama-host",
  localModel: "docuai-local-model",
  lastExtraction: "docuai-last-extraction",
  activeModels: "docuai-active-models",
  defaultMethod: "docuai-default-method",
  authToken: "docuai-auth-token"
};

export function readStoredValue(key: string, fallback = "") {
  if (typeof window === "undefined") {
    return fallback;
  }
  return window.localStorage.getItem(key) ?? fallback;
}

export function writeStoredValue(key: string, value: string) {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.setItem(key, value);
}

export function readStoredJson<T>(key: string, fallback: T): T {
  if (typeof window === "undefined") {
    return fallback;
  }
  const raw = window.localStorage.getItem(key);
  if (!raw) {
    return fallback;
  }
  try {
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

export function writeStoredJson(key: string, value: unknown) {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.setItem(key, JSON.stringify(value));
}

export function readSessionValue(key: string, fallback = "") {
  if (typeof window === "undefined") {
    return fallback;
  }
  return window.sessionStorage.getItem(key) ?? fallback;
}

export function writeSessionValue(key: string, value: string) {
  if (typeof window === "undefined") {
    return;
  }
  window.sessionStorage.setItem(key, value);
}

export function removeSessionValue(key: string) {
  if (typeof window === "undefined") {
    return;
  }
  window.sessionStorage.removeItem(key);
}
