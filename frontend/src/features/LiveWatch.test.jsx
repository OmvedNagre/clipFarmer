import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import LiveWatch from "./LiveWatch";
import { api } from "../api";
vi.mock("../api", () => ({ api: vi.fn() }));
beforeEach(() => {
  vi.clearAllMocks();
  api.mockImplementation((path) =>
    Promise.resolve(path === "/watch/status" ? {} : []),
  );
});
test("shows live requirements and requires creator authorization", async () => {
  render(<LiveWatch />);
  expect(
    await screen.findByText("YouTube API: key needed"),
  ).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Start watch" })).toBeDisabled();
  fireEvent.click(
    screen.getByLabelText(
      "This creator has authorized me to capture and reuse this stream.",
    ),
  );
  expect(screen.getByRole("button", { name: "Start watch" })).toBeEnabled();
});
test("queues a watch with creator provenance", async () => {
  api.mockImplementation((path, options) =>
    Promise.resolve(
      options?.method === "POST"
        ? { id: "watch" }
        : path === "/watch/status"
          ? {}
          : [],
    ),
  );
  render(<LiveWatch />);
  fireEvent.change(screen.getByLabelText("Live-stream URL"), {
    target: { value: "https://www.youtube.com/watch?v=Z0CPIt32Ux0" },
  });
  fireEvent.change(screen.getByLabelText("Platform creator ID"), {
    target: { value: "UC_authorized" },
  });
  fireEvent.change(screen.getByLabelText("Creator credit"), {
    target: { value: "Creator" },
  });
  fireEvent.change(screen.getByLabelText("Permission record"), {
    target: { value: "Written permission" },
  });
  fireEvent.click(
    screen.getByLabelText(
      "This creator has authorized me to capture and reuse this stream.",
    ),
  );
  fireEvent.click(screen.getByRole("button", { name: "Start watch" }));
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith(
      "/watch/sessions",
      expect.objectContaining({ method: "POST" }),
    ),
  );
  const call = api.mock.calls.find(([, o]) => o?.method === "POST");
  expect(JSON.parse(call[1].body).creator_id).toBe("UC_authorized");
});
test("reports a connection failure without claiming a successful watch", async () => {
  api.mockRejectedValue(new Error("Connection unavailable"));
  render(<LiveWatch />);
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Connection unavailable",
  );
});
