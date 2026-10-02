import { useCallback, useEffect, useRef, useState } from "react";
import { request } from "./api";
import { acceptSnapshot, isComplete, mergeEvents } from "./state";
import type { RunEvent, Snapshot } from "./types";
const storageKey = "research-studio.run-id";
function remembered() {
  try {
    return sessionStorage.getItem(storageKey);
  } catch {
    return null;
  }
}
function remember(id: string | null) {
  try {
    if (id) sessionStorage.setItem(storageKey, id);
    else sessionStorage.removeItem(storageKey);
  } catch {
    /* storage is optional */
  }
}
export function useRun() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null),
    [events, setEvents] = useState<RunEvent[]>([]),
    [disconnected, setDisconnected] = useState(false),
    [pending, setPending] = useState(false),
    [error, setError] = useState("");
  const current = useRef<Snapshot | null>(null),
    stream = useRef<EventSource | null>(null),
    retry = useRef<ReturnType<typeof setTimeout> | null>(null),
    generation = useRef(0);
  const stop = useCallback(() => {
    stream.current?.close();
    stream.current = null;
    if (retry.current) clearTimeout(retry.current);
    retry.current = null;
  }, []);
  const apply = useCallback(
    (next: Snapshot) => {
      const accepted = acceptSnapshot(current.current, next);
      current.current = accepted;
      setSnapshot(accepted);
      if (accepted && next.run_id === accepted.run_id && next.retained_events) {
        setEvents(old => mergeEvents(old, next.retained_events ?? [], accepted));
      }
      if (accepted && isComplete(accepted)) {
        stop();
        setDisconnected(false);
      }
    },
    [stop],
  );
  const connect = useCallback(
    function subscribe(id: string, token: number) {
      if (
        token !== generation.current ||
        !current.current ||
        isComplete(current.current)
      )
        return;
      const es = new EventSource(
        `/api/runs/${encodeURIComponent(id)}/events?after=${current.current.last_seq}`,
      );
      stream.current = es;
      const recover = () => {
        if (token !== generation.current || stream.current !== es ||
            (current.current && isComplete(current.current))) return;
        es.close();
        setDisconnected(true);
        retry.current = setTimeout(async () => {
          try {
            const fresh = await request<Snapshot>(
              `/api/runs/${encodeURIComponent(id)}?include_events=true`,
            );
            if (token !== generation.current) return;
            apply(fresh);
            subscribe(id, token);
          } catch (failure) {
            if (token !== generation.current) return;
            if (
              failure instanceof Error &&
              failure.message.startsWith("실행 기록")
            ) {
              stop();
              generation.current++;
              setError(failure.message);
              setDisconnected(false);
              current.current = null;
              setSnapshot(null);
              remember(null);
              return;
            }
            recover();
          }
        }, 1000);
      };
      es.onopen = () => {
        if (token === generation.current) setDisconnected(false);
      };
      es.onmessage = (message) => {
        if (token !== generation.current) return;
        try {
          const event = JSON.parse(message.data) as RunEvent;
          if (
            event.run_id !== id ||
            event.seq <= (current.current?.last_seq ?? 0) ||
            event.data?.snapshot?.run_id !== id ||
            event.data.snapshot.last_seq !== event.seq
          )
            return;
          setEvents((old) => mergeEvents(old, [event], event.data.snapshot));
          // Explicit terminal events also finalize older payloads without finished_at.
          apply(event.type === "terminal"
            ? { ...event.data.snapshot, finished_at: event.data.snapshot.finished_at ?? event.timestamp }
            : event.data.snapshot);
          setDisconnected(false);
        } catch {
          recover();
        }
      };
      es.onerror = recover;
    },
    [apply, stop],
  );
  useEffect(() => {
    const id = remembered();
    const token = ++generation.current;
    if (id) {
      setPending(true);
      request<Snapshot>(`/api/runs/${encodeURIComponent(id)}?include_events=true`)
        .then((s) => {
          if (token !== generation.current) return;
          current.current = null;
          apply(s);
          connect(id, token);
        })
        .catch((e) => {
          if (token === generation.current) {
            setError(e.message);
            remember(null);
          }
        })
        .finally(() => {
          if (token === generation.current) setPending(false);
        });
    }
    return () => {
      generation.current++;
      stop();
    };
  }, [apply, connect, stop]);
  async function start(
    question: string,
    mode: "test" | "live",
    scenario: string,
  ) {
    stop();
    const token = ++generation.current;
    setPending(true);
    setError("");
    setEvents([]);
    setDisconnected(false);
    try {
      const next = await request<Snapshot>("/api/runs", {
        method: "POST",
        body: JSON.stringify({ question, mode, scenario: mode === "live" ? "pass" : scenario }),
      });
      if (token !== generation.current) return;
      current.current = null;
      apply(next);
      remember(next.run_id);
      connect(next.run_id, token);
    } catch (e) {
      if (token === generation.current) setError((e as Error).message);
    } finally {
      if (token === generation.current) setPending(false);
    }
  }
  async function cancel() {
    if (!current.current) return;
    const token = generation.current;
    setPending(true);
    setError("");
    try {
      const next = await request<Snapshot>(
        `/api/runs/${encodeURIComponent(current.current.run_id)}/cancel`,
        { method: "POST" },
      );
      if (token === generation.current) apply(next);
    } catch (e) {
      if (token === generation.current) setError((e as Error).message);
    } finally {
      if (token === generation.current) setPending(false);
    }
  }
  return { snapshot, events, disconnected, pending, error, start, cancel };
}
