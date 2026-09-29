import { useState } from "react";
import { isComplete } from "./state";
import { safeEvent } from "./Timeline";
import type { RunEvent, Snapshot, Stage } from "./types";

export const stages = [
  { id: "Listener", label: "요청 확인", active: "요청 확인 중", path: "M5 4h14v12H9l-4 4V4zm4 5h6m-6 3h4" },
  { id: "Planner", label: "조사 계획", active: "조사 계획 중", path: "M8 5h12M8 12h12M8 19h12M3 5h.1M3 12h.1M3 19h.1" },
  { id: "Researcher", label: "자료 수집", active: "자료 수집 중", path: "M20 20l-5-5m2-5a7 7 0 1 1-14 0 7 7 0 0 1 14 0" },
  { id: "Reporter", label: "보고서 작성", active: "보고서 작성 중", path: "M6 3h8l4 4v14H6V3zm8 0v5h4M9 12h6m-6 4h6" },
  { id: "Evaluator", label: "검토", active: "검토 중", path: "M12 3l8 3v6c0 5-8 9-8 9s-8-4-8-9V6l8-3zm-4 9 3 3 5-6" },
] satisfies { id: Stage; label: string; active: string; path: string }[];

export function FocusRail({ snapshot: s, events, disconnected }: {
  snapshot: Snapshot | null; events: RunEvent[]; disconnected: boolean;
}) {
  const [pinned, setPinned] = useState<Stage | null>(null);
  const selected = pinned ?? s?.stage ?? "Listener";
  // Listener runs once before Planner increments the first iteration.
  const currentEvents = events.filter(e => e.run_id === s?.run_id &&
    (e.data.snapshot.iteration === s?.iteration || (e.data.role ?? e.data.snapshot.stage) === "Listener"));
  const stageEvents = currentEvents.filter(e => (e.data.role ?? e.data.snapshot.stage) === selected);
  const latest = stageEvents.at(-1);
  const complete = !!s && isComplete(s);
  const stageState = (id: Stage) => {
    const observed = currentEvents.filter(e => (e.data.role ?? e.data.snapshot.stage) === id);
    const lastNode = observed.filter(e => e.type === "node_start" || e.type === "node_complete").at(-1);
    if (s?.stage === id) {
      if (complete) return s.status === "success" ? "완료" : "실행 종료";
      return disconnected ? "연결 확인 중" : "진행 중";
    }
    if (lastNode?.type === "node_complete") return "완료";
    if (observed.length) return "기록 있음";
    if (s && stages.findIndex(stage => stage.id === id) < stages.findIndex(stage => stage.id === s.stage)) return "기록 없음";
    return "대기";
  };
  const output = !s ? "아직 시작하지 않았습니다." : selected === "Listener"
    ? s.interpreted_request ? `요청 요약: ${s.interpreted_request}` : "반영된 요청 요약이 없습니다."
    : selected === "Planner" ? s.plan.length ? `계획: ${s.plan.join(" · ")}` : "반영된 조사 계획이 없습니다."
    : selected === "Researcher" ? `반영된 근거 ${s.evidence.length}건 · 검색 결과와 도구 응답은 근거 반영 전까지 포함하지 않습니다.`
    : selected === "Reporter" ? s.report ? `보고서: ${s.report.title}` : "반영된 보고서가 없습니다."
    : s.evaluation ? `검토 결과: ${s.evaluation.decision === "pass" ? "통과" : "보완 필요"} · ${s.evaluation.issues.length}개 이슈` : "반영된 검토 결과가 없습니다.";
  return <>
    <ol className="stages" aria-label="조사 단계">
      {stages.map((stage, i) => <li key={stage.id} className={`${!complete && s?.stage === stage.id ? "current" : ""} ${stageState(stage.id) === "완료" ? "done" : ""}`} aria-current={!complete && s?.stage === stage.id ? "step" : undefined}>
        <button type="button" aria-label={`${i + 1}단계 ${stage.label}`} aria-pressed={selected === stage.id} onClick={() => setPinned(stage.id)}>
          <span className="stage-icon"><svg viewBox="0 0 24 24" aria-hidden="true"><path d={stage.path}/></svg></span>
          <strong>{stage.label}</strong><small>{stageState(stage.id)}</small>
        </button>
      </li>)}
    </ol>
    <section className="focus-card" aria-label="현재 작업">
      <div className="focus-heading"><div><span className="eyebrow">{selected}</span><h3>{stages.find(stage => stage.id === selected)?.label}</h3></div><span className="draft-label">{stageState(selected)}</span></div>
      <div className="focus-outputs"><div><h4>반영된 결과</h4><p>{output}</p></div><div><h4>최근 공개 활동</h4><p>{latest ? `수신 기록: ${safeEvent(latest)}` : "수신된 활동 기록 없음 · 상태는 최신 snapshot 기준입니다."}</p></div></div>
      <div className="focus-footer"><span>{s ? `${s.iteration}회차 · 근거 ${s.evidence.length}건` : "실행 대기"} · {complete ? "실행 종료" : disconnected ? "연결 복구 중" : pinned ? "선택한 단계" : "현재 단계 자동 따라가기"}</span>{pinned && <button type="button" onClick={() => setPinned(null)}>현재 단계로</button>}</div>
    </section>
  </>;
}
