import { useState } from "react";
import { api } from "../api";
import { humanize } from "../format";
import { EVENT_TYPES, type CampaignEvent, type Candidate, type CandidateInput, type EventInput, type PollInput } from "../types";
import { ErrorNotice, Field, Modal } from "./ui";

export function CandidateForm({ initial, onClose, onSaved }: { initial?: Candidate; onClose: () => void; onSaved: (c: Candidate) => void }) {
  const [form, setForm] = useState<CandidateInput>({
    name: initial?.name ?? "",
    office: initial?.office ?? "",
    party: initial?.party ?? "",
    jurisdiction: initial?.jurisdiction ?? "",
    opponent_name: initial?.opponent_name ?? "",
    election_date: initial?.election_date ?? null,
    bio: initial?.bio ?? "",
  });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof CandidateInput) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => setForm({ ...form, [k]: e.target.value || (k === "election_date" ? null : "") });

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onSaved(initial ? await api.updateCandidate(initial.id, form) : await api.createCandidate(form));
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  return (
    <Modal title={initial ? "Edit candidate" : "New candidate"} onClose={onClose}>
      <form onSubmit={save}>
        <div className="form-grid">
          <Field label="Name" full>
            <input className="input" required value={form.name} onChange={set("name")} />
          </Field>
          <Field label="Office">
            <input className="input" value={form.office} onChange={set("office")} placeholder="Governor, US Senate, Mayor…" />
          </Field>
          <Field label="Party">
            <input className="input" value={form.party} onChange={set("party")} />
          </Field>
          <Field label="Jurisdiction">
            <input className="input" value={form.jurisdiction} onChange={set("jurisdiction")} placeholder="State, district or city" />
          </Field>
          <Field label="Election date">
            <input className="input" type="date" value={form.election_date ?? ""} onChange={set("election_date")} />
          </Field>
          <Field label="Main opponent" full>
            <input className="input" value={form.opponent_name} onChange={set("opponent_name")} />
          </Field>
          <Field label="Background" hint="context Claude should know" full>
            <textarea className="input" rows={4} value={form.bio} onChange={set("bio")} placeholder="Record, positions, the shape of the race…" />
          </Field>
        </div>
        <ErrorNotice error={error} />
        <div className="modal-actions">
          <button type="button" className="btn ghost" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="btn primary" disabled={busy}>
            {initial ? "Save" : "Create"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

const emptyEvent: EventInput = { date: "", type: "speech", title: "", summary: "", content: "", topics: [], tone: "", venue: "", audience: "", url: "" };

export function EventForm({ cid, initial, vocabulary, onClose, onSaved }: { cid: string; initial?: CampaignEvent; vocabulary: string[]; onClose: () => void; onSaved: () => void }) {
  const [form, setForm] = useState<EventInput>(initial ? { ...emptyEvent, ...initial } : emptyEvent);
  const [topicsText, setTopicsText] = useState((initial?.topics ?? []).join(", "));
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [tagging, setTagging] = useState(false);
  const set = (k: keyof EventInput) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => setForm({ ...form, [k]: e.target.value });

  const topics = () =>
    topicsText
      .split(",")
      .map((t) => t.trim().toLowerCase())
      .filter(Boolean);

  async function autoTag() {
    setTagging(true);
    setError(null);
    try {
      const tags = await api.tagEvent(cid, { title: form.title, summary: form.summary, content: form.content, existing_topics: vocabulary });
      setTopicsText(tags.topics.join(", "));
      setForm((f) => ({ ...f, tone: tags.tone, summary: f.summary || tags.summary }));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setTagging(false);
    }
  }

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const body = { ...form, topics: topics() };
    try {
      if (initial) await api.updateEvent(cid, initial.id, body);
      else await api.addEvent(cid, body);
      onSaved();
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  return (
    <Modal title={initial ? "Edit event" : "Add an event"} onClose={onClose} width={720}>
      <form onSubmit={save}>
        <div className="form-grid">
          <Field label="Title" full>
            <input className="input" required value={form.title} onChange={set("title")} placeholder="What happened, in a few words" />
          </Field>
          <Field label="Date">
            <input className="input" type="date" required value={form.date} onChange={set("date")} />
          </Field>
          <Field label="Type">
            <select className="input" value={form.type} onChange={set("type")}>
              {EVENT_TYPES.map((t) => (
                <option key={t} value={t}>
                  {humanize(t)}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Venue / outlet">
            <input className="input" value={form.venue} onChange={set("venue")} />
          </Field>
          <Field label="Audience">
            <input className="input" value={form.audience} onChange={set("audience")} />
          </Field>
          <Field label="What was said" hint="quotes, transcript excerpt, ad script" full>
            <textarea className="input" rows={6} value={form.content} onChange={set("content")} />
          </Field>
          <Field label="Summary" full>
            <textarea className="input" rows={2} style={{ minHeight: 56 }} value={form.summary} onChange={set("summary")} placeholder="How it was covered, how it played" />
          </Field>
          <Field label="Topics" hint="comma separated">
            <input className="input" value={topicsText} onChange={(e) => setTopicsText(e.target.value)} list="topic-vocab" placeholder="economy, housing" />
            <datalist id="topic-vocab">
              {vocabulary.map((t) => (
                <option key={t} value={t} />
              ))}
            </datalist>
          </Field>
          <Field label="Tone">
            <input className="input" value={form.tone} onChange={set("tone")} placeholder="optimistic, combative…" />
          </Field>
          <Field label="Source link" full>
            <input className="input" type="url" value={form.url} onChange={set("url")} placeholder="https://" />
          </Field>
        </div>
        <ErrorNotice error={error} />
        <div className="modal-actions" style={{ justifyContent: "space-between" }}>
          <button type="button" className="btn" onClick={autoTag} disabled={tagging || !(form.title || form.content)}>
            {tagging ? "Tagging…" : "✦ Suggest topics & tone"}
          </button>
          <div className="row">
            <button type="button" className="btn ghost" onClick={onClose}>
              Cancel
            </button>
            <button type="submit" className="btn primary" disabled={busy}>
              Save event
            </button>
          </div>
        </div>
      </form>
    </Modal>
  );
}

const emptyPoll = (metric: string, segment: string): PollInput => ({
  date: new Date().toISOString().slice(0, 10),
  pollster: "",
  sample_size: null,
  population: "LV",
  metric,
  segment,
  value: 0,
  opponent_value: null,
  margin_of_error: null,
});

export function PollForm({ cid, metric, segment, onClose, onSaved }: { cid: string; metric: string; segment: string; onClose: () => void; onSaved: () => void }) {
  const [form, setForm] = useState<PollInput>(emptyPoll(metric, segment));
  const [error, setError] = useState<string | null>(null);
  const num = (k: keyof PollInput) => (e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, [k]: e.target.value === "" ? null : Number(e.target.value) });
  const str = (k: keyof PollInput) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setForm({ ...form, [k]: e.target.value });

  async function save(e: React.FormEvent) {
    e.preventDefault();
    try {
      await api.addPoll(cid, form);
      onSaved();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <Modal title="Add a poll" onClose={onClose}>
      <form onSubmit={save}>
        <div className="form-grid">
          <Field label="Last day in field">
            <input className="input" type="date" required value={form.date} onChange={str("date")} />
          </Field>
          <Field label="Pollster">
            <input className="input" required value={form.pollster} onChange={str("pollster")} />
          </Field>
          <Field label="Candidate %">
            <input className="input" type="number" step="0.1" min={0} max={100} required value={form.value || ""} onChange={num("value")} />
          </Field>
          <Field label="Opponent %" hint="optional">
            <input className="input" type="number" step="0.1" min={0} max={100} value={form.opponent_value ?? ""} onChange={num("opponent_value")} />
          </Field>
          <Field label="Sample size">
            <input className="input" type="number" min={1} value={form.sample_size ?? ""} onChange={num("sample_size")} />
          </Field>
          <Field label="Population">
            <select className="input" value={form.population} onChange={str("population")}>
              <option value="LV">Likely voters</option>
              <option value="RV">Registered voters</option>
              <option value="A">Adults</option>
            </select>
          </Field>
          <Field label="Metric" hint="vote_share, approval, favorability…">
            <input className="input" required value={form.metric} onChange={str("metric")} />
          </Field>
          <Field label="Segment" hint="All, or a crosstab group">
            <input className="input" required value={form.segment} onChange={str("segment")} />
          </Field>
        </div>
        <ErrorNotice error={error} />
        <div className="modal-actions">
          <button type="button" className="btn ghost" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="btn primary">
            Add poll
          </button>
        </div>
      </form>
    </Modal>
  );
}

const SAMPLES = {
  polls: `date,pollster,sample_size,population,metric,segment,value,opponent_value
2026-09-01,Example Research,800,LV,vote_share,All,45,47
2026-09-01,Example Research,240,LV,vote_share,Independents,39,44`,
  events: `date,type,title,summary,content,topics,tone,venue,audience
2026-09-03,speech,Labor Day rally,"Rally focused on wages","""We will raise the minimum wage to 17 dollars.""",economy;wages,optimistic,Union hall,Union members`,
};

export function CsvImport({ cid, kind, onClose, onDone }: { cid: string; kind: "polls" | "events"; onClose: () => void; onDone: () => void }) {
  const [text, setText] = useState("");
  const [replace, setReplace] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function run() {
    setError(null);
    try {
      const r = kind === "polls" ? await api.importPolls(cid, text, replace) : await api.importEvents(cid, text, replace);
      const parts = [`Imported ${r.imported} ${kind}.`];
      if (r.error_count) parts.push(`${r.error_count} rows skipped (first: row ${r.errors[0].row}: ${r.errors[0].error}).`);
      if (r.ignored_columns.length) parts.push(`Ignored columns: ${r.ignored_columns.join(", ")}.`);
      setResult(parts.join(" "));
      if (r.imported) onDone();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <Modal title={`Import ${kind} from CSV`} onClose={onClose} width={720}>
      <div className="stack-sm">
        <p className="small secondary">
          {kind === "polls"
            ? "Needs date and value columns. Also understood: pollster, sample_size (n), population, metric, segment, opponent_value, margin_of_error."
            : "Needs date and title columns. Also understood: type, summary, content (transcript/quotes), topics (separated by ; or |), tone, venue, audience, url."}
        </p>
        <input
          type="file"
          accept=".csv,text/csv"
          onChange={async (e) => {
            const f = e.target.files?.[0];
            if (f) setText(await f.text());
          }}
        />
        <textarea className="input" rows={10} value={text} onChange={(e) => setText(e.target.value)} placeholder={SAMPLES[kind]} style={{ fontFamily: "var(--mono)", fontSize: 12.5 }} />
        <label className="row small">
          <input type="checkbox" checked={replace} onChange={(e) => setReplace(e.target.checked)} /> Replace all existing {kind} for this candidate
        </label>
        <ErrorNotice error={error} />
        {result && <div className="notice">{result}</div>}
      </div>
      <div className="modal-actions">
        <button className="btn ghost" onClick={onClose}>
          Close
        </button>
        <button className="btn primary" onClick={run} disabled={!text.trim()}>
          Import
        </button>
      </div>
    </Modal>
  );
}
