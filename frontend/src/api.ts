export type Severity = "high" | "medium" | "low" | "none";
export type Status = "pending" | "approved" | "overridden" | "auto_accepted";

export interface QueueRow {
  clause_id: string; doc_id: string; doc_title: string; contract_type: string; matter_team: string;
  clause_type: string; current_value: string | null; confidence: number; severity: Severity;
  status: Status; assigned_to: string | null; updated_at: string;
}
export interface Review {
  review_id: number; reviewer: string; action: "approve" | "override"; old_value: string | null;
  new_value: string | null; comment: string | null; reviewed_at: string;
}
export interface Clause extends QueueRow {
  extracted_value: string | null; normalized_value: string | null; source_snippet: string | null;
  top_rule_id: string | null; risk_explanation: string | null; matter_id: string; reviews: Review[];
}
export interface DocSummary {
  doc_id: string; doc_title: string; contract_type: string; matter_id: string; matter_team: string;
  clauses: number; pending: number; reviewed: number; sev_rank: number; updated_at: string;
}
export interface DocDetail {
  doc_id: string; clauses: Clause[]; full_text: string | null; page_count: string | null;
  party_name: string | null; row_filter_visible: boolean;
}
export interface Overview {
  kpis: Record<string, string | number | null>;
  by_contract_type: { label: string; value: string }[];
  by_severity: { label: string; value: string }[];
  by_rule: { rule_id: string; severity: string; rule_text: string; flags: string }[];
  auto_renewals: { doc_id: string; title: string; contract_type: string; matter_team: string;
                   expiration_date: string; uncapped_liability: string }[];
  user: string;
}
export interface ActionResult { review_id: number; status: Status; old_value: string | null; new_value: string | null; duration_ms: number; }
export interface GenieAnswer {
  conversation_id: string; message_id: string; status: string; text: string | null; sql: string | null;
  description: string | null; columns: string[]; rows: (string | null)[][]; error: string | null;
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...init });
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`;
    try { const j = await r.json(); msg = j.detail ?? msg; } catch { /* ignore */ }
    throw new Error(msg);
  }
  return r.json() as Promise<T>;
}

export const api = {
  me: () => call<{ email: string; genie_configured: boolean; catalog: string }>("/api/me"),
  overview: () => call<Overview>("/api/overview"),
  queue: (f: { status: string[]; severity: string[]; team: string[] }) =>
    call<{ rows: QueueRow[]; ms: number }>(
      `/api/queue?status=${f.status.join(",")}&severity=${f.severity.join(",")}&team=${encodeURIComponent(f.team.join(","))}`),
  documents: () => call<DocSummary[]>("/api/documents"),
  document: (id: string) => call<DocDetail>(`/api/documents/${id}`),
  approve: (id: string, comment?: string) =>
    call<ActionResult>(`/api/clauses/${id}/approve`, { method: "POST", body: JSON.stringify({ comment }) }),
  override: (id: string, new_value: string, comment: string) =>
    call<ActionResult>(`/api/clauses/${id}/override`, { method: "POST", body: JSON.stringify({ new_value, comment }) }),
  genie: (question: string, conversation_id?: string | null) =>
    call<GenieAnswer>("/api/genie", { method: "POST", body: JSON.stringify({ question, conversation_id }) }),
  audit: (action: string, entity?: string, entity_id?: string) =>
    call("/api/audit", { method: "POST", body: JSON.stringify({ action, entity, entity_id }) }).catch(() => undefined),
};

export const CLAUSE_LABEL: Record<string, string> = {
  governing_law: "Governing law", effective_date: "Effective date", expiration_date: "Expiration date",
  renewal_term: "Renewal term", auto_renewal: "Auto-renewal", notice_period_days: "Notice period (days)",
  liability_cap: "Liability cap", uncapped_liability: "Uncapped liability", indemnification: "Indemnification",
  termination_for_convenience: "Termination for convenience", exclusivity: "Exclusivity",
  non_compete: "Non-compete", assignment_restriction: "Assignment restriction", parties: "Parties",
};
