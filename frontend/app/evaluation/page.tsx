import {
  BarChart3,
  CheckCircle2,
  Cloud,
  Cpu,
  Database,
  FileJson2,
  Gauge,
  ShieldCheck,
  Timer,
} from "lucide-react";

import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";

const datasetCards = [
  { label: "Dataset prepare", value: "1199", helper: "Exemples train / validation / test" },
  { label: "Split test", value: "182", helper: "Documents reserves a l'evaluation" },
  { label: "Medical test", value: "35", helper: "Ground truth exploitable" },
  { label: "Tickets test", value: "147", helper: "Ground truth SROIE / receipts" },
];

const pipelines = [
  {
    name: "OCR local classique",
    icon: FileJson2,
    stack: "OpenCV + Tesseract + regles",
    role: "Baseline locale rapide et explicable.",
    bestFor: "STEG, analyses medicales structurees",
    limit: "Sensible au bruit et aux mises en page variables.",
  },
  {
    name: "IA locale hybride",
    icon: Cpu,
    stack: "Docling + PaddleOCR + Qwen2.5 via Ollama",
    role: "Extraction structuree locale sans API cloud.",
    bestFor: "PDF propres, factures fournisseurs, documents variables",
    limit: "Plus lente, depend d'Ollama et de la machine.",
  },
  {
    name: "Gemini API",
    icon: Cloud,
    stack: "Gemini Vision / Gemini 2.5 Flash",
    role: "Reference cloud pour documents complexes.",
    bestFor: "Tickets, factures fournisseurs, images difficiles",
    limit: "Depend d'une cle API, du quota et du reseau.",
  },
];

const metrics = [
  {
    label: "Detection Accuracy",
    formula: "documents bien classes / documents testes",
    note: "Mesure si le routeur choisit le bon type de document.",
  },
  {
    label: "Valid JSON Rate",
    formula: "JSON valides / sorties produites",
    note: "Indispensable pour verifier qu'un LLM retourne une sortie exploitable.",
  },
  {
    label: "Field Accuracy",
    formula: "champs corrects / champs attendus",
    note: "Metrique la plus lisible pour juger la qualite metier.",
  },
  {
    label: "Precision / Recall / F1",
    formula: "F1 = 2 x P x R / (P + R)",
    note: "Calcule champ par champ sur les valeurs JSON normalisees.",
  },
];

const decisions = [
  ["Facture STEG", "OCR local specialise ou Gemini si image difficile", "Structure relativement fixe, controle metier simple."],
  ["Analyse medicale", "OCR structure + validation, IA si besoin", "Champs critiques et besoin de verification."],
  ["Ticket de caisse", "Gemini ou IA locale hybride", "Mise en page tres variable."],
  ["Facture fournisseur", "Gemini ou Docling + Qwen", "Documents heterogenes et semantique importante."],
] as const;

const benchmarkRows = [
  ["OCR local", "A mesurer", "A mesurer", "A mesurer", "A mesurer", "Locale"],
  ["Docling + Qwen2.5", "A mesurer", "A mesurer", "A mesurer", "A mesurer", "Locale"],
  ["Gemini Vision", "A mesurer", "A mesurer", "A mesurer", "A mesurer", "Cloud/API"],
] as const;

