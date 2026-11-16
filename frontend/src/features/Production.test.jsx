import {
  render,
  screen,
  fireEvent,
  waitFor,
  cleanup,
} from "@testing-library/react";
import { vi } from "vitest";
import { Processing, Outputs } from "./Production";
import AuthGate from "../components/AuthGate";
const response = (data) =>
  Promise.resolve({ ok: true, json: () => Promise.resolve(data) });
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
it("shows media import controls and durable queue empty state", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn((url) =>
      response(
        url.includes("/system/status")
          ? {
              max_upload_mb: 500,
              worker: "running",
              processing_capabilities: { ffmpeg: true, subtitles: false },
            }
          : [],
      ),
    ),
  );
  render(<Processing />);
  expect(await screen.findByText("No media here yet")).toBeInTheDocument();
  expect(screen.getByLabelText("Video file")).toBeInTheDocument();
  expect(screen.getByText("No processing jobs yet")).toBeInTheDocument();
});
it("surfaces a failed job with retry and error history", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn((url) =>
      response(
        url.includes("/system/status")
          ? { processing_capabilities: { ffmpeg: true }, worker: "running" }
          : url.includes("/processing/jobs")
            ? [
                {
                  id: "job",
                  media_asset_id: "mediaid",
                  status: "failed",
                  progress_percent: 5,
                  attempt_count: 1,
                  max_attempts: 3,
                  retryable: true,
                  error_message: "Processing timed out.",
                  options: { profiles: ["original"] },
                },
              ]
            : [],
      ),
    ),
  );
  render(<Processing />);
  expect(await screen.findByText("Processing timed out.")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Retry" })).toBeEnabled();
});
it("requires review before showing output download", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn((url) =>
      response(
        url.endsWith("/outputs")
          ? [
              {
                id: "output",
                processing_job_id: "job",
                profile: "original",
                filename: "clip.mp4",
                width: 320,
                height: 180,
                duration_seconds: 1,
                size_bytes: 1000,
                video_codec: "h264",
                audio_codec: "aac",
                media: {
                  id: "asset",
                  original_filename: "source.mp4",
                  review_status: "pending",
                  publishing_metadata: {},
                },
              },
            ]
          : [],
      ),
    ),
  );
  render(<Outputs />);
  expect(await screen.findByRole("button", { name: "Approve" })).toBeEnabled();
  expect(
    screen.getByRole("button", { name: "Approve to download" }),
  ).toBeDisabled();
  expect(screen.getByRole("button", { name: "Telegram" })).toBeDisabled();
});
it("unlocks a protected workspace without exposing the token in a URL", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn((url, opts) =>
      response(
        url.endsWith("/auth/status")
          ? { required: true, authenticated: false }
          : { authenticated: true },
      ),
    ),
  );
  render(
    <AuthGate>
      <p>Studio ready</p>
    </AuthGate>,
  );
  fireEvent.change(await screen.findByLabelText("Workspace access token"), {
    target: { value: "secret" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Unlock" }));
  expect(await screen.findByText("Studio ready")).toBeInTheDocument();
  expect(fetch).toHaveBeenCalledWith(
    "/api/v1/auth/login",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ token: "secret" }),
    }),
  );
});

it("keeps the workspace locked after a rejected login and shows the error", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn((url) =>
      url.endsWith("/auth/status")
        ? response({ required: true, authenticated: false })
        : Promise.resolve({
            ok: false,
            json: () =>
              Promise.resolve({
                error: { message: "Invalid workspace access token." },
              }),
          }),
    ),
  );
  render(
    <AuthGate>
      <p>Private studio</p>
    </AuthGate>,
  );
  fireEvent.change(await screen.findByLabelText("Workspace access token"), {
    target: { value: "wrong" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Unlock" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Invalid workspace access token.",
  );
  expect(screen.queryByText("Private studio")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Unlock" })).toBeEnabled();
});

it("shows an upload failure and lets the user retry", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn((url) =>
      response(
        url.includes("/system/status")
          ? {
              max_upload_mb: 500,
              worker: "running",
              processing_capabilities: { ffmpeg: true, subtitles: false },
            }
          : [],
      ),
    ),
  );
  class FailedUpload {
    constructor() {
      this.upload = {};
      this.status = 413;
      this.responseText = JSON.stringify({
        error: { message: "File exceeds the upload limit." },
      });
    }
    open() {}
    send() {
      queueMicrotask(() => this.onload());
    }
  }
  vi.stubGlobal("XMLHttpRequest", FailedUpload);
  render(<Processing />);
  await screen.findByText("No media here yet");
  fireEvent.change(screen.getByLabelText("Video file"), {
    target: { files: [new File(["test"], "test.mp4", { type: "video/mp4" })] },
  });
  fireEvent.change(screen.getByLabelText("Media rights"), {
    target: { value: "user_owned" },
  });
  fireEvent.submit(
    screen.getByRole("button", { name: "Import & inspect" }).closest("form"),
  );
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "File exceeds the upload limit.",
  );
  expect(
    screen.getByRole("button", { name: "Import & inspect" }),
  ).toBeEnabled();
});
