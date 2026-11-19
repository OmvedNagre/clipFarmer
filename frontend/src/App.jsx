import { useEffect, useState } from "react";
import {
  LayoutDashboard,
  Compass,
  Library,
  SlidersHorizontal,
  Plug,
  ArrowUpRight,
  Search,
  ArrowRight,
  Film,
  Bookmark,
  Check,
  RefreshCw,
  Radio,
  ChevronRight,
} from "lucide-react";
import { api, names } from "./api";
import { Processing, Outputs } from "./features/Production";
import SourceSubmission from "./features/SourceSubmission";
import LiveWatch from "./features/LiveWatch";
import { DailyFeed, LinkStudio } from "./features/ContentStudio";

const nav = [
  ["Dashboard", LayoutDashboard],
  ["Discovery", Compass],
  ["Daily GTA Gameplay", Search],
  ["Link Studio", Film],
  ["Live Watch", Radio],
  ["Library", Library],
  ["Media & processing", Film],
  ["Outputs", Check],
  ["Integrations", Plug],
  ["Settings", SlidersHorizontal],
];
const icons = {
  youtube: "▶",
  reddit: "r",
  twitch: "▧",
  tiktok: "♪",
  x: "𝕏",
  instagram: "◎",
};
const format = (n) =>
  new Intl.NumberFormat("en", { notation: "compact" }).format(n);
