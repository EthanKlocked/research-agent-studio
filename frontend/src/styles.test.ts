import { readFileSync } from "node:fs";
import { expect, it } from "vitest";

const css = readFileSync("src/styles.css", "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
const rules = [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map(([, selectors, body]) => ({
  selectors: selectors.trim().split(",").map(s => s.trim()), body,
}));
const bodies = (selector: string) => rules.filter(r => r.selectors.includes(selector)).map(r => r.body).join("\n");

it("keeps the question surface unchanged for mouse and keyboard focus", () => {
  expect(bodies(".query-row textarea")).toMatch(/outline:\s*none/);
  expect(bodies(".query-row textarea")).toMatch(/box-shadow:\s*none/);
  expect(rules.filter(r => r.selectors.some(s => /(?:^|\s)textarea[^\s]*:focus[^\s]*$/.test(s)))).toEqual([]);
  expect(rules.filter(r => r.selectors.some(s => /query-panel:focus-within/.test(s)))).toEqual([]);
});

it("locates question keyboard focus on its label, not an input ring", () => {
  expect(bodies('.query-panel:has(textarea:focus-visible) .query-label label')).toMatch(/text-decoration:\s*underline/);
});

it("keeps keyboard control outlines inside their boxes", () => {
  for (const selector of ["button:focus-visible", "a:focus-visible", "select:focus-visible", "summary:focus-visible", "[tabindex]:focus-visible"]) {
    expect(bodies(selector)).toMatch(/outline:\s*2px solid #526174/);
    expect(bodies(selector)).toMatch(/outline-offset:\s*-3px/);
  }
});

it("keeps stage selection and tab indicators inside their boxes without hover rings", () => {
  expect(bodies('.stages button[aria-pressed="true"] .stage-icon')).not.toMatch(/outline:/);
  expect(bodies('.stages button[aria-pressed="true"] .stage-icon')).toMatch(/box-shadow:\s*inset /);
  expect(bodies('.view-tabs button[aria-pressed="true"]')).toMatch(/box-shadow:\s*inset /);
  for (const rule of rules.filter(r => r.selectors.some(s => s.includes(":hover")))) {
    expect(rule.body).not.toMatch(/outline:|box-shadow:|transform:/);
  }
});

it("aligns header and content gutters on desktop and mobile", () => {
  expect(bodies(".topbar")).toContain("padding: 0 max(30px, calc((100vw - 1180px) / 2))");
  const mobile = css.slice(css.lastIndexOf("@media (max-width: 700px)"));
  expect(mobile).toMatch(/main\s*\{[^}]*padding: 24px 14px 0/);
  expect(mobile).toMatch(/\.topbar\s*\{[^}]*padding: 0 14px/);
});

it("disables anchoring during async updates", () => {
  expect(bodies("html")).toMatch(/overflow-anchor:\s*none/);
});
it("animates activity and stage content and pauses dashboard motion", () => {
  expect(bodies(".status-dot.active")).toMatch(/animation:.*activity-pulse/);
  expect(bodies(".focus-content")).toMatch(/animation:.*stage-enter/);
  expect(bodies('.dashboard[data-motion="paused"] *')).toMatch(/animation-play-state:\s*paused/);
  expect(css).toContain("@keyframes activity-pulse");
  expect(css.match(/@keyframes stage-enter/g)).toHaveLength(1);
});
it("fits the five-stage rail without a side menu", () => {
  expect(css).toContain(".focus-outputs");
  expect(css).not.toContain("minmax(118px,1fr)");
  expect(css).not.toContain(".workspace-sidebar");
});
