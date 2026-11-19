import { useEffect, useState } from "react";
import { api } from "../api";

const initial = {
  source_url: "",
  creator_id: "",
  creator_name: "",
  authorization_notes: "",
  authorized: false,
  ratio: 3,
  minimum: 10,
  distinct: 5,
  pre_roll: 30,
  post_roll: 15,
  chat_delay: 0,
  max_hours: 12,
  auto_render: true,
  transcribe: false,
};

export default function LiveWatch() {
  const [form, setForm] = useState(initial);
  const [sessions, setSessions] = useState([]);
  const [health, setHealth] = useState(null);
  const [selected, setSelected] = useState(null);
  const [moments, setMoments] = useState([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [schedules, setSchedules] = useState([]);
  const [query, setQuery] = useState("");
  const [creators, setCreators] = useState("");
  const [platform, setPlatform] = useState("youtube");
  const [interval, setIntervalValue] = useState(60);
  async function refresh() {
    const [rows, status, rules] = await Promise.all([
      api("/watch/sessions"),
      api("/watch/status"),
      api("/discovery/schedules"),
    ]);
    setSessions(rows);
    setHealth(status);
    setSchedules(rules);
  }
  useEffect(() => {
    let alive = true;
    const run = () => {
      if (alive) refresh().catch((e) => alive && setError(e.message));
    };
    run();
    const timer = setInterval(run, 5000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, []);
  useEffect(() => {
    if (!selected) return;
    let alive = true;
    const run = async () => {
      try {
        const rows = await api(`/watch/sessions/${selected}/moments`);
        if (alive) setMoments(rows);
      } catch (e) {
        if (alive) setError(e.message);
      }
    };
    run();
    const timer = setInterval(run, 5000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [selected]);
  function field(name, value) {
    setForm((f) => ({ ...f, [name]: value }));
  }
  async function act(fn) {
    setBusy(true);
    setError("");
    try {
      await fn();
      await refresh();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  const current = sessions.find((s) => s.id === selected);
  return (
    <div className="live-workspace">
      <header className="section-header">
        <div>
          <p className="eyebrow">UNATTENDED CAPTURE</p>
          <h1>Live Watch</h1>
          <p>
            Watch an authorized creator, find chat reactions, and prepare clips
            for review.
          </p>
        </div>
      </header>
      {error && (
        <div className="error" role="alert">
          {error}
        </div>
      )}
      <div className="notice">
        Live Watch always uses real platform connections. Start the separate
        watcher process on an always-on server. Closing this page does not stop
        a watch.
      </div>
      {health && (
        <div className="live-health" aria-label="Connection requirements">
          <span>
            Capture tools:{" "}
            {health.streamlink && health.ffmpeg ? "installed" : "setup needed"}
          </span>
          <span>
            YouTube API:{" "}
            {health.youtube_configured ? "configured" : "key needed"}
          </span>
          <span>
            Twitch chat:{" "}
            {health.twitch_configured ? "configured" : "token needed"}
          </span>
          <span>
            Local captions:{" "}
            {health.local_captions_configured ? "configured" : "model needed"}
          </span>
        </div>
      )}
      <section className="panel live-panel">
        <h2>Start watching</h2>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            act(async () => {
              const row = await api("/watch/sessions", {
                method: "POST",
                body: JSON.stringify(form),
              });
              setSelected(row.id);
            });
          }}
        >
          <div className="live-form-grid">
            <label>
              Live-stream URL
              <input
                required
                type="url"
                value={form.source_url}
                placeholder="https://www.youtube.com/watch?v=…"
                onChange={(e) => field("source_url", e.target.value)}
              />
            </label>
            <label>
              Platform creator ID
              <input
                required
                value={form.creator_id}
                placeholder="YouTube UC… ID or numeric Twitch user ID"
                onChange={(e) => field("creator_id", e.target.value)}
              />
            </label>
            <label>
              Creator credit
              <input
                required
                value={form.creator_name}
                onChange={(e) => field("creator_name", e.target.value)}
              />
            </label>
            <label>
              Permission record
              <input
                required
                minLength={5}
                value={form.authorization_notes}
                placeholder="How and when the creator authorized clipping"
                onChange={(e) => field("authorization_notes", e.target.value)}
              />
            </label>
          </div>
          <details>
            <summary>Detection and clip settings</summary>
            <div className="live-form-grid">
              {[
                ["ratio", "Spike multiplier", 1.5, 10, 0.5],
                ["minimum", "Minimum messages / 10 sec", 3, 10000, 1],
                ["distinct", "Minimum different chatters", 2, 1000, 1],
                ["pre_roll", "Seconds before reaction", 5, 120, 1],
                ["post_roll", "Seconds after reaction bucket", 5, 120, 1],
                ["chat_delay", "Chat delay adjustment (seconds)", -60, 60, 0.5],
                ["max_hours", "Maximum watch hours", 1, 24, 1],
              ].map(([key, label, min, max, step]) => (
                <label key={key}>
                  {label}
                  <input
                    type="number"
                    required
                    min={min}
                    max={max}
                    step={step}
                    value={form[key]}
                    onChange={(e) => field(key, Number(e.target.value))}
                  />
                </label>
              ))}
            </div>
            <p>
              Five-minute baseline; repeated messages and single-user bursts are
              dampened. Timing is capture-relative: review and adjust the clip
              before publishing.
            </p>
          </details>
          <label className="live-check">
            <input
              type="checkbox"
              checked={form.authorized}
              required
              onChange={(e) => field("authorized", e.target.checked)}
            />
            This creator has authorized me to capture and reuse this stream.
          </label>
          <label className="live-check">
            <input
              type="checkbox"
              checked={form.auto_render}
              onChange={(e) => field("auto_render", e.target.checked)}
            />
            Automatically render original and vertical outputs for review
          </label>
          <label className="live-check">
            <input
              type="checkbox"
              checked={form.transcribe}
              onChange={(e) => field("transcribe", e.target.checked)}
            />
            Generate local captions (requires whisper.cpp and a model)
          </label>
          <button className="primary" disabled={busy || !form.authorized}>
            Start watch
          </button>
        </form>
      </section>
      <section className="panel live-panel">
        <h2>Watch sessions</h2>
        {!sessions.length && (
          <p>No watches yet. Add an authorized stream above.</p>
        )}
        {sessions.map((s) => (
          <article className="live-session" key={s.id}>
            <div>
              <button className="text-button" onClick={() => setSelected(s.id)}>
                {s.creator_name} · {s.platform}
              </button>
              <p>
                <strong>{s.status}</strong> · {s.diagnostic}
              </p>
              <small>
                Heartbeat:{" "}
                {s.heartbeat_at
                  ? new Date(s.heartbeat_at).toLocaleString()
                  : "Waiting for worker"}
              </small>
              {s.heartbeat_at &&
                Date.now() - Date.parse(s.heartbeat_at) > 120000 &&
                ["recording", "waiting", "reconnecting"].includes(s.status) && (
                  <p role="status">
                    Worker heartbeat is stale. Check the server.
                  </p>
                )}
            </div>
            {["queued", "waiting", "recording", "reconnecting"].includes(
              s.status,
            ) && (
              <button
                disabled={busy || s.stop_requested}
                onClick={() =>
                  act(() =>
                    api(`/watch/sessions/${s.id}/stop`, { method: "POST" }),
                  )
                }
              >
                {s.stop_requested ? "Stopping…" : "Stop"}
              </button>
            )}
          </article>
        ))}
      </section>
      {current && (
        <section className="panel live-panel">
          <h2>{current.creator_name}: reaction timeline</h2>
          <div
            className="chat-timeline"
            aria-label="Chat messages per ten seconds"
          >
            {current.chat_buckets.map((b, i) => (
              <div
                key={i}
                title={`${b.start}s: ${b.count} messages, ${b.authors} chatters`}
                style={{
                  height: `${Math.max(3, (100 * b.count) / Math.max(1, ...current.chat_buckets.map((v) => v.count)))}%`,
                  background: b.spike ? "#c5ff73" : "#42775b",
                }}
              />
            ))}
          </div>
          {!moments.length && (
            <p>No reaction clips yet. Quiet streams may produce none.</p>
          )}
          {moments.map((m) => (
            <article className="live-session" key={m.id}>
              <div>
                <strong>
                  {m.start_seconds.toFixed(1)}–{m.end_seconds.toFixed(1)} sec ·{" "}
                  {m.status}
                </strong>
                <p>{m.reason}</p>
                {m.media_asset_id && (
                  <small>
                    Clip is available in Media & processing. Rendered versions
                    appear in Outputs for approval.
                  </small>
                )}
              </div>
            </article>
          ))}
        </section>
      )}
      <section className="panel live-panel">
        <h2>Scheduled discovery</h2>
        <p>
          Search real platform APIs and save results from your approved creator
          IDs. Metadata-only results still need an authorized source file.
        </p>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            act(() =>
              api("/discovery/schedules", {
                method: "POST",
                body: JSON.stringify({
                  query,
                  platforms: [platform],
                  creator_ids: creators
                    .split(",")
                    .map((s) => s.trim())
                    .filter(Boolean),
                  interval_minutes: Number(interval),
                }),
              }),
            );
          }}
        >
          <div className="live-form-grid">
            <label>
              Search query
              <input
                required
                maxLength={200}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </label>
            <label>
              Platform
              <select
                value={platform}
                onChange={(e) => setPlatform(e.target.value)}
              >
                {["youtube", "twitch", "reddit", "x"].map((p) => (
                  <option key={p}>{p}</option>
                ))}
              </select>
            </label>
            <label>
              Approved creator IDs (comma separated)
              <input
                required
                value={creators}
                onChange={(e) => setCreators(e.target.value)}
              />
            </label>
            <label>
              Every (minutes)
              <input
                type="number"
                min={15}
                max={10080}
                required
                value={interval}
                onChange={(e) => setIntervalValue(e.target.value)}
              />
            </label>
          </div>
          <button className="primary" disabled={busy}>
            Schedule discovery
          </button>
        </form>
        {schedules.map((r) => (
          <article className="live-session" key={r.id}>
            <div>
              <strong>
                {r.query} · every {r.interval_minutes} minutes
              </strong>
              <p>{r.diagnostic}</p>
              <small>
                Next run: {new Date(r.next_run_at).toLocaleString()}
              </small>
            </div>
            <button
              disabled={busy}
              onClick={() =>
                act(() =>
                  api(`/discovery/schedules/${r.id}`, {
                    method: "PATCH",
                    body: JSON.stringify({ enabled: !r.enabled }),
                  }),
                )
              }
            >
              {r.enabled ? "Pause" : "Resume"}
            </button>
          </article>
        ))}
      </section>
    </div>
  );
}
