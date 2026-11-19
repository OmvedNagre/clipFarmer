import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { DailyFeed, LinkStudio } from "./ContentStudio";
import { api } from "../api";
vi.mock("../api", () => ({ api: vi.fn() }));
beforeEach(() => {
  vi.clearAllMocks();
  api.mockResolvedValue([]);
});
test("own livestream mode has no permission checkbox", async () => {
  render(<LinkStudio />);
  fireEvent.click(
    screen.getByRole("button", { name: "My livestream highlights" }),
  );
  expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Find my stream highlights" }),
  ).toBeEnabled();
  fireEvent.change(screen.getByLabelText("Video or recording URL"), {
    target: { value: "https://youtu.be/Z0CPIt32Ux0" },
  });
  api.mockImplementation((path, options) =>
    Promise.resolve(options?.method === "POST" ? { id: "job" } : []),
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Find my stream highlights" }),
  );
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith(
      "/links",
      expect.objectContaining({ method: "POST" }),
    ),
  );
  expect(
    JSON.parse(api.mock.calls.find(([, o]) => o?.method === "POST")[1].body)
      .mode,
  ).toBe("stream");
});
test("normal video download requires source permission", async () => {
  render(<LinkStudio />);
  await screen.findByText("No link jobs yet.");
  expect(screen.getByRole("button", { name: "Fetch video" })).toBeDisabled();
  fireEvent.click(screen.getByRole("checkbox"));
  expect(screen.getByRole("button", { name: "Fetch video" })).toBeEnabled();
});
test("daily feed shows split target and midnight schedule", async () => {
  api.mockResolvedValue({
    config: {
      enabled: true,
      attachments: true,
      approved_creators: [],
      next_run_at: "2026-11-17T18:30:00Z",
      heartbeat_at: null,
    },
    runs: [],
    items: [],
  });
  render(<DailyFeed onOpenLink={() => {}} />);
  expect(await screen.findByText("First feed pending")).toBeInTheDocument();
  expect(
    screen.getByText(/Runs at 12:00 AM Asia\/Kolkata/),
  ).toBeInTheDocument();
  expect(screen.getByText("Face detected · 0/10")).toBeInTheDocument();
  expect(screen.getByText("No face detected · 0/10")).toBeInTheDocument();
});
