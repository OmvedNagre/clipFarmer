import { useEffect, useState } from "react";
import { api } from "../api";

function usePolling(path, interval = 4000) {
  const [data, setData] = useState(null),
    [error, setError] = useState("");
  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const value = await api(path);
        if (alive) {
          setData(value);
          setError("");
        }
      } catch (e) {
        if (alive) setError(e.message);
      }
    };
    load();
    const timer = setInterval(load, interval);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [path, interval]);
  return [data, error];
}
const stamp = (value) => {
  const sec = Math.max(0, Math.floor(value));
  return `${Math.floor(sec / 3600)
    .toString()
    .padStart(2, "0")}:${Math.floor((sec % 3600) / 60)
    .toString()
    .padStart(2, "0")}:${(sec % 60).toString().padStart(2, "0")}`;
};
function ClipWindow({ job, moment, onMessage }) {
  const [start, setStart] = useState(moment.start),
    [end, setEnd] = useState(moment.end),
    [profile, setProfile] = useState("shorts_720x1280"),
    [busy, setBusy] = useState(false);
  async function render(e) {
    e.preventDefault();
    setBusy(true);
    try {
      const result = await api(`/links/${job.id}/clip`, {
        method: "POST",
        body: JSON.stringify({
          start: Number(start),
          end: Number(end),
          profile,
        }),
      });
      onMessage(
        `Clip queued (${result.id.slice(0, 8)}). Open Outputs when rendering finishes.`,
      );
    } catch (e) {
      onMessage(e.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <form className="clip-window" onSubmit={render}>
      <div>
        <strong>
          {stamp(moment.time ?? start)} ·{" "}
          {moment.method?.replaceAll("_", " ") || "Manual selection"}
        </strong>
        <p>{moment.evidence}</p>
      </div>
      <div className="live-form-grid">
        <label>
          Start (seconds)
          <input
            type="number"
            min="0"
            step="0.1"
            required
            value={start}
            onChange={(e) => setStart(e.target.value)}
          />
        </label>
        <label>
          End (seconds)
          <input
            type="number"
            min="0.1"
            max={job.metadata_snapshot.duration}
            step="0.1"
            required
            value={end}
            onChange={(e) => setEnd(e.target.value)}
          />
        </label>
        <label>
          Format
          <select value={profile} onChange={(e) => setProfile(e.target.value)}>
            <option value="shorts_720x1280">Vertical 720p</option>
            <option value="shorts_1080x1920">Vertical 1080p</option>
            <option value="original">Original dimensions</option>
          </select>
        </label>
      </div>
      <button disabled={busy}>
        {busy ? "Queuing…" : "Create downloadable clip"}
      </button>
    </form>
  );
}

export function LinkStudio({ initialUrl = "" }) {
  const [url, setUrl] = useState(initialUrl),
    [mode, setMode] = useState("video"),
    [permission, setPermission] = useState(false),
    [authorization, setAuthorization] = useState("creator_authorized"),
    [notes, setNotes] = useState("");
  const [jobs, loadError] = usePolling("/links"),
    [message, setMessage] = useState(""),
    [busy, setBusy] = useState(false),
    [selected, setSelected] = useState(null);
  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setMessage("");
    try {
      const row = await api("/links", {
        method: "POST",
        body: JSON.stringify({
          source_url: url,
          mode,
          permission_confirmed: permission,
          authorization,
          notes,
        }),
      });
      setSelected(row.id);
      setMessage("Queued. This page will update automatically.");
    } catch (e) {
      setMessage(e.message);
    } finally {
      setBusy(false);
    }
  }
  const current = (jobs || []).find((j) => j.id === selected);
  return (
    <div className="live-workspace">
      <div>
        <p className="eyebrow">FROM LINK TO CLIP</p>
        <h1>Link Studio</h1>
        <p>
          Download a supported video or find highlights in your own finished
          livestream.
        </p>
      </div>
      {(message || loadError) && (
        <div className="notice" role="status">
          {message || loadError}
        </div>
      )}
      <section className="panel live-panel">
        <form onSubmit={submit}>
          <div className="studio-mode" role="group" aria-label="Link workflow">
            <button
              type="button"
              aria-pressed={mode === "video"}
              onClick={() => setMode("video")}
            >
              Download a video
            </button>
            <button
              type="button"
              aria-pressed={mode === "stream"}
              onClick={() => setMode("stream")}
            >
              My livestream highlights
            </button>
          </div>
          <div className="live-form-grid">
            <label>
              Video or recording URL
              <input
                required
                type="url"
                placeholder="YouTube video or Twitch recording/clip"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
              />
            </label>
          </div>
          {mode === "video" ? (
            <>
              <div className="live-form-grid">
                <label>
                  Source permission
                  <select
                    value={authorization}
                    onChange={(e) => setAuthorization(e.target.value)}
                  >
                    <option value="creator_authorized">
                      Creator authorized me
                    </option>
                    <option value="user_owned">My own video</option>
                    <option value="licensed">Licensed for my use</option>
                  </select>
                </label>
                <label>
                  Notes
                  <input
                    value={notes}
                    onChange={(e) => setNotes(e.target.value)}
                    placeholder="Optional source or permission details"
                  />
                </label>
              </div>
              <label className="live-check">
                <input
                  type="checkbox"
                  checked={permission}
                  onChange={(e) => setPermission(e.target.checked)}
                />
                I own or have permission to download this video.
              </label>
            </>
          ) : (
            <p>
              This workflow treats the recording as your own. No permission or
              approval step. It ranks available chat-replay or replay-intensity
              peaks; if neither is usable, it labels audio-energy suggestions
              separately. Active streams belong in Live Watch.
            </p>
          )}
          <button
            className="primary"
            disabled={busy || (mode === "video" && !permission)}
          >
            {busy
              ? "Queuing…"
              : mode === "stream"
                ? "Find my stream highlights"
                : "Fetch video"}
          </button>
          <p>
            One public, accessible video at a time. Private sources, playlists,
            DRM and login-restricted media are not supported. Nothing is posted
            automatically from this page.
          </p>
        </form>
      </section>
      <section className="panel live-panel">
        <h2>Your link jobs</h2>
        {jobs?.length === 0 && <p>No link jobs yet.</p>}
        {(jobs || []).map((j) => (
          <article className="live-session" key={j.id}>
            <div>
              <button onClick={() => setSelected(j.id)}>
                {j.metadata_snapshot.title || j.source_url}
              </button>
              <p>
                <strong>{j.status}</strong> · {j.progress}
              </p>
            </div>
            {["queued", "running"].includes(j.status) && (
              <button
                onClick={async () => {
                  try {
                    await api(`/links/${j.id}/cancel`, { method: "POST" });
                    setMessage("Cancellation requested");
                  } catch (e) {
                    setMessage(e.message);
                  }
                }}
              >
                Cancel
              </button>
            )}
            {j.status === "ready" && (
              <a className="button" href={`/api/v1/links/${j.id}/download`}>
                Download video
              </a>
            )}
          </article>
        ))}
      </section>
      {current?.status === "ready" && (
        <section className="panel live-panel">
          <h2>{current.metadata_snapshot.title}</h2>
          <p>{current.progress}</p>
          <video
            className="studio-preview"
            controls
            preload="metadata"
            src={`/api/v1/media/${current.media_asset_id}/download?preview=true`}
          />
          {current.moments.map((moment, index) => (
            <ClipWindow
              key={`${current.id}-${index}`}
              job={current}
              moment={moment}
              onMessage={setMessage}
            />
          ))}
          <details>
            <summary>Select a clip manually</summary>
            <ClipWindow
              key={current.id}
              job={current}
              moment={{
                start: 0,
                end: Math.min(45, current.metadata_snapshot.duration),
              }}
              onMessage={setMessage}
            />
          </details>
        </section>
      )}
    </div>
  );
}

export function DailyFeed({ onOpenLink }) {
  const [data, loadError] = usePolling("/daily-feed", 5000),
    [message, setMessage] = useState(""),
    [busy, setBusy] = useState(false),
    [creators, setCreators] = useState(null);
  async function update(patch) {
    setBusy(true);
    try {
      await api("/daily-feed", {
        method: "PATCH",
        body: JSON.stringify({
          enabled: data.config.enabled,
          attachments: data.config.attachments,
          approved_creators: data.config.approved_creators,
          ...patch,
        }),
      });
      setMessage("Settings saved");
    } catch (e) {
      setMessage(e.message);
    } finally {
      setBusy(false);
    }
  }
  const latest = data?.runs[0];
  const items = data?.items.filter((i) => i.run_id === latest?.id) || [];
  const next = data
    ? new Date(data.config.next_run_at).toLocaleString("en-IN", {
        timeZone: "Asia/Kolkata",
      })
    : "Loading…";
  return (
    <div className="live-workspace">
      <div>
        <p className="eyebrow">MIDNIGHT DISCOVERY · IST</p>
        <h1>Daily GTA Gameplay</h1>
        <p>
          Up to 10 face and 10 faceless gameplay candidates, ranked by views
          within each group. No trailers, news, speculation or GTA V mods.
        </p>
      </div>
      {(message || loadError) && (
        <div className="notice" role="status">
          {message || loadError}
        </div>
      )}
      <section className="panel live-panel">
        <h2>Your daily delivery</h2>
        {data?.gameplay_not_before && (
          <p>
            Gameplay publication cutoff:{" "}
            <strong>{data.gameplay_not_before}</strong>. Pre-release uploads are
            excluded to reduce misleading results.
          </p>
        )}
        <p>
          Runs at 12:00 AM Asia/Kolkata while ClipForge is running and your Mac
          is awake. Next reset: <strong>{next} IST</strong>.
        </p>
        <p>
          The 20-link allowance resets each day; delivery history remains to
          prevent repeats. Video attachments are additional and limited to
          licensed or creator-authorized sources. Existing Telegram messages are
          never deleted.
        </p>
        {data && (
          <>
            <div className="studio-mode">
              <button
                disabled={busy}
                onClick={() => update({ enabled: !data.config.enabled })}
              >
                {data.config.enabled ? "Pause daily feed" : "Enable daily feed"}
              </button>
              <button
                disabled={busy || !data.config.enabled}
                onClick={async () => {
                  setBusy(true);
                  try {
                    await api("/daily-feed/run", { method: "POST" });
                    setMessage(
                      "Today's feed queued; it will use today's allowance.",
                    );
                  } catch (e) {
                    setMessage(e.message);
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                Run today's feed now
              </button>
            </div>
            <label className="live-check">
              <input
                type="checkbox"
                checked={data.config.attachments}
                disabled={busy}
                onChange={(e) => update({ attachments: e.target.checked })}
              />
              Attach eligible videos when they fit Telegram's size limit
            </label>
            <details>
              <summary>Creators who authorized automatic attachments</summary>
              <p>
                Discovery finds creators automatically. This list is only for
                permission to redistribute their videos. YouTube-declared
                Creative Commons sources are also eligible, with credit.
              </p>
              <div className="live-form-grid">
                <label>
                  Authorized YouTube channel IDs (comma separated)
                  <input
                    value={creators ?? data.config.approved_creators.join(", ")}
                    onChange={(e) => setCreators(e.target.value)}
                  />
                </label>
              </div>
              <button
                disabled={busy}
                onClick={() =>
                  update({
                    approved_creators: (
                      creators ?? data.config.approved_creators.join(",")
                    )
                      .split(",")
                      .map((s) => s.trim())
                      .filter(Boolean),
                  })
                }
              >
                Save authorized creators
              </button>
            </details>
            <p>
              Worker heartbeat:{" "}
              {data.config.heartbeat_at
                ? new Date(data.config.heartbeat_at).toLocaleString()
                : "Waiting for app worker"}
            </p>
            {data.config.heartbeat_at &&
              Date.now() - Date.parse(data.config.heartbeat_at) > 180000 && (
                <p role="status">
                  Heartbeat is stale or a long feed check is running. Check the
                  app process before relying on tonight's delivery.
                </p>
              )}
          </>
        )}
      </section>
      <section className="panel live-panel">
        <h2>{latest ? `Latest feed · ${latest.day}` : "First feed pending"}</h2>
        <p>
          {latest?.status} {latest?.diagnostic}
        </p>
        <p>
          Face grouping samples video frames and can mistake game characters for
          a presenter or miss a facecam. Gameplay matching uses source titles;
          it cannot certify that footage is genuine GTA VI. Unavailable or
          uncertain classifications are skipped, and shortfalls are reported.
        </p>
        {["face", "faceless"].map((category) => (
          <div key={category}>
            <h3>
              {category === "face" ? "Face detected" : "No face detected"} ·{" "}
              {items.filter((i) => i.category === category).length}/10
            </h3>
            {items
              .filter((i) => i.category === category)
              .map((item) => (
                <article className="live-session" key={item.id}>
                  <div>
                    <a
                      href={item.snapshot.canonical_url}
                      target="_blank"
                      rel="noreferrer"
                    >
                      {item.snapshot.title}
                    </a>
                    <p>
                      {item.snapshot.creator_name} ·{" "}
                      {(item.snapshot.view_count || 0).toLocaleString()} views
                    </p>
                    <small>{item.snapshot.classification}</small>
                    <p>
                      Link: {item.link_status} · Attachment:{" "}
                      {item.attachment_status}
                    </p>
                    <small>{item.diagnostic}</small>
                  </div>
                  <button
                    onClick={() => onOpenLink(item.snapshot.canonical_url)}
                  >
                    Open in Link Studio
                  </button>
                </article>
              ))}
          </div>
        ))}
      </section>
      <details className="panel live-panel">
        <summary>Previous runs</summary>
        {data?.runs.slice(1).map((run) => (
          <p key={run.id}>
            {run.day} · {run.status} · {run.diagnostic}
          </p>
        ))}
      </details>
    </div>
  );
}
