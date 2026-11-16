import { useEffect, useState } from "react";
import {
  Upload,
  Film,
  Play,
  Download,
  Check,
  X,
  RefreshCw,
  Send,
  Archive,
  Wand2,
} from "lucide-react";
import { api } from "../api";

const authLabels = {
  user_owned: "I own this media",
  creator_authorized: "Creator authorized",
  licensed: "Licensed",
  unverified: "Not verified",
  not_authorized: "Not authorized",
  unknown: "Unknown",
};
const profileLabels = {
  original: "Original aspect ratio",
  shorts_1080x1920: "Vertical · 1080 × 1920",
  shorts_720x1280: "Vertical · 720 × 1280",
};
const size = (bytes) => `${(bytes / 1024 / 1024).toFixed(1)} MB`;
export function Notice({ error, success }) {
  return (
    <>
      {error && (
        <div role="alert" className="error">
          {error}
        </div>
      )}
      {success && (
        <div role="status" className="info-note">
          {success}
        </div>
      )}
    </>
  );
}
function Title({ title, description }) {
  return (
    <div className="page-title">
      <div>
        <span className="eyebrow">LOCAL PRODUCTION STUDIO</span>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
    </div>
  );
}

export function Processing() {
  const [media, setMedia] = useState([]),
    [jobs, setJobs] = useState([]),
    [selected, setSelected] = useState(null),
    [system, setSystem] = useState(null),
    [error, setError] = useState(""),
    [success, setSuccess] = useState(""),
    [loading, setLoading] = useState(true),
    [busy, setBusy] = useState(false),
    [progress, setProgress] = useState(null),
    [history, setHistory] = useState(null),
    [archived, setArchived] = useState(false);
  async function refresh() {
    const [m, j, s] = await Promise.all([
      api(`/media?archived=${archived}`),
      api("/processing/jobs"),
      api("/system/status"),
    ]);
    setMedia(m);
    setJobs(j);
    setSystem(s);
  }
  useEffect(() => {
    let alive = true;
    async function load() {
      try {
        const [m, j, s] = await Promise.all([
          api(`/media?archived=${archived}`),
          api("/processing/jobs"),
          api("/system/status"),
        ]);
        if (alive) {
          setMedia(m);
          setJobs(j);
          setSystem(s);
        }
      } catch (e) {
        if (alive) setError(e.message);
      } finally {
        if (alive) setLoading(false);
      }
    }
    load();
    const timer = setInterval(load, 3000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [archived]);
  async function upload(event) {
    event.preventDefault();
    setError("");
    setSuccess("");
    setBusy(true);
    setProgress(0);
    const data = new FormData(event.currentTarget);
    try {
      const result = await new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        xhr.open("POST", "/api/v1/media/upload");
        xhr.upload.onprogress = (e) => {
          if (e.lengthComputable)
            setProgress(Math.round((e.loaded / e.total) * 100));
        };
        xhr.onload = () => {
          try {
            const data = JSON.parse(xhr.responseText);
            xhr.status >= 200 && xhr.status < 300
              ? resolve(data)
              : reject(new Error(data.error?.message || "Upload failed."));
          } catch {
            reject(new Error("Upload returned an invalid response."));
          }
        };
        xhr.onerror = () =>
          reject(new Error("Upload connection failed. Try again."));
        xhr.timeout = 300000;
        xhr.ontimeout = () =>
          reject(new Error("Upload timed out. Try a smaller file."));
        xhr.send(data);
      });
      setSelected(result);
      setSuccess(
        "Media inspected and imported. Matching files reuse the existing asset.",
      );
      await refresh();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
      setProgress(null);
    }
  }
  async function act(job, action) {
    setError("");
    try {
      await api(`/processing/jobs/${job.id}/${action}`, { method: "POST" });
      await refresh();
    } catch (e) {
      setError(e.message);
    }
  }
  async function archive(asset) {
    if (
      !window.confirm(
        `${asset.archived ? "Restore" : "Archive"} ${asset.original_filename}? Files and history will be retained.`,
      )
    )
      return;
    try {
      await api(`/media/${asset.id}`, {
        method: "PATCH",
        body: JSON.stringify({ archived: !asset.archived }),
      });
      if (selected?.id === asset.id) setSelected(null);
      await refresh();
    } catch (e) {
      setError(e.message);
    }
  }
  return (
    <>
      <Title
        title="Media & processing"
        description="Import authorized footage. Shape it for your next story."
      />
      <Notice error={error} success={success} />
      {system && !system.processing_capabilities.ffmpeg && (
        <div className="warning">
          Install FFmpeg and FFprobe to inspect and process videos.
        </div>
      )}
      <div className="production-layout">
        <section className="panel">
          <h2>Import a video</h2>
          <form className="stack-form" onSubmit={upload}>
            <label className="upload-zone">
              <Upload size={28} />
              <strong>Choose your source file</strong>
              <span>
                MP4, MOV, M4V, WebM or MKV · up to{" "}
                {system?.max_upload_mb ?? 500} MB
              </span>
              <input
                required
                name="file"
                aria-label="Video file"
                type="file"
                accept=".mp4,.mov,.m4v,.webm,.mkv"
                disabled={busy}
              />
            </label>
            <label>
              Media rights
              <select name="authorization_status" required defaultValue="">
                <option value="" disabled>
                  Select authorization
                </option>
                {Object.entries(authLabels).map(([id, label]) => (
                  <option key={id} value={id}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Permission / license notes
              <textarea
                name="authorization_notes"
                maxLength={4000}
                placeholder="Where this footage came from and your permission to use it"
              />
            </label>
            <label>
              Source URL (optional)
              <input type="url" name="source_url" placeholder="https://…" />
            </label>
            <button className="primary" disabled={busy}>
              {busy
                ? progress === 100
                  ? "Inspecting media…"
                  : `Uploading ${progress ?? 0}%…`
                : "Import & inspect"}
              <Upload size={15} />
            </button>
          </form>
        </section>
        <section className="panel">
          <div className="section-head">
            <h2>Your media</h2>
            <label className="check-label">
              <input
                type="checkbox"
                checked={archived}
                onChange={(e) => setArchived(e.target.checked)}
              />
              Archived
            </label>
          </div>
          {loading ? (
            <p role="status">Loading media…</p>
          ) : !media.length ? (
            <div className="empty">
              <Film />
              <h3>No media here yet</h3>
              <p>
                Import a video to begin. Discovery metadata is separate from
                source files.
              </p>
            </div>
          ) : (
            <div className="media-list">
              {media.map((m) => (
                <div
                  className={`media-row ${selected?.id === m.id ? "selected" : ""}`}
                  key={m.id}
                >
                  <button
                    className="media-select"
                    onClick={() => setSelected(m)}
                  >
                    <Film size={20} />
                    <span>
                      <strong>{m.original_filename}</strong>
                      <small>
                        {m.width} × {m.height} · {m.duration_seconds.toFixed(1)}
                        s · {size(m.size_bytes)}
                      </small>
                      <small>
                        {authLabels[m.authorization_status]} · {m.review_status}
                      </small>
                    </span>
                  </button>
                  <button
                    className="icon-button"
                    aria-label={`${m.archived ? "Restore" : "Archive"} ${m.original_filename}`}
                    onClick={() => archive(m)}
                  >
                    <Archive size={16} />
                  </button>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
      {selected && (
        <Editor
          key={selected.id}
          asset={selected}
          system={system}
          onUpdate={async (m) => {
            setSelected(m);
            await refresh();
          }}
          onQueued={async () => {
            setSuccess(
              "Job queued. Progress and attempt history appear below.",
            );
            await refresh();
          }}
        />
      )}
      <section className="panel jobs-panel">
        <div className="section-head">
          <h2>Processing history</h2>
          <span className="muted">
            Persistent local queue · {system?.worker ?? "checking"} worker
          </span>
        </div>
        {jobs.length ? (
          jobs.map((job) => (
            <div className="job-row" key={job.id}>
              <div>
                <strong>
                  {media.find((m) => m.id === job.media_asset_id)
                    ?.original_filename ||
                    `Media ${job.media_asset_id.slice(0, 8)}`}
                </strong>
                <small>
                  {job.options.profiles
                    .map((p) => profileLabels[p])
                    .join(" + ")}{" "}
                  · attempt {job.attempt_count}/{job.max_attempts}
                </small>
                <progress
                  value={job.progress_percent}
                  max="100"
                  aria-label={`Job ${job.id} progress`}
                />
                {job.error_message && (
                  <p className="job-error">{job.error_message}</p>
                )}
              </div>
              <span className={`job-status ${job.status}`}>
                {job.status} · {job.progress_percent}%
              </span>
              <div className="job-actions">
                {["queued", "running"].includes(job.status) && (
                  <button onClick={() => act(job, "cancel")}>Cancel</button>
                )}
                {job.status === "failed" &&
                  job.retryable &&
                  job.attempt_count < job.max_attempts && (
                    <button onClick={() => act(job, "retry")}>Retry</button>
                  )}
                <button
                  onClick={async () => {
                    try {
                      setHistory(
                        await api(`/processing/jobs/${job.id}/events`),
                      );
                    } catch (e) {
                      setError(e.message);
                    }
                  }}
                >
                  History
                </button>
              </div>
            </div>
          ))
        ) : (
          <div className="empty">
            <h3>No processing jobs yet</h3>
            <p>Select imported media and choose an output profile.</p>
          </div>
        )}
        {history && (
          <div className="audit-history">
            <div className="section-head">
              <h3>Attempt history</h3>
              <button
                onClick={() => setHistory(null)}
                aria-label="Close history"
              >
                <X size={14} />
              </button>
            </div>
            {history.map((e) => (
              <p key={e.id}>
                <time>{new Date(e.created_at).toLocaleString()}</time> · Attempt{" "}
                {e.attempt} · {e.message}
              </p>
            ))}
          </div>
        )}
      </section>
    </>
  );
}

function Editor({ asset, system, onUpdate, onQueued }) {
  const [authorization, setAuthorization] = useState(
      asset.authorization_status,
    ),
    [notes, setNotes] = useState(asset.authorization_notes),
    [srt, setSrt] = useState(asset.subtitle_srt),
    [metadata, setMetadata] = useState({
      title: "",
      description: "",
      hashtags: "",
      hook: "",
      ...asset.publishing_metadata,
    }),
    [start, setStart] = useState(0),
    [end, setEnd] = useState(asset.duration_seconds),
    [profiles, setProfiles] = useState(["original", "shorts_1080x1920"]),
    [fps, setFps] = useState(30),
    [crf, setCrf] = useState(23),
    [normalize, setNormalize] = useState(false),
    [mute, setMute] = useState(false),
    [burn, setBurn] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [success, setSuccess] = useState("");
  async function save() {
    const updated = await api(`/media/${asset.id}`, {
      method: "PATCH",
      body: JSON.stringify({
        authorization_status: authorization,
        authorization_notes: notes,
        subtitle_srt: srt,
        publishing_metadata: metadata,
      }),
    });
    await onUpdate(updated);
    return updated;
  }
  async function action(fn, message) {
    setBusy(true);
    setError("");
    setSuccess("");
    try {
      await fn();
      if (message) setSuccess(message);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  async function queue() {
    await save();
    await api("/processing/jobs", {
      method: "POST",
      body: JSON.stringify({
        media_id: asset.id,
        profiles,
        trim_start_seconds: Number(start),
        trim_end_seconds: Number(end),
        fps: Number(fps),
        crf: Number(crf),
        normalize_audio: normalize,
        mute_audio: mute,
        burn_subtitles: burn,
      }),
    });
    await onQueued();
  }
  return (
    <section className="panel editor-panel">
      <div className="section-head">
        <h2>Edit · {asset.original_filename}</h2>
        <span className="pill">
          {asset.video_codec} / {asset.audio_codec || "no audio"}
        </span>
      </div>
      <Notice error={error} success={success} />
      <div className="production-layout">
        <div>
          <video
            className="video-preview"
            controls
            preload="metadata"
            src={`/api/v1/media/${asset.id}/download?preview=true`}
          />
          <div className="metadata-strip">
            <span>
              {asset.width} × {asset.height}
            </span>
            <span>{asset.duration_seconds.toFixed(2)} seconds</span>
            <span>{size(asset.size_bytes)}</span>
          </div>
          <details>
            <summary>Provenance & file integrity</summary>
            <p>
              Source:{" "}
              {asset.source_provenance.source_url || "Local file upload"}
            </p>
            <p className="hash">SHA-256: {asset.sha256}</p>
          </details>
          <div className="stack-form">
            <label>
              Authorization
              <select
                value={authorization}
                onChange={(e) => setAuthorization(e.target.value)}
              >
                {Object.entries(authLabels).map(([k, v]) => (
                  <option key={k} value={k}>
                    {v}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Authorization notes
              <textarea
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                maxLength={4000}
              />
            </label>
            <div className="form-columns">
              <label>
                Trim start (seconds)
                <input
                  type="number"
                  min="0"
                  step="0.01"
                  max={asset.duration_seconds}
                  value={start}
                  onChange={(e) => setStart(e.target.value)}
                />
              </label>
              <label>
                Trim end (seconds)
                <input
                  type="number"
                  min="0.01"
                  step="0.01"
                  max={asset.duration_seconds}
                  value={end}
                  onChange={(e) => setEnd(e.target.value)}
                />
              </label>
            </div>
            <fieldset>
              <legend>Output profiles</legend>
              {Object.entries(profileLabels).map(([id, name]) => (
                <label className="check-label" key={id}>
                  <input
                    type="checkbox"
                    checked={profiles.includes(id)}
                    onChange={(e) =>
                      setProfiles((v) =>
                        e.target.checked
                          ? [...v, id]
                          : v.filter((p) => p !== id),
                      )
                    }
                  />
                  {name}
                </label>
              ))}
            </fieldset>
            <div className="form-columns">
              <label>
                Frame rate
                <select value={fps} onChange={(e) => setFps(e.target.value)}>
                  {[24, 30, 60].map((v) => (
                    <option key={v} value={v}>
                      {v} FPS
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Quality (CRF 16–35)
                <input
                  type="number"
                  min="16"
                  max="35"
                  value={crf}
                  onChange={(e) => setCrf(e.target.value)}
                />
              </label>
            </div>
            <label className="check-label">
              <input
                type="checkbox"
                checked={normalize}
                onChange={(e) => setNormalize(e.target.checked)}
                disabled={mute || !asset.audio_codec}
              />
              Normalize audio
            </label>
            <label className="check-label">
              <input
                type="checkbox"
                checked={mute}
                onChange={(e) => setMute(e.target.checked)}
              />
              Mute audio
            </label>
            <label className="check-label">
              <input
                type="checkbox"
                checked={burn}
                onChange={(e) => setBurn(e.target.checked)}
                disabled={!system?.processing_capabilities.subtitles}
              />
              Burn captions into video
            </label>
            {!system?.processing_capabilities.subtitles && (
              <p className="muted">
                This FFmpeg build does not include libass. Captions are
                available as sidecar SRT files.
              </p>
            )}
          </div>
        </div>
        <div className="stack-form">
          <div className="section-head">
            <h3>Publishing copy</h3>
            <button
              disabled={busy}
              onClick={() =>
                action(async () => {
                  const result = await api("/ai/suggest", {
                    method: "POST",
                    body: JSON.stringify({
                      context: `Filename: ${asset.original_filename}\nUser description: ${metadata.description}\nTitle: ${metadata.title}`,
                    }),
                  });
                  setMetadata(result);
                }, "AI draft ready. Review and save your edits.")
              }
            >
              <Wand2 size={14} />
              Suggest with AI
            </button>
          </div>
          <p className="muted">
            Optional AI sends your filename and entered title/description to
            OpenAI. Nothing is published automatically.
          </p>
          {Object.entries({
            title: "Title",
            description: "Description",
            hashtags: "Hashtags",
            hook: "Hook",
          }).map(([key, label]) => (
            <label key={key}>
              {label}
              {key === "description" ? (
                <textarea
                  value={metadata[key]}
                  maxLength={5000}
                  onChange={(e) =>
                    setMetadata((v) => ({ ...v, [key]: e.target.value }))
                  }
                />
              ) : (
                <input
                  value={metadata[key]}
                  maxLength={5000}
                  onChange={(e) =>
                    setMetadata((v) => ({ ...v, [key]: e.target.value }))
                  }
                />
              )}
            </label>
          ))}
          <div className="section-head">
            <h3>Captions (SRT)</h3>
            <button
              disabled={busy}
              onClick={() => {
                if (
                  window.confirm(
                    "Send this video’s audio to OpenAI for transcription? This may incur API charges.",
                  )
                )
                  action(async () => {
                    const result = await api(`/media/${asset.id}/transcribe`, {
                      method: "POST",
                    });
                    setSrt(result.subtitle_srt);
                  }, "Transcript ready. Review and save before processing.");
              }}
            >
              Transcribe audio
            </button>
          </div>
          <textarea
            className="caption-editor"
            aria-label="SRT captions"
            value={srt}
            maxLength={100000}
            onChange={(e) => setSrt(e.target.value)}
            placeholder={"1\n00:00:00,000 --> 00:00:02,000\nYour caption here"}
          />
          <p className="muted">
            Caption times refer to the original media. Exported captions are
            shifted and clipped to your trim.
          </p>
          <button
            disabled={busy}
            onClick={() =>
              action(save, "Changes saved. Review status reset to pending.")
            }
          >
            Save edits
          </button>
          <button
            className="primary"
            disabled={busy || !profiles.length || asset.archived}
            onClick={() => action(queue)}
          >
            <Play size={15} />
            {busy ? "Working…" : "Save & create outputs"}
          </button>
        </div>
      </div>
    </section>
  );
}

export function Outputs() {
  const [outputs, setOutputs] = useState([]),
    [jobs, setJobs] = useState([]),
    [media, setMedia] = useState([]),
    [loading, setLoading] = useState(true),
    [error, setError] = useState(""),
    [success, setSuccess] = useState(""),
    [busy, setBusy] = useState("");
  async function load() {
    const [o, j, m] = await Promise.all([
      api("/outputs"),
      api("/processing/jobs"),
      api("/media"),
    ]);
    setOutputs(o);
    setJobs(j);
    setMedia(m);
  }
  useEffect(() => {
    load()
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);
  async function review(asset, action) {
    setBusy(asset.id);
    setError("");
    try {
      await api(`/media/${asset.id}/review`, {
        method: "POST",
        body: JSON.stringify({ action, notes: "" }),
      });
      await load();
      setSuccess(
        `Media ${action}. Review applies to all outputs for this source.`,
      );
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy("");
    }
  }
  async function deliver(output) {
    if (
      !window.confirm(
        "Send this approved video and publishing copy to your configured Telegram chat?",
      )
    )
      return;
    setBusy(output.id);
    setError("");
    try {
      const history = await api(`/outputs/${output.id}/deliveries`);
      const hasPrevious = history.some((r) =>
        ["sent", "unknown"].includes(r.status),
      );
      if (
        hasPrevious &&
        !window.confirm(
          "A previous delivery was sent or uncertain. Have you checked Telegram and want to resend?",
        )
      )
        return;
      const result = await api(`/outputs/${output.id}/telegram-send`, {
        method: "POST",
        body: JSON.stringify({ confirm_resend: hasPrevious }),
      });
      if (result.status !== "sent")
        throw new Error(result.error_message || "Delivery did not complete.");
      setSuccess("Video delivered to Telegram.");
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy("");
    }
  }
  return (
    <>
      <Title
        title="Outputs & review"
        description="Inspect the final cut. Approve it, then download or deliver."
      />
      <Notice error={error} success={success} />
      {loading ? (
        <p role="status">Loading outputs…</p>
      ) : !outputs.length ? (
        <div className="empty">
          <Film />
          <h3>No finished outputs yet</h3>
          <p>
            Create a processing job from Media & processing. Only validated
            files appear here.
          </p>
        </div>
      ) : (
        <div className="outputs-grid">
          {outputs.map((o) => {
            const job = jobs.find((j) => j.id === o.processing_job_id);
            const asset =
              o.media || media.find((m) => m.id === job?.media_asset_id);
            return (
              <article className="panel output-card" key={o.id}>
                <video
                  controls
                  preload="metadata"
                  src={`/api/v1/outputs/${o.id}/download?preview=true`}
                />
                <div className="section-head">
                  <h2>{profileLabels[o.profile]}</h2>
                  <span className="pill green">VERIFIED</span>
                </div>
                <p>{asset?.original_filename || o.filename}</p>
                <div className="metadata-strip">
                  <span>
                    {o.width} × {o.height}
                  </span>
                  <span>{o.duration_seconds.toFixed(2)}s</span>
                  <span>{size(o.size_bytes)}</span>
                  <span>
                    {o.video_codec} / {o.audio_codec || "muted"}
                  </span>
                </div>
                <p className="review-state">
                  Review:{" "}
                  <strong>
                    {asset?.review_status ||
                      "Source archived — restore to review"}
                  </strong>
                </p>
                {asset && (
                  <div className="output-actions">
                    <button
                      disabled={!!busy}
                      onClick={() => review(asset, "approved")}
                    >
                      <Check size={14} />
                      Approve
                    </button>
                    <button
                      disabled={!!busy}
                      onClick={() => review(asset, "rejected")}
                    >
                      <X size={14} />
                      Reject
                    </button>
                    <button
                      disabled={!!busy}
                      onClick={() => review(asset, "needs_changes")}
                    >
                      Needs changes
                    </button>
                  </div>
                )}
                <div className="output-actions">
                  {asset?.review_status === "approved" ? (
                    <a
                      className="button-link primary"
                      href={`/api/v1/outputs/${o.id}/download`}
                    >
                      <Download size={14} />
                      Download MP4
                    </a>
                  ) : (
                    <button disabled>Approve to download</button>
                  )}
                  <button
                    disabled={!!busy || asset?.review_status !== "approved"}
                    onClick={() => deliver(o)}
                  >
                    <Send size={14} />
                    Telegram
                  </button>
                </div>
                <div className="output-actions">
                  <button
                    onClick={async () => {
                      try {
                        const r = await fetch(
                          `/api/v1/outputs/${o.id}/subtitles`,
                        );
                        if (!r.ok) {
                          const d = await r.json();
                          throw new Error(d.error?.message || "No captions");
                        }
                        const blob = await r.blob();
                        const url = URL.createObjectURL(blob);
                        const a = document.createElement("a");
                        a.href = url;
                        a.download = o.filename.replace(".mp4", ".srt");
                        a.click();
                        URL.revokeObjectURL(url);
                      } catch (e) {
                        setError(e.message);
                      }
                    }}
                  >
                    Download captions
                  </button>
                  {asset && (
                    <button
                      onClick={() => {
                        const blob = new Blob(
                          [JSON.stringify(asset.publishing_metadata, null, 2)],
                          { type: "application/json" },
                        );
                        const url = URL.createObjectURL(blob);
                        const a = document.createElement("a");
                        a.href = url;
                        a.download = "publishing-metadata.json";
                        a.click();
                        URL.revokeObjectURL(url);
                      }}
                    >
                      Metadata JSON
                    </button>
                  )}
                </div>
              </article>
            );
          })}
        </div>
      )}
    </>
  );
}
