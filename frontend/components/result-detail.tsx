"use client";

import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { Braces, Clipboard, FileJson, FileText, Info, Maximize2, ZoomIn, ZoomOut } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import type { HistoryDetail } from "@/lib/types";
import { resolveApiUrl } from "@/lib/api";
import { readSessionValue, storageKeys } from "@/lib/storage";

const TECHNICAL_KEYS = new Set([
  "_meta",
  "raw_text",
  "warnings",
  "extraction_quality",
  "extraction_source",
  "source_file",
  "file_name",
  "document_type",
  "local_pipeline",
  "mode",
  "method",
]);

const FIELD_LABELS: Record<string, string> = {
  document_type: "Type de document",
  "lab_info.lab_name": "Laboratoire",
  "lab_info.doctor_name": "Medecin",
  "patient_info.patient_name": "Patient",
  "patient_info.patient_id": "Code patient",
  "patient_info.date_of_birth": "Date de naissance",
  "patient_info.sex": "Sexe",
  "document_metadata.exam_number": "Numero d'examen",
  "document_metadata.dossier_number": "Numero dossier",
  "document_metadata.received_date": "Date de reception",
  "document_metadata.edited_date": "Date d'edition",
  "document_metadata.request_date": "Date de demande",
  "document_metadata.sample_date": "Date de reception",
  "document_metadata.report_date": "Date d'edition",
  "document_metadata.page_number": "Page",
  "document_metadata.organization": "Organisation",
  patient_name: "Patient",
  doctor_name: "Medecin",
  date: "Date",
  reference: "Reference client",
  numero_compteur: "Numero compteur",
  identifiant_compteur: "Numero compteur",
  compteur_id: "Numero compteur",
  date_facture: "Date facture",
  montant_a_payer: "Montant a payer",
  date_limite_paiement: "Date limite paiement",
  periode_du: "Periode du",
  periode_au: "Periode au",
  coupon_reference_raw: "Reference coupon",
  coupon_montant: "Montant coupon",
  store_name: "Magasin",
  time: "Heure",
  ticket_number: "Numero ticket",
  currency: "Devise",
  total: "Total",
  payment_method: "Mode de paiement",
  address: "Adresse",
  invoice_number: "Numero facture",
  invoice_date: "Date facture",
  due_date: "Date echeance",
  "seller.name": "Fournisseur",
  "seller.address": "Adresse fournisseur",
  "seller.tax_id": "Identifiant fiscal fournisseur",
  "seller.iban": "IBAN fournisseur",
  "seller.email": "Email fournisseur",
  "seller.phone": "Telephone fournisseur",
  "client.name": "Client",
  "client.address": "Adresse client",
  "client.tax_id": "Identifiant fiscal client",
  "client.email": "Email client",
  "client.phone": "Telephone client",
  "summary.subtotal": "Sous-total",
  "summary.tax_total": "Total TVA",
  "summary.discount": "Remise",
  "summary.shipping": "Livraison",
  "summary.total_amount": "Total TTC",
  "summary.amount_due": "Reste a payer",
};

const RECEIPT_DISPLAY_FIELDS = ["store_name", "date", "ticket_number", "total"];

const MEDICAL_KINDS = new Set(["medical_ocr", "medical_gemini", "medical_local"]);

const STEG_DISPLAY_FIELDS = [
  { label: "Reference client", paths: ["reference"] },
  { label: "Numero compteur", paths: ["numero_compteur", "identifiant_compteur", "compteur_id", "n_compteur"] },
  { label: "Date facture", paths: ["date_facture", "invoice_date", "date", "periode_au"] },
  { label: "Montant a payer", paths: ["montant_a_payer"] },
];

const SUPPLIER_DISPLAY_FIELDS = [
  { label: "Fournisseur", paths: ["seller.name", "fournisseur", "supplier_name"] },
  { label: "Client", paths: ["client.name", "client", "customer_name"] },
  { label: "Numero facture", paths: ["invoice_number", "numero_facture"] },
  { label: "Date", paths: ["invoice_date", "date", "date_facture"] },
  { label: "Articles", paths: ["items"] },
  { label: "Total TTC", paths: ["summary.total_amount", "summary.amount_due", "total_ttc", "total"] },
];

