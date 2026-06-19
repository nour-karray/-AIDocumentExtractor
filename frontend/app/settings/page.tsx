"use client";

import {
  Bot,
  Check,
  CircleHelp,
  FolderArchive,
  Globe,
  Info,
  LayoutGrid,
  Monitor,
  MoonStar,
  RotateCcw,
  Shield,
  SlidersHorizontal,
  Sparkles,
  SunMedium
} from "lucide-react";
import { useEffect, useState } from "react";

import { PageHeader } from "@/components/page-header";
import { useTheme } from "@/components/theme-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { fetchMeta } from "@/lib/api";
import {
  readStoredJson,
  readStoredValue,
  storageKeys,
  writeStoredJson,
  writeStoredValue
} from "@/lib/storage";
import { cn } from "@/lib/utils";
import type { MetaPayload } from "@/lib/types";

type SettingsTab = "general" | "extraction" | "ai" | "security" | "storage";

type UiSettings = {
  appName: string;
  version: string;
  language: string;
  timezone: string;
  dateFormat: string;
  numberFormat: string;
  density: "comfortable" | "compact" | "spacious";
  animations: boolean;
  autoVerify: boolean;
  autoSaveResults: boolean;
  confirmDeletion: boolean;
  advancedMode: boolean;
};

const settingsDefaults: UiSettings = {
  appName: "DocuAI",
  version: "v2.1.0",
  language: "Francais",
  timezone: "(UTC+01:00) Europe/Paris",
  dateFormat: "10 mai 2026 (DD MMMM YYYY)",
  numberFormat: "1 234,56",
  density: "comfortable",
  animations: true,
  autoVerify: true,
  autoSaveResults: true,
  confirmDeletion: true,
  advancedMode: false,
};

const tabItems: Array<{ value: SettingsTab; label: string; icon: typeof Globe }> = [
  { value: "general", label: "General", icon: Globe },
  { value: "extraction", label: "Extraction locale", icon: Sparkles },
  { value: "ai", label: "IA & Modeles", icon: Bot },
  { value: "security", label: "Securite", icon: Shield },
  { value: "storage", label: "Stockage & Exports", icon: FolderArchive },
];