export default function EvaluationPage() {
  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Evaluation IA"
        title="Evaluation des pipelines IA"
        description="Comparaison professionnelle des pipelines OCR local, IA locale hybride et Gemini sur la sortie JSON finale."
        chips={["Accuracy", "Precision", "Recall", "F1-score", "JSON valide"]}
      />

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {datasetCards.map((item) => (
          <Card key={item.label} className="min-h-[132px]">
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="text-[12px] font-semibold uppercase text-[#7a83a2]">
                  {item.label}
                </div>
                <div className="mt-3 text-[34px] font-black leading-none text-[#111b3d] dark:text-white">
                  {item.value}
                </div>
              </div>
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-[#effcf4] text-[#2eb764] dark:bg-[#11271d]">
                <Database className="h-5 w-5" />
              </div>
            </div>
            <div className="mt-4 text-[12px] leading-5 text-[#6f7898] dark:text-[#aab4d1]">
              {item.helper}
            </div>
          </Card>
        ))}
      </section>

      <section className="grid gap-4 xl:grid-cols-[0.78fr,1.22fr]">
        <Card>
          <div className="mb-4 flex items-center gap-2">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-[#f5f0ff] text-[#7455f2] dark:bg-[#1d1736]">
              <CheckCircle2 className="h-5 w-5" />
            </div>
            <div>
              <div className="text-[15px] font-bold text-[#111b3d] dark:text-white">
                Resultat reel disponible
              </div>
              <div className="text-[12px] text-[#7a83a2]">Smoke test multi-familles</div>
            </div>
          </div>
          <div className="rounded-[18px] border border-[#bee8ce] bg-[#effcf4] p-4 dark:border-[#1f6b41] dark:bg-[#0f2b1e]">
            <div className="text-[38px] font-black leading-none text-[#24a256] dark:text-[#7df7af]">
              4/4
            </div>
            <div className="mt-2 text-sm font-semibold text-[#1b2440] dark:text-white">
              STEG, medical, ticket et facture fournisseur detectes correctement.
            </div>
          </div>
          <div className="mt-4 text-[13px] leading-6 text-[#5f6888] dark:text-[#b7c0dc]">
            Ce resultat confirme le bon fonctionnement du routeur sur un echantillon controle.
            Il ne remplace pas un benchmark statistique large.
          </div>
        </Card>

        <Card>
          <div className="mb-4 flex items-center gap-2">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-[#f8faff] text-[#5987ff] dark:bg-white/5">
              <BarChart3 className="h-5 w-5" />
            </div>
            <div>
              <div className="text-[15px] font-bold text-[#111b3d] dark:text-white">
                Benchmark a presenter
              </div>
              <div className="text-[12px] text-[#7a83a2]">
                Les cases F1 restent a mesurer avec les predictions JSON de chaque pipeline.
              </div>
            </div>
          </div>
          <div className="overflow-x-auto">
            <table className="min-w-full text-left text-[12px]">
              <thead className="text-[#7a83a2]">
                <tr>
                  <th className="pb-3 font-semibold">Pipeline</th>
                  <th className="pb-3 font-semibold">Field acc.</th>
                  <th className="pb-3 font-semibold">Precision</th>
                  <th className="pb-3 font-semibold">Recall</th>
                  <th className="pb-3 font-semibold">F1</th>
                  <th className="pb-3 font-semibold">Donnees</th>
                </tr>
              </thead>
              <tbody>
                {benchmarkRows.map((row) => (
                  <tr key={row[0]} className="border-t border-[rgba(139,147,172,0.1)]">
                    {row.map((cell, index) => (
                      <td
                        key={`${row[0]}-${index}`}
                        className={index === 0 ? "py-3 font-bold text-[#111b3d] dark:text-white" : "py-3 text-[#5f6888] dark:text-[#b7c0dc]"}
                      >
                        {index > 0 && cell === "A mesurer" ? (
                          <Badge tone="warning">{cell}</Badge>
                        ) : (
                          cell
                        )}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </section>

      <section className="grid gap-4 xl:grid-cols-3">
        {pipelines.map((pipeline) => {
          const Icon = pipeline.icon;
          return (
            <Card key={pipeline.name} className="flex min-h-[260px] flex-col">
              <div className="mb-4 flex items-start justify-between gap-3">
                <div>
                  <div className="text-[15px] font-bold text-[#111b3d] dark:text-white">
                    {pipeline.name}
                  </div>
                  <div className="mt-1 text-[12px] font-semibold text-[#7455f2]">
                    {pipeline.stack}
                  </div>
                </div>
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[#f5f0ff] text-[#7455f2] dark:bg-[#1d1736]">
                  <Icon className="h-5 w-5" />
                </div>
              </div>
              <div className="space-y-3 text-[13px] leading-6 text-[#5f6888] dark:text-[#b7c0dc]">
                <div>{pipeline.role}</div>
                <div>
                  <span className="font-bold text-[#111b3d] dark:text-white">Adapte pour: </span>
                  {pipeline.bestFor}
                </div>
                <div>
                  <span className="font-bold text-[#111b3d] dark:text-white">Limite: </span>
                  {pipeline.limit}
                </div>
              </div>
            </Card>
          );
        })}
      </section>

      <section className="grid gap-4 xl:grid-cols-[1fr,1fr]">
        <Card>
          <div className="mb-4 flex items-center gap-2">
            <Gauge className="h-5 w-5 text-[#7455f2]" />
            <div className="text-[15px] font-bold text-[#111b3d] dark:text-white">
              Metriques defendables
            </div>
          </div>
          <div className="grid gap-3 md:grid-cols-2">
            {metrics.map((metric) => (
              <div
                key={metric.label}
                className="rounded-[18px] border border-[rgba(139,147,172,0.14)] bg-[#fbfcff] p-4 dark:border-white/10 dark:bg-[#0f1525]"
              >
                <div className="font-bold text-[#111b3d] dark:text-white">{metric.label}</div>
                <div className="mt-2 font-mono text-[12px] text-[#7455f2]">{metric.formula}</div>
                <div className="mt-2 text-[12px] leading-5 text-[#6f7898] dark:text-[#aab4d1]">
                  {metric.note}
                </div>
              </div>
            ))}
          </div>
        </Card>

        <Card>
          <div className="mb-4 flex items-center gap-2">
            <ShieldCheck className="h-5 w-5 text-[#2eb764]" />
            <div className="text-[15px] font-bold text-[#111b3d] dark:text-white">
              Decision technique par document
            </div>
          </div>
          <div className="space-y-3">
            {decisions.map(([type, pipeline, reason]) => (
              <div
                key={type}
                className="rounded-[18px] border border-[rgba(139,147,172,0.14)] bg-[#fbfcff] p-4 dark:border-white/10 dark:bg-[#0f1525]"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="font-bold text-[#111b3d] dark:text-white">{type}</div>
                  <Badge tone="success">{pipeline}</Badge>
                </div>
                <div className="mt-2 text-[12px] leading-5 text-[#6f7898] dark:text-[#aab4d1]">
                  {reason}
                </div>
              </div>
            ))}
          </div>
        </Card>
      </section>

      <Card>
        <div className="grid gap-4 xl:grid-cols-[0.9fr,1.1fr]">
          <div>
            <div className="mb-3 flex items-center gap-2">
              <Timer className="h-5 w-5 text-[#ff9a3d]" />
              <div className="text-[15px] font-bold text-[#111b3d] dark:text-white">
                Message a dire en presentation
              </div>
            </div>
            <div className="text-[14px] leading-7 text-[#5f6888] dark:text-[#b7c0dc]">
              Nous ne comparons pas seulement des modeles, mais des pipelines complets.
              Chaque pipeline produit un JSON normalise, puis ce JSON est compare a une
              verite terrain champ par champ. Les metriques retenues sont l'accuracy de
              detection, le taux de JSON valide, la field accuracy, la precision, le recall
              et le F1-score.
            </div>
          </div>
          <div className="rounded-[18px] border border-[#f1e1a6] bg-[#fffaf0] p-4 dark:border-[#6c5815] dark:bg-[#30260e]">
            <div className="font-bold text-[#7a5600] dark:text-[#ffd576]">
              Limite a annoncer clairement
            </div>
            <div className="mt-2 text-[13px] leading-6 text-[#6f5b25] dark:text-[#ffe7a3]">
              Le F1 global n'est pas encore annonce sur toutes les familles. Les familles
              medical et ticket ont un ground truth exploitable dans le split test; STEG et
              fournisseur demandent encore plus d'annotations manuelles pour un score
              statistique global.
            </div>
          </div>
        </div>
      </Card>
    </div>
  );
}