const MEDICAL_DISPLAY_FIELDS = [
  { label: "Laboratoire", paths: ["lab_info.lab_name", "laboratoire", "lab_name"] },
  { label: "Patient", paths: ["patient_info.patient_name", "patient_name"] },
  { label: "Code patient", paths: ["patient_info.patient_id", "patient_id"] },
  { label: "Date de naissance", paths: ["patient_info.date_of_birth", "date_of_birth"] },
  { label: "Sexe", paths: ["patient_info.sex", "sex"] },
  { label: "Numero dossier", paths: ["document_metadata.dossier_number", "dossier_number", "reference_dossier"] },
  { label: "Numero d'examen", paths: ["document_metadata.exam_number", "exam_number"] },
  { label: "Date de reception", paths: ["document_metadata.received_date", "document_metadata.sample_date", "sample_date"] },
  { label: "Date d'edition", paths: ["document_metadata.edited_date", "document_metadata.report_date", "report_date"] },
  { label: "Medecin demandeur", paths: ["lab_info.doctor_name", "doctor_name", "medecin"] },
  { label: "Resultats des examens", paths: ["tests", "analyses"] },
];

const ARRAY_FIELD_LABELS: Record<string, string> = {
  "tests[].raw_test_name": "Nom analyse",
  "tests[].normalized_name": "Nom normalise",
  "tests[].category": "Categorie",
  "tests[].value_text": "Valeur texte",
  "tests[].value": "Valeur",
  "tests[].secondary_value": "Valeur secondaire",
  "tests[].previous_value": "Valeur precedente",
  "tests[].unit": "Unite",
  "tests[].reference_range.min": "Reference min",
  "tests[].reference_range.max": "Reference max",
  "tests[].reference_range.raw_text": "Intervalle de reference",
  "tests[].status": "Statut",
  "tests[].raw_line": "Ligne OCR",
  "tests[].confidence": "Confiance ligne",
  "tests[].notes": "Notes",
  "analyses[].test_name": "Nom analyse",
  "analyses[].value": "Valeur",
  "analyses[].unit": "Unite",
  "items[].description": "Description",
  "items[].quantity": "Quantite",
  "items[].unit": "Unite",
  "items[].unit_price": "Prix unitaire",
  "items[].line_total": "Total ligne",
  "items[].net_amount": "Montant HT",
  "items[].tax_rate": "TVA",
  "items[].tax_amount": "Montant TVA",
  "items[].gross_amount": "Montant TTC",
};

type DisplayRow = {
  label: string;
  value: ReactNode;
  wide?: boolean;
};

function renderValue(value: unknown): string {
  if (value === null || value === undefined || value === "") {
    return "Non detecte";
  }
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return JSON.stringify(value);
}

function valueAtPath(payload: Record<string, unknown>, path: string): unknown {
  return path.split(".").reduce<unknown>((current, part) => {
    if (!current || typeof current !== "object" || Array.isArray(current)) {
      return undefined;
    }
    return (current as Record<string, unknown>)[part];
  }, payload);
}

function firstValueAtPaths(payload: Record<string, unknown>, paths: string[]) {
  for (const path of paths) {
    const value = valueAtPath(payload, path);
    if (value !== null && value !== undefined && value !== "") {
      return value;
    }
  }
  return undefined;
}

function hasDisplayValue(value: unknown) {
  if (value === null || value === undefined || value === "") {
    return false;
  }
  if (Array.isArray(value)) {
    return value.length > 0;
  }
  return true;
}

function renderItems(value: unknown) {
  if (!Array.isArray(value) || value.length === 0) {
    return "Aucun element detecte";
  }
  return value
    .map((item, index) => {
      if (!item || typeof item !== "object" || Array.isArray(item)) {
        return `Article ${index + 1}: ${renderValue(item)}`;
      }
      const row = item as Record<string, unknown>;
      const description = renderValue(row.description ?? row.name ?? row.designation);
      const quantity = renderValue(row.quantity ?? row.qty);
      const total = renderValue(row.gross_amount ?? row.line_total ?? row.net_amount ?? row.total);
      return `Article ${index + 1}: ${description} | Quantite: ${quantity} | Total: ${total}`;
    })
    .join("\n");
}

