import { useEffect, useState } from "react";
import { sim } from "../api";
import { ErrorNotice, Modal, Working } from "../components/ui";
import { levelLabel } from "./nav";
import type { Agent } from "./types";

const EXPERTS: [string, string][] = [
  ["psychologist", "Psychologist"],
  ["behavioral_economist", "Behavioral economist"],
  ["political_scientist", "Political scientist"],
  ["demographer", "Demographer"],
];

export function describeAgent(a: Pick<Agent, "demographics" | "first_name">): string {
  const d = a.demographics;
  return [d.age ?? d.age_band, d.gender, d.race, d.education && levelLabel(d.education, { hs_or_less: "HS or less", some_college: "some college", bachelors: "bachelor's", postgrad: "postgrad" }), d.party, d.state]
    .filter(Boolean)
    .join(" · ");
}

export function AgentModal({ agentId, onClose }: { agentId: string; onClose: () => void }) {
  const [agent, setAgent] = useState<Agent | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<"profile" | "record" | "experts" | "answers">("profile");
  useEffect(() => {
    sim.agent(agentId).then(setAgent).catch((e) => setError((e as Error).message));
  }, [agentId]);

  const d = agent?.demographics;
  const t = agent?.traits;
  return (
    <Modal title={agent ? `${agent.first_name} · simulated ${agent.source === "synthetic" ? "person" : "respondent"}` : "Agent"} onClose={onClose} width={760}>
      <ErrorNotice error={error} />
      {!agent && !error && <Working label="Loading…" />}
      {agent && d && t && (
        <div className="stack">
          <nav className="tabs" style={{ marginBottom: 0 }}>
            {(
              [
                ["profile", "Profile"],
                ["record", agent.transcript ? "Interview" : "Survey answers"],
                ["experts", "Expert notes"],
                ["answers", `Answers (${agent.responses?.length ?? 0})`],
              ] as const
            ).map(([id, label]) => (
              <button key={id} className="tab" aria-selected={tab === id} onClick={() => setTab(id)}>
                {label}
              </button>
            ))}
          </nav>
          {tab === "profile" && (
            <div className="stack-sm">
              {agent.identity && <div className="quote">{agent.identity}</div>}
              <dl className="kv">
                <dt>Demographics</dt>
                <dd>{describeAgent(agent)}</dd>
                <dt>Ideology</dt>
                <dd>{[d.ideology, d.lean && d.lean !== "none" ? `leans ${d.lean}` : null].filter(Boolean).join(", ") || "—"}</dd>
                <dt>2024 vote</dt>
                <dd>{d.vote_2024 ?? "—"}</dd>
                <dt>Income · community</dt>
                <dd>{[d.income, d.urbanicity, d.region].filter(Boolean).join(" · ") || "—"}</dd>
                <dt>Work · household</dt>
                <dd>
                  {t.occupation} · {t.household}
                </dd>
                <dt>Religion</dt>
                <dd>{t.religion}</dd>
                <dt>News</dt>
                <dd>{t.news_diet.join(", ")}</dd>
                <dt>On their mind</dt>
                <dd>{t.salient_issues.join(", ")}</dd>
                <dt>Personality</dt>
                <dd>{Object.entries(t.big5).map(([k, v]) => `${k} ${v.toFixed(2)}`).join(" · ")}</dd>
                <dt>Social media</dt>
                <dd>
                  {t.social_media_use} · type: {levelLabel(t.psych_type)}
                </dd>
                <dt>Survey weight</dt>
                <dd>
                  {agent.weight.toFixed(2)}
                  {agent.weight_cal != null && ` · calibrated ${agent.weight_cal.toFixed(2)}`}
                </dd>
              </dl>
              {agent.persona_status === "failed" && <div className="notice error small">Persona generation failed: {agent.persona_error}</div>}
            </div>
          )}
          {tab === "record" &&
            (agent.transcript ? (
              <div className="transcript">{agent.transcript}</div>
            ) : agent.raw && Object.keys(agent.raw).length ? (
              <div className="table-wrap">
                <table className="data">
                  <tbody>
                    {Object.entries(agent.raw).map(([q, a]) => (
                      <tr key={q}>
                        <td className="secondary" style={{ width: "45%" }}>
                          {q}
                        </td>
                        <td>{a}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="muted small">This agent has only a demographic card{agent.persona_status === "pending" ? " (its interview hasn't been generated yet)" : ""}.</p>
            ))}
          {tab === "experts" &&
            (agent.reflections ? (
              <div className="grid cols-2-even">
                {EXPERTS.map(([k, label]) => (
                  <div key={k} className="stack-sm">
                    <strong className="small">{label}</strong>
                    <ul className="bullets small">
                      {(agent.reflections?.[k as keyof typeof agent.reflections] ?? []).map((n, i) => (
                        <li key={i}>{n}</li>
                      ))}
                    </ul>
                  </div>
                ))}
              </div>
            ) : (
              <p className="muted small">No expert reflections for this agent.</p>
            ))}
          {tab === "answers" && (
            <div className="stack-sm">
              {!agent.responses?.length && <p className="muted small">This agent hasn't been in a simulation yet.</p>}
              {agent.responses?.map((r) => (
                <div key={r.id} className="quote-card">
                  <div className="who">
                    {r.run_title} · arm {r.arm_id}
                    {r.status === "error" && " · failed"}
                  </div>
                  {r.reasoning && <div>{r.reasoning}</div>}
                  <div className="tiny secondary">
                    {Object.entries(r.answers)
                      .map(([k, v]) => `${k}: ${v}`)
                      .join(" · ")}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </Modal>
  );
}
