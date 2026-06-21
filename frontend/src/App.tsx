import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent, type MouseEvent } from "react";

// ponytail: empty VITE_API_URL = same-origin (/api via nginx or vite proxy)
const API = (import.meta.env.VITE_API_URL ?? "http://localhost:8000").replace(/\/$/, "");
const AUTH_TOKEN_KEY = "checkimg_token";
const GUEST_SCAN_KEY = "checkimg_guest_scan";
const SCAN_STORAGE_KEY = "checkimg_scan_token";

function getAuthToken(): string | null {
  return localStorage.getItem(AUTH_TOKEN_KEY);
}

function setAuthToken(token: string | null) {
  if (token) localStorage.setItem(AUTH_TOKEN_KEY, token);
  else localStorage.removeItem(AUTH_TOKEN_KEY);
}

function getGuestScanToken(): string | null {
  try {
    return sessionStorage.getItem(GUEST_SCAN_KEY);
  } catch {
    return null;
  }
}

function setGuestScanToken(token: string | null) {
  try {
    if (token) sessionStorage.setItem(GUEST_SCAN_KEY, token);
    else sessionStorage.removeItem(GUEST_SCAN_KEY);
  } catch {
    /* ponytail: private mode */
  }
}

function isScanToken(raw: string | null): raw is string {
  return Boolean(raw && /^[A-Za-z0-9_-]{16,}$/.test(raw));
}

function authHeaders(extra?: HeadersInit): HeadersInit {
  const token = getAuthToken();
  return token ? { ...extra, Authorization: `Bearer ${token}` } : { ...extra };
}

function scanAccessHeaders(extra?: HeadersInit): HeadersInit {
  const auth = getAuthToken();
  if (auth) return { ...extra, Authorization: `Bearer ${auth}` };
  const guest = getGuestScanToken();
  if (guest) return { ...extra, "X-Scan-Token": guest };
  return { ...extra };
}

async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    /* ponytail: clipboard blocked on http — fall through */
  }
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.style.cssText = "position:fixed;left:-9999px";
  document.body.appendChild(ta);
  ta.select();
  const ok = document.execCommand("copy");
  document.body.removeChild(ta);
  return ok;
}

async function apiFetch(path: string, init?: RequestInit) {
  return fetch(`${API}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...authHeaders(init?.headers as HeadersInit) },
  });
}

async function scanFetch(path: string, init?: RequestInit) {
  return fetch(`${API}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...scanAccessHeaders(init?.headers as HeadersInit) },
  });
}

type RiskLevel =
  | "safe"
  | "warning"
  | "suspect"
  | "danger"
  | "dmca_protected"
  | "dmca_violation"
  | "piracy_blacklist"
  | "ai_generated";

const RISK_LABELS: Record<RiskLevel, string> = {
  safe: "safe",
  warning: "warning",
  suspect: "suspect",
  danger: "danger",
  dmca_protected: "DMCA ✓",
  dmca_violation: "DMCA ⚠",
  piracy_blacklist: "piracy",
  ai_generated: "AI",
};

const SITE_TYPE_RU: Record<string, string> = {
  photobank: "фотобанк",
  microstock: "микросток",
  social: "соцсеть",
  marketplace: "маркетплейс",
  news: "новости",
  other: "сайт",
};

const MATCH_KIND_RU: Record<string, string> = {
  exact: "точная копия",
  similar: "похожее",
  unverified: "не проверено",
  weak: "слабое сходство",
};

interface EngineEvidence {
  best_match_url?: string | null;
  title?: string | null;
  site_type?: string | null;
  text_snippet?: string | null;
  match_count?: number;
  buy_pattern?: boolean;
  best_match_kind?: string | null;
  best_similarity_score?: number | null;
  exact_count?: number;
  similar_count?: number;
}

function formatMatchKind(engine: EngineEvidence | null): string | null {
  if (!engine?.best_match_kind) return null;
  const label = MATCH_KIND_RU[engine.best_match_kind] ?? engine.best_match_kind;
  if (engine.best_similarity_score != null) {
    return `${label} (${Math.round(engine.best_similarity_score * 100)}%)`;
  }
  return label;
}

function getEngineEvidence(evidence: Record<string, unknown> | null | undefined, engine: "google" | "yandex") {
  return (evidence?.[engine] as EngineEvidence | undefined) ?? null;
}

function formatReasonsForTable(reasons: string[]): string {
  if (!reasons.length) return "—";
  const urlRe = /https?:\/\/[^\s;]+/g;
  return reasons
    .map((r) => r.replace(urlRe, (url) => (url.length > 48 ? `${url.slice(0, 45)}…` : url)))
    .join("; ");
}

function pagePath(url: string): string {
  try {
    const u = new URL(url);
    const path = u.pathname + u.search + u.hash;
    return path || "/";
  } catch {
    return url;
  }
}

function shortErr(msg: string, max = 100): string {
  const one = msg.replace(/\s+/g, " ").trim();
  return one.length > max ? `${one.slice(0, max - 1)}…` : one;
}

function pct(score: number | undefined): string {
  return score != null ? `${Math.round(score * 100)}%` : "—";
}

function getDmcaSummaryLines(dmca: Record<string, unknown> | null | undefined): string[] {
  if (!dmca || Object.keys(dmca).length === 0) return [];
  const lines: string[] = [];

  const bl = dmca.pirate_blacklist as { listed?: boolean; domain?: string } | undefined;
  if (bl) {
    lines.push(
      bl.listed
        ? `Blacklist: ${bl.domain ?? "домен"} — в списке`
        : `Blacklist: ${bl.domain ?? "домен"} — не в списке`,
    );
  }

  const lumen = dmca.lumen as {
    infringing_match?: boolean;
    found?: boolean;
    notice_count?: number;
    error?: string | null;
  } | undefined;
  if (lumen) {
    if (lumen.error) {
      const msg = shortErr(lumen.error);
      if (/недоступен|unavailable|connect/i.test(msg)) {
        lines.push(`Lumen Database: недоступен (внешний сервис)`);
      } else {
        lines.push(`Lumen Database: ошибка — ${msg}`);
      }
    } else if (lumen.infringing_match) {
      lines.push(`Lumen Database: infringing URL (${lumen.notice_count ?? 0} notices)`);
    } else if (lumen.found) {
      lines.push(`Lumen Database: ${lumen.notice_count ?? 0} notices, URL не совпал`);
    } else {
      lines.push("Lumen Database: совпадений нет");
    }
  }

  const gt = dmca.google_transparency as {
    domain?: string;
    checked?: boolean;
    has_removals?: boolean;
    removal_count?: number | null;
    detail?: string;
    error?: string | null;
  } | undefined;
  if (gt) {
    if (gt.error) lines.push(`Google Transparency: ошибка — ${shortErr(gt.error)}`);
    else if (gt.has_removals) {
      lines.push(`Google Transparency: ${gt.removal_count ?? "?"} удалений (${gt.domain ?? ""})`);
    } else if (gt.checked) {
      lines.push(
        gt.detail
          ? `Google Transparency: ${gt.detail} (${gt.domain ?? ""})`
          : `Google Transparency: проверен (${gt.domain ?? ""})`,
      );
    } else {
      lines.push(`Google Transparency: не проверен (${gt.domain ?? ""})`);
    }
  }

  const prot = dmca.protection_id as { id?: string | null; verified?: boolean; error?: string } | undefined;
  if (prot) {
    if (prot.id) {
      lines.push(`DMCA Protection ID: ${prot.id}${prot.verified ? " ✓ подтверждён" : " (не подтверждён)"}`);
    } else {
      lines.push("DMCA Protection ID: не обнаружен");
    }
  }

  const site = dmca.site_signals as { has_dmca_badge?: boolean; footer_text_hits?: string[] } | undefined;
  if (site?.has_dmca_badge) lines.push("На сайте: DMCA-badge");
  for (const hit of (site?.footer_text_hits ?? []).slice(0, 2)) {
    lines.push(`Футер: ${hit}`);
  }

  return lines;
}