function renderMedicalTestsTable(value: unknown) {
  if (!Array.isArray(value) || value.length === 0) {
    return <span>Aucun examen detecte</span>;
  }

  const rows = value
    .map((item, index) => {
      if (!item || typeof item !== "object" || Array.isArray(item)) {
        return {
          key: `raw-${index}`,
          name: `Examen ${index + 1}`,
          value: renderValue(item),
          unit: "Non detecte",
        };
      }
      const row = item as Record<string, unknown>;
      return {
        key: `${index}-${renderValue(row.raw_test_name ?? row.test_name ?? row.name ?? row.normalized_name)}`,
        name: renderValue(row.raw_test_name ?? row.test_name ?? row.name ?? row.normalized_name),
        value: renderValue(row.value ?? row.value_text),
        unit: renderValue(row.unit),
      };
    });

  return (
    <div className="overflow-x-auto rounded-[14px] border border-[rgba(139,147,172,0.12)] dark:border-white/10">
      <table className="min-w-[720px] w-full text-left text-[12px]">
        <thead className="bg-[#f4f7fc] text-[11px] uppercase tracking-[0.08em] text-[#7a83a2] dark:bg-[#151c30] dark:text-[#aeb7d2]">
          <tr>
            <th className="px-3 py-2 font-semibold">Analyse</th>
            <th className="px-3 py-2 font-semibold">Valeur</th>
            <th className="px-3 py-2 font-semibold">Unite</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr
              key={row.key}
              className={index % 2 === 0 ? "bg-white dark:bg-[#0f1525]" : "bg-[#fbfcff] dark:bg-[#121a2d]"}
            >
              <td className="px-3 py-2 font-semibold text-[#1b2440] dark:text-white">{row.name}</td>
              <td className="px-3 py-2 text-[#1b2440] dark:text-white">{row.value}</td>
              <td className="px-3 py-2 text-[#5f6888] dark:text-[#b7c0dc]">{row.unit}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function isTechnicalPath(path: string) {
  return path
    .split(".")
    .some((part) => TECHNICAL_KEYS.has(part.replace(/\[\d+\]/g, "")));
}

function readableLabel(path: string) {
  if (FIELD_LABELS[path]) {
    return FIELD_LABELS[path];
  }

  const normalized = path.replace(/\[\d+\]/g, "[]");
  const indexMatch = path.match(/\[(\d+)\]/);
  const itemNumber = indexMatch ? Number(indexMatch[1]) + 1 : null;
  if (ARRAY_FIELD_LABELS[normalized]) {
    if (normalized.startsWith("tests[]") || normalized.startsWith("analyses[]")) {
      return `Analyse ${itemNumber ?? ""} - ${ARRAY_FIELD_LABELS[normalized]}`.trim();
    }
    if (normalized.startsWith("items[]")) {
      return `Ligne ${itemNumber ?? ""} - ${ARRAY_FIELD_LABELS[normalized]}`.trim();
    }
    return ARRAY_FIELD_LABELS[normalized];
  }

  return path
    .split(".")
    .map((part) =>
      part
        .replace(/\[(\d+)\]/g, " $1")
        .replace(/_/g, " ")
        .replace(/\b\w/g, (char) => char.toUpperCase())
    )
    .join(" - ");
}

function flattenPayload(payload: Record<string, unknown>, prefix = "") {
  const rows: DisplayRow[] = [];
  for (const [key, value] of Object.entries(payload)) {
    if (TECHNICAL_KEYS.has(key)) {
      continue;
    }
    const label = prefix ? `${prefix}.${key}` : key;
    if (isTechnicalPath(label)) {
      continue;
    }
    if (Array.isArray(value)) {
      if (!value.length) {
        rows.push({ label: readableLabel(label), value: "Aucun element detecte" });
        continue;
      }
      value.forEach((item, index) => {
        if (item && typeof item === "object") {
          rows.push(...flattenPayload(item as Record<string, unknown>, `${label}[${index}]`));
        } else {
          rows.push({ label: readableLabel(`${label}[${index}]`), value: renderValue(item) });
        }
      });
      continue;
    }
    if (value && typeof value === "object") {
      rows.push(...flattenPayload(value as Record<string, unknown>, label));
      continue;
    }
    rows.push({ label: readableLabel(label), value: renderValue(value) });
  }
  return rows;
}

function extractReceiptNumberFromText(rawText: unknown): string {
  if (typeof rawText !== "string") {
    return "";
  }
  const patterns = [
    /\b(\d{5,14})\s+\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\s+\d{1,2}:\d{2}\b/i,
    /(?:date\s+heure|heure\s+date)[^\n]*\n[^\d]{0,24}(\d{5,14})\s+\d{1,2}[./-]\d{1,2}[./-]\d{2,4}/i,
    /\bInvoice\s*(?:No|Number|#)?\.?\s*:?\s*([A-Z0-9][A-Z0-9\-\/]{2,})/i,
    /\bInv(?:oice)?\s*(?:No|#)?\.?\s*:?\s*([A-Z0-9][A-Z0-9\-\/]{2,})/i,
    /\bBill\s*(?:No|#)?\.?\s*:?\s*([A-Z0-9][A-Z0-9\-\/]{2,})/i,
    /\bReceipt\s*(?:No|#)?\.?\s*:?\s*([A-Z0-9][A-Z0-9\-\/]{2,})/i,
  ];
  for (const pattern of patterns) {
    const match = rawText.match(pattern);
    if (match?.[1]) {
      return match[1].replace(/[.:-]+$/g, "");
    }
  }
  return "";
}

function normalizeShortYear(rawYear: string) {
  const year = Number(rawYear);
  return year <= 79 ? 2000 + year : 1900 + year;
}

function formatDateFromParts(year: number, month: number, day: number) {
  const parsed = new Date(Date.UTC(year, month - 1, day));
  if (
    parsed.getUTCFullYear() !== year ||
    parsed.getUTCMonth() !== month - 1 ||
    parsed.getUTCDate() !== day
  ) {
    return "";
  }
  return `${day.toString().padStart(2, "0")}/${month.toString().padStart(2, "0")}/${year
    .toString()
    .padStart(4, "0")}`;
}

function normalizeDisplayDate(value: unknown) {
  if (typeof value !== "string" && typeof value !== "number") {
    return "";
  }
  const raw = String(value).trim();
  if (!raw) {
    return "";
  }

  let match = raw.match(/\b([29]0\d{2})[./-](\d{1,2})[./-](\d{1,2})\b/);
  if (match) {
    return formatDateFromParts(Number(match[1]), Number(match[2]), Number(match[3]));
  }

  match = raw.match(/\b(\d{1,2})[./-](\d{1,2})[./-]([29]0\d{2})\b/);
  if (match) {
    return formatDateFromParts(Number(match[3]), Number(match[2]), Number(match[1]));
  }

  match = raw.match(/\b(\d{1,2})[./-](\d{1,2})[./-](\d{2})\b/);
  if (match) {
    return formatDateFromParts(normalizeShortYear(match[3]), Number(match[2]), Number(match[1]));
  }

  return raw;
}

function dateFromText(rawText: unknown) {
  if (typeof rawText !== "string") {
    return "";
  }
  return normalizeDisplayDate(rawText);
}

function domainStoreFromText(rawText: unknown) {
  if (typeof rawText !== "string") {
    return "";
  }
  const ignored = new Set(["facebook", "google", "instagram", "youtube", "gmail", "hotmail", "mail"]);
  const normalized = rawText.replace(/\s+/g, " ");
  const matches = normalized.matchAll(
    /(?:www\s*\.?\s*)?([a-z][a-z0-9-]{1,24})\s*\.\s*(?:com|tn|fr|net|org)(?:\s*\.\s*[a-z]{2})?/gi
  );
  for (const match of matches) {
    const domain = match[1]?.trim().toLowerCase();
    if (domain && !ignored.has(domain)) {
      return domain.length <= 3 ? domain.toUpperCase() : domain.replace(/-/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
    }
  }
  return "";
}

function looksLikeStoreNoise(value: unknown) {
  if (typeof value !== "string") {
    return true;
  }
  const cleaned = value.replace(/\s+/g, " ").trim();
  if (!cleaned) {
    return true;
  }
  if (cleaned.includes("°") || cleaned.includes("Â°")) {
    return true;
  }
  const letters = (cleaned.match(/[A-Za-zÀ-ÿ]/g) ?? []).length;
  const digits = (cleaned.match(/\d/g) ?? []).length;
  if (letters < 2) {
    return true;
  }
  if (digits > letters && !/\b7\s*-?\s*eleven\b/i.test(cleaned)) {
    return true;
  }
  return false;
}

function storeFromText(rawText: unknown) {
  if (typeof rawText !== "string") {
    return "";
  }
  const domainStore = domainStoreFromText(rawText);
  if (domainStore) {
    return domainStore;
  }

  const knownBrands = ["zara", "carrefour", "monoprix", "geant", "aziza", "mg", "costco", "walmart", "decathlon", "lc waikiki"];
  const lower = rawText.toLowerCase();
  for (const brand of knownBrands) {
    if (new RegExp(`\\b${brand.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\b`, "i").test(lower)) {
      return brand.toUpperCase();
    }
  }
  return "";
}

function receiptDisplayValue(key: string, payload: Record<string, unknown>) {
  if (key === "store_name") {
    const fallback = storeFromText(payload.raw_text);
    const current = payload.store_name;
    return fallback && looksLikeStoreNoise(current) ? fallback : current;
  }
  if (key === "date") {
    return normalizeDisplayDate(payload.date) || dateFromText(payload.raw_text);
  }
  if (key === "ticket_number" && !payload.ticket_number) {
    return extractReceiptNumberFromText(payload.raw_text);
  }
  return payload[key];
}

function rowsForDisplay(kind: string, payload: Record<string, unknown>): DisplayRow[] {
  if (MEDICAL_KINDS.has(kind)) {
    return MEDICAL_DISPLAY_FIELDS.flatMap((field) => {
      const value = firstValueAtPaths(payload, field.paths);
      if (field.label !== "Resultats des examens" && !hasDisplayValue(value)) {
        return [];
      }
      return [
        {
          label: field.label,
          value: field.label === "Resultats des examens" ? renderMedicalTestsTable(value) : renderValue(value),
          wide: field.label === "Resultats des examens",
        },
      ];
    });
  }
  if (["receipt", "receipt_local", "receipt_test"].includes(kind)) {
    return RECEIPT_DISPLAY_FIELDS.map((key) => {
      const value = receiptDisplayValue(key, payload);
      return { label: readableLabel(key), value: renderValue(value) };
    });
  }
  if (["steg_ocr", "steg_gemini", "steg_local"].includes(kind)) {
    return STEG_DISPLAY_FIELDS.map((field) => ({
      label: field.label,
      value: renderValue(field.label.includes("Date") ? normalizeDisplayDate(firstValueAtPaths(payload, field.paths)) : firstValueAtPaths(payload, field.paths)),
    }));
  }
  if (["supplier_invoice", "supplier_invoice_local"].includes(kind)) {
    return SUPPLIER_DISPLAY_FIELDS.map((field) => {
      const value = firstValueAtPaths(payload, field.paths);
      return {
        label: field.label,
        value: field.label === "Articles" ? renderItems(value) : renderValue(field.label.includes("Date") ? normalizeDisplayDate(value) : value),
      };
    });
  }
  return flattenPayload(payload);
}

function isMedicalKind(kind: string) {
  return MEDICAL_KINDS.has(kind);
}

function stableMedicalInfoRows(detail: HistoryDetail): DisplayRow[] {
  return [
    { label: "Document", value: detail.sourceFilename },
    { label: "Type detecte", value: detail.kindLabel },
    { label: "Methode", value: detail.method },
    { label: "Date traitement", value: detail.savedDate ?? "A verifier" },
    {
      label: "Score qualite",
      value:
        detail.qualityScore === null || Number.isNaN(detail.qualityScore)
          ? "A verifier"
          : `${detail.qualityScore.toFixed(1)}/100`,
    },
  ];
}

function medicalTestRows(payload: Record<string, unknown>) {
  const tests = firstValueAtPaths(payload, ["tests", "analyses"]);
  if (!Array.isArray(tests)) {
    return [];
  }

  return tests.map((item, index) => {
    if (!item || typeof item !== "object" || Array.isArray(item)) {
      return {
        key: `medical-${index}`,
        name: `Analyse ${index + 1}`,
        value: renderValue(item),
        unit: "-",
        reference: "-",
      };
    }

    const row = item as Record<string, unknown>;
    const range = row.reference_range;
    const rangeRow =
      range && typeof range === "object" && !Array.isArray(range)
        ? (range as Record<string, unknown>)
        : {};
    const reference =
      row.reference ??
      row.normal_range ??
      row.reference_text ??
      rangeRow.raw_text ??
      [rangeRow.min, rangeRow.max].filter((value) => value !== undefined && value !== null && value !== "").join(" - ");

    return {
      key: `${index}-${renderValue(row.raw_test_name ?? row.test_name ?? row.name ?? row.normalized_name)}`,
      name: renderValue(row.raw_test_name ?? row.test_name ?? row.name ?? row.normalized_name),
      value: renderValue(row.value ?? row.value_text),
      unit: renderValue(row.unit),
      reference: renderValue(reference),
    };
  });
}

export function ResultDetail({
  detail,
  layout = "full",
}: {
  detail: HistoryDetail | null;
  layout?: "full" | "stacked";
}) {
  const sourceUrl = detail?.sourceAvailable ? resolveApiUrl(detail.sourceUrl) : null;
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [jsonCopied, setJsonCopied] = useState(false);
  const [previewScale, setPreviewScale] = useState(1);

  useEffect(() => {
    if (!sourceUrl) {
      setPreviewUrl(null);
      return;
    }
    let alive = true;
    let objectUrl: string | null = null;
    const token = readSessionValue(storageKeys.authToken, "");
    fetch(sourceUrl, {
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
          setPreviewUrl(null);
        }
      });
    return () => {
      alive = false;
      if (objectUrl) {
        URL.revokeObjectURL(objectUrl);
      }
    };
  }, [sourceUrl]);

  useEffect(() => {
    setPreviewScale(1);
  }, [detail?.entryKey]);

  if (!detail) {
    return (
      <Card className="flex min-h-[360px] items-center justify-center">
        <div className="max-w-md text-center">
          <div className="proto-title text-xl font-bold text-[#1b2440] dark:text-white">
            Aucun document selectionne
          </div>
          <p className="mt-3 text-sm leading-6 text-[#7a83a2] dark:text-[#96a1c2]">
            Lance une extraction ou ouvre le detail d&apos;un document depuis Documents ou
            Historiques pour voir le fichier, les champs extraits et le JSON technique.
          </p>
        </div>
      </Card>
    );
  }

  const rows = rowsForDisplay(detail.kind, detail.payload);
  const isMedicalDocument = isMedicalKind(detail.kind);
  const keyRows = isMedicalDocument ? stableMedicalInfoRows(detail) : rows.filter((row) => !row.wide).slice(0, 5);
  const tableRows = rows.filter((row) => !row.wide);
  const wideRows = rows.filter((row) => row.wide);
  const medicalRows = isMedicalDocument ? medicalTestRows(detail.payload) : [];
  const technicalJson = JSON.stringify(detail.payload, null, 2);
  const sourceSuffix = detail.sourceFilename.split(".").pop()?.toLowerCase() ?? "";
  const isImage = ["jpg", "jpeg", "png", "webp", "bmp", "tif", "tiff"].includes(sourceSuffix);
  const stackedLayout = layout === "stacked";
  const previewHeight = stackedLayout ? "h-[300px]" : "h-[500px]";
  const tableMaxHeight = stackedLayout ? "max-h-[300px]" : "max-h-[540px]";
  const jsonMaxHeight = stackedLayout ? "max-h-[300px]" : "max-h-[540px]";

  const copyJson = async () => {
    try {
      await navigator.clipboard.writeText(technicalJson);
      setJsonCopied(true);
      window.setTimeout(() => setJsonCopied(false), 1600);
    } catch {
      setJsonCopied(false);
    }
  };

  const previewBlock = (
    <div className="overflow-hidden rounded-[18px] border border-[rgba(139,147,172,0.12)] bg-gradient-to-br from-[#fbfcff] to-[#f3f6fb] dark:border-white/10 dark:from-[#0f1525] dark:to-[#111827]">
      {previewUrl ? (
        isImage ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={previewUrl}
            alt={detail.sourceFilename}
            className={`${previewHeight} w-full object-contain transition-transform duration-200`}
            style={{ transform: `scale(${previewScale})` }}
          />
        ) : (
          <iframe
            src={previewUrl}
            title={detail.sourceFilename}
            className={`${previewHeight} w-full bg-white`}
          />
        )
      ) : (
        <div className={`flex ${previewHeight} items-center justify-center text-sm text-[#8d95ae]`}>
          Aucun document source archive.
        </div>
      )}
    </div>
  );

  const infoPanel = (
    <Card className="p-4">
      <div className="mb-3 flex items-center gap-2">
        <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-[#f2ecff] text-[#7c4dff] dark:bg-[#21183a]">
          <Info className="h-4 w-4" />
        </span>
        <div className="proto-title text-[14px] font-bold text-[#1b2440] dark:text-white">
          Informations cles
        </div>
      </div>
      <div className="divide-y divide-[rgba(139,147,172,0.12)] dark:divide-white/10">
        {keyRows.length ? (
          keyRows.map((row) => (
            <div key={row.label} className="grid grid-cols-[150px_minmax(0,1fr)] gap-3 py-3 text-[12px]">
              <div className="font-semibold text-[#6f7898] dark:text-[#aeb7d2]">{row.label}</div>
              <div className="min-w-0 break-words text-[#1b2440] dark:text-white">{row.value}</div>
            </div>
          ))
        ) : (
          <div className="py-3 text-sm text-[#8d95ae]">Aucune information cle detectee.</div>
        )}
      </div>
    </Card>
  );

  const fieldsTable = (
    <Card className="p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-[#f2ecff] text-[#7c4dff] dark:bg-[#21183a]">
            <Braces className="h-4 w-4" />
          </span>
          <div className="proto-title text-[14px] font-bold text-[#1b2440] dark:text-white">
            {isMedicalDocument ? "Analyses extraites" : "Champs extraits"}
          </div>
        </div>
        <Badge tone="default">{isMedicalDocument ? "Resultats biologiques" : "Donnees structurees"}</Badge>
      </div>
      <div className={`${tableMaxHeight} overflow-auto rounded-[18px] border border-[rgba(139,147,172,0.12)] dark:border-white/10`}>
        <table className={`${isMedicalDocument ? "min-w-[560px]" : "min-w-[720px]"} w-full text-left text-[12px]`}>
          <thead className="sticky top-0 z-10 bg-[#f8faff] text-[10px] uppercase tracking-[0.08em] text-[#7782a0] dark:bg-[#151c30] dark:text-[#aeb7d2]">
            <tr>
              <th className="px-4 py-3 font-bold">Parametre</th>
              <th className="px-4 py-3 font-bold">Valeur</th>
              <th className="px-4 py-3 font-bold">Unite</th>
              {!isMedicalDocument ? <th className="px-4 py-3 font-bold">Reference</th> : null}
            </tr>
          </thead>
          <tbody className="divide-y divide-[rgba(139,147,172,0.08)] dark:divide-white/10">
            {(medicalRows.length ? medicalRows : tableRows).map((row, index) => {
              if ("name" in row) {
                return (
                  <tr key={row.key} className={index % 2 === 0 ? "bg-white dark:bg-[#0f1525]" : "bg-[#fbfcff] dark:bg-[#121a2d]"}>
                    <td className="px-4 py-3 font-semibold text-[#1b2440] dark:text-white">{row.name}</td>
                    <td className="px-4 py-3 text-[#1b2440] dark:text-white">{row.value}</td>
                    <td className="px-4 py-3 text-[#5f6888] dark:text-[#b7c0dc]">{row.unit}</td>
                    {!isMedicalDocument ? (
                      <td className="px-4 py-3 text-[#5f6888] dark:text-[#b7c0dc]">{row.reference}</td>
                    ) : null}
                  </tr>
                );
              }

              return (
                <tr key={row.label} className={index % 2 === 0 ? "bg-white dark:bg-[#0f1525]" : "bg-[#fbfcff] dark:bg-[#121a2d]"}>
                  <td className="px-4 py-3 font-semibold text-[#1b2440] dark:text-white">{row.label}</td>
                  <td className="whitespace-pre-line px-4 py-3 text-[#1b2440] dark:text-white">{row.value}</td>
                  <td className="px-4 py-3 text-[#8d95ae]">-</td>
                  {!isMedicalDocument ? <td className="px-4 py-3 text-[#8d95ae]">-</td> : null}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {wideRows.length && !medicalRows.length ? (
        <div className="mt-3 space-y-3">
          {wideRows.map((row) => (
            <div key={row.label} className="rounded-[16px] border border-[rgba(139,147,172,0.12)] bg-[#fbfcff] p-3 dark:border-white/10 dark:bg-[#0f1525]">
              <div className="mb-2 text-[11px] font-semibold uppercase tracking-[0.08em] text-[#8d95ae]">
                {row.label}
              </div>
              <div className="text-[12px] text-[#1b2440] dark:text-white">{row.value}</div>
            </div>
          ))}
        </div>
      ) : null}
    </Card>
  );

  const jsonPanel = (
    <Card className="p-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-[#f2ecff] text-[#7c4dff] dark:bg-[#21183a]">
            <FileJson className="h-4 w-4" />
          </span>
          <div className="proto-title text-[14px] font-bold text-[#1b2440] dark:text-white">
            JSON technique
          </div>
        </div>
        <Button variant="secondary" size="sm" className="h-8 gap-2 px-3 text-[12px]" onClick={copyJson}>
          <Clipboard className="h-3.5 w-3.5" />
          {jsonCopied ? "Copie" : "Copier"}
        </Button>
      </div>
      <pre className={`${jsonMaxHeight} overflow-auto rounded-[18px] bg-[#0b1220] p-4 text-[11px] leading-5 text-[#9ef7c0] shadow-inner`}>
        {technicalJson}
      </pre>
    </Card>
  );

  if (stackedLayout) {
    return (
      <div className="grid gap-4 xl:grid-cols-2">
        <Card className="p-4">
          <div className="mb-3 flex items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-[#f2ecff] text-[#7c4dff] dark:bg-[#21183a]">
                <FileText className="h-4 w-4" />
              </span>
              <div className="proto-title text-[14px] font-bold text-[#1b2440] dark:text-white">
                Document original
              </div>
            </div>
            <div className="flex items-center gap-1.5 text-[#6f7898] dark:text-[#aeb7d2]">
              <button
                type="button"
                onClick={() => setPreviewScale((current) => Math.max(0.75, Number((current - 0.1).toFixed(2))))}
                className="flex h-7 w-7 items-center justify-center rounded-lg hover:bg-[#f3f6ff] disabled:opacity-40 dark:hover:bg-white/5"
                disabled={!previewUrl || !isImage}
                title="Reduire"
              >
                <ZoomOut className="h-4 w-4" />
              </button>
              <button
                type="button"
                onClick={() => setPreviewScale(1)}
                className="h-7 rounded-lg px-2 text-[11px] font-semibold hover:bg-[#f3f6ff] disabled:opacity-40 dark:hover:bg-white/5"
                disabled={!previewUrl || !isImage}
                title="Taille normale"
              >
                {Math.round(previewScale * 100)}%
              </button>
              <button
                type="button"
                onClick={() => setPreviewScale((current) => Math.min(1.6, Number((current + 0.1).toFixed(2))))}
                className="flex h-7 w-7 items-center justify-center rounded-lg hover:bg-[#f3f6ff] disabled:opacity-40 dark:hover:bg-white/5"
                disabled={!previewUrl || !isImage}
                title="Agrandir"
              >
                <ZoomIn className="h-4 w-4" />
              </button>
              <button
                type="button"
                onClick={() => setPreviewScale(1.25)}
                className="flex h-7 w-7 items-center justify-center rounded-lg hover:bg-[#f3f6ff] disabled:opacity-40 dark:hover:bg-white/5"
                disabled={!previewUrl || !isImage}
                title="Ajuster"
              >
                <Maximize2 className="h-4 w-4" />
              </button>
            </div>
          </div>
          {previewBlock}
        </Card>
        {infoPanel}
        {fieldsTable}
        {jsonPanel}
      </div>
    );
  }

  return (
    <div className="grid gap-4 xl:grid-cols-[1.05fr,0.95fr,0.7fr]">
      <Card className="p-4">
        <div className="mb-3 flex items-center justify-between">
          <div className="proto-title text-[14px] font-bold text-[#1b2440] dark:text-white">
            Document original
          </div>
          <Badge tone={detail.status === "ok" ? "success" : "danger"}>
            {detail.status === "ok" ? "Succes" : "Erreur"}
          </Badge>
        </div>
        <div className="overflow-hidden rounded-[18px] border border-[rgba(139,147,172,0.14)] bg-[#fbfcff] dark:border-white/10 dark:bg-[#0f1525]">
          {previewUrl ? (
            isImage ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={previewUrl}
                alt={detail.sourceFilename}
                className="h-[500px] w-full object-contain"
              />
            ) : (
              <iframe
                src={previewUrl}
                title={detail.sourceFilename}
                className="h-[500px] w-full bg-white"
              />
            )
          ) : (
            <div className="flex h-[500px] items-center justify-center text-sm text-[#8d95ae]">
              Aucun document source archive.
            </div>
          )}
        </div>
      </Card>

      <Card className="p-4">
        <div className="mb-3 flex items-center justify-between">
          <div className="proto-title text-[14px] font-bold text-[#1b2440] dark:text-white">
            Champs extraits
          </div>
          <Badge tone="default">Donnees structurees</Badge>
        </div>
        <div className="max-h-[540px] space-y-2 overflow-auto pr-1">
          {rows.length ? (
            rows.map((row) => (
              <div
                key={row.label}
                className={`grid gap-2 rounded-[16px] border border-[rgba(139,147,172,0.12)] bg-[#fbfcff] px-4 py-3 dark:border-white/10 dark:bg-[#0f1525] ${
                  row.wide ? "" : "md:grid-cols-[minmax(220px,0.9fr)_minmax(0,1.1fr)]"
                }`}
              >
                <div className="text-[11px] font-semibold uppercase tracking-[0.08em] text-[#8d95ae]">
                  {row.label}
                </div>
                <div className="min-w-0 break-words text-[12px] leading-6 text-[#1b2440] dark:text-white">
                  {row.value}
                </div>
              </div>
            ))
          ) : (
            <div className="text-sm text-[#8d95ae]">Aucune donnee exploitable.</div>
          )}
        </div>
      </Card>

      <Card className="p-4">
        <div className="mb-3 proto-title text-[14px] font-bold text-[#1b2440] dark:text-white">
          JSON technique
        </div>
        <pre className="max-h-[540px] overflow-auto rounded-[18px] bg-[#111827] p-4 text-[11px] leading-5 text-[#98f5b7]">
          {technicalJson}
        </pre>
      </Card>
    </div>
  );
}
