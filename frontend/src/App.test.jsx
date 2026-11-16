import {
  render,
  screen,
  fireEvent,
  waitFor,
  cleanup,
} from "@testing-library/react";
import App from "./App";
import { vi } from "vitest";
const respond = (data) =>
  Promise.resolve({ ok: true, json: () => Promise.resolve(data) });
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});
function mockApi(searchResponse) {
  vi.stubGlobal(
    "fetch",
    vi.fn((url, opts) => {
      if (url.endsWith("/health")) return respond({ mode: "mock" });
      if (url.endsWith("/stats/overview"))
        return respond({
          discovered_items: 0,
          saved_items: 0,
          searches: 0,
          recent_discoveries: [],
        });
      if (url.endsWith("/sources") || url.endsWith("/discovery/searches"))
        return respond([]);
      if (url.endsWith("/discovery/search")) return searchResponse();
      return respond({});
    }),
  );
}
it("renders API metrics, empty state and demo disclosure", async () => {
  mockApi(() => respond({}));
  render(<App />);
  expect(await screen.findByText("A fresh start")).toBeInTheDocument();
  expect(screen.getByText("DEMO MODE")).toBeInTheDocument();
  expect(screen.getByText("Saved to library")).toBeInTheDocument();
});
it("renders loading and failed searches with actionable message", async () => {
  mockApi(() =>
    Promise.resolve({
      ok: false,
      json: () =>
        Promise.resolve({
          error: { message: "Connector unavailable. Try again." },
        }),
    }),
  );
  render(<App />);
  fireEvent.click(screen.getByRole("button", { name: "Discovery" }));
  fireEvent.click(screen.getByRole("button", { name: /Search content/ }));
  expect(screen.getByRole("status")).toHaveTextContent("Searching");
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Connector unavailable",
  );
});
it("searches selected sources and shows an empty successful response", async () => {
  mockApi(() => respond({ items: [], warnings: [] }));
  render(<App />);
  fireEvent.click(screen.getByRole("button", { name: "Discovery" }));
  fireEvent.click(screen.getByRole("button", { name: /Search content/ }));
  expect(await screen.findByText("No results found")).toBeInTheDocument();
  expect(fetch).toHaveBeenCalledWith(
    "/api/v1/discovery/search",
    expect.objectContaining({
      method: "POST",
      body: expect.stringContaining("GTA VI"),
    }),
  );
});
it("shows normalized results and saves to library", async () => {
  mockApi(() =>
    respond({
      warnings: [],
      items: [
        {
          id: "one",
          platform: "youtube",
          title: "Demo video",
          creator_name: "Demo creator",
          published_at: "2026-01-01",
          duration_seconds: 30,
          view_count: 1200,
          raw_metadata: { demo: true },
          canonical_url: "https://www.youtube.com/",
          saved: false,
        },
      ],
    }),
  );
  render(<App />);
  fireEvent.click(screen.getByRole("button", { name: "Discovery" }));
  fireEvent.click(screen.getByRole("button", { name: /Search content/ }));
  expect(await screen.findByText("Demo video")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Save: Demo video" }));
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "Saved: Demo video" }),
    ).toBeDisabled(),
  );
});
