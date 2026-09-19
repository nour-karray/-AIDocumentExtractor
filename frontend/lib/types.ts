export type ChartDatum = {
  label: string;
  value: number;
};

export type DailyDatum = {
  date: string;
  documents: number;
};

export type TrendPoint = {
  date: string;
  value: number;
};

export type TrendSeries = {
  label: string;
  color: string;
  points: TrendPoint[];
};

export type SummaryInfo = {
  headline: string;
  subline: string;
};

export type HistoryItem = {
  entryKey: string;
  relative: string;
  kind: string;
  kindLabel: string;
  family: string;
  method: string;
  savedAt: string;
  savedDate: string | null;
  sourceFilename: string;
  status: "ok" | "error";
  warningsCount: number;
  qualityScore: number | null;
  sizeBytes: number;
  summary: SummaryInfo;
  reportUrl: string;
  detailUrl: string;
  sourceUrl: string;
  hasSourceArchive: boolean;
};

export type HistoryDetail = HistoryItem & {
  payload: Record<string, unknown>;
  sourceAvailable: boolean;
};

export type DashboardPayload = {
  overview: {
    totalDocuments: number;
    successCount: number;
    errorCount: number;
    successRate: number;
    warningCount: number;
    warningRate: number;
    aiHealthScore: number;
  };
  recentActivity: HistoryItem[];
  latestResult: HistoryDetail | null;
  distributions: {
    byKind: ChartDatum[];
    byMethod: ChartDatum[];
    byFamily: ChartDatum[];
    byStatus: ChartDatum[];
    dailyVolume: DailyDatum[];
    trendSeries: TrendSeries[];
  };
  insights: string[];
};

export type HistoryListPayload = {
  items: HistoryItem[];
  filters: {
    kind: string;
    search: string;
    typeQuery: string;
    dateFrom: string | null;
    dateTo: string | null;
    availableKinds: { value: string; label: string }[];
    availableDates: { value: string; label: string }[];
  };
  pagination: {
    page: number;
    pageSize: number;
    total: number;
    totalPages: number;
  };
};

export type ExtractionResultItem = {
  filename: string;
  sourceOrigin: string;
  detectedType: string;
  status: "ok" | "error";
  kind: string | null;
  kindLabel: string | null;
  method: string | null;
  payload: Record<string, unknown> | null;
  warnings: { code?: string; message?: string }[];
  summary: SummaryInfo;
  historyEntryKey: string | null;
  reportUrl: string | null;
  sourceUrl: string | null;
  detailUrl: string | null;
  error?: string;
};

export type ExtractionBatchPayload = {
  summary: {
    total: number;
    okCount: number;
    errorCount: number;
    mode: string;
    method: string;
  };
  items: ExtractionResultItem[];
  latestSuccess: ExtractionResultItem | null;
};

export type MetaPayload = {
  appName: string;
  apiVersion: string;
  themes: { value: string; label: string }[];
  modes: { value: string; label: string }[];
  methods: { value: string; label: string }[];
  localPipeline?: {
    doclingAvailable: boolean;
    paddleocrAvailable?: boolean;
    ollamaAvailable: boolean;
    available: boolean;
  };
  geminiConfigured: boolean;
  auth?: {
    enabled: boolean;
    loginUrl: string;
    meUrl: string;
    tokenType: "bearer";
    ttlMinutes: number;
    usernameHint: string | null;
  };
  navigation: { href: string; label: string }[];
};

export type AuthLoginPayload = {
  username: string;
  password: string;
};

export type AuthLoginResponse = {
  accessToken: string;
  tokenType: "bearer";
  expiresAt: string;
  user: {
    username: string;
  };
};

export type AuthMeResponse = {
  user: {
    username: string;
  };
  mode: "bearer" | "disabled";
};

export type ModelsPayload = {
  runtime: {
    geminiModel: string;
    geminiConfigured: boolean;
    tesseractConfigured: boolean;
    tesseractPath: string;
    ollamaHost?: string;
    localModel?: string;
    doclingConfigured?: boolean;
    paddleocrConfigured?: boolean;
    ollamaConfigured?: boolean;
  };
  models: {
    id: string;
    name: string;
    provider: string;
    status: string;
    description: string;
    version?: string;
    precision?: number | null;
    lastUsed?: string | null;
    available?: boolean;
    toggleable?: boolean;
    methodValue?: "local" | "gemini" | "ocr" | null;
    reason?: string | null;
  }[];
  coverage: ChartDatum[];
};
