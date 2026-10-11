import { useEffect, useRef, type ReactNode } from "react";
import { deltaClass, fmtPts, SIGNAL_TEXT } from "../format";
import type { Signal } from "../types";

export function Spinner() {
  return <span className="spinner" aria-hidden="true" />;
}

export function Delta({ value, digits = 1, unit = true, threshold }: { value: number | null | undefined; digits?: number; unit?: boolean; threshold?: number }) {
  const cls = deltaClass(value, threshold);
  const icon = cls === "up" ? "▲" : cls === "down" ? "▼" : "";
  return (
    <span className={`delta ${cls}`}>
      {icon && (
        <span aria-hidden="true" style={{ fontSize: "0.7em" }}>
          {icon}
        </span>
      )}
      {fmtPts(value, digits, unit)}
    </span>
  );
}

/** Measured event impact: a direction icon + label so color is never the only cue. */
export function ImpactBadge({ delta, signal }: { delta: number | null; signal: Signal }) {
  if (delta == null || signal === "insufficient") return <span className="chip">not enough polls</span>;
  const strong = signal === "strong" || signal === "clear";
  const cls = !strong ? "" : delta > 0 ? "good" : "bad";
  return (
    <span className={`chip ${cls}`} title={SIGNAL_TEXT[signal]}>
      {strong ? (delta > 0 ? "▲" : "▼") : "●"} {fmtPts(delta)}
    </span>
  );
}

export function Card({ title, sub, actions, children, className = "" }: { title?: ReactNode; sub?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`card ${className}`}>
      {(title || actions) && (
        <div className="card-head">
          <div>
            {title && <h2>{title}</h2>}
            {sub && <div className="card-sub">{sub}</div>}
          </div>
          {actions && <div className="row">{actions}</div>}
        </div>
      )}
      {children}
    </section>
  );
}

export function Modal({ title, onClose, children, width }: { title: string; onClose: () => void; children: ReactNode; width?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    ref.current?.querySelector<HTMLElement>("input, textarea, select")?.focus();
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-modal="true" aria-label={title} ref={ref} style={width ? { width: `min(${width}px, 100%)` } : undefined}>
        <h2>{title}</h2>
        {children}
      </div>
    </div>
  );
}

export function ErrorNotice({ error }: { error: string | null }) {
  if (!error) return null;
  return (
    <div className="notice error" role="alert">
      {error}
    </div>
  );
}

export function Working({ label }: { label: string }) {
  return (
    <div className="working" role="status">
      <Spinner />
      <span>{label}</span>
    </div>
  );
}

export function Field({ label, hint, children, full }: { label: string; hint?: string; children: ReactNode; full?: boolean }) {
  return (
    <label className={`field ${full ? "full" : ""}`}>
      <span>
        {label} {hint && <span className="hint">· {hint}</span>}
      </span>
      {children}
    </label>
  );
}

export function Paragraphs({ text }: { text: string }) {
  return (
    <div className="prose">
      {text
        .split(/\n{2,}/)
        .filter(Boolean)
        .map((p, i) => (
          <p key={i}>{p}</p>
        ))}
    </div>
  );
}
