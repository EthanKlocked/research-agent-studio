import { describe, it, expect } from "vitest";
import { acceptSnapshot, safeUrl, isTerminal } from "./state";
import { snapshot } from "./test/fixtures";
describe("authoritative state", () => {
  it("rejects stale and duplicate snapshots", () => {
    const current = snapshot({ last_seq: 4 });
    expect(acceptSnapshot(current, snapshot({ last_seq: 3 }))).toBe(current);
    expect(acceptSnapshot(current, snapshot({ last_seq: 4 }))).toBe(current);
  });
  it("rejects cross-run events", () => {
    const current = snapshot();
    expect(
      acceptSnapshot(current, snapshot({ run_id: "other", last_seq: 8 })),
    ).toBe(current);
  });
  it("accepts new real stage and terminal state", () => {
    expect(
      acceptSnapshot(snapshot(), snapshot({ last_seq: 2, stage: "Planner" }))
        ?.stage,
    ).toBe("Planner");
    expect(isTerminal("limit_reached")).toBe(true);
    expect(isTerminal("running")).toBe(false);
  });
  it("allows only http source links", () => {
    expect(safeUrl("javascript:alert(1)")).toBeNull();
    expect(safeUrl("file:///etc/passwd")).toBeNull();
    expect(safeUrl("https://example.org/source")).toBe(
      "https://example.org/source",
    );
  });
});
