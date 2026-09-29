import type { Snapshot, Status } from "./types";
export function acceptSnapshot(
  current: Snapshot | null,
  next: Snapshot,
): Snapshot | null {
  if (
    current &&
    (current.run_id !== next.run_id || current.last_seq >= next.last_seq)
  )
    return current;
  return next;
}
export const isTerminal = (status: Status) =>
  !["queued", "running"].includes(status);
// Evaluator status can be final before the run has emitted its last events.
export const isComplete = (snapshot: Snapshot) => snapshot.finished_at != null;
export function safeUrl(value: string): string | null {
  try {
    const url = new URL(value);
    return ["https:", "http:"].includes(url.protocol) &&
      !url.username &&
      !url.password
      ? url.href
      : null;
  } catch {
    return null;
  }
}