function getAiSummaryLines(
  ai: Record<string, unknown> | null | undefined,
  gemini: Record<string, unknown> | null | undefined,
): string[] {
  if (!ai || Object.keys(ai).length === 0) return [];
  const lines: string[] = [];

  const hf = ai.huggingface as {
    watermark?: { detected?: boolean; score?: number; error?: string };
    ai_generated?: { detected?: boolean; score?: number; error?: string };
    error?: string;
  } | undefined;
  if (hf) {
    if (hf.error && !(hf.watermark as { source?: string } | undefined)?.source) {
      lines.push(`Hugging Face: ошибка — ${shortErr(hf.error)}`);
    } else {
      const wm = hf.watermark as { detected?: boolean; score?: number; error?: string; source?: string; model?: string };
      if (wm?.error && !wm.detected) lines.push(`HF watermark: ошибка — ${shortErr(wm.error)}`);
      else {
        const src = wm?.source === "local" || wm?.source === "local_fallback" ? "локальная эвристика" : "HF API";
        lines.push(`Watermark (${src}): ${wm?.detected ? `да (${pct(wm?.score)})` : `нет (${pct(wm?.score)})`}`);
      }

      const ag = hf.ai_generated as { detected?: boolean; score?: number; error?: string; skipped?: boolean; reason?: string };
      if (ag?.skipped) lines.push(`AI-generated: ${ag.reason ?? "пропущено (нет HF token)"}`);
      else if (ag?.error) lines.push(`HF AI-generated: ошибка — ${shortErr(ag.error)}`);
      else lines.push(`HF AI-generated: ${ag?.detected ? `да (${pct(ag?.score)})` : `нет (${pct(ag?.score)})`}`);
    }
  }

  const ddg = ai.duckduckgo as { match_count?: number; error?: string; method?: string } | undefined;
  if (ddg) {
    if (ddg.error && !ddg.match_count) lines.push(`DuckDuckGo: ошибка — ${shortErr(String(ddg.error))}`);
    else {
      const via = ddg.method === "text" ? " (текстовый поиск)" : ddg.method === "images" ? " (images)" : "";
      lines.push(`DuckDuckGo${via}: ${ddg.match_count ?? 0} совпадений`);
    }
  }

  const tineye = ai.tineye as { match_count?: number; error?: string; earliest_match?: { url?: string; first_seen?: string } } | undefined;
  if (tineye) {
    if (tineye.error) lines.push(`TinEye: ошибка — ${shortErr(tineye.error)}`);
    else {
      lines.push(`TinEye: ${tineye.match_count ?? 0} совпадений`);
      if (tineye.earliest_match?.url) {
        lines.push(`TinEye earliest: ${tineye.earliest_match.first_seen ?? "?"} — ${tineye.earliest_match.url}`);
      }
    }
  }

  const gem = (gemini ?? ai.gemini) as { reasoning?: string; source_type?: string; error?: string } | undefined;
  if (gem?.reasoning) {
    lines.push(`Gemini (${gem.source_type ?? "analysis"}): ${String(gem.reasoning).slice(0, 180)}`);
  } else if (gem?.error) {
    lines.push(`Gemini: ошибка — ${shortErr(gem.error)}`);
  }

  const perplexity = ai.perplexity as { stock_mentions?: boolean; result_count?: number; error?: string; method?: string } | undefined;
  if (perplexity) {
    if (perplexity.error) lines.push(`Perplexity: ошибка — ${shortErr(perplexity.error)}`);
    else {
      lines.push(
        `Perplexity: ${perplexity.stock_mentions ? "упоминание стоков" : "стоков не найдено"} (${perplexity.result_count ?? 0} результатов)`,
      );
    }
  }

  const copilot = ai.copilot as { stock_mentions?: boolean; result_count?: number; error?: string } | undefined;
  if (copilot) {
    if (copilot.error) lines.push(`Copilot: ошибка — ${shortErr(copilot.error)}`);
    else {
      lines.push(
        `Copilot: ${copilot.stock_mentions ? "упоминание стоков" : "стоков не найдено"} (${copilot.result_count ?? 0} результатов)`,
      );
    }
  }

  const signals = ai.signals as {
    ai_generated?: boolean;
    stock_photo_confirmed?: boolean;
    wide_distribution?: boolean;
    stock_confirmations?: number;
  } | undefined;
  if (signals) {
    if (signals.stock_photo_confirmed) lines.push("Итог: несколько AI-сервисов подтвердили сток");
    if (signals.ai_generated) lines.push("Итог: вероятно AI-generated");
    if (signals.wide_distribution) lines.push("Итог: широкое распространение (>10 копий)");
    if (!lines.some((l) => l.startsWith("Итог:")) && signals.stock_confirmations === 0) {
      lines.push("Итог: явных AI-сигналов нет");
    }
  }

  return lines;
}

function getReasons(check: ImageResult["copyright_check"]): string[] {
  if (!check || check.risk_level === "safe") return [];
  const evidence = check.source_evidence;
  if (Array.isArray(evidence?.reasons) && evidence.reasons.length > 0) {
    return evidence.reasons as string[];
  }
  const lines: string[] = [];
  const wm = evidence?.watermark as { detected?: boolean; details?: string } | undefined;
  if (wm?.detected) lines.push(`Возможный водяной знак (${wm.details ?? "overlay"})`);

  const google = getEngineEvidence(evidence, "google");
  const yandex = getEngineEvidence(evidence, "yandex");

  if (yandex?.buy_pattern) {
    lines.push(`Яндекс: ${yandex.text_snippet ?? "признак стока «Купить…»"}`);
  }
  if (yandex?.best_match_url && yandex.site_type) {
    lines.push(`Яндекс (${SITE_TYPE_RU[yandex.site_type] ?? yandex.site_type}): ${yandex.best_match_url}`);
  }
  if (google?.best_match_url && google.site_type) {
    lines.push(`Google (${SITE_TYPE_RU[google.site_type] ?? google.site_type}): ${google.best_match_url}`);
  }

  const exif = evidence?.exif_summary as {
    copyright?: string;
    artist?: string;
    domain_mismatch?: boolean;
  } | undefined;
  if (exif?.copyright) lines.push(`EXIF Copyright: ${exif.copyright}`);
  if (exif?.artist) lines.push(`EXIF Artist: ${exif.artist}`);
  if (exif?.domain_mismatch) lines.push("Метаданные не совпадают с доменом сайта");
  if (exif && "dmca_protection_id" in exif && exif.dmca_protection_id) {
    lines.push(`EXIF DMCA ID: ${exif.dmca_protection_id as string}`);
  }

  const dmca = check.dmca_evidence as Record<string, unknown> | null | undefined;
  if (dmca?.pirate_blacklist && (dmca.pirate_blacklist as { listed?: boolean }).listed) {
    lines.push("Домен в чёрном списке пиратских сайтов");
  }
  if (dmca?.lumen && (dmca.lumen as { infringing_match?: boolean }).infringing_match) {
    lines.push("Lumen Database: infringing URL");
  }
  const prot = dmca?.protection_id as { verified?: boolean; id?: string } | undefined;
  if (prot?.verified) lines.push(`DMCA Protection ID подтверждён: ${prot.id}`);

  if (!lines.length && (google?.match_count || yandex?.match_count)) {
    lines.push(`Найдены совпадения (Google: ${google?.match_count ?? 0}, Яндекс: ${yandex?.match_count ?? 0})`);
  }
  return lines;
}

