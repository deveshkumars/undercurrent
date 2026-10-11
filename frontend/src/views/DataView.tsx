import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { CandidateForm, CsvImport, EventForm, PollForm } from "../components/Forms";
import { Card, ErrorNotice } from "../components/ui";
import { fmtDate, humanize, metricLabel } from "../format";
import type { CampaignEvent, Candidate, Poll } from "../types";

export function DataView({
  candidate,
  metric,
  segment,
  onChanged,
  onCandidateSaved,
  onCandidateDeleted,
}: {
  candidate: Candidate;
  metric: string;
  segment: string;
  onChanged: () => void;
  onCandidateSaved: (c: Candidate) => void;
  onCandidateDeleted: () => void;
}) {
  const cid = candidate.id;
  const [polls, setPolls] = useState<Poll[]>([]);
  const [events, setEvents] = useState<CampaignEvent[]>([]);
  const [modal, setModal] = useState<null | "poll" | "event" | "polls-csv" | "events-csv" | "candidate" | { edit: CampaignEvent }>(null);
  const [pollFilter, setPollFilter] = useState<"view" | "all">("view");
  const [showAllPolls, setShowAllPolls] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [p, e] = await Promise.all([api.polls(cid), api.events(cid)]);
      setPolls(p);
      setEvents(e);
    } catch (err) {
      setError((err as Error).message);
    }
  }, [cid]);

  useEffect(() => {
    load();
  }, [load]);

  const changed = () => {
    load();
    onChanged();
  };

  const vocabulary = useMemo(() => [...new Set(events.flatMap((e) => e.topics))].sort(), [events]);
  const visiblePolls = pollFilter === "view" ? polls.filter((p) => p.metric === metric && p.segment === segment) : polls;
  const shownPolls = showAllPolls ? visiblePolls : visiblePolls.slice(0, 25);

  return (
    <div className="stack">
      <ErrorNotice error={error} />
      <Card
        title="Events"
        sub="Speeches, interviews, debates, ads, votes, statements: anything voters might react to. Include what was actually said; Claude uses it."
        actions={
          <>
            <button className="btn" onClick={() => setModal("events-csv")}>
              Import CSV
            </button>
            <button className="btn primary" onClick={() => setModal("event")}>
              Add event
            </button>
          </>
        }
      >
        {events.length === 0 ? (
          <p className="muted small">No events yet.</p>
        ) : (
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Event</th>
                  <th>Type</th>
                  <th>Topics</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {events.map((ev) => (
                  <tr key={ev.id}>
                    <td className="num" style={{ whiteSpace: "nowrap" }}>
                      {fmtDate(ev.date, true)}
                    </td>
                    <td>
                      <strong>{ev.title}</strong>
                      {ev.summary && <div className="tiny muted">{ev.summary.length > 140 ? ev.summary.slice(0, 140) + "…" : ev.summary}</div>}
                    </td>
                    <td>{humanize(ev.type)}</td>
                    <td>
                      <div className="row" style={{ gap: 4 }}>
                        {ev.topics.map((t) => (
                          <span key={t} className="chip">
                            {t}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td style={{ whiteSpace: "nowrap", textAlign: "right" }}>
                      <button className="btn ghost sm" onClick={() => setModal({ edit: ev })}>
                        Edit
                      </button>
                      <button
                        className="btn ghost sm danger"
                        onClick={async () => {
                          if (confirm(`Delete “${ev.title}”?`)) {
                            await api.deleteEvent(cid, ev.id);
                            changed();
                          }
                        }}
                      >
                        Delete
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card
        title="Polls"
        sub={`${polls.length} polls stored. Each row is one topline or crosstab result.`}
        actions={
          <>
            <div className="seg-toggle" role="group" aria-label="Filter polls">
              <button aria-pressed={pollFilter === "view"} onClick={() => setPollFilter("view")}>
                {metricLabel(metric)} · {segment}
              </button>
              <button aria-pressed={pollFilter === "all"} onClick={() => setPollFilter("all")}>
                All
              </button>
            </div>
            <button className="btn" onClick={() => setModal("polls-csv")}>
              Import CSV
            </button>
            <button className="btn primary" onClick={() => setModal("poll")}>
              Add poll
            </button>
          </>
        }
      >
        {visiblePolls.length === 0 ? (
          <p className="muted small">No polls here yet.</p>
        ) : (
          <>
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>Pollster</th>
                    <th className="num">n</th>
                    <th>Pop.</th>
                    {pollFilter === "all" && <th>Metric</th>}
                    {pollFilter === "all" && <th>Segment</th>}
                    <th className="num">{candidate.name.split(" ")[0]}</th>
                    <th className="num">{candidate.opponent_name ? candidate.opponent_name.split(" ")[0] : "Opp."}</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {shownPolls.map((p) => (
                    <tr key={p.id}>
                      <td className="num">{fmtDate(p.date, true)}</td>
                      <td>{p.pollster}</td>
                      <td className="num">{p.sample_size ?? "—"}</td>
                      <td>{p.population || "—"}</td>
                      {pollFilter === "all" && <td>{metricLabel(p.metric)}</td>}
                      {pollFilter === "all" && <td>{p.segment}</td>}
                      <td className="num">{p.value}</td>
                      <td className="num">{p.opponent_value ?? "—"}</td>
                      <td style={{ textAlign: "right" }}>
                        <button
                          className="btn ghost sm danger"
                          aria-label={`Delete ${p.pollster} poll from ${p.date}`}
                          onClick={async () => {
                            await api.deletePoll(cid, p.id);
                            changed();
                          }}
                        >
                          ✕
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {visiblePolls.length > 25 && (
              <button className="btn ghost sm" style={{ marginTop: 8 }} onClick={() => setShowAllPolls(!showAllPolls)}>
                {showAllPolls ? "Show fewer" : `Show all ${visiblePolls.length}`}
              </button>
            )}
          </>
        )}
      </Card>

      <Card
        title="Candidate profile"
        actions={
          <>
            <button className="btn" onClick={() => setModal("candidate")}>
              Edit profile
            </button>
            <button
              className="btn danger"
              onClick={async () => {
                if (confirm(`Delete ${candidate.name} and all of their polls, events and reports? This can't be undone.`)) {
                  await api.deleteCandidate(cid);
                  onCandidateDeleted();
                }
              }}
            >
              Delete candidate
            </button>
          </>
        }
      >
        <dl className="kv">
          {(
            [
              ["Office", candidate.office],
              ["Party", candidate.party],
              ["Jurisdiction", candidate.jurisdiction],
              ["Opponent", candidate.opponent_name],
              ["Election", candidate.election_date ? fmtDate(candidate.election_date, true) : ""],
            ] as const
          ).map(([k, v]) => (
            <div key={k} style={{ display: "contents" }}>
              <dt>{k}</dt>
              <dd>{v || "—"}</dd>
            </div>
          ))}
        </dl>
        {candidate.bio && <p className="small secondary" style={{ marginTop: 10 }}>{candidate.bio}</p>}
      </Card>

      {modal === "poll" && <PollForm cid={cid} metric={metric} segment={segment} onClose={() => setModal(null)} onSaved={() => (setModal(null), changed())} />}
      {modal === "event" && <EventForm cid={cid} vocabulary={vocabulary} onClose={() => setModal(null)} onSaved={() => (setModal(null), changed())} />}
      {modal && typeof modal === "object" && (
        <EventForm cid={cid} initial={modal.edit} vocabulary={vocabulary} onClose={() => setModal(null)} onSaved={() => (setModal(null), changed())} />
      )}
      {modal === "polls-csv" && <CsvImport cid={cid} kind="polls" onClose={() => setModal(null)} onDone={changed} />}
      {modal === "events-csv" && <CsvImport cid={cid} kind="events" onClose={() => setModal(null)} onDone={changed} />}
      {modal === "candidate" && (
        <CandidateForm
          initial={candidate}
          onClose={() => setModal(null)}
          onSaved={(c) => {
            setModal(null);
            onCandidateSaved(c);
          }}
        />
      )}
    </div>
  );
}
