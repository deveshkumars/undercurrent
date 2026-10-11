import type { Margins, SimMeta } from "./types";
import { levelLabel } from "./nav";

/** Edit population margins in percent. Only variables the user touches are sent as targets. */
export function TargetsEditor({ meta, preset, targets, onChange, vars }: {
  meta: SimMeta;
  preset: string;
  targets: Margins;
  onChange: (t: Margins) => void;
  vars?: string[];
}) {
  const base = meta.presets[preset]?.margins ?? {};
  const shown = vars ?? ["party", "age_band", "gender", "race", "education", "region", "ideology", "vote_2024"];
  return (
    <div className="target-grid">
      {shown.map((v) => {
        const levels = meta.levels[v] ?? [];
        const current = targets[v] ?? base[v];
        const sum = levels.reduce((acc, l) => acc + (current?.[l] ?? 0), 0);
        const edited = !!targets[v];
        return (
          <div key={v} className="stack-sm" style={{ gap: 4 }}>
            <div className="row" style={{ justifyContent: "space-between" }}>
              <strong className="small">{meta.labels[v] ?? v}</strong>
              {edited ? (
                <button
                  type="button"
                  className="btn ghost sm"
                  onClick={() => {
                    const next = { ...targets };
                    delete next[v];
                    onChange(next);
                  }}
                >
                  Reset
                </button>
              ) : (
                <span className="tiny muted">{current ? "preset" : "not set"}</span>
              )}
            </div>
            {levels.map((l) => (
              <label key={l} className="level">
                <span className="secondary">{levelLabel(l, meta.level_labels)}</span>
                <input
                  className="input"
                  type="number"
                  min={0}
                  max={100}
                  step={1}
                  value={current?.[l] != null ? Math.round((current[l] / (sum || 1)) * 1000) / 10 : ""}
                  onChange={(e) => {
                    const val = Math.max(0, Number(e.target.value) || 0) / 100;
                    const start = { ...(current ?? {}) };
                    // normalize the untouched levels so the margin keeps summing to 100%
                    const others = levels.filter((x) => x !== l);
                    const otherSum = others.reduce((acc, x) => acc + (start[x] ?? 0), 0);
                    const remaining = Math.max(0, 1 - val);
                    const next: Record<string, number> = { [l]: val };
                    for (const x of others) next[x] = otherSum > 0 ? ((start[x] ?? 0) / otherSum) * remaining : remaining / others.length;
                    onChange({ ...targets, [v]: next });
                  }}
                />
              </label>
            ))}
          </div>
        );
      })}
    </div>
  );
}
