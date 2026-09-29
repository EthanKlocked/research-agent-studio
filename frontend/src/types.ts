export type Status =
  | "queued"
  | "running"
  | "success"
  | "limit_reached"
  | "empty"
  | "error"
  | "cancelled";
export type Stage =
  | "Listener"
  | "Planner"
  | "Researcher"
  | "Reporter"
  | "Evaluator";
export interface Config {
  configured: boolean;
  test_mode_available: boolean;
  dataset: { name: string; as_of: string };
  limits: { max_iterations: number };
}
export interface Evidence {
  id: string;
  document_id: string;
  section_id: string;
  title: string;
  url: string;
  published_at: string;
  as_of: string;
  excerpt: string;
}
export interface Report {
  title: string;
  summary: string;
  claims: { text: string; citation_ids: string[] }[];
  limitations: string[];
}
export interface Evaluation {
  decision: "pass" | "revise";
  issues: string[];
  follow_up: string[];
}
export interface Revision {
  iteration: number;
  report: Report;
  evidence_ids: string[];
  added_evidence_ids: string[];
  evaluation: Evaluation;
}
export interface Snapshot {
  run_id: string;
  question: string;
  mode: "test" | "live";
  status: Status;
  stage: Stage | null;
  iteration: number;
  started_at: string;
  finished_at: string | null;
  last_seq: number;
  interpreted_request: string;
  plan: string[];
  evidence: Evidence[];
  report: Report | null;
  revisions: Revision[];
  evaluation: Evaluation | null;
  feedback: string[];
  errors: string[];
}
export interface RunEvent {
  seq: number;
  run_id: string;
  type: string;
  timestamp: string;
  data: {
    snapshot: Snapshot;
    tool?: string;
    tool_name?: string;
    input_summary?: string;
    count?: number;
    state_fields?: string[];
    changed_fields?: string[];
    reason?: string;
    branch?: string;
  };
}