function SectionShell({
  icon,
  title,
  description,
  children
}: {
  icon: React.ReactNode;
  title: string;
  description: string;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-[22px] border border-[rgba(139,147,172,0.12)] bg-white p-4 shadow-[0_10px_28px_rgba(18,27,52,0.04)] dark:border-white/10 dark:bg-[#121829]">
      <div className="grid gap-4 lg:grid-cols-[170px,minmax(0,1fr)]">
        <div className="space-y-4">
          <div>
            <div className="text-[15px] font-bold text-[#1b2440] dark:text-white">{title}</div>
            <div className="mt-1 text-[12px] leading-6 text-[#7a83a2] dark:text-[#aeb7d2]">
              {description}
            </div>
          </div>
          <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-[linear-gradient(145deg,#f4fff8,#edf5ff)] text-[#30c56f] shadow-[inset_0_0_0_1px_rgba(48,197,111,0.08)] dark:bg-[linear-gradient(145deg,#11271d,#101625)] dark:text-[#86f7b6]">
            {icon}
          </div>
        </div>
        <div>{children}</div>
      </div>
    </div>
  );
}

function SegmentButton({
  active,
  icon,
  label,
  onClick
}: {
  active: boolean;
  icon?: React.ReactNode;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "inline-flex h-11 items-center justify-center gap-2 rounded-xl border px-4 text-sm font-medium transition",
        active
          ? "border-[#9de0b8] bg-[#f1fcf5] text-[#27b665] shadow-[0_10px_20px_rgba(48,197,111,0.08)] dark:border-[#226a44] dark:bg-[#10271c] dark:text-[#8ef8b8]"
          : "border-[rgba(139,147,172,0.16)] bg-white text-[#55607f] hover:bg-[#fafcff] dark:border-white/10 dark:bg-[#0f1525] dark:text-[#b1bcda] dark:hover:bg-[#141b2c]"
      )}
    >
      {icon}
      {label}
    </button>
  );
}

function ToggleRow({
  label,
  description,
  checked,
  onChange
}: {
  label: string;
  description: string;
  checked: boolean;
  onChange: (next: boolean) => void;
}) {
  return (
    <div className="flex items-center justify-between gap-4 py-2">
      <div className="min-w-0">
        <div className="text-sm font-medium text-[#1b2440] dark:text-white">{label}</div>
        <div className="text-[12px] leading-5 text-[#7a83a2] dark:text-[#aeb7d2]">{description}</div>
      </div>
      <button
        type="button"
        aria-pressed={checked}
        onClick={() => onChange(!checked)}
        className={`relative h-6 w-11 shrink-0 rounded-full transition ${
          checked ? "bg-[#30c56f]" : "bg-[#d5dbec] dark:bg-[#2a3450]"
        }`}
      >
        <span
          className={`absolute top-0.5 h-5 w-5 rounded-full bg-white transition ${
            checked ? "left-5" : "left-0.5"
          }`}
        />
      </button>
    </div>
  );
}

export default function SettingsPage() {
  const { theme, setTheme } = useTheme();
  const [meta, setMeta] = useState<MetaPayload | null>(null);
  const [activeTab, setActiveTab] = useState<SettingsTab>("general");
  const [uiSettings, setUiSettings] = useState<UiSettings>(settingsDefaults);
  const [aiProvider, setAiProvider] = useState("local");
  const [ollamaHost, setOllamaHost] = useState("http://127.0.0.1:11434");
  const [localModel, setLocalModel] = useState("qwen2.5:7b-instruct");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    fetchMeta().then((payload) => {
      setMeta(payload);
      setUiSettings(readStoredJson(storageKeys.uiSettings, settingsDefaults));
      setAiProvider(readStoredValue(storageKeys.aiProvider, "local"));
      setOllamaHost(readStoredValue(storageKeys.ollamaHost, payload.defaultOllamaHost ?? "http://127.0.0.1:11434"));
      setLocalModel(readStoredValue(storageKeys.localModel, payload.defaultLocalModel ?? "qwen2.5:7b-instruct"));
    });
  }, []);

  const saveSettings = () => {
    writeStoredJson(storageKeys.uiSettings, uiSettings);
    writeStoredValue(storageKeys.aiProvider, aiProvider);
    writeStoredValue(storageKeys.ollamaHost, ollamaHost);
    writeStoredValue(storageKeys.localModel, localModel);
    writeStoredValue(storageKeys.defaultMethod, "local");
    setSaved(true);
    window.setTimeout(() => setSaved(false), 1800);
  };

  const resetSettings = () => {
    setUiSettings(settingsDefaults);
    setAiProvider("local");
    setOllamaHost("http://127.0.0.1:11434");
    setLocalModel("qwen2.5:7b-instruct");
    setTheme("system");
    setSaved(false);
  };

  const updateSetting = <K extends keyof UiSettings>(key: K, value: UiSettings[K]) => {
    setUiSettings((current) => ({ ...current, [key]: value }));
    setSaved(false);
  };

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="7. PARAMETRES"
        title="Parametres"
        description="Personnalisez l'application selon vos besoins."
        action={
          <div className="flex flex-wrap justify-end gap-2">
            <Button variant="secondary" onClick={resetSettings} className="gap-2">
              <RotateCcw className="h-4 w-4" />
              Reinitialiser les parametres
            </Button>
            <Button variant="success" onClick={saveSettings} className="gap-2">
              <Check className="h-4 w-4" />
              Enregistrer les modifications
            </Button>
          </div>
        }
      />

      <Card className="space-y-5">
        <div className="flex flex-wrap items-center gap-2 border-b border-[rgba(139,147,172,0.12)] pb-3 dark:border-white/10">
          {tabItems.map((item) => {
            const Icon = item.icon;
            return (
              <button
                key={item.value}
                type="button"
                onClick={() => setActiveTab(item.value)}
                className={cn(
                  "inline-flex items-center gap-2 rounded-xl border px-3 py-2 text-[12px] font-semibold transition",
                  activeTab === item.value
                    ? "border-[#9de0b8] bg-[#f1fcf5] text-[#27b665] dark:border-[#226a44] dark:bg-[#10271c] dark:text-[#8ef8b8]"
                    : "border-transparent text-[#697390] hover:border-[rgba(139,147,172,0.12)] hover:bg-[#fbfcff] dark:text-[#b1bcda] dark:hover:border-white/10 dark:hover:bg-[#141b2c]"
                )}
              >
                <Icon className="h-4 w-4" />
                {item.label}
              </button>
            );
          })}
        </div>

        {saved ? (
          <div className="flex items-center justify-end">
            <Badge tone="success">Modifications enregistrees</Badge>
          </div>
        ) : null}

        {activeTab === "general" ? (
          <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_300px]">
            <div className="space-y-4">
              <SectionShell
                icon={<Info className="h-5 w-5" />}
                title="Informations generales"
                description="Configurez les informations de base de votre application."
              >
                <div className="grid gap-4 md:grid-cols-2">
                  <div className="space-y-2">
                    <div className="text-[12px] font-semibold text-[#687292]">Nom de l'application</div>
                    <Input
                      value={uiSettings.appName}
                      onChange={(event) => updateSetting("appName", event.target.value)}
                    />
                  </div>
                  <div className="space-y-2">
                    <div className="text-[12px] font-semibold text-[#687292]">Fuseau horaire</div>
                    <Select
                      value={uiSettings.timezone}
                      onChange={(event) => updateSetting("timezone", event.target.value)}
                    >
                      <option>(UTC+01:00) Europe/Paris</option>
                      <option>(UTC+01:00) Africa/Lagos</option>
                      <option>(UTC+00:00) UTC</option>
                    </Select>
                  </div>
                  <div className="space-y-2">
                    <div className="text-[12px] font-semibold text-[#687292]">Version</div>
                    <Input
                      value={uiSettings.version}
                      onChange={(event) => updateSetting("version", event.target.value)}
                    />
                  </div>
                  <div className="space-y-2">
                    <div className="text-[12px] font-semibold text-[#687292]">Format de date</div>
                    <Select
                      value={uiSettings.dateFormat}
                      onChange={(event) => updateSetting("dateFormat", event.target.value)}
                    >
                      <option>10 mai 2026 (DD MMMM YYYY)</option>
                      <option>2026-05-10 (YYYY-MM-DD)</option>
                      <option>10/05/2026 (DD/MM/YYYY)</option>
                    </Select>
                  </div>
                  <div className="space-y-2">
                    <div className="text-[12px] font-semibold text-[#687292]">Langue</div>
                    <Select
                      value={uiSettings.language}
                      onChange={(event) => updateSetting("language", event.target.value)}
                    >
                      <option>Francais</option>
                      <option>Anglais</option>
                      <option>Arabe</option>
                    </Select>
                  </div>
                  <div className="space-y-2">
                    <div className="text-[12px] font-semibold text-[#687292]">Format de nombre</div>
                    <Select
                      value={uiSettings.numberFormat}
                      onChange={(event) => updateSetting("numberFormat", event.target.value)}
                    >
                      <option>1 234,56</option>
                      <option>1,234.56</option>
                      <option>1234.56</option>
                    </Select>
                  </div>
                </div>
              </SectionShell>

              <SectionShell
                icon={<Monitor className="h-5 w-5" />}
                title="Preferences d'affichage"
                description="Personnalisez l'interface selon vos preferences."
              >
                <div className="space-y-5">
                  <div className="space-y-2">
                    <div className="text-[12px] font-semibold text-[#687292]">Theme</div>
                    <div className="flex flex-wrap gap-2">
                      <SegmentButton
                        active={theme === "light"}
                        label="Clair"
                        icon={<SunMedium className="h-4 w-4" />}
                        onClick={() => setTheme("light")}
                      />
                      <SegmentButton
                        active={theme === "dark"}
                        label="Sombre"
                        icon={<MoonStar className="h-4 w-4" />}
                        onClick={() => setTheme("dark")}
                      />
                      <SegmentButton
                        active={theme === "system"}
                        label="Systeme"
                        icon={<Monitor className="h-4 w-4" />}
                        onClick={() => setTheme("system")}
                      />
                    </div>
                  </div>

                  <div className="space-y-2">
                    <div className="text-[12px] font-semibold text-[#687292]">Densite de l'interface</div>
                    <div className="flex flex-wrap gap-2">
                      <SegmentButton
                        active={uiSettings.density === "comfortable"}
                        label="Confortable"
                        icon={<LayoutGrid className="h-4 w-4" />}
                        onClick={() => updateSetting("density", "comfortable")}
                      />
                      <SegmentButton
                        active={uiSettings.density === "compact"}
                        label="Compacte"
                        icon={<LayoutGrid className="h-4 w-4" />}
                        onClick={() => updateSetting("density", "compact")}
                      />
                      <SegmentButton
                        active={uiSettings.density === "spacious"}
                        label="Spacieuse"
                        icon={<LayoutGrid className="h-4 w-4" />}
                        onClick={() => updateSetting("density", "spacious")}
                      />
                    </div>
                  </div>

                  <ToggleRow
                    label="Animations"
                    description="Activer les animations et transitions."
                    checked={uiSettings.animations}
                    onChange={(next) => updateSetting("animations", next)}
                  />
                </div>
              </SectionShell>

              <SectionShell
                icon={<SlidersHorizontal className="h-5 w-5" />}
                title="Comportement de l'application"
                description="Definissez le comportement par defaut de l'application."
              >
                <div className="divide-y divide-[rgba(139,147,172,0.12)] dark:divide-white/10">
                  <ToggleRow
                    label="Verification automatique des nouveaux documents"
                    description="Verifier automatiquement les nouveaux documents importes."
                    checked={uiSettings.autoVerify}
                    onChange={(next) => updateSetting("autoVerify", next)}
                  />
                  <ToggleRow
                    label="Sauvegarde automatique des resultats"
                    description="Enregistrer automatiquement les resultats d'extraction."
                    checked={uiSettings.autoSaveResults}
                    onChange={(next) => updateSetting("autoSaveResults", next)}
                  />
                  <ToggleRow
                    label="Confirmer avant suppression"
                    description="Demander une confirmation avant de supprimer un document."
                    checked={uiSettings.confirmDeletion}
                    onChange={(next) => updateSetting("confirmDeletion", next)}
                  />
                  <ToggleRow
                    label="Mode avance"
                    description="Afficher les options avancees pour les utilisateurs experimentes."
                    checked={uiSettings.advancedMode}
                    onChange={(next) => updateSetting("advancedMode", next)}
                  />
                </div>
              </SectionShell>
            </div>

            <div className="space-y-4">
              <Card className="space-y-4 bg-[linear-gradient(180deg,#fbfff9,white)] dark:bg-[linear-gradient(180deg,#12201a,#101625)]">
                <div>
                  <div className="text-[15px] font-bold text-[#1b2440] dark:text-white">Besoin d'aide ?</div>
                  <div className="mt-1 text-[12px] leading-6 text-[#7a83a2] dark:text-[#aeb7d2]">
                    Consultez notre documentation ou contactez notre equipe.
                  </div>
                </div>
                <div className="space-y-2">
                  <div className="flex items-center justify-between rounded-xl border border-[rgba(139,147,172,0.12)] bg-white px-4 py-3 text-sm font-medium text-[#27b665] dark:border-white/10 dark:bg-[#0f1525]">
                    <span>Voir la documentation</span>
                    <span>&gt;</span>
                  </div>
                  <div className="flex items-center justify-between rounded-xl border border-[rgba(139,147,172,0.12)] bg-white px-4 py-3 text-sm font-medium text-[#27b665] dark:border-white/10 dark:bg-[#0f1525]">
                    <span>Contacter le support</span>
                    <span>&gt;</span>
                  </div>
                </div>
              </Card>

              <Card className="space-y-3">
                <div className="text-[15px] font-bold text-[#1b2440] dark:text-white">A propos</div>
                <div className="text-[12px] leading-6 text-[#7a83a2] dark:text-[#aeb7d2]">
                  DocuAI est une solution d'extraction intelligente de documents basee sur l'IA.
                </div>
                <div className="text-[12px] text-[#9aa3bf]">© 2026 DocuAI. Tous droits reserves.</div>
              </Card>
            </div>
          </div>
        ) : null}

        {activeTab === "extraction" ? (
          <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
            <SectionShell
              icon={<Sparkles className="h-5 w-5" />}
              title="Extraction locale"
              description="Ajustez les preferences d'extraction et le moteur utilise par defaut."
            >
              <div className="grid gap-4 md:grid-cols-2">
                <div className="space-y-2">
                  <div className="text-[12px] font-semibold text-[#687292]">Fournisseur IA par defaut</div>
                  <Select value={aiProvider} onChange={(event) => setAiProvider(event.target.value)}>
                    <option value="local">Docling + Qwen2.5 local</option>
                  </Select>
                </div>
                <div className="space-y-2">
                  <div className="text-[12px] font-semibold text-[#687292]">Pipeline actif</div>
                  <Select defaultValue="Docling + Qwen2.5 local">
                    <option>Docling + Qwen2.5 local</option>
                  </Select>
                </div>
              </div>
            </SectionShell>

            <Card className="space-y-3">
              <div className="text-[15px] font-bold text-[#1b2440] dark:text-white">Conseil</div>
              <div className="text-[12px] leading-6 text-[#7a83a2] dark:text-[#aeb7d2]">
                Le mode par defaut est l'architecture locale hybride : pretraitement, Docling, controle qualite, fallback PaddleOCR, puis Qwen2.5 local.
              </div>
            </Card>
          </div>
        ) : null}

        {activeTab === "ai" ? (
          <div className="space-y-4">
            <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
              <Card className="space-y-3">
                <div className="flex items-center justify-between gap-2">
                  <div className="text-[15px] font-bold text-[#1b2440] dark:text-white">Docling + Qwen2.5</div>
                  <Badge tone={meta?.localPipeline?.available ? "success" : "warning"}>
                    {meta?.localPipeline?.available ? "Actif" : "A configurer"}
                  </Badge>
                </div>
                <Input
                  value={ollamaHost}
                  onChange={(event) => setOllamaHost(event.target.value)}
                  placeholder="http://127.0.0.1:11434"
                />
                <Input
                  value={localModel}
                  onChange={(event) => setLocalModel(event.target.value)}
                  placeholder="qwen2.5:7b-instruct"
                />
                <div className="text-[12px] leading-6 text-[#7a83a2] dark:text-[#aeb7d2]">
                  Pipeline local branche au backend : le fichier est valide et pretraite, Docling produit le Markdown, le backend verifie sa qualite, PaddleOCR prend le relais si le contenu est faible, puis Qwen2.5 via Ollama retourne le JSON valide.
                </div>
              </Card>

              <Card className="space-y-3">
                <div className="text-[15px] font-bold text-[#1b2440] dark:text-white">Etat local</div>
                <div className="text-[12px] leading-6 text-[#7a83a2] dark:text-[#aeb7d2]">
                  Docling : {meta?.localPipeline?.doclingAvailable ? "installe" : "non installe"}
                  <br />
                  PaddleOCR : {meta?.localPipeline?.paddleocrAvailable ? "installe" : "non installe"}
                  <br />
                  Ollama : {meta?.localPipeline?.ollamaAvailable ? "joignable" : "non joignable"}
                </div>
              </Card>
            </div>

            <SectionShell
              icon={<Sparkles className="h-5 w-5" />}
              title="Architecture"
              description="Chemin reel utilise par le backend pour extraire les champs metier."
            >
              <div className="grid gap-2 md:grid-cols-3 xl:grid-cols-6">
                {(meta?.localPipeline?.architecture ?? [
                  "Document PDF/image",
                  "Pretraitement",
                  "Docling vers Markdown",
                  "Controle qualite",
                  "Fallback PaddleOCR",
                  "Qwen2.5 vers JSON",
                  "Validation metier",
                ]).map((step, index) => (
                  <div
                    key={step}
                    className="rounded-[16px] border border-[rgba(139,147,172,0.14)] bg-[#fbfcff] p-3 dark:border-white/10 dark:bg-[#0f1525]"
                  >
                    <div className="text-[11px] font-bold text-[#7c4dff]">{index + 1}</div>
                    <div className="mt-2 text-[12px] font-semibold leading-5 text-[#1b2440] dark:text-white">{step}</div>
                  </div>
                ))}
              </div>
            </SectionShell>
          </div>
        ) : null}

        {activeTab === "security" ? (
          <SectionShell
            icon={<Shield className="h-5 w-5" />}
            title="Securite"
            description="Controlez les confirmations et le niveau d'acces aux options sensibles."
          >
            <div className="divide-y divide-[rgba(139,147,172,0.12)] dark:divide-white/10">
              <ToggleRow
                label="Confirmer avant suppression"
                description="Eviter les suppressions accidentelles dans les listes de documents et historiques."
                checked={uiSettings.confirmDeletion}
                onChange={(next) => updateSetting("confirmDeletion", next)}
              />
              <ToggleRow
                label="Mode avance"
                description="Afficher les options sensibles reservees aux utilisateurs experimentes."
                checked={uiSettings.advancedMode}
                onChange={(next) => updateSetting("advancedMode", next)}
              />
            </div>
          </SectionShell>
        ) : null}

        {activeTab === "storage" ? (
          <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
            <SectionShell
              icon={<FolderArchive className="h-5 w-5" />}
              title="Stockage & Exports"
              description="Configurez le comportement des exports et l'archivage des documents."
            >
              <div className="divide-y divide-[rgba(139,147,172,0.12)] dark:divide-white/10">
                <ToggleRow
                  label="Sauvegarde automatique des resultats"
                  description="Conserver automatiquement les rapports et sorties structures."
                  checked={uiSettings.autoSaveResults}
                  onChange={(next) => updateSetting("autoSaveResults", next)}
                />
                <ToggleRow
                  label="Verification automatique des nouveaux documents"
                  description="Verifier chaque nouveau document avant stockage final."
                  checked={uiSettings.autoVerify}
                  onChange={(next) => updateSetting("autoVerify", next)}
                />
              </div>
            </SectionShell>

            <Card className="space-y-3">
              <div className="text-[15px] font-bold text-[#1b2440] dark:text-white">Chemin backend</div>
              <div className="rounded-xl bg-[#111827] px-3 py-2 font-mono text-[11px] text-[#9bf5b7]">
                {meta?.geminiInstructions.pathHint}
              </div>
            </Card>
          </div>
        ) : null}
      </Card>
    </div>
  );
}
