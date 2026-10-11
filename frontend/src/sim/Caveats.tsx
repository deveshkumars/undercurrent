import type { Population } from "./types";

export function ProvenanceBadge({ population }: { population: Pick<Population, "source" | "persona_mode"> }) {
  if (population.source === "csv") return <span className="badge-prov" title="Agents built from real respondents' answers or interviews">◆ Real respondents (CSV)</span>;
  if (population.persona_mode === "demographic")
    return (
      <span className="badge-prov" title="Agents know only a demographic card: Park et al.'s weakest baseline">
        ○ Card only
      </span>
    );
  return (
    <span className="badge-prov" title="LLM-written life-history interviews conditioned on demographics. Fluent, but no more information than the card.">
      ◇ Synthetic interviews
    </span>
  );
}

const COMMON = [
  "These are simulated people. Use the results to compare messages and spot risks, not as a poll.",
  "Intervals reflect simulation noise only (which agents, which model draw), not whether the agents resemble real voters.",
];

const BY_KIND: Record<string, string[]> = {
  panel: [
    "LLM agents tend to read every word and agree too readily, so raw effects run much larger than real poll movement. Compare arms with each other; use a backtest to scale effects to real-world size.",
    "Agents can exaggerate differences between groups and flatten disagreement within them. Small segments (grayed) and cells without the FDR mark are hints, not findings.",
  ],
  calibration: [
    "Calibration matches the levels in the polls; it doesn't make agents respond to messages more realistically. Heavy reweighting (high design effect) means the population was a poor fit to begin with.",
  ],
  backtest: [
    "Agents may already know about real, well-known events from their training data, which can flatter a backtest. Fictional or obscure races avoid this.",
    "Measured event effects are correlational and noisy; the slope is only as good as the polling around each event.",
  ],
  social: [
    "Social scenarios are for exploring dynamics (what spreads, which interventions calm or inflame), not predicting volumes. POSIM's parameters were calibrated on Weibo with a much larger population.",
    "Always compare a branch against its no-change control from the same checkpoint; single runs vary.",
  ],
};

export function Caveats({ kind, population }: { kind: string; population?: Pick<Population, "source" | "persona_mode"> | null }) {
  const extra =
    population && population.source !== "csv"
      ? [
          population.persona_mode === "demographic"
            ? "Card-only agents correspond to the weakest setup in Park et al. (2024): about 74% of human test-retest accuracy on the GSS, versus 85% for agents built from real interviews."
            : "Synthetic interviews are written by the model from a demographic card, so they add detail but not real information. Park et al.'s accuracy gains came from real people's interviews; import real survey or interview data for higher fidelity.",
        ]
      : [];
  return (
    <details className="caveats">
      <summary style={{ cursor: "pointer", fontWeight: 600 }}>How far to trust this</summary>
      <ul>
        {[...COMMON, ...(BY_KIND[kind] ?? []), ...extra].map((c) => (
          <li key={c}>{c}</li>
        ))}
      </ul>
    </details>
  );
}
