import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { Report } from "../types";

/** Saved AI reports of one kind for a candidate, newest first, plus which one is on screen. */
export function useReports<R extends Report>(cid: string, kind: R["kind"]) {
  const [reports, setReports] = useState<R[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);

  const reload = useCallback(async () => {
    const list = await api.reports<R>(cid, kind);
    setReports(list);
    setActiveId((cur) => (cur && list.some((r) => r.id === cur) ? cur : (list[0]?.id ?? null)));
  }, [cid, kind]);

  useEffect(() => {
    setReports([]);
    setActiveId(null);
    reload().catch(() => {});
  }, [reload]);

  const add = (r: R) => {
    setReports((prev) => [r, ...prev]);
    setActiveId(r.id);
  };

  const remove = async (id: string) => {
    await api.deleteReport(cid, id);
    await reload();
  };

  const active = reports.find((r) => r.id === activeId) ?? null;
  return { reports, active, setActiveId, add, remove };
}
