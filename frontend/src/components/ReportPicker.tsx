import { relTime } from "../format";
import type { Report } from "../types";

export function ReportPicker<R extends Report>({
  reports,
  activeId,
  onPick,
  onDelete,
  label,
}: {
  reports: R[];
  activeId: string | null;
  onPick: (id: string) => void;
  onDelete: (id: string) => void;
  label: (r: R) => string;
}) {
  if (reports.length === 0) return null;
  return (
    <div className="row">
      <select className="input" style={{ width: "auto", maxWidth: 360 }} value={activeId ?? ""} onChange={(e) => onPick(e.target.value)} aria-label="Saved reports">
        {reports.map((r) => (
          <option key={r.id} value={r.id}>
            {relTime(r.created_at)} · {label(r)}
          </option>
        ))}
      </select>
      {activeId && (
        <button
          className="btn ghost sm danger"
          onClick={() => {
            if (confirm("Delete this saved report?")) onDelete(activeId);
          }}
        >
          Delete
        </button>
      )}
    </div>
  );
}

export function UsageNote({ report }: { report: Report }) {
  const u = report.quant?.usage;
  return (
    <div className="tiny muted">
      {report.model}
      {u ? ` · ${u.input_tokens + u.cache_read_input_tokens + u.cache_creation_input_tokens} in / ${u.output_tokens} out tokens` : ""} ·{" "}
      {new Date(report.created_at).toLocaleString()}
    </div>
  );
}
