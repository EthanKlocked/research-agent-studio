import type { RunEvent, Snapshot, Status } from "./types";
// Stable server sequence IDs, not model-call IDs (start/complete are distinct).
// History is bounded and never used to recompute the authoritative cost summary.
export function mergeEvents(old: RunEvent[], incoming: RunEvent[], snapshot: Snapshot): RunEvent[] {
  const bySeq = new Map<number, RunEvent>();
  for (const e of [...old, ...incoming]) {
    if (e.run_id === snapshot.run_id && Number.isSafeInteger(e.seq) && e.seq > 0 &&
        e.seq <= snapshot.last_seq && e.data?.snapshot?.run_id === snapshot.run_id &&
        e.data.snapshot.last_seq === e.seq && !bySeq.has(e.seq)) bySeq.set(e.seq, e);
  }
  return [...bySeq.values()].sort((a,b)=>a.seq-b.seq).slice(-150);
}
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
