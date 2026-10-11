import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, sim } from "../api";
import type { SimRun } from "./types";

const ACTIVE = new Set(["pending", "running", "finalizing"]);
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export function isActive(run: SimRun<unknown> | null | undefined): boolean {
  return !!run && ACTIVE.has(run.status);
}

/**
 * Drives a simulation run from the browser: calls /step in a loop until the run stops.
 * If another tab holds the step lease, this tab just watches (polls) until it can help.
 */
export function useRunDriver<R = Record<string, unknown>>(
  runId: string | null,
  opts: { auto?: boolean; onDone?: (run: SimRun<R>) => void; setTitle?: boolean } = {},
) {
  const { auto = true, setTitle = true } = opts;
  const [run, setRun] = useState<SimRun<R> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [driving, setDriving] = useState(false);
  const [watching, setWatching] = useState(false);
  const alive = useRef(true);
  const loopId = useRef(0);
  const onDone = useRef(opts.onDone);
  onDone.current = opts.onDone;

  const refresh = useCallback(async () => {
    if (!runId) return null;
    try {
      const r = await sim.run<R>(runId);
      if (alive.current) setRun(r);
      return r;
    } catch (e) {
      if (alive.current) setError((e as Error).message);
      return null;
    }
  }, [runId]);

  const drive = useCallback(async () => {
    if (!runId) return;
    const me = ++loopId.current;
    setDriving(true);
    setError(null);
    let failures = 0;
    try {
      while (alive.current && me === loopId.current) {
        let current: SimRun<R>;
        try {
          current = await sim.step<R>(runId);
          failures = 0;
          setWatching(false);
        } catch (e) {
          if (e instanceof ApiError && e.status === 409) {
            const r = await refresh();
            if (!r || !isActive(r)) break;
            setWatching(true); // another tab is stepping it; watch until the lease frees up
            await sleep(3000);
            continue;
          }
          if (e instanceof ApiError && e.status < 500 && e.status !== 429) {
            setError(e.message);
            break;
          }
          failures += 1;
          if (failures > 3) {
            setError(`${(e as Error).message}. Stopped after repeated errors; press Resume to try again.`);
            break;
          }
          await sleep([2000, 5000, 10000][failures - 1]);
          continue;
        }
        if (!alive.current || me !== loopId.current) break;
        setRun(current);
        if (!isActive(current)) {
          if (current.status === "done") onDone.current?.(current);
          break;
        }
      }
    } finally {
      if (me === loopId.current) {
        setDriving(false);
        setWatching(false);
      }
    }
  }, [runId, refresh]);

  useEffect(() => {
    alive.current = true;
    setRun(null);
    setError(null);
    if (!runId) return;
    refresh().then((r) => {
      if (auto && r && isActive(r)) drive();
    });
    return () => {
      alive.current = false;
      loopId.current += 1;
    };
  }, [runId, auto, refresh, drive]);

  // warn before leaving while this tab is the one doing the work
  useEffect(() => {
    if (!driving) return;
    const warn = (e: BeforeUnloadEvent) => {
      e.preventDefault();
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [driving]);

  useEffect(() => {
    if (!driving || !run || !setTitle) return;
    const old = document.title;
    const pct = run.total ? Math.round((100 * run.cursor) / run.total) : 0;
    document.title = `${pct}% · ${run.title}`;
    return () => {
      document.title = old;
    };
  }, [driving, run, setTitle]);

  const act = useCallback(
    async (action: "pause" | "resume" | "cancel" | "retry-failed" | "summarize" | "recompute" | "apply-calibration") => {
      if (!runId) return;
      setError(null);
      try {
        if (action === "pause" || action === "cancel") loopId.current += 1;
        const r = await sim.control<R>(runId, action);
        setRun(r);
        if ((action === "resume" || action === "retry-failed") && isActive(r)) drive();
        return r;
      } catch (e) {
        setError((e as Error).message);
      }
    },
    [runId, drive],
  );

  return { run, setRun, error, driving, watching, drive, refresh, act };
}
