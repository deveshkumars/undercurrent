import { Fragment, useState } from "react";
import { sim, type ImportChunkResult } from "../api";
import { Card, ErrorNotice, Field } from "../components/ui";
import type { Candidate } from "../types";
import { csvChunks } from "./csvChunks";
import { goSim, simHref } from "./nav";
import type { Population, SimMeta } from "./types";

const EXAMPLE = `respondent_id,age,gender,race,education,party_id,ideology,weight,most_important_issue,trust_in_government,describe_your_week
r001,34,Female,White,Bachelor's degree,Democrat,Liberal,1.1,Housing costs,Some of the time,"Worked doubles at the clinic, picked up my kid, too tired to cook"
r002,67,Male,Black,High school graduate,Democrat,Moderate,0.9,Social Security,Rarely,"Church on Sunday, fixed my neighbor's porch, watched the news"
r003,45,Male,White,Some college,Republican,Conservative,1.2,Inflation,Never,"Long haul to Ohio and back, gas killed me this week"`;

export function PopulationImport({ meta, candidates, candidateId }: { meta: SimMeta; candidates: Candidate[]; candidateId: string | null }) {
  const [name, setName] = useState("");
  const [mode, setMode] = useState<"auto" | "survey" | "interview">("auto");
  const [consent, setConsent] = useState(false);
  const [geography, setGeography] = useState(candidates.find((c) => c.id === candidateId)?.jurisdiction ?? "");
  const [cand, setCand] = useState<string | null>(candidateId);
  const [file, setFile] = useState<File | null>(null);
  const [pasted, setPasted] = useState("");
  const [pop, setPop] = useState<Population | null>(null);
  const [report, setReport] = useState<ImportChunkResult | null>(null);
  const [progress, setProgress] = useState<string | null>(null);
  const [rake, setRake] = useState(true);
  const [preset, setPreset] = useState("us_registered_voters");
  const [reflections, setReflections] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function upload(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const text = file ? await file.text() : pasted;
      const chunks = csvChunks(text);
      if (!chunks.length) throw new Error("That file has a header but no rows.");
      const p = await sim.importStart({ name, description: "", mode, consent_attested: consent, card_detail: "light", geography, candidate_id: cand });
      setPop(p);
      let last: ImportChunkResult | null = null;
      for (let i = 0; i < chunks.length; i++) {
        setProgress(`Uploading part ${i + 1} of ${chunks.length}…`);
        last = await sim.importChunk(p.id, chunks[i]);
      }
      setReport(last);
      setProgress(null);
    } catch (err) {
      setError((err as Error).message);
      setProgress(null);
    } finally {
      setBusy(false);
    }
  }

  async function finish() {
    if (!pop) return;
    setBusy(true);
    try {
      await sim.importFinish(pop.id, { rake, preset, generate_reflections: reflections });
      goSim(`pop/${pop.id}`);
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  return (
    <div className="stack">
      <div className="sim-head">
        <div>
          <div className="crumbs">
            <a href={simHref()}>Simulations</a> / Import respondents
          </div>
          <h1>Import real respondents</h1>
          <div className="cand-sub small">One row per person. Survey answers or interview transcripts become that person's agent; Park et al. found agents built from real answers far more accurate than demographics alone.</div>
        </div>
      </div>
      {!report && (
        <form className="grid form-split" onSubmit={upload}>
          <Card title="Upload">
            <div className="stack-sm">
              <Field label="Name">
                <input className="input" required value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. March 2026 voter panel" />
              </Field>
              <div className="form-grid">
                <Field label="What each row holds">
                  <select className="input" value={mode} onChange={(e) => setMode(e.target.value as typeof mode)}>
                    <option value="auto">Detect automatically</option>
                    <option value="survey">Survey answers</option>
                    <option value="interview">Interview transcript column</option>
                  </select>
                </Field>
                <Field label="Place">
                  <input className="input" value={geography} onChange={(e) => setGeography(e.target.value)} placeholder="optional" />
                </Field>
                <Field label="Link to candidate" full>
                  <select className="input" value={cand ?? ""} onChange={(e) => setCand(e.target.value || null)}>
                    <option value="">None</option>
                    {candidates.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.name}
                      </option>
                    ))}
                  </select>
                </Field>
              </div>
              <Field label="CSV file">
                <input className="input" type="file" accept=".csv,text/csv" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
              </Field>
              {!file && (
                <Field label="…or paste CSV">
                  <textarea className="input" rows={6} value={pasted} onChange={(e) => setPasted(e.target.value)} placeholder="header row, then one row per respondent" />
                </Field>
              )}
              <label className="row small" style={{ alignItems: "flex-start" }}>
                <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} style={{ marginTop: 3 }} />
                <span>Respondents consented to their answers being used for research like this. I understand rows are sent to the model provider to build agents.</span>
              </label>
              <ErrorNotice error={error} />
              <div className="row" style={{ justifyContent: "space-between" }}>
                <button className="btn primary" type="submit" disabled={busy || !consent || !name.trim() || (!file && !pasted.trim())}>
                  {progress ?? (busy ? "Uploading…" : "Upload")}
                </button>
                <button type="button" className="btn ghost sm" onClick={() => setPasted(EXAMPLE)}>
                  Paste an example
                </button>
              </div>
            </div>
          </Card>
          <Card title="What gets used">
            <ul className="bullets small secondary">
              <li>Recognized demographic columns (age, gender, race, education, income, region, state, party, ideology, 2024 vote) fill each agent's card. Missing values stay unknown; nothing is guessed.</li>
              <li>A column named weight, wt or weights becomes the starting survey weight.</li>
              <li>Columns that look like names, emails, phone numbers, addresses, ZIP codes, IPs or birth dates are dropped before anything is stored.</li>
              <li>Every other column becomes a survey answer the agent remembers, or with an interview column, the transcript does.</li>
              <li>Each agent gets a pseudonym and four expert reflections written from its record.</li>
            </ul>
          </Card>
        </form>
      )}
      {report && pop && (
        <div className="grid form-split">
          <Card title={`${report.total.toLocaleString()} respondents imported`}>
            <div className="stack-sm">
              <Field label="Weight to a known population">
                <select className="input" value={rake ? preset : ""} onChange={(e) => (e.target.value ? (setRake(true), setPreset(e.target.value)) : setRake(false))}>
                  <option value="">No, keep the file's weights</option>
                  {Object.entries(meta.presets).map(([k, p]) => (
                    <option key={k} value={k}>
                      Rake to {p.label}
                    </option>
                  ))}
                </select>
              </Field>
              <label className="row small">
                <input type="checkbox" checked={reflections} onChange={(e) => setReflections(e.target.checked)} />
                Write expert reflections and pseudonyms ({report.total} model calls)
              </label>
              <ErrorNotice error={error} />
              <button className="btn primary" onClick={finish} disabled={busy}>
                {busy ? "Finishing…" : "Finish import"}
              </button>
            </div>
          </Card>
          <Card title="Column mapping">
            <div className="stack-sm small">
              <dl className="kv">
                {Object.entries(report.columns.mapping).map(([field, col]) => (
                  <Fragment key={field}>
                    <dt>{field}</dt>
                    <dd>{col}</dd>
                  </Fragment>
                ))}
              </dl>
              <div>
                <strong>Dropped as personal data:</strong> {report.columns.pii_dropped.join(", ") || "none"}
              </div>
              <div>
                <strong>Survey answers kept:</strong> {report.columns.answer_columns.length} columns
              </div>
              {Object.keys(report.unknown_values).length > 0 && (
                <div className="notice warn small">
                  Some values weren't recognized and were left unknown:{" "}
                  {Object.entries(report.unknown_values)
                    .map(([f, vals]) => `${f} (${Object.keys(vals).slice(0, 4).join(", ")})`)
                    .join("; ")}
                </div>
              )}
            </div>
          </Card>
        </div>
      )}
    </div>
  );
}
