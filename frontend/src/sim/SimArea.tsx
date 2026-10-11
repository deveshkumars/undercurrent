import { useEffect, useState } from "react";
import { sim } from "../api";
import { ErrorNotice, Working } from "../components/ui";
import type { Candidate } from "../types";
import type { SimRoute } from "./nav";
import { PanelBuilder } from "./PanelBuilder";
import { PopulationImport } from "./PopulationImport";
import { PopulationNew } from "./PopulationNew";
import { PopulationView } from "./PopulationView";
import { RunView } from "./RunView";
import { SimHome } from "./SimHome";
import { SocialBuilder } from "./SocialBuilder";
import type { SimMeta } from "./types";

export function SimArea({ route, candidates }: { route: SimRoute; candidates: Candidate[] }) {
  const [meta, setMeta] = useState<SimMeta | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    sim.meta().then(setMeta).catch((e) => setError((e as Error).message));
  }, []);
  if (error) return <ErrorNotice error={error} />;
  if (!meta) return <Working label="Loading…" />;
  const [a, b] = route.parts;
  const cand = route.query.get("cand");
  const key = `${route.parts.join("/")}?${route.query.toString()}`;
  return (
    <div key={key}>
      {!meta.llm_ready && (
        <div className="notice warn" style={{ marginBottom: 16 }}>
          No model is configured, so agents can't be generated or asked anything yet. Card-only populations still work.
        </div>
      )}
      {!a && <SimHome />}
      {a === "pop" && b === "new" && <PopulationNew meta={meta} candidates={candidates} candidateId={cand} />}
      {a === "pop" && b === "import" && <PopulationImport meta={meta} candidates={candidates} candidateId={cand} />}
      {a === "pop" && b && b !== "new" && b !== "import" && <PopulationView meta={meta} pid={b} candidates={candidates} />}
      {a === "panel" && <PanelBuilder meta={meta} candidates={candidates} query={route.query} />}
      {a === "social" && <SocialBuilder meta={meta} candidates={candidates} query={route.query} />}
      {a === "run" && b && <RunView meta={meta} rid={b} candidates={candidates} />}
    </div>
  );
}
