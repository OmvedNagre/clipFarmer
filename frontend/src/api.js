export async function api(path, options = {}) {
  const response = await fetch(`/api/v1${path}`, {
    ...options,
    headers: { "Content-Type": "application/json", ...options.headers },
  });
  const data = await response.json();
  if (!response.ok)
    throw new Error(data.error?.message || "Request failed. Try again.");
  return data;
}
export const names = {
  youtube: "YouTube",
  reddit: "Reddit",
  twitch: "Twitch",
  tiktok: "TikTok",
  x: "X",
  instagram: "Instagram",
};