export function Empty({ title, children }) {
  return (
    <div className="empty">
      <Film size={30} />
      <h3>{title}</h3>
      <p>{children}</p>
    </div>
  );
}
export function ErrorNotice({ message }) {
  return message ? (
    <div className="error" role="alert">
      {message}
    </div>
  ) : null;
}
function PlatformIcon({ platform }) {
  return <span className={`platform-icon ${platform}`}>{icons[platform]}</span>;
}
function Pill({ children, green = false }) {
  return <span className={`pill ${green ? "green" : ""}`}>{children}</span>;
}
function ContentCard({ item, onSave }) {
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  async function save() {
    setBusy(true);
    setError("");
    try {
      await api(`/discovery/items/${item.id}/save`, { method: "POST" });
      onSave(item.id);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <article className="content-card">
      <div className={`poster poster-${item.platform}`}>
        {item.thumbnail_url ? (
          <img
            className="source-thumbnail"
            src={item.thumbnail_url}
            alt=""
            loading="lazy"
          />
        ) : (
          <div className="poster-grid" />
        )}
        <span className="poster-label">
          {item.raw_metadata.demo ? "DEMO / CONCEPT FRAME" : "METADATA ONLY"}
        </span>
        <span
          className="poster-word"
          style={item.thumbnail_url ? { display: "none" } : undefined}
        >
          VI<span>LEONIDA ARCHIVE</span>
        </span>
        <span className="duration">{item.duration_seconds ?? "—"} sec</span>
      </div>
      <div className="card-body">
        <div className="card-platform">
          <span>
            <PlatformIcon platform={item.platform} />
            {names[item.platform]}
          </span>
          {item.raw_metadata.demo && <Pill>DEMO</Pill>}
        </div>
        <h3>{item.title}</h3>
        <details className="source-details">
          <summary>Source details</summary>
          <p>{item.description || "User-supplied source metadata."}</p>
          <p>
            {(item.media_access_type || "metadata_only").replaceAll("_", " ")} ·
            reuse permission not verified
          </p>
        </details>
        <p>
          {item.creator_name}{" "}
          <span>· {new Date(item.published_at).toLocaleDateString()}</span>
        </p>
        <div className="card-foot">
          <span>
            {item.view_count == null
              ? "No metrics"
              : `${format(item.view_count)} ${item.raw_metadata.demo ? "sample views" : "views"}`}
          </span>
          <button
            className="icon-button"
            aria-label={
              item.saved ? `Saved: ${item.title}` : `Save: ${item.title}`
            }
            disabled={busy || item.saved}
            onClick={save}
          >
            {item.saved ? <Check size={17} /> : <Bookmark size={17} />}
          </button>
        </div>
        <a
          className="source-link"
          href={item.canonical_url}
          target="_blank"
          rel="noreferrer"
        >
          {item.raw_metadata.demo
            ? "Visit platform (demo)"
            : "Open original source"}
          <ArrowUpRight size={13} />
        </a>
        <ErrorNotice message={error} />
      </div>
    </article>
  );
}
function Dashboard({ go, version }) {
  const [data, setData] = useState(null),
    [sources, setSources] = useState([]),
    [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    Promise.all([api("/stats/overview"), api("/sources")])
      .then(([d, s]) => {
        if (active) {
          setData(d);
          setSources(s);
        }
      })
      .catch((e) => active && setError(e.message));
    return () => {
      active = false;
    };
  }, [version]);
  return (
    <>
      <PageTitle
        eyebrow="YOUR CREATIVE WORKSPACE"
        title="Overview"
        description="From the first discovery to the final cut."
        action={
          <button className="primary" onClick={() => go("Discovery")}>
            <Search size={16} /> Discover content
          </button>
        }
      />
      <ErrorNotice message={error} />
      {!data && !error ? (
        <p role="status">Loading workspace…</p>
      ) : (
        data && (
          <>
            <section className="stats-grid">
              {[
                [
                  "Discovered items",
                  data.discovered_items,
                  Compass,
                  "Across your connected sources",
                ],
                [
                  "Saved to library",
                  data.saved_items,
                  Bookmark,
                  "Collected for a closer look",
                ],
                [
                  "Discovery searches",
                  data.searches,
                  Search,
                  "Your research history",
                ],
                [
                  "Imported media",
                  data.media_assets ?? 0,
                  Film,
                  `${data.processing?.completed ?? 0} completed jobs`,
                ],
              ].map(([label, value, Icon, note]) => (
                <div className="stat" key={label}>
                  <div>
                    {label}
                    <Icon size={17} />
                  </div>
                  <strong>
                    {typeof value === "number" ? format(value) : value}
                  </strong>
                  <p>{note}</p>
                </div>
              ))}
            </section>
            <section className="workspace-banner">
              <div>
                <span className="eyebrow">DISCOVER. COLLECT. CREATE.</span>
                <h2>Your next story starts here.</h2>
                <p>
                  Explore six platforms. Keep the ideas that matter.
                  <br />
                  Build your GTA VI content library in one place.
                </p>
                <button
                  className="light-button"
                  onClick={() => go("Discovery")}
                >
                  Explore content <ArrowRight size={16} />
                </button>
              </div>
              <div className="banner-art" aria-hidden="true">
                <span>VI</span>
                <small>CLIPFORGE / CREATOR STUDIO</small>
              </div>
            </section>
            <div className="dashboard-bottom">
              <section className="panel">
                <div className="section-head">
                  <h2>Recent discoveries</h2>
                  <button
                    className="text-button"
                    onClick={() => go("Discovery")}
                  >
                    View discovery <ArrowUpRight size={14} />
                  </button>
                </div>
                {data.recent_discoveries.length ? (
                  data.recent_discoveries.map((i) => (
                    <div className="recent-row" key={i.id}>
                      <PlatformIcon platform={i.platform} />
                      <div>
                        <strong>{i.title}</strong>
                        <p>
                          {names[i.platform]} · {i.creator_name}
                        </p>
                      </div>
                      {i.raw_metadata.demo && <Pill>DEMO</Pill>}
                    </div>
                  ))
                ) : (
                  <Empty title="A fresh start">
                    Run your first search to fill this space with discoveries.
                  </Empty>
                )}
              </section>
              <section className="panel">
                <div className="section-head">
                  <h2>Source connections</h2>
                  <Radio size={16} />
                </div>
                {sources.map((s) => (
                  <div className="source-row" key={s.platform}>
                    <PlatformIcon platform={s.platform} />
                    <span>{s.display_name}</span>
                    <span className={`status-dot ${s.enabled ? "on" : ""}`} />
                    <small>
                      {!s.enabled
                        ? "Disabled"
                        : s.mode === "mock"
                          ? "Demo ready"
                          : s.status.replaceAll("_", " ")}
                    </small>
                  </div>
                ))}
                <button
                  className="wide-link"
                  onClick={() => go("Integrations")}
                >
                  Manage integrations <ChevronRight size={15} />
                </button>
              </section>
            </div>
          </>
        )
      )}
    </>
  );
}
function PageTitle({ eyebrow, title, description, action }) {
  return (
    <div className="page-title">
      <div>
        <span className="eyebrow">{eyebrow}</span>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {action}
    </div>
  );
}
function Discovery({ onSaved }) {
  const [query, setQuery] = useState("GTA VI"),
    [selected, setSelected] = useState(Object.keys(names)),
    [sort, setSort] = useState("newest"),
    [limit, setLimit] = useState(6),
    [items, setItems] = useState([]),
    [history, setHistory] = useState([]),
    [loading, setLoading] = useState(false),
    [searched, setSearched] = useState(false),
    [error, setError] = useState(""),
    [warnings, setWarnings] = useState([]),
    [page, setPage] = useState(0);
  useEffect(() => {
    api("/discovery/searches")
      .then(setHistory)
      .catch((e) => setError(e.message));
  }, []);
  async function search(e) {
    e.preventDefault();
    setLoading(true);
    setError("");
    setWarnings([]);
    try {
      const r = await api("/discovery/search", {
        method: "POST",
        body: JSON.stringify({
          query,
          platforms: selected,
          sort,
          limit: Number(limit),
        }),
      });
      setItems(r.items);
      setWarnings(r.warnings);
      setSearched(true);
      setPage(0);
      setHistory(await api("/discovery/searches"));
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }
  async function loadHistory(id) {
    if (!id) return;
    setLoading(true);
    setError("");
    try {
      const r = await api(`/discovery/searches/${id}`);
      setItems(r.items);
      setQuery(r.search.query);
      setWarnings(r.search.warnings);
      setSearched(true);
      setPage(0);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }
  function save(id) {
    setItems((v) => v.map((i) => (i.id === id ? { ...i, saved: true } : i)));
    onSaved();
  }
  return (
    <>
      <PageTitle
        eyebrow="FIND YOUR NEXT IDEA"
        title="Discovery"
        description="A wider view of the GTA VI conversation."
      />
      <SourceSubmission />
      <form className="search-panel" onSubmit={search}>
        <div className="search-bar">
          <Search size={20} />
          <input
            aria-label="Search keywords"
            value={query}
            maxLength={200}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search keywords, topics, moments…"
            required
          />
          <button
            className="primary"
            disabled={loading || !selected.length || !query.trim()}
          >
            {loading ? "Searching…" : "Search content"}
            <ArrowRight size={16} />
          </button>
        </div>
        <div className="filter-row">
          <span>Sources</span>
          {Object.entries(names).map(([id, name]) => (
            <button
              type="button"
              key={id}
              className={`filter-chip ${selected.includes(id) ? "selected" : ""}`}
              aria-pressed={selected.includes(id)}
              onClick={() =>
                setSelected((v) =>
                  v.includes(id) ? v.filter((p) => p !== id) : [...v, id],
                )
              }
            >
              <PlatformIcon platform={id} />
              {name}
            </button>
          ))}
        </div>
        <div className="search-options">
          <label>
            Sort{" "}
            <select value={sort} onChange={(e) => setSort(e.target.value)}>
              <option value="newest">Newest first</option>
              <option value="engagement">Most views</option>
            </select>
          </label>
          <label>
            Per source{" "}
            <select value={limit} onChange={(e) => setLimit(e.target.value)}>
              {[6, 12, 24, 50].map((n) => (
                <option key={n}>{n}</option>
              ))}
            </select>
          </label>
          <label>
            History{" "}
            <select
              aria-label="Search history"
              value=""
              onChange={(e) => loadHistory(e.target.value)}
              disabled={loading}
            >
              <option value="">Previous searches</option>
              {history.map((h) => (
                <option value={h.id} key={h.id}>
                  {h.query} · {h.result_count} results
                </option>
              ))}
            </select>
          </label>
        </div>
      </form>
      <ErrorNotice message={error} />
      {warnings.map((w) => (
        <div className="warning" key={w}>
          {w}
        </div>
      ))}
      <div className="section-head">
        <h2>
          {searched
            ? `${items.length} discoveries`
            : "Explore the conversation"}
        </h2>
        <span className="muted">
          Metadata discovery · source files required for editing
        </span>
      </div>
      {loading ? (
        <div className="empty" role="status">
          <RefreshCw className="spin" />
          <p>Searching selected sources…</p>
        </div>
      ) : items.length ? (
        <>
          <div className="content-grid">
            {items.slice(page * 12, page * 12 + 12).map((i) => (
              <ContentCard key={i.id} item={i} onSave={save} />
            ))}
          </div>
          <div className="pagination">
            <button disabled={!page} onClick={() => setPage((p) => p - 1)}>
              Previous
            </button>
            <span>
              Page {page + 1} of {Math.ceil(items.length / 12)}
            </span>
            <button
              disabled={(page + 1) * 12 >= items.length}
              onClick={() => setPage((p) => p + 1)}
            >
              Next
            </button>
          </div>
        </>
      ) : (
        <Empty title={searched ? "No results found" : "Follow your curiosity"}>
          {searched
            ? "Try another search or enable more sources."
            : "Choose your sources and search a topic to start collecting ideas."}
        </Empty>
      )}
    </>
  );
}
function LibraryPage() {
  const [items, setItems] = useState([]),
    [q, setQ] = useState(""),
    [platform, setPlatform] = useState(""),
    [error, setError] = useState(""),
    [loading, setLoading] = useState(true),
    [page, setPage] = useState(0);
  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    api(
      `/clips?q=${encodeURIComponent(q)}&limit=24&offset=${page * 24}${platform ? `&platform=${platform}` : ""}`,
    )
      .then((r) => active && setItems(r))
      .catch((e) => active && setError(e.message))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [q, platform, page]);
  return (
    <>
      <PageTitle
        eyebrow="YOUR CONTENT COLLECTION"
        title="Library"
        description="Ideas you've saved, ready for the next step."
      />
      <div className="library-filters">
        <input
          aria-label="Filter library"
          placeholder="Filter saved discoveries…"
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setPage(0);
          }}
        />
        <select
          aria-label="Filter by platform"
          value={platform}
          onChange={(e) => {
            setPlatform(e.target.value);
            setPage(0);
          }}
        >
          <option value="">All platforms</option>
          {Object.entries(names).map(([p, n]) => (
            <option key={p} value={p}>
              {n}
            </option>
          ))}
        </select>
      </div>
      <div className="info-note">
        Saved discoveries contain source metadata. Import authorized files in
        Media &amp; processing.
      </div>
      <ErrorNotice message={error} />
      {loading ? (
        <p role="status">Loading library…</p>
      ) : items.length ? (
        <div className="content-grid">
          {items.map((i) => (
            <ContentCard key={i.id} item={i} onSave={() => {}} />
          ))}
        </div>
      ) : (
        <Empty title="Nothing saved here yet">
          Save a discovery to keep it in your library.
        </Empty>
      )}
      <div className="pagination">
        <button disabled={!page} onClick={() => setPage((p) => p - 1)}>
          Previous
        </button>
        <span>Page {page + 1}</span>
        <button
          disabled={items.length < 24}
          onClick={() => setPage((p) => p + 1)}
        >
          Next
        </button>
      </div>
    </>
  );
}
function Integrations() {
  const [sources, setSources] = useState(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState("");
  useEffect(() => {
    api("/sources")
      .then(setSources)
      .catch((e) => setError(e.message));
  }, []);
  async function act(s, test) {
    setBusy(s.platform);
    setError("");
    try {
      const r = await api(`/sources/${s.platform}${test ? "/test" : ""}`, {
        method: test ? "POST" : "PATCH",
        ...(!test ? { body: JSON.stringify({ enabled: !s.enabled }) } : {}),
      });
      setSources((v) => v.map((x) => (x.platform === s.platform ? r : x)));
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy("");
    }
  }
  return (
    <>
      <PageTitle
        eyebrow="CONNECTED RESEARCH"
        title="Integrations"
        description="Know what each source can do, and where it stands."
      />
      <ErrorNotice message={error} />
      {!sources && !error ? (
        <p role="status">Loading connectors…</p>
      ) : (
        <div className="integrations-grid">
          {sources?.map((s) => (
            <article className="panel connector" key={s.platform}>
              <div className="section-head">
                <PlatformIcon platform={s.platform} />
                <Pill green={s.enabled && s.status === "connected"}>
                  {s.mode === "mock" && s.enabled
                    ? "DEMO READY"
                    : s.status.replaceAll("_", " ").toUpperCase()}
                </Pill>
              </div>
              <h2>{s.display_name}</h2>
              <p>{s.diagnostic}</p>
              <div className="capabilities">
                {s.capabilities.map((c) => (
                  <span key={c}>
                    <Check size={13} />
                    {c.replaceAll("_", " ")}
                  </span>
                ))}
              </div>
              <p className="setup-note">
                {s.mode === "mock"
                  ? "No credentials needed in demo mode."
                  : "Configure approved API access in .env and restart."}{" "}
                Discovery provides metadata. Import an authorized source file to
                edit.
              </p>
              <div className="connector-actions">
                <button
                  disabled={busy === s.platform}
                  onClick={() => act(s, true)}
                >
                  <RefreshCw size={14} />
                  Test connector
                </button>
                <button
                  aria-label={`${s.enabled ? "Disable" : "Enable"} ${s.display_name}`}
                  aria-pressed={s.enabled}
                  disabled={busy === s.platform}
                  className={s.enabled ? "toggle on" : "toggle"}
                  onClick={() => act(s, false)}
                >
                  <span />
                </button>
              </div>
              {s.last_checked_at && (
                <small className="muted">
                  Checked {new Date(s.last_checked_at).toLocaleTimeString()}
                </small>
              )}
            </article>
          ))}
        </div>
      )}
    </>
  );
}
function Settings() {
  const [data, setData] = useState(null),
    [error, setError] = useState("");
  useEffect(() => {
    api("/system/status")
      .then(setData)
      .catch((e) => setError(e.message));
  }, []);
  return (
    <>
      <PageTitle
        eyebrow="LOCAL WORKSPACE"
        title="Settings"
        description="Configuration stays on your machine."
      />
      <ErrorNotice message={error} />
      {data ? (
        <section className="panel settings-panel">
          <h2>System status</h2>
          {[
            [
              "Application mode",
              data.mode === "mock" ? "Demo / mock adapters" : "Live",
            ],
            ["Database", data.database],
            ["Storage", data.storage],
            ["Configured upload limit", `${data.max_upload_mb} MB`],
            ["Processing worker", data.worker],
            ["Telegram", data.telegram],
            ["AI assistance", data.ai],
            [
              "Caption burn-in",
              data.processing_capabilities?.subtitles
                ? "Available"
                : "Requires FFmpeg with libass",
            ],
          ].map(([k, v]) => (
            <div className="settings-row" key={k}>
              <span>{k}</span>
              <strong>{v}</strong>
            </div>
          ))}
          <div className="info-note">
            Edit the project .env file and restart the backend to change
            configuration. API keys stay on the backend. Workspace protection:{" "}
            {data.authentication}. Keep the app local unless deployed behind
            HTTPS with an access token.
          </div>
        </section>
      ) : (
        !error && <p role="status">Checking system…</p>
      )}
    </>
  );
}
export default function App() {
  const [sourceLink, setSourceLink] = useState("");
  const [page, setPage] = useState("Dashboard"),
    [version, setVersion] = useState(0),
    [mode, setMode] = useState(null);
  useEffect(() => {
    api("/health")
      .then((r) => setMode(r.mode))
      .catch(() => setMode("offline"));
  }, []);
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a
          href="#"
          className="brand"
          onClick={(e) => {
            e.preventDefault();
            setPage("Dashboard");
          }}
        >
          <span className="brand-mark">VI</span>
          <span>
            ClipForge<small>CREATOR WORKSPACE</small>
          </span>
        </a>
        <div className="workspace-label">WORKSPACE</div>
        <nav aria-label="Main navigation">
          {nav.map(([name, Icon]) => (
            <button
              key={name}
              className={page === name ? "active" : ""}
              onClick={() => setPage(name)}
              aria-current={page === name ? "page" : undefined}
            >
              <Icon size={18} />
              {name}
              {page === name && <span className="nav-dot" />}
            </button>
          ))}
        </nav>
        <div className="sidebar-footer">
          <div className="local-status">
            <span className="status-dot on" />
            Local workspace
          </div>
          <p>Built for your next great cut.</p>
          <span className="version">LOCAL STUDIO · v1.0.0</span>
        </div>
      </aside>
      <div className="main-shell">
        <header>
          <div className="breadcrumb">
            Workspace <ChevronRight size={13} />
            <strong>{page}</strong>
          </div>
          <div className="header-right">
            <Pill green={mode === "mock"}>
              {["Live Watch", "Daily GTA Gameplay", "Link Studio"].includes(
                page,
              )
                ? "CONNECTED WORKFLOWS"
                : mode === null
                  ? "CONNECTING"
                  : mode === "mock"
                    ? "DEMO MODE"
                    : mode === "offline"
                      ? "API OFFLINE"
                      : "LIVE MODE"}
            </Pill>
            <span className="avatar">CF</span>
          </div>
        </header>
        <main>
          {mode === "mock" &&
            !["Live Watch", "Daily GTA Gameplay", "Link Studio"].includes(
              page,
            ) && (
              <div className="demo-strip">
                <Radio size={14} />
                <span>
                  Manual discovery is in demo mode. Sample results are labeled
                  DEMO. Live Watch and scheduled discovery use real connections.
                </span>
              </div>
            )}
          {page === "Dashboard" ? (
            <Dashboard go={setPage} version={version} />
          ) : page === "Discovery" ? (
            <Discovery onSaved={() => setVersion((v) => v + 1)} />
          ) : page === "Daily GTA Gameplay" ? (
            <DailyFeed
              onOpenLink={(url) => {
                setSourceLink(url);
                setPage("Link Studio");
              }}
            />
          ) : page === "Link Studio" ? (
            <LinkStudio initialUrl={sourceLink} />
          ) : page === "Live Watch" ? (
            <LiveWatch />
          ) : page === "Library" ? (
            <LibraryPage />
          ) : page === "Media & processing" ? (
            <Processing />
          ) : page === "Outputs" ? (
            <Outputs />
          ) : page === "Integrations" ? (
            <Integrations />
          ) : (
            <Settings />
          )}
          <footer>
            VI CLIPFORGE
            <span>Research with context. Create with permission.</span>
          </footer>
        </main>
      </div>
    </div>
  );
}
