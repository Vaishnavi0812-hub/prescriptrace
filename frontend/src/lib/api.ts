export const API_BASE: string =
  (import.meta.env.VITE_API_BASE as string | undefined) ?? "http://localhost:8000";

// ---------------------------------------------------------------- types (mirror app/schemas/api.py)

export type Severity = "contraindicated" | "major" | "moderate" | "minor" | "unknown";
export type MatchStatus = "resolved" | "confirm" | "unknown";

export interface Health {
  status: "ok" | "degraded";
  database: boolean;
  datasets_loaded: number;
  search_ready?: boolean;
}

export interface Candidate {
  label: string;
  kind: string;
  ingredients: string[];
  ingredient_names: string[];
  confidence: number;
  method: string;
  ref: string;
  source: string;
}

export interface SearchHit {
  label: string;
  kind: string;
  ingredients: string[];
  ingredient_names: string[];
  ref: string;
  source: string;
}

export interface Strength {
  value: string;
  unit: string | null;
}

export interface NormalisedLine {
  raw: string;
  query: string;
  status: MatchStatus;
  confidence: number;
  best: Candidate | null;
  candidates: Candidate[];
  strengths: Strength[];
  dose_form: string | null;
}

export interface Evidence {
  dataset: string;
  dataset_name: string;
  dataset_version: string | null;
  record_id: string;
  url: string | null;
  quote: string | null;
}

export interface Finding {
  id: string;
  type: "interaction" | "duplicate_ingredient" | "duplicate_class" | "cumulative" | "context";
  severity: Severity;
  medicines: string[];
  drug_labels: string[];
  ingredients: string[];
  ingredient_ids: string[];
  title: string;
  simple: string;
  professional: string;
  consider: string;
  evidence: Evidence[];
  provenance: "structured" | "label_text" | "rule";
  confidence: "high" | "medium" | "low";
  rule_id: string | null;
  related: string[];
  related_rules: string[];
}

export interface CheckNote {
  context: string;
  medicine: string;
  ingredient: string;
  text: string;
  evidence: Evidence;
}

export interface RecallFlag {
  medicine_id: string;
  medicine_label: string;
  match: "batch" | "product" | "related" | "ingredient";
  level: "serious" | "warning" | "info";
  region: string;
  kind: string;
  title: string;
  simple: string;
  consider: string;
  product_description: string;
  reason: string | null;
  firm: string | null;
  status: string | null;
  report_date: string | null;
  lot_info: string | null;
  evidence: Evidence;
}

export interface IngredientSummary {
  medicine_id: string;
  medicine_label: string;
  region: string;
  total: number;
  recent: RecallFlag[];
}

export interface ChecklistItem {
  id: string;
  check: string;
  why: string;
  source: string;
  source_url: string | null;
}

export interface CheckResponse {
  summary: {
    headline: string;
    needs_attention: number;
    worth_checking: number;
    other: number;
    checked_medicines: number;
    unresolved: number;
  };
  medicines: {
    id: string;
    text: string;
    label: string;
    ingredients: { rxcui: string; name: string }[];
    how: string;
    confidence: number | null;
    batch: string | null;
  }[];
  unresolved: { id: string; text: string; status: MatchStatus; candidates: Candidate[] }[];
  findings: Finding[];
  notes: CheckNote[];
  recalls: {
    flags: RecallFlag[];
    ingredient_summaries: IngredientSummary[];
    checklist: ChecklistItem[];
    coverage_notes: string[];
  };
  no_known_issue_pairs: string[][];
  disclaimer: string;
  absence_note: string;
  data_versions: { code: string; name: string; version: string | null; licence: string }[];
}

export interface CheckRequestItem {
  id: string;
  text: string;
  selection?: { ref: string | null; label: string; ingredients: string[] };
  batch?: string;
}

export interface PatientContext {
  age_group: "child" | "adult" | "older" | null;
  pregnant: boolean;
  renal: boolean;
  hepatic: boolean;
}

export interface DatasetInfo {
  code: string;
  name: string;
  version: string | null;
  source_url: string;
  licence: string;
  licence_url: string | null;
  region: string | null;
  downloaded_at: string | null;
  record_count: number | null;
  limitations: string | null;
  last_ingest_status: string | null;
  last_ingest_at: string | null;
}

// ---------------------------------------------------------------- calls

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    // FormData (photo upload) sets its own multipart Content-Type with the boundary.
    headers: typeof init?.body === "string" ? { "Content-Type": "application/json" } : undefined,
  });
  if (!response.ok) {
    let detail = `${response.status}`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // keep the status code as the message
    }
    throw new ApiError(detail, response.status);
  }
  return (await response.json()) as T;
}

export const fetchHealth = (signal?: AbortSignal): Promise<Health> =>
  request<Health>("/api/v1/health", { signal });

export const searchDrugs = (q: string, signal?: AbortSignal): Promise<{ hits: SearchHit[] }> =>
  request(`/api/v1/drugs/search?q=${encodeURIComponent(q)}&limit=8`, { signal });

export const normaliseLines = (lines: string[]): Promise<{ results: NormalisedLine[] }> =>
  request("/api/v1/normalise", { method: "POST", body: JSON.stringify({ lines }) });

export const runCheck = (
  items: CheckRequestItem[],
  context: PatientContext,
  signal?: AbortSignal,
): Promise<CheckResponse> =>
  request("/api/v1/check", {
    method: "POST",
    body: JSON.stringify({ items, context }),
    signal,
  });

export const fetchDatasets = (
  signal?: AbortSignal,
): Promise<{ datasets: DatasetInfo[]; non_commercial_notice: string }> =>
  request("/api/v1/datasets", { signal });

// ---------------------------------------------------------------- OCR

export interface ScannedLine {
  text: string;
  ocr_confidence: number;
  box: number[];
  likely_medicine: boolean;
  status: MatchStatus;
  normalised: NormalisedLine | null;
  crop_png_b64: string | null;
}

export interface ScanResponse {
  engine: string;
  sends_image_off_device: boolean;
  lines: ScannedLine[];
  warnings: string[];
  skew_degrees: number;
  millis: number;
}

export const scanPrescription = (image: Blob, signal?: AbortSignal): Promise<ScanResponse> => {
  const form = new FormData();
  form.append("file", image, image instanceof File ? image.name : "prescription.jpg");
  return request("/api/v1/ocr", { method: "POST", body: form, signal });
};
