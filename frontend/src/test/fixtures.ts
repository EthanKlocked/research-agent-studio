import type { Snapshot, Config } from "../types";
export const config: Config = {
  configured: false,
  test_mode_available: true,
  capabilities: { general_web: false, search_provider: null },
  dataset: { name: "공개 기업 자료", as_of: "2024-12-31" },
  limits: { max_iterations: 2 },
};
export const snapshot = (overrides: Partial<Snapshot> = {}): Snapshot => ({
  run_id: "run-1",
  question: "실적과 위험요인을 조사해 주세요.",
  mode: "test",
  status: "running",
  stage: "Listener",
  iteration: 1,
  started_at: new Date().toISOString(),
  finished_at: null,
  last_seq: 1,
  interpreted_request: "공개 자료의 실적과 위험요인 분석",
  plan: [],
  evidence: [],
  report: null,
  revisions: [],
  evaluation: null,
  feedback: [],
  errors: [],
  ...overrides,
});