type FlatImage = ImageResult & { pageUrl: string };

function tsvCell(value: string): string {
  const s = value.replace(/\t/g, " ").replace(/\r?\n/g, " ");
  return s.includes('"') || s.includes("\n") ? `"${s.replace(/"/g, '""')}"` : s;
}

function buildTableTsv(images: FlatImage[]): string {
  const headers = ["Риск", "URL изображения", "Страница", "Причины", "Google", "Яндекс"];
  const rows = images.map((img) => {
    const risk = img.copyright_check?.risk_level ?? "pending";
    const ev = img.copyright_check?.source_evidence;
    const google = getEngineEvidence(ev, "google")?.best_match_url ?? "";
    const yandex = getEngineEvidence(ev, "yandex")?.best_match_url ?? "";
    const reasons = getReasons(img.copyright_check).join("; ");
    return [risk, img.src_url, img.pageUrl, reasons, google, yandex].map(tsvCell).join("\t");
  });
  return [headers.join("\t"), ...rows].join("\n");
}

type ScanStatus = "pending" | "in_progress" | "paused" | "cancelled" | "done" | "failed";

interface ScanOptions {
  google_search: boolean;
  yandex_search: boolean;
  match_verify: boolean;
  dmca_checks: boolean;
  dmca_lumen_per_image: boolean;
  ai_search: boolean;
  duckduckgo: boolean;
  huggingface: boolean;
  gemini: boolean;
  tineye: boolean;
  perplexity: boolean;
  copilot: boolean;
  min_file_size_kb: number;
  min_image_width: number;
  min_image_height: number;
  gemini_api_key: string;
  huggingface_api_token: string;
  tineye_api_key: string;
  tineye_api_secret: string;
  dmca_api_key: string;
  serpapi_key: string;
}

interface KeysConfigured {
  gemini: boolean;
  huggingface: boolean;
  tineye: boolean;
  dmca: boolean;
  serpapi: boolean;
}

interface ScanOptionsDefaults {
  defaults: ScanOptions;
  presets: { full: ScanOptions; fast: ScanOptions };
  keys_configured: KeysConfigured;
}

interface UserInfo {
  id: number;
  email: string;
}

interface ScanHistoryItem {
  token: string;
  url: string;
  status: ScanStatus;
  depth: number;
  pages_scanned: number;
  images_found: number;
  images_processed: number;
  created_at: string;
  options_summary?: string;
  share_enabled?: boolean;
}

interface ScanStatusResponse {
  token: string;
  url: string;
  status: ScanStatus;
  depth: number;
  depth_reached: number;
  share_enabled: boolean;
  progress_pct: number;
  pages_scanned: number;
  images_found: number;
  images_processed: number;
  scan_options?: ScanOptions | null;
  error_message?: string | null;
}

interface ImageResult {
  id: number;
  src_url: string;
  alt_text: string | null;
  copyright_check: {
    risk_level: RiskLevel;
    source_evidence: Record<string, unknown> | null;
    dmca_evidence: Record<string, unknown> | null;
    excluded: boolean;
  } | null;
}

interface PageResult {
  id: number;
  url: string;
  images: ImageResult[];
}

interface ScanResults {
  scan_token: string;
  status: ScanStatus;
  pages: PageResult[];
  summary: Record<string, number>;
}

type Filter = "all" | "violations" | "clean";
type ViewMode = "grid" | "table";
type RiskSort = "default" | "risk_desc" | "risk_asc";

const RISK_SORT_ORDER: Record<string, number> = {
  danger: 0,
  dmca_violation: 1,
  piracy_blacklist: 2,
  suspect: 3,
  warning: 4,
  dmca_protected: 5,
  ai_generated: 6,
  safe: 7,
  pending: 8,
};

const ACTIVE: ScanStatus[] = ["pending", "in_progress", "paused"];

function readScanTokenFromUrl(): string | null {
  const raw = new URLSearchParams(window.location.search).get("scan");
  return isScanToken(raw) ? raw : null;
}

function readScanTokenFromStorage(): string | null {
  try {
    const raw = localStorage.getItem(SCAN_STORAGE_KEY);
    return isScanToken(raw) ? raw : null;
  } catch {
    return null;
  }
}

function persistScanToken(token: string | null, shareInUrl: boolean) {
  try {
    if (shareInUrl && token) localStorage.setItem(SCAN_STORAGE_KEY, token);
    else localStorage.removeItem(SCAN_STORAGE_KEY);
  } catch {
    /* ponytail: private mode may block storage */
  }
  const u = new URL(window.location.href);
  if (shareInUrl && token) u.searchParams.set("scan", token);
  else u.searchParams.delete("scan");
  window.history.replaceState({}, "", u);
}

function initialScanToken(): string | null {
  const fromUrl = readScanTokenFromUrl();
  if (fromUrl) {
    if (!getAuthToken()) setGuestScanToken(fromUrl);
    return fromUrl;
  }
  if (getAuthToken()) return readScanTokenFromStorage();
  return getGuestScanToken();
}

function buildShareUrl(token: string): string {
  const u = new URL(window.location.href);
  u.searchParams.set("scan", token);
  return u.toString();
}

function PreviewImg({
  scanToken,
  imageId,
  alt,
  className,
}: {
  scanToken: string;
  imageId: number;
  alt?: string;
  className?: string;
}) {
  const [src, setSrc] = useState<string | null>(null);

  useEffect(() => {
    let blobUrl: string | null = null;
    let cancelled = false;
    scanFetch(`/api/preview/${scanToken}/${imageId}`)
      .then((res) => (res.ok ? res.blob() : null))
      .then((blob) => {
        if (!blob || cancelled) return;
        blobUrl = URL.createObjectURL(blob);
        setSrc(blobUrl);
      })
      .catch(() => setSrc(null));
    return () => {
      cancelled = true;
      if (blobUrl) URL.revokeObjectURL(blobUrl);
    };
  }, [scanToken, imageId]);

  if (!src) return <div className={`preview-placeholder ${className ?? ""}`} />;
  return <img src={src} alt={alt ?? ""} className={className} />;
}

const EMPTY_API_KEYS = {
  gemini_api_key: "",
  huggingface_api_token: "",
  tineye_api_key: "",
  tineye_api_secret: "",
  dmca_api_key: "",
  serpapi_key: "",
};

const FALLBACK_SCAN_OPTIONS: ScanOptions = {
  google_search: true,
  yandex_search: true,
  match_verify: true,
  dmca_checks: true,
  dmca_lumen_per_image: false,
  ai_search: true,
  duckduckgo: true,
  huggingface: true,
  gemini: true,
  tineye: false,
  perplexity: false,
  copilot: false,
  min_file_size_kb: 0,
  min_image_width: 32,
  min_image_height: 32,
  ...EMPTY_API_KEYS,
};

function OptionSlider({
  label,
  value,
  min,
  max,
  step,
  unit,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  unit: string;
  onChange: (v: number) => void;
}) {
  return (
    <label className="option-slider">
      <span>
        {label}: <strong>{value}</strong> {unit}
      </span>
      <input type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} />
    </label>
  );
}

function ApiKeyField({
  show,
  label,
  value,
  onChange,
  configured,
  placeholder,
}: {
  show: boolean;
  label: string;
  value: string;
  onChange: (v: string) => void;
  configured?: boolean;
  placeholder?: string;
}) {
  if (!show) return null;
  return (
    <label className="option-key">
      <span>
        {label}
        {configured && !value ? <span className="key-hint"> — из .env</span> : null}
      </span>
      <input
        type="password"
        autoComplete="off"
        spellCheck={false}
        value={value}
        placeholder={configured && !value ? "используется ключ сервера" : placeholder}
        onChange={(e) => onChange(e.target.value)}
      />
    </label>
  );
}

