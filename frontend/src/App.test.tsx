import {
  render,
  screen,
  waitFor,
  fireEvent,
  act,
} from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import App from "./App";
import { config, snapshot } from "./test/fixtures";
class Stream {
  static instances: Stream[] = [];
  onmessage: ((event: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  onopen: (() => void) | null = null;
  close = vi.fn();
  url: string;
  constructor(url: string) {
    this.url = url;
    Stream.instances.push(this);
  }
  emit(s: ReturnType<typeof snapshot>, type = "node_complete") {
    this.onmessage?.({
      data: JSON.stringify({
        seq: s.last_seq,
        run_id: s.run_id,
        type,
        timestamp: new Date().toISOString(),
        data: { snapshot: s },
      }),
    });
  }
}
beforeEach(() => {
  Stream.instances = [];
  vi.stubGlobal("EventSource", Stream);
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => ({
      ok: true,
      json: async () => (url === "/api/config" ? config : snapshot()),
    })),
  );
});
async function start() {
  render(<App />);
  await screen.findByText("공개 기업 자료");
  fireEvent.change(screen.getByLabelText("리서치 질문"), {
    target: { value: "실적과 위험요인을 조사해 주세요." },
  });
  fireEvent.click(screen.getByRole("button", { name: "리서치 시작" }));
  await waitFor(() => expect(Stream.instances.length).toBe(1));
  return Stream.instances[0];
}
describe("workbench", () => {
  it.each(["stream", "restore"])("keeps a failed revision's retained report and error visible via %s", async (delivery) => {
    const report = { title: "보존된 보고서", summary: "이전 평가를 받은 요약",
      claims: [{ text: "보존된 주장", citation_ids: ["e1"] }], limitations: ["아직 자료가 부족합니다"] };
    const evaluation = { decision: "revise" as const, issues: ["위험 근거 부족"], follow_up: ["추가 조회 필요"] };
    const retained = snapshot({ status: "error", iteration: 2, last_seq: 9,
      finished_at: new Date().toISOString(), report, evaluation,
      partial_result: { iteration: 1, reason: "revision_failed" },
      errors: ["추가 조사 요청 시간이 초과되었습니다."],
      evidence: [{ id: "e1", document_id: "d1", section_id: "s1", title: "보존된 출처",
        url: "https://example.org/report", published_at: "2024-10-01", as_of: "2024-09-28", excerpt: "이전 근거 원문" }],
      revisions: [{ iteration: 1, report, evaluation, evidence_ids: ["e1"], added_evidence_ids: ["e1"] }],
    });
    if (delivery === "stream") {
      const stream = await start();
      act(() => stream.emit(retained, "terminal"));
      expect(stream.close).toHaveBeenCalled();
    } else {
      sessionStorage.setItem("research-studio.run-id", "run-1");
      vi.mocked(fetch).mockImplementation(async (url) => ({ ok: true,
        json: async () => url === "/api/config" ? config : retained,
      } as Response));
      render(<App />);
    }
    expect(await screen.findByText("이전 보고서 · 추가 조사 실패 · 평가 미통과")).toBeVisible();
    expect(screen.getByText("보존된 보고서: 1차 보고서")).toBeVisible();
    expect(screen.getByText("이전 평가를 받은 요약")).toBeVisible();
    expect(screen.getByText("보존된 주장")).toBeVisible();
    expect(screen.getByText("조사 중 오류가 발생했습니다")).toBeVisible();
    expect(screen.getByText("추가 조사 요청 시간이 초과되었습니다.")).toBeVisible();
    expect(screen.getByText("위험 근거 부족")).toBeVisible();
    expect(screen.queryByText("조사가 완료되었습니다")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "출처 e1 보기" }));
    expect(screen.getByText("이전 근거 원문")).toBeVisible();
  });
  it.each([null, undefined])("does not label an ordinary report as partial (%s)", async (partial_result) => {
    const stream = await start();
    act(() => stream.emit(snapshot({ status: "success", last_seq: 9, partial_result,
      report: { title: "정상 보고서", summary: "완료 요약", claims: [], limitations: [] } }), "terminal"));
    expect(screen.getByText("완료 요약")).toBeVisible();
    expect(screen.queryByText("이전 보고서 · 추가 조사 실패 · 평가 미통과")).not.toBeInTheDocument();
  });
  it("shows recoverable tool input errors without completing the lookup or run", async () => {
    const stream = await start();
    const reason = "도구 입력을 확인하고 다시 조회해 주세요.";
    const running = snapshot({ status: "running", stage: "Researcher", last_seq: 2 });
    act(() => stream.onmessage?.({ data: JSON.stringify({
      run_id: running.run_id, seq: 2, type: "tool_error", timestamp: new Date().toISOString(),
      data: { snapshot: running, tool: "get_document", reason,
        arguments: { document_id: "private invalid ID" }, error: "private traceback" },
    }) }));
    expect(screen.getByText("도구 입력 오류")).toBeVisible();
    expect(screen.getByText("⚠")).toBeVisible();
    expect(screen.getByText(reason)).toBeVisible();
    expect(screen.queryByText(/조회 완료|결과 0건/)).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByText("근거 수집 중")).toBeVisible();
    expect(screen.getByRole("button", { name: "실행 중단" })).toBeEnabled();
    expect(stream.close).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText("개발 상세"));
    expect(screen.getByText(`도구 입력 오류 · get_document · ${reason}`)).toBeVisible();
    expect(screen.queryByText(/private invalid ID|private traceback/)).not.toBeInTheDocument();

    // An actual successful empty lookup remains distinct from the input error.
    act(() => stream.onmessage?.({ data: JSON.stringify({
      run_id: running.run_id, seq: 3, type: "tool_complete", timestamp: new Date().toISOString(),
      data: { snapshot: { ...running, last_seq: 3 }, tool: "search", count: 0 },
    }) }));
    expect(screen.getByText("조회 완료 · 0건")).toBeVisible();
    expect(screen.getByText("도구 입력 오류")).toBeVisible();
    expect(stream.close).not.toHaveBeenCalled();
    act(() => stream.onmessage?.({ data: JSON.stringify({
      run_id: running.run_id, seq: 4, type: "tool_complete", timestamp: new Date().toISOString(),
      data: { snapshot: { ...running, last_seq: 4 }, tool: "get_document", count: 1 },
    }) }));
    expect(screen.getByText("조회 완료 · 1건")).toBeVisible();
    const report = { title: "재조회 후 보고서", summary: "수정된 결과", claims: [], limitations: [] };
    act(() => stream.emit(snapshot({ last_seq: 5, stage: "Reporter", report })));
    expect(screen.getByText("수정된 결과")).toBeVisible();
    expect(stream.close).not.toHaveBeenCalled();
    act(() => stream.emit(snapshot({ last_seq: 6, status: "success", report,
      finished_at: new Date().toISOString() }), "terminal"));
    expect(screen.getByText("조사가 완료되었습니다")).toBeVisible();
    expect(screen.getByText("도구 입력 오류")).toBeVisible();
    expect(stream.close).toHaveBeenCalled();
  });
  it("shows safe MCP input summaries in tool history and event details", async () => {
    const stream = await start();
    act(() => stream.onmessage?.({ data: JSON.stringify({
      run_id: "run-1", seq: 2, type: "tool_start", timestamp: new Date().toISOString(),
      data: { snapshot: snapshot({ last_seq: 2 }), tool_name: "search",
        input_summary: "검색어 12자 · limit 5", input: { query: "private raw query" } },
    }) }));
    expect(screen.getByText("검색어 12자 · limit 5")).toBeVisible();
    fireEvent.click(screen.getByText("개발 상세"));
    expect(screen.getByText("도구 호출 · search · 검색어 12자 · limit 5")).toBeVisible();
    expect(screen.queryByText(/private raw query/)).not.toBeInTheDocument();
  });
  it.each(["success", "limit_reached", "empty"] as const)(
    "keeps %s evaluator snapshots active until the terminal event",
    async (status) => {
      const stream = await start();
      const intermediate = snapshot({ status, stage: "Evaluator", last_seq: 2,
        started_at: "2026-01-01T00:00:00Z" });
      act(() => stream.emit(intermediate));
      expect(stream.close).not.toHaveBeenCalled();
      expect(screen.getByRole("button", { name: "실행 중단" })).toBeEnabled();
      expect(screen.getByLabelText("리서치 질문")).toBeDisabled();
      expect(screen.getByText("결과 평가 중")).toBeVisible();
      act(() => stream.emit({ ...intermediate, last_seq: 3 }, "branch"));
      act(() => stream.emit({ ...intermediate, last_seq: 4,
        finished_at: "2026-01-01T00:00:12Z" }, "terminal"));
      expect(stream.close).toHaveBeenCalled();
      expect(screen.getByRole("button", { name: "리서치 시작" })).toBeEnabled();
      expect(screen.getByText("0분 12초")).toBeVisible();
      fireEvent.click(screen.getByText("개발 상세"));
      expect(screen.getByText("분기 결정")).toBeVisible();
      expect(screen.getByText("실행 종료")).toBeVisible();
      vi.spyOn(Date, "now").mockReturnValue(Date.parse("2026-01-01T00:10:00Z"));
      fireEvent.change(screen.getByLabelText("리서치 질문"), { target: { value: "새 질문" } });
      expect(screen.getByText("0분 12초")).toBeVisible();
    },
  );
  it("reconnects after an unfinished success snapshot", async () => {
    const stream = await start();
    vi.mocked(fetch).mockResolvedValueOnce({ ok: true,
      json: async () => snapshot({ status: "success", last_seq: 7 }),
    } as Response);
    act(() => stream.onerror?.());
    await waitFor(() => expect(Stream.instances.length).toBe(2), { timeout: 3500 });
    expect(Stream.instances[1].url).toContain("after=7");
    expect(screen.getByRole("button", { name: "실행 중단" })).toBeEnabled();
  });
  it("restores an unfinished success run with an active stream", async () => {
    sessionStorage.setItem("research-studio.run-id", "run-1");
    vi.mocked(fetch).mockImplementation(async (url) => ({ ok: true,
      json: async () => url === "/api/config" ? config : snapshot({ status: "success", last_seq: 7 }),
    } as Response));
    render(<App />);
    await waitFor(() => expect(Stream.instances.length).toBe(1));
    expect(Stream.instances[0].url).toContain("after=7");
  });
  it("does not reconnect after an explicit terminal event without finished_at", async () => {
    const stream = await start();
    act(() => stream.emit(snapshot({ status: "success", last_seq: 8 }), "terminal"));
    act(() => stream.onerror?.());
    expect(screen.queryByText(/연결 복구 중/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "리서치 시작" })).toBeEnabled();
  });
  it.each([true, false])("sends scenario pass in live mode (test available: %s)", async (testAvailable) => {
    vi.mocked(fetch).mockImplementation(async (url) => ({ ok: true,
      json: async () => url === "/api/config"
        ? { ...config, configured: true, test_mode_available: testAvailable }
        : snapshot({ mode: "live" }),
    } as Response));
    render(<App />);
    await screen.findByText("공개 기업 자료");
    if (testAvailable) {
      expect(screen.getByLabelText("테스트 시나리오")).toHaveValue("revise");
      fireEvent.change(screen.getByLabelText("실행 모드"), { target: { value: "live" } });
    }
    expect(screen.queryByLabelText("테스트 시나리오")).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("리서치 질문"), { target: { value: "실제 조사" } });
    fireEvent.click(screen.getByRole("button", { name: "리서치 시작" }));
    await waitFor(() => expect(fetch).toHaveBeenCalledWith("/api/runs", expect.objectContaining({
      method: "POST", body: JSON.stringify({ question: "실제 조사", mode: "live", scenario: "pass" }),
    })));
  });
  it("releases missing runs after reconnect instead of retrying forever", async () => {
    const stream = await start();
    vi.mocked(fetch).mockResolvedValueOnce({
      ok: false,
      status: 404,
    } as Response);
    act(() => stream.onerror?.());
    expect(
      await screen.findByRole("alert", {}, { timeout: 3500 }),
    ).toHaveTextContent("실행 기록을 찾을 수 없습니다");
    expect(screen.getByRole("button", { name: "리서치 시작" })).toBeEnabled();
    expect(sessionStorage.getItem("research-studio.run-id")).toBeNull();
  });
  it("labels test mode and disables unconfigured live mode", async () => {
    render(<App />);
    await screen.findByText("공개 기업 자료");
    expect(
      screen.getByRole("option", { name: "실제 모델 · 연결 미설정" }),
    ).toBeDisabled();
    expect(screen.getByText("테스트 모드 / 실제 모델 호출 없음")).toBeVisible();
    expect(screen.getByText("2024-12-31")).toBeVisible();
  });
  it("sends explicit API controls and only updates stages from events", async () => {
    const stream = await start();
    expect(fetch).toHaveBeenCalledWith(
      "/api/runs",
      expect.objectContaining({
        body: JSON.stringify({
          question: "실적과 위험요인을 조사해 주세요.",
          mode: "test",
          scenario: "revise",
        }),
      }),
    );
    expect(screen.getByText("요청 해석 중")).toBeVisible();
    act(() => stream.emit(snapshot({ last_seq: 2, stage: "Planner" })));
    expect(screen.getByText("조사 계획 중")).toBeVisible();
    act(() => stream.emit(snapshot({ last_seq: 1, stage: "Evaluator" })));
    expect(screen.getByText("조사 계획 중")).toBeVisible();
  });
  it("renders citations, source excerpt and revision comparison from snapshot", async () => {
    const stream = await start();
    const report = {
      title: "근거 기반 분석",
      summary: "요약 결과",
      claims: [{ text: "공시된 실적입니다.", citation_ids: ["e1"] }],
      limitations: ["데이터 기준일 이후 변경 미반영"],
    };
    act(() =>
      stream.emit(
        snapshot({
          status: "success",
          stage: "Evaluator",
          last_seq: 9,
          report,
          evidence: [
            {
              id: "e1",
              document_id: "d1",
              section_id: "s1",
              title: "공개 보고서",
              url: "https://example.org/report",
              published_at: "2024-10-01",
              as_of: "2024-12-31",
              excerpt: "검증 가능한 인용 구간",
            },
          ],
          revisions: [
            {
              iteration: 1,
              report: { ...report, summary: "이전 요약" },
              evidence_ids: [],
              added_evidence_ids: [],
              evaluation: {
                decision: "revise",
                issues: ["자료 부족"],
                follow_up: ["추가 조회"],
              },
            },
            {
              iteration: 2,
              report,
              evidence_ids: ["e1"],
              added_evidence_ids: ["e1"],
              evaluation: { decision: "pass", issues: [], follow_up: [] },
            },
          ],
        }),
        "terminal",
      ),
    );
    expect(stream.close).toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "출처 e1 보기" }));
    expect(screen.getByText("검증 가능한 인용 구간")).toBeVisible();
    expect(screen.getByRole("link", { name: /원문 보기/ })).toHaveAttribute(
      "href",
      "https://example.org/report",
    );
    fireEvent.click(screen.getByText("이전 보고서와 비교"));
    expect(screen.getByText("이전 요약")).toBeVisible();
    expect(screen.getByText("추가 근거 1건")).toBeVisible();
    fireEvent.change(screen.getByLabelText("보고서 버전"), { target: { value: "1" } });
    await waitFor(() => expect(screen.getByText("이전 요약")).toBeVisible());
    expect(screen.getByText("1차 검토본")).toBeVisible();
    expect(screen.queryByText("요약 결과")).not.toBeInTheDocument();
  });
  it("reconnects via fresh snapshot before subscribing after last sequence", async () => {
    const stream = await start();
    vi.mocked(fetch).mockResolvedValueOnce({
      ok: true,
      json: async () => snapshot({ last_seq: 7, stage: "Researcher" }),
    } as Response);
    act(() => stream.onerror?.());
    expect(await screen.findByText(/연결 복구 중/)).toBeVisible();
    await waitFor(() => expect(Stream.instances.length).toBe(2), {
      timeout: 3500,
    });
    expect(Stream.instances[1].url).toContain("after=7");
    expect(stream.close).toHaveBeenCalled();
  });
  it("cancels through backend and closes stream on terminal snapshot", async () => {
    const stream = await start();
    vi.mocked(fetch).mockResolvedValueOnce({
      ok: true,
      json: async () => snapshot({ status: "cancelled", last_seq: 3, finished_at: new Date().toISOString() }),
    } as Response);
    fireEvent.click(screen.getByRole("button", { name: "실행 중단" }));
    await screen.findByText("실행이 중단되었습니다");
    expect(fetch).toHaveBeenCalledWith(
      "/api/runs/run-1/cancel",
      expect.objectContaining({ method: "POST" }),
    );
    expect(stream.close).toHaveBeenCalled();
  });
  it("shows fetch failure without fake report", async () => {
    vi.mocked(fetch).mockRejectedValue(new Error("private upstream detail"));
    render(<App />);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "서버에 연결할 수 없습니다",
    );
    expect(
      screen.queryByText("private upstream detail"),
    ).not.toBeInTheDocument();
  });
  it("closes event stream on unmount", async () => {
    sessionStorage.setItem("research-studio.run-id", "run-1");
    const view = render(<App />);
    await waitFor(() => expect(Stream.instances.length).toBe(1));
    view.unmount();
    expect(Stream.instances[0].close).toHaveBeenCalled();
  });
  it("restores only the saved run ID via a server snapshot", async () => {
    sessionStorage.setItem("research-studio.run-id", "run-1");
    render(<App />);
    await waitFor(() => expect(Stream.instances.length).toBe(1));
    expect(fetch).toHaveBeenCalledWith("/api/runs/run-1", expect.anything());
    expect(Stream.instances[0].url).toContain("after=1");
    expect(sessionStorage.length).toBe(1);
  });
  it.each([
    ["empty", "관련 근거를 찾지 못했습니다"],
    ["error", "조사 중 오류가 발생했습니다"],
    ["limit_reached", "반복 한도에 도달했습니다"],
  ] as const)("distinguishes %s state", async (status, label) => {
    const stream = await start();
    act(() => stream.emit(snapshot({ status, last_seq: 8 }), "terminal"));
    expect(await screen.findByText(label)).toBeVisible();
    expect(stream.close).toHaveBeenCalled();
  });
  it("ignores a different run event", async () => {
    const stream = await start();
    act(() =>
      stream.emit(
        snapshot({ run_id: "other-run", last_seq: 100, stage: "Evaluator" }),
      ),
    );
    expect(screen.getByText("요청 해석 중")).toBeVisible();
  });
  it("moves keyboard focus to selected source and rejects unsafe URLs", async () => {
    const stream = await start();
    const report = {
      title: "안전한 보고서",
      summary: "요약",
      claims: [{ text: "검증 주장", citation_ids: ["e1"] }],
      limitations: [],
    };
    act(() =>
      stream.emit(
        snapshot({
          status: "success",
          last_seq: 10,
          report,
          evidence: [
            {
              id: "e1",
              document_id: "d",
              section_id: "s",
              title: "출처",
              url: "javascript:alert(1)",
              published_at: "2024",
              as_of: "2024",
              excerpt: "자료 구간",
            },
          ],
        }),
        "terminal",
      ),
    );
    fireEvent.click(screen.getByRole("button", { name: "출처 e1 보기" }));
    expect(screen.getByRole("article", { name: "선택한 출처" })).toHaveFocus();
    expect(
      screen.queryByRole("link", { name: /원문 보기/ }),
    ).not.toBeInTheDocument();
  });
});
