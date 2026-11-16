import { useState } from "react";
import { api } from "../api";
export default function SourceSubmission() {
  const [error, setError] = useState(""),
    [success, setSuccess] = useState(""),
    [busy, setBusy] = useState(false);
  async function submit(e) {
    e.preventDefault();
    const form = e.currentTarget;
    const values = Object.fromEntries(new FormData(form));
    setBusy(true);
    setError("");
    setSuccess("");
    try {
      await api("/discovery/submit", {
        method: "POST",
        body: JSON.stringify(values),
      });
      setSuccess(
        "Source saved to Library. Import an authorized file separately to edit it.",
      );
      form.reset();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <details className="panel source-submission">
      <summary>Save a source URL manually</summary>
      <p className="muted">
        Useful when a platform requires API approval. This saves your supplied
        metadata without downloading the media.
      </p>
      <form className="stack-form" onSubmit={submit}>
        <label>
          Public source URL
          <input
            required
            type="url"
            name="url"
            placeholder="https://www.instagram.com/p/…"
          />
        </label>
        <div className="form-columns">
          <label>
            Title
            <input required name="title" maxLength={500} />
          </label>
          <label>
            Creator
            <input
              name="creator_name"
              maxLength={200}
              defaultValue="User-submitted source"
            />
          </label>
        </div>
        <button className="primary" disabled={busy}>
          Save source
        </button>
      </form>
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
    </details>
  );
}