function isFastScanOptions(o: ScanOptions): boolean {
  return !o.yandex_search && !o.match_verify && !o.ai_search && !o.dmca_lumen_per_image;
}

export default function App() {
  const bootScanToken = useRef(initialScanToken());
  const [url, setUrl] = useState("https://example.com");
  const [depth, setDepth] = useState(3);
  const [scanOptions, setScanOptions] = useState<ScanOptions>(FALLBACK_SCAN_OPTIONS);
  const [defaultOptions, setDefaultOptions] = useState<ScanOptions>(FALLBACK_SCAN_OPTIONS);
  const [fastPreset, setFastPreset] = useState<ScanOptions | null>(null);
  const [keysConfigured, setKeysConfigured] = useState<KeysConfigured>({
    gemini: false,
    huggingface: false,
    tineye: false,
    dmca: false,
    serpapi: false,
  });
  const [optionsOpen, setOptionsOpen] = useState(false);
  const [scanToken, setScanToken] = useState<string | null>(() => bootScanToken.current);
  const [restoredSession, setRestoredSession] = useState(() => bootScanToken.current !== null);
  const [status, setStatus] = useState<ScanStatusResponse | null>(null);
  const [results, setResults] = useState<ScanResults | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [riskSort, setRiskSort] = useState<RiskSort>("default");
  const [viewMode, setViewMode] = useState<ViewMode>("grid");
  const [copyDone, setCopyDone] = useState(false);
  const [shareCopied, setShareCopied] = useState<string | null>(null);
  const [selected, setSelected] = useState<ImageResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [controlBusy, setControlBusy] = useState(false);
  const knownIds = useRef<Set<number>>(new Set());

  const [user, setUser] = useState<UserInfo | null>(null);
  const [authOpen, setAuthOpen] = useState(false);
  const [authMode, setAuthMode] = useState<"login" | "register">("login");
  const [authEmail, setAuthEmail] = useState("");
  const [authPassword, setAuthPassword] = useState("");
  const [authError, setAuthError] = useState("");
  const [authBusy, setAuthBusy] = useState(false);
  const [history, setHistory] = useState<ScanHistoryItem[]>([]);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [settingsBusy, setSettingsBusy] = useState(false);
  const [settingsSaved, setSettingsSaved] = useState(false);

  const loadUserSettings = useCallback(async () => {
    const res = await apiFetch("/api/user/settings");
    if (!res.ok) return;
    const data = await res.json();
    if (data?.settings) setScanOptions(data.settings);
    if (data?.keys_configured) setKeysConfigured(data.keys_configured);
  }, []);

  const loadHistory = useCallback(async () => {
    try {
      const res = await apiFetch("/api/user/scans");
      if (!res.ok) return;
      const data = await res.json();
      setHistory(data.items ?? []);
    } catch {
      /* ponytail: network/CORS — ignore on bootstrap */
    }
  }, []);

  const bootstrapAuth = useCallback(async () => {
    if (!getAuthToken()) return;
    const res = await apiFetch("/api/auth/me");
    if (!res.ok) {
      setAuthToken(null);
      return;
    }
    const me: UserInfo = await res.json();
    setUser(me);
    await Promise.all([loadUserSettings(), loadHistory()]);
  }, [loadHistory, loadUserSettings]);

  useEffect(() => {
    bootstrapAuth();
  }, [bootstrapAuth]);

  useEffect(() => {
    if (!user) return;
    const saved = readScanTokenFromUrl() ?? readScanTokenFromStorage();
    if (saved) setScanToken(saved);
  }, [user]);

  useEffect(() => {
    fetch(`${API}/api/scan/options-defaults`)
      .then((r) => r.json())
      .then((data: ScanOptionsDefaults) => {
        if (data?.defaults && !getAuthToken()) {
          setDefaultOptions(data.defaults);
          setScanOptions(data.defaults);
        } else if (data?.defaults) {
          setDefaultOptions(data.defaults);
        }
        if (data?.presets?.fast) setFastPreset(data.presets.fast);
        if (data?.keys_configured) setKeysConfigured(data.keys_configured);
      })
      .catch(() => {
        /* ponytail: use FALLBACK_SCAN_OPTIONS */
      });
  }, []);

  const setOption = (key: keyof ScanOptions, value: boolean) => {
    setScanOptions((prev) => {
      const next = { ...prev, [key]: value };
      if (key === "ai_search" && !value) {
        next.duckduckgo = false;
        next.huggingface = false;
        next.gemini = false;
        next.tineye = false;
        next.perplexity = false;
        next.copilot = false;
      }
      return next;
    });
  };

  const setApiKey = (key: keyof typeof EMPTY_API_KEYS, value: string) => {
    setScanOptions((prev) => ({ ...prev, [key]: value }));
  };

  const setFilterOption = (key: "min_file_size_kb" | "min_image_width" | "min_image_height", value: number) => {
    setScanOptions((prev) => ({ ...prev, [key]: value }));
  };

  const applyPreset = (preset: ScanOptions) =>
    setScanOptions((prev) => ({
      ...preset,
      min_file_size_kb: prev.min_file_size_kb,
      min_image_width: prev.min_image_width,
      min_image_height: prev.min_image_height,
      gemini_api_key: prev.gemini_api_key,
      huggingface_api_token: prev.huggingface_api_token,
      tineye_api_key: prev.tineye_api_key,
      tineye_api_secret: prev.tineye_api_secret,
      dmca_api_key: prev.dmca_api_key,
      serpapi_key: prev.serpapi_key,
    }));

  const saveSettings = async () => {
    if (!user) return;
    setSettingsBusy(true);
    setSettingsSaved(false);
    try {
      const res = await apiFetch("/api/user/settings", {
        method: "PUT",
        body: JSON.stringify(scanOptions),
      });
      if (res.ok) {
        setSettingsSaved(true);
        setTimeout(() => setSettingsSaved(false), 2000);
      }
    } finally {
      setSettingsBusy(false);
    }
  };

  const submitAuth = async (e: FormEvent) => {
    e.preventDefault();
    setAuthError("");
    setAuthBusy(true);
    try {
      const res = await fetch(`${API}/api/auth/${authMode}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: authEmail.trim(), password: authPassword }),
      });
      const data = await res.json();
      if (!res.ok) {
        const detail = data.detail;
        setAuthError(typeof detail === "string" ? detail : detail?.[0]?.msg ?? "Ошибка авторизации");
        return;
      }
      setAuthToken(data.access_token);
      setUser(data.user);
      setAuthOpen(false);
      setAuthPassword("");
      await Promise.all([loadUserSettings(), loadHistory()]);
    } finally {
      setAuthBusy(false);
    }
  };

  const logout = () => {
    setAuthToken(null);
    setUser(null);
    setHistory([]);
    setHistoryOpen(false);
    setScanOptions(defaultOptions);
    setScanToken(null);
    setGuestScanToken(null);
    persistScanToken(null, false);
    setStatus(null);
    setResults(null);
  };

  const openHistoryScan = (token: string) => {
    setScanToken(token);
    persistScanToken(token, true);
    setRestoredSession(true);
    setResults(null);
    setStatus(null);
    setHistoryOpen(false);
  };

  const deleteHistoryScan = async (token: string, e: MouseEvent) => {
    e.stopPropagation();
    if (!confirm("Удалить проверку из истории?")) return;
    const res = await apiFetch(`/api/scan/${token}`, { method: "DELETE" });
    if (!res.ok) return;
    setHistory((prev) => prev.filter((h) => h.token !== token));
    if (scanToken === token) {
      setScanToken(null);
      persistScanToken(null, false);
      setStatus(null);
      setResults(null);
    }
  };

  const toggleShare = async (token: string, enabled: boolean) => {
    const res = await apiFetch(`/api/scan/${token}/share`, { method: enabled ? "POST" : "DELETE" });
    if (!res.ok) return;
    const data = await res.json();
    setHistory((prev) => prev.map((h) => (h.token === token ? { ...h, share_enabled: data.share_enabled } : h)));
    if (scanToken === token && status) setStatus({ ...status, share_enabled: data.share_enabled });
  };

  const copyShareLink = async (token: string) => {
    await copyText(buildShareUrl(token));
    setShareCopied(token);
    setTimeout(() => setShareCopied(null), 2000);
  };

  const startScan = async () => {
    const submittedUrl = url.trim();
    setLoading(true);
    setResults(null);
    setStatus(null);
    setRestoredSession(false);
    setScanToken(null);
    setGuestScanToken(null);
    persistScanToken(null, false);
    knownIds.current = new Set();
    try {
      const res = await scanFetch("/api/scan", {
        method: "POST",
        body: JSON.stringify({ url: submittedUrl, depth, options: scanOptions }),
      });
      const data = await res.json();
      setScanToken(data.token);
      if (user) {
        persistScanToken(data.token, true);
        loadHistory();
      } else {
        setGuestScanToken(data.token);
      }
    } finally {
      setLoading(false);
    }
  };

  const scanControl = async (action: "pause" | "resume" | "stop") => {
    if (!scanToken) return;
    setControlBusy(true);
    try {
      await scanFetch(`/api/scan/${scanToken}/${action}`, { method: "POST" });
      await poll();
    } finally {
      setControlBusy(false);
    }
  };

  const poll = useCallback(async () => {
    if (!scanToken) return;
    const res = await scanFetch(`/api/scan/${scanToken}`);
    if (res.status === 404 || res.status === 403) {
      persistScanToken(null, Boolean(user));
      setGuestScanToken(null);
      setScanToken(null);
      setStatus(null);
      setResults(null);
      setRestoredSession(false);
      return;
    }
    const s: ScanStatusResponse = await res.json();
    setStatus(s);

    const live = ACTIVE.includes(s.status) || s.status === "cancelled";
    if (live || s.status === "done" || s.status === "failed") {
      const r: ScanResults = await scanFetch(`/api/scan/${scanToken}/results`).then((res) => res.json());
      setResults(r);
    }
    if (!ACTIVE.includes(s.status)) {
      setRestoredSession(false);
    }
  }, [scanToken, user]);

  useEffect(() => {
    if (scanToken && user) persistScanToken(scanToken, true);
  }, [scanToken, user]);

  useEffect(() => {
    if (!scanToken) return;
    poll();
    const ms = status && ACTIVE.includes(status.status) ? 800 : 2000;
    const t = setInterval(poll, ms);
    return () => clearInterval(t);
  }, [scanToken, poll, status?.status]);

  const flatImages = useMemo(() => {
    if (!results) return [];
    return results.pages.flatMap((p) =>
      p.images.map((img) => ({ ...img, pageUrl: p.url })),
    );
  }, [results]);

  const filtered = useMemo(() => {
    const list = flatImages.filter((img) => {
      const risk = img.copyright_check?.risk_level;
      if (filter === "violations") return risk && risk !== "safe";
      if (filter === "clean") return risk === "safe";
      return true;
    });
    if (riskSort === "default") return list;
    const order = (img: FlatImage) => RISK_SORT_ORDER[img.copyright_check?.risk_level ?? "pending"] ?? 9;
    return [...list].sort((a, b) => (riskSort === "risk_desc" ? order(a) - order(b) : order(b) - order(a)));
  }, [flatImages, filter, riskSort]);

  const isActive = status && (status.status === "in_progress" || status.status === "paused");
  const pendingCount = flatImages.filter((i) => !i.copyright_check).length;
  const checkingCount = pendingCount;
  const showGrid = results && (flatImages.length > 0 || (isActive && (status?.images_found ?? 0) > 0));

  const copyTable = async () => {
    const tsv = buildTableTsv(filtered);
    await copyText(tsv);
    setCopyDone(true);
    setTimeout(() => setCopyDone(false), 2000);
  };

  const selectedReasons = selected ? getReasons(selected.copyright_check) : [];
  const selectedRisk = selected?.copyright_check?.risk_level;
  const googleHit = selected ? getEngineEvidence(selected.copyright_check?.source_evidence, "google") : null;
  const yandexHit = selected ? getEngineEvidence(selected.copyright_check?.source_evidence, "yandex") : null;
  const selectedDmca = selected?.copyright_check?.dmca_evidence as Record<string, unknown> | null | undefined;
  const selectedAi = selected?.copyright_check?.source_evidence?.ai_search_evidence as
    | Record<string, unknown>
    | null
    | undefined;
  const selectedGemini = selected?.copyright_check?.source_evidence?.ai_analysis as
    | Record<string, unknown>
    | null
    | undefined;
  const dmcaLines = selected ? getDmcaSummaryLines(selectedDmca) : [];
  const aiLines = selected ? getAiSummaryLines(selectedAi, selectedGemini) : [];
  const selectedEvidence = selected?.copyright_check?.source_evidence;
  const noSearchMatch = Boolean(
    selectedEvidence &&
      selectedEvidence.has_search_match === false &&
      selected?.copyright_check?.risk_level &&
      selected.copyright_check.risk_level !== "safe",
  );

  return (
    <div className="app">
      <header>
        <div className="header-row">
          <div>
            <h1>CheckImg</h1>
            <p>Copyright image scanner for websites</p>
          </div>
          <div className="auth-bar">
            {user ? (
              <>
                <span className="auth-email">{user.email}</span>
                <button type="button" className="btn-secondary" onClick={() => setHistoryOpen((v) => !v)}>
                  История
                </button>
                <button type="button" className="btn-secondary" onClick={logout}>
                  Выйти
                </button>
              </>
            ) : (
              <>
                <span className="guest-hint">Без входа — проверка доступна, история не сохраняется</span>
                <button type="button" className="btn-secondary" onClick={() => { setAuthMode("login"); setAuthOpen(true); }}>
                  Войти
                </button>
                <button type="button" className="btn-primary-outline" onClick={() => { setAuthMode("register"); setAuthOpen(true); }}>
                  Регистрация
                </button>
              </>
            )}
          </div>
        </div>
      </header>

      {authOpen && (
        <div className="auth-modal-backdrop" onClick={() => setAuthOpen(false)}>
          <form className="auth-modal" onClick={(e) => e.stopPropagation()} onSubmit={submitAuth}>
            <h2>{authMode === "login" ? "Вход" : "Регистрация"}</h2>
            <label>
              Email
              <input type="email" value={authEmail} onChange={(e) => setAuthEmail(e.target.value)} required autoComplete="email" />
            </label>
            <label>
              Пароль
              <input type="password" value={authPassword} onChange={(e) => setAuthPassword(e.target.value)} required minLength={6} autoComplete={authMode === "login" ? "current-password" : "new-password"} />
            </label>
            {authError ? <p className="auth-error">{authError}</p> : null}
            <div className="auth-modal-actions">
              <button type="submit" disabled={authBusy}>{authMode === "login" ? "Войти" : "Зарегистрироваться"}</button>
              <button type="button" className="btn-secondary" onClick={() => setAuthMode(authMode === "login" ? "register" : "login")}>
                {authMode === "login" ? "Создать аккаунт" : "Уже есть аккаунт"}
              </button>
            </div>
          </form>
        </div>
      )}

      {user && historyOpen && (
        <aside className="history-panel">
          <h3>История проверок</h3>
          {history.length === 0 ? (
            <p className="history-empty">Пока нет сохранённых сканов</p>
          ) : (
            <ul className="history-list">
              {history.map((item) => (
                <li key={item.token} className="history-row">
                  <button type="button" className="history-item" onClick={() => openHistoryScan(item.token)}>
                    <span className="history-url">{item.url}</span>
                    <span className="history-meta">
                      {item.status} · глубина {item.depth} · {new Date(item.created_at).toLocaleString()}
                    </span>
                    {item.options_summary ? (
                      <span className="history-options" title={item.options_summary}>
                        {item.options_summary}
                      </span>
                    ) : null}
                  </button>
                  <div className="history-actions">
                    <button
                      type="button"
                      className="btn-icon"
                      title={item.share_enabled ? "Отключить доступ по ссылке" : "Поделиться"}
                      onClick={(e) => {
                        e.stopPropagation();
                        void toggleShare(item.token, !item.share_enabled);
                      }}
                    >
                      {item.share_enabled ? "🔗" : "↗"}
                    </button>
                    {item.share_enabled ? (
                      <button
                        type="button"
                        className="btn-icon"
                        title="Копировать ссылку"
                        onClick={(e) => {
                          e.stopPropagation();
                          void copyShareLink(item.token);
                        }}
                      >
                        {shareCopied === item.token ? "✓" : "📋"}
                      </button>
                    ) : null}
                    <button
                      type="button"
                      className="btn-icon btn-icon-danger"
                      title="Удалить"
                      onClick={(e) => deleteHistoryScan(item.token, e)}
                    >
                      ✕
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </aside>
      )}

      <form
        className="scan-form"
        onSubmit={(e) => {
          e.preventDefault();
          startScan();
        }}
      >
        <label>
          Site URL
          <input type="url" value={url} onChange={(e) => setUrl(e.target.value)} required />
        </label>
        <label className="depth-label">
          <span className="depth-label-row">
            Crawl depth ({depth})
            <span
              className="hint-icon"
              title="Глубина обхода: 1 — только указанная страница; 2 — страница и ссылки с неё; 3 — ещё один уровень вглубь. Больше уровней = дольше скан и больше страниц."
            >
              ?
            </span>
          </span>
          <input
            type="range"
            min={1}
            max={10}
            value={depth}
            onChange={(e) => setDepth(Number(e.target.value))}
          />
        </label>
        <details
          className="scan-options"
          open={optionsOpen}
          onToggle={(e) => setOptionsOpen((e.target as HTMLDetailsElement).open)}
        >
          <summary>Опции проверки</summary>
          <div className="option-presets">
            <button type="button" className="preset-btn" onClick={() => applyPreset(defaultOptions)}>
              Стандарт
            </button>
            <button
              type="button"
              className="preset-btn preset-btn-fast"
              onClick={() => applyPreset(fastPreset ?? { ...defaultOptions, yandex_search: false, match_verify: false, ai_search: false, duckduckgo: false, huggingface: false, gemini: false, tineye: false, perplexity: false, copilot: false, dmca_lumen_per_image: false })}
            >
              Быстро
            </button>
          </div>
          <fieldset className="option-filters">
            <legend>Фильтры изображений</legend>
            <OptionSlider
              label="Мин. размер файла"
              value={scanOptions.min_file_size_kb}
              min={0}
              max={500}
              step={5}
              unit="КБ"
              onChange={(v) => setFilterOption("min_file_size_kb", v)}
            />
            <OptionSlider
              label="Мин. ширина"
              value={scanOptions.min_image_width}
              min={0}
              max={2000}
              step={10}
              unit="px"
              onChange={(v) => setFilterOption("min_image_width", v)}
            />
            <OptionSlider
              label="Мин. высота"
              value={scanOptions.min_image_height}
              min={0}
              max={2000}
              step={10}
              unit="px"
              onChange={(v) => setFilterOption("min_image_height", v)}
            />
            <p className="option-hint">0 = без ограничения (кроме иконок 80 байт). По умолчанию 32×32 px.</p>
          </fieldset>
          <div className="option-grid">
            <fieldset>
              <legend>Обратный поиск</legend>
              <label>
                <input
                  type="checkbox"
                  checked={scanOptions.google_search}
                  onChange={(e) => setOption("google_search", e.target.checked)}
                />
                Google Lens
              </label>
              <ApiKeyField
                show={scanOptions.google_search}
                label="SerpAPI key (опционально, fallback)"
                value={scanOptions.serpapi_key}
                configured={keysConfigured.serpapi}
                placeholder="serpapi_…"
                onChange={(v) => setApiKey("serpapi_key", v)}
              />
              <label>
                <input
                  type="checkbox"
                  checked={scanOptions.yandex_search}
                  onChange={(e) => setOption("yandex_search", e.target.checked)}
                />
                Яндекс.Картинки
              </label>
              <label>
                <input
                  type="checkbox"
                  checked={scanOptions.match_verify}
                  onChange={(e) => setOption("match_verify", e.target.checked)}
                />
                Визуальная верификация (медленно)
              </label>
            </fieldset>
            <fieldset>
              <legend>DMCA</legend>
              <label>
                <input
                  type="checkbox"
                  checked={scanOptions.dmca_checks}
                  onChange={(e) => setOption("dmca_checks", e.target.checked)}
                />
                Lumen / Google Transparency / blacklist
              </label>
              <ApiKeyField
                show={scanOptions.dmca_checks}
                label="DMCA.com API key (опционально)"
                value={scanOptions.dmca_api_key}
                configured={keysConfigured.dmca}
                placeholder="dmca API key"
                onChange={(v) => setApiKey("dmca_api_key", v)}
              />
              <label>
                <input
                  type="checkbox"
                  checked={scanOptions.dmca_lumen_per_image}
                  disabled={!scanOptions.dmca_checks}
                  onChange={(e) => setOption("dmca_lumen_per_image", e.target.checked)}
                />
                Lumen по каждому URL (очень медленно)
              </label>
            </fieldset>
            <fieldset>
              <legend>AI-поиск</legend>
              <label>
                <input
                  type="checkbox"
                  checked={scanOptions.ai_search}
                  onChange={(e) => setOption("ai_search", e.target.checked)}
                />
                Включить AI-модуль
              </label>
              <label className="option-sub">
                <input
                  type="checkbox"
                  checked={scanOptions.duckduckgo}
                  disabled={!scanOptions.ai_search}
                  onChange={(e) => setOption("duckduckgo", e.target.checked)}
                />
                DuckDuckGo
              </label>
              <label className="option-sub">
                <input
                  type="checkbox"
                  checked={scanOptions.huggingface}
                  disabled={!scanOptions.ai_search}
                  onChange={(e) => setOption("huggingface", e.target.checked)}
                />
                Hugging Face
              </label>
              <ApiKeyField
                show={scanOptions.ai_search && scanOptions.huggingface}
                label="Hugging Face token"
                value={scanOptions.huggingface_api_token}
                configured={keysConfigured.huggingface}
                placeholder="hf_…"
                onChange={(v) => setApiKey("huggingface_api_token", v)}
              />
              <label className="option-sub">
                <input
                  type="checkbox"
                  checked={scanOptions.gemini}
                  disabled={!scanOptions.ai_search}
                  onChange={(e) => setOption("gemini", e.target.checked)}
                />
                Gemini
              </label>
              <ApiKeyField
                show={scanOptions.ai_search && scanOptions.gemini}
                label="Gemini API key"
                value={scanOptions.gemini_api_key}
                configured={keysConfigured.gemini}
                placeholder="AIza…"
                onChange={(v) => setApiKey("gemini_api_key", v)}
              />
              <label className="option-sub">
                <input
                  type="checkbox"
                  checked={scanOptions.tineye}
                  disabled={!scanOptions.ai_search}
                  onChange={(e) => setOption("tineye", e.target.checked)}
                />
                TinEye
              </label>
              <ApiKeyField
                show={scanOptions.ai_search && scanOptions.tineye}
                label="TinEye API key"
                value={scanOptions.tineye_api_key}
                configured={keysConfigured.tineye}
                placeholder="public key"
                onChange={(v) => setApiKey("tineye_api_key", v)}
              />
              <ApiKeyField
                show={scanOptions.ai_search && scanOptions.tineye}
                label="TinEye API secret"
                value={scanOptions.tineye_api_secret}
                configured={keysConfigured.tineye}
                placeholder="private key"
                onChange={(v) => setApiKey("tineye_api_secret", v)}
              />
              <label className="option-sub">
                <input
                  type="checkbox"
                  checked={scanOptions.perplexity}
                  disabled={!scanOptions.ai_search}
                  onChange={(e) => setOption("perplexity", e.target.checked)}
                />
                Perplexity (DDG probe)
              </label>
              <label className="option-sub">
                <input
                  type="checkbox"
                  checked={scanOptions.copilot}
                  disabled={!scanOptions.ai_search}
                  onChange={(e) => setOption("copilot", e.target.checked)}
                />
                Copilot (DDG probe)
              </label>
            </fieldset>
          </div>
          {user ? (
            <div className="settings-save-row">
              <button type="button" className="btn-secondary" disabled={settingsBusy} onClick={saveSettings}>
                {settingsBusy ? "Сохранение…" : settingsSaved ? "Сохранено ✓" : "Сохранить настройки в ЛК"}
              </button>
              <span className="option-hint">Ключи API и фильтры сохраняются в аккаунте</span>
            </div>
          ) : null}
        </details>
        <button type="submit" disabled={loading || (isActive ?? false)}>
          {loading ? "Starting…" : "Start scan"}
        </button>
      </form>

      {restoredSession && status && ACTIVE.includes(status.status) && (
        <p className="reconnect-notice">
          Восстановлено подключение к скану ({status.url}). Проверка идёт на сервере — обновление
          страницы её не останавливает. Нажмите Stop, чтобы прервать.
          <button type="button" className="link-btn" onClick={() => setRestoredSession(false)}>
            Скрыть
          </button>
        </p>
      )}

      {status && (
        <div className="progress">
          <div className="progress-row">
            <strong>{status.url}</strong>
            {status.scan_options && isFastScanOptions(status.scan_options) && (
              <span className="scan-mode-tag">режим: быстрый</span>
            )}
            <span className="scan-target-url" title={status.url}>
              {status.url}
            </span>
            <span className={`status-pill ${status.status}`}>{status.status}</span>
            <span>{status.progress_pct}%</span>
            <span>
              глубина {status.depth_reached}/{status.depth}
            </span>
            <span>{status.pages_scanned} pages</span>
            <span>{status.images_processed}/{status.images_found} checked</span>
            {checkingCount > 0 && (
              <span className="pending-count checking-pulse">{checkingCount} проверяется…</span>
            )}
            {user && scanToken && (
              <>
                <button
                  type="button"
                  className="btn-secondary btn-sm"
                  onClick={() => void toggleShare(scanToken, !status.share_enabled)}
                >
                  {status.share_enabled ? "Ссылка активна" : "Поделиться"}
                </button>
                {status.share_enabled ? (
                  <button type="button" className="btn-secondary btn-sm" onClick={() => void copyShareLink(scanToken)}>
                    {shareCopied === scanToken ? "Скопировано" : "Копировать ссылку"}
                  </button>
                ) : null}
              </>
            )}
          </div>
          {isActive && status.images_found > status.images_processed && (
            <p className="progress-hint">
              Найдено {status.images_found} · проверено {status.images_processed} · идёт анализ (Google/Яндекс/EXIF)…
            </p>
          )}
          <div className="progress-bar">
            <div className="progress-fill" style={{ width: `${status.progress_pct}%` }} />
          </div>
          {isActive && (
            <div className="scan-controls">
              {status.status === "in_progress" ? (
                <button type="button" disabled={controlBusy} onClick={() => scanControl("pause")}>
                  Pause
                </button>
              ) : (
                <button type="button" disabled={controlBusy} onClick={() => scanControl("resume")}>
                  Resume
                </button>
              )}
              <button type="button" className="btn-stop" disabled={controlBusy} onClick={() => scanControl("stop")}>
                Stop
              </button>
            </div>
          )}
          {status.error_message && <p className="error-msg">{status.error_message}</p>}
        </div>
      )}

      {showGrid && (
        <div className="results-panel">
          <div className="toolbar">
            <div className="filters">
              {(["all", "violations", "clean"] as Filter[]).map((f) => (
                <button
                  key={f}
                  type="button"
                  className={filter === f ? "active" : ""}
                  onClick={() => setFilter(f)}
                >
                  {f === "all" ? "All" : f === "violations" ? "Violations" : "Clean"} (
                  {f === "all"
                    ? flatImages.length
                    : f === "violations"
                      ? flatImages.filter((i) => i.copyright_check && i.copyright_check.risk_level !== "safe").length
                      : flatImages.filter((i) => i.copyright_check?.risk_level === "safe").length}
                  )
                </button>
              ))}
            </div>
            <div className="view-controls">
              <label className="sort-select">
                Сортировка
                <select value={riskSort} onChange={(e) => setRiskSort(e.target.value as RiskSort)}>
                  <option value="default">по порядку</option>
                  <option value="risk_desc">риск ↓</option>
                  <option value="risk_asc">риск ↑</option>
                </select>
              </label>
              <button
                type="button"
                className={viewMode === "grid" ? "active" : ""}
                onClick={() => setViewMode("grid")}
              >
                Сетка
              </button>
              <button
                type="button"
                className={viewMode === "table" ? "active" : ""}
                onClick={() => setViewMode("table")}
              >
                Таблица
              </button>
              <button type="button" className="btn-copy" onClick={copyTable} disabled={!filtered.length}>
                {copyDone ? "Скопировано!" : "Копировать для Excel"}
              </button>
            </div>
          </div>

          {viewMode === "grid" ? (
          <div className="grid">
            {filtered.map((img) => {
              const checked = !!img.copyright_check;
              const risk = img.copyright_check?.risk_level ?? "pending";
              const isNew = !knownIds.current.has(img.id);
              knownIds.current.add(img.id);
              const flagged = checked && risk !== "safe";
              return (
                <article
                  key={img.id}
                  className={`card ${risk}${isNew ? " card-new" : ""}${!checked ? " card-checking" : ""}`}
                  onClick={() => checked && setSelected(img)}
                  title={flagged ? getReasons(img.copyright_check).join("\n") : checked ? undefined : "Проверяется…"}
                >
                  <PreviewImg scanToken={results.scan_token} imageId={img.id} alt={img.alt_text ?? ""} />
                  <div className="card-body">
                    <span className={`badge ${risk}`}>
                      {checked ? (RISK_LABELS[risk as RiskLevel] ?? risk) : "checking…"}
                    </span>
                    {flagged && (
                      <p className="card-hint">{getReasons(img.copyright_check)[0] ?? "Подозрительное изображение"}</p>
                    )}
                    <p className="card-url">{img.src_url.slice(0, 80)}…</p>
                  </div>
                </article>
              );
            })}
          </div>
          ) : (
          <div className="table-wrap">
            <div className="results-table" role="table">
              <div className="results-table-head" role="rowgroup">
                <div className="results-table-row results-table-row-head" role="row">
                  <div role="columnheader">Риск</div>
                  <div role="columnheader">Изображение</div>
                  <div role="columnheader">Страница</div>
                  <div role="columnheader">Причины</div>
                  <div role="columnheader">Google</div>
                  <div role="columnheader">Яндекс</div>
                </div>
              </div>
              <div className="results-table-body" role="rowgroup">
                {filtered.map((img) => {
                  const risk = img.copyright_check?.risk_level ?? "pending";
                  const ev = img.copyright_check?.source_evidence;
                  const google = getEngineEvidence(ev, "google");
                  const yandex = getEngineEvidence(ev, "yandex");
                  const reasons = getReasons(img.copyright_check);
                  return (
                    <div
                      key={img.id}
                      className={`results-table-row row-${risk}`}
                      role="row"
                      onClick={() => img.copyright_check && setSelected(img)}
                    >
                      <div className="cell-risk" role="cell">
                        <span className={`badge ${risk}`}>{RISK_LABELS[risk as RiskLevel] ?? risk}</span>
                      </div>
                      <div className="cell-thumb" role="cell">
                        <a
                          href={img.src_url}
                          title={img.src_url}
                          target="_blank"
                          rel="noreferrer"
                          onClick={(e) => e.stopPropagation()}
                        >
                          <PreviewImg scanToken={results!.scan_token} imageId={img.id} alt="" />
                        </a>
                      </div>
                      <div className="cell-page" role="cell">
                        <a
                          href={img.pageUrl}
                          title={img.pageUrl}
                          target="_blank"
                          rel="noreferrer"
                          onClick={(e) => e.stopPropagation()}
                        >
                          {pagePath(img.pageUrl)}
                        </a>
                      </div>
                      <div
                        className="cell-reasons"
                        role="cell"
                        title={reasons.length ? reasons.join("; ") : undefined}
                      >
                        <span className="cell-reasons-text">{formatReasonsForTable(reasons)}</span>
                      </div>
                      <div className="cell-action" role="cell">
                        {google?.best_match_url ? (
                          <a
                            href={google.best_match_url}
                            className="btn-link"
                            title={google.best_match_url}
                            target="_blank"
                            rel="noreferrer"
                            onClick={(e) => e.stopPropagation()}
                          >
                            Перейти
                          </a>
                        ) : (
                          "—"
                        )}
                      </div>
                      <div className="cell-action" role="cell">
                        {yandex?.best_match_url ? (
                          <a
                            href={yandex.best_match_url}
                            className="btn-link"
                            title={yandex.best_match_url}
                            target="_blank"
                            rel="noreferrer"
                            onClick={(e) => e.stopPropagation()}
                          >
                            Перейти
                          </a>
                        ) : (
                          "—"
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
          )}
        </div>
      )}

      {selected && results && (
        <div className="modal-backdrop" onClick={() => setSelected(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2>Детали изображения</h2>
              {selectedRisk && selectedRisk !== "safe" && (
                <span className={`badge ${selectedRisk}`}>{selectedRisk}</span>
              )}
            </div>

            {noSearchMatch && selectedReasons.length > 0 && (
              <div className="reasons-box no-search">
                <h3>Без совпадений в Google / Яндекс</h3>
                <p className="no-search-note">
                  Риск выставлен по другим сигналам (EXIF, эвристика водяного знака, текст выдачи Яндекса):
                </p>
                <ul>
                  {selectedReasons.map((r) => (
                    <li key={r}>{r}</li>
                  ))}
                </ul>
              </div>
            )}

            {selectedReasons.length > 0 && !noSearchMatch && (
              <div className={`reasons-box${selectedRisk === "danger" || selectedRisk === "dmca_violation" ? " danger" : ""}`}>
                <h3>Причина подозрения</h3>
                <ul>
                  {selectedReasons.map((r) => (
                    <li key={r}>{r}</li>
                  ))}
                </ul>
              </div>
            )}

            {dmcaLines.length > 0 && (
              <div className="dmca-box">
                <h3>DMCA Evidence</h3>
                <ul className="dmca-list">
                  {dmcaLines.map((line, i) => (
                    <li key={`dmca-${i}`}>{line}</li>
                  ))}
                </ul>
              </div>
            )}

            {aiLines.length > 0 && (
              <div className="ai-box">
                <h3>AI-проверка</h3>
                <ul>
                  {aiLines.map((line, i) => (
                    <li key={`ai-${i}`}>{line}</li>
                  ))}
                </ul>
              </div>
            )}

            {selected?.copyright_check && dmcaLines.length === 0 && aiLines.length === 0 && (
              <p className="evidence-empty">
                DMCA / AI: данные не сохранены (запустите новый скан после обновления).
              </p>
            )}

            <div className="compare compare-triple">
              <div className="compare-col">
                <h3>На сайте</h3>
                <PreviewImg scanToken={results.scan_token} imageId={selected.id} alt="" />
                <a className="modal-link" href={selected.src_url} target="_blank" rel="noreferrer">
                  {selected.src_url}
                </a>
              </div>
              <div className="compare-col">
                <h3>Google</h3>
                {googleHit?.best_match_url ? (
                  <>
                    {googleHit.site_type && (
                      <span className="engine-type">{SITE_TYPE_RU[googleHit.site_type] ?? googleHit.site_type}</span>
                    )}
                    {googleHit.title && googleHit.title !== googleHit.best_match_url && (
                      <p className="engine-title">{googleHit.title}</p>
                    )}
                    {formatMatchKind(googleHit) && (
                      <span className={`engine-match-kind kind-${googleHit.best_match_kind}`}>
                        {formatMatchKind(googleHit)}
                      </span>
                    )}
                    <a className="modal-link" href={googleHit.best_match_url} target="_blank" rel="noreferrer">
                      {googleHit.best_match_url}
                    </a>
                    <p className="engine-meta">
                      {googleHit.exact_count ? `${googleHit.exact_count} точных` : null}
                      {googleHit.exact_count && googleHit.similar_count ? ", " : null}
                      {googleHit.similar_count ? `${googleHit.similar_count} похожих` : null}
                      {!googleHit.exact_count && !googleHit.similar_count ? `${googleHit.match_count ?? 0} в выдаче` : null}
                    </p>
                  </>
                ) : (
                  <p className="engine-empty">Совпадений не найдено</p>
                )}
              </div>
              <div className="compare-col">
                <h3>Яндекс</h3>
                {yandexHit?.best_match_url ? (
                  <>
                    {yandexHit.site_type && (
                      <span className="engine-type">{SITE_TYPE_RU[yandexHit.site_type] ?? yandexHit.site_type}</span>
                    )}
                    {yandexHit.text_snippet && yandexHit.text_snippet !== yandexHit.best_match_url && (
                      <p className="engine-title">{yandexHit.text_snippet}</p>
                    )}
                    {formatMatchKind(yandexHit) && (
                      <span className={`engine-match-kind kind-${yandexHit.best_match_kind}`}>
                        {formatMatchKind(yandexHit)}
                      </span>
                    )}
                    <a className="modal-link" href={yandexHit.best_match_url} target="_blank" rel="noreferrer">
                      {yandexHit.best_match_url}
                    </a>
                    <p className="engine-meta">
                      {yandexHit.exact_count ? `${yandexHit.exact_count} точных` : null}
                      {yandexHit.exact_count && yandexHit.similar_count ? ", " : null}
                      {yandexHit.similar_count ? `${yandexHit.similar_count} похожих` : null}
                      {!yandexHit.exact_count && !yandexHit.similar_count ? `${yandexHit.match_count ?? 0} в выдаче` : null}
                    </p>
                  </>
                ) : (
                  <p className="engine-empty">Совпадений не найдено</p>
                )}
              </div>
            </div>
            <button type="button" onClick={() => setSelected(null)} style={{ marginTop: 16 }}>
              Закрыть
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
