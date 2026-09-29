import { readFileSync } from "node:fs";
import { expect, it } from "vitest";
it("keeps a neutral visible keyboard focus and fits the five-stage rail without a side menu", () => {
  const css = readFileSync("src/styles.css", "utf8");
  expect(css).not.toContain("outline: 3px solid #7296f5");
  expect(css).toContain("outline: 2px solid #526174");
  expect(css).toContain(".focus-outputs");
  expect(css).not.toContain("minmax(118px,1fr)");
  expect(css).not.toContain(".workspace-sidebar");
});
