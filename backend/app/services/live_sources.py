"""Official metadata/chat APIs. Capture receives only canonical public platform URLs."""

import socket
import ssl
from datetime import datetime
from urllib.parse import parse_qs, urlparse

import httpx

from app.core.config import get_settings


class LiveError(Exception):
    def __init__(self, message, terminal=False):
        self.terminal = terminal
        super().__init__(message)


def request(url, **kwargs):
    try:
        response = httpx.get(url, timeout=15, follow_redirects=False, **kwargs)
        if response.status_code in {401, 403}:
            raise LiveError(
                "Platform access denied or quota exhausted. Check credentials and quota before restarting.",
                True,
            )
        if response.status_code == 429:
            raise LiveError("Platform rate limit reached; retrying with backoff")
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError):
        raise LiveError("Platform request failed; retrying with backoff") from None


class YouTubeLive:
    def __init__(self, row):
        self.key = get_settings().youtube_api_key.get_secret_value()
        if not self.key:
            raise LiveError(
                "Set YOUTUBE_API_KEY in the server environment, then create a new watch.", True
            )
        self.video = parse_qs(urlparse(row.source_url).query)["v"][0]
        self.creator = row.creator_id
        self.chat = None
        self.page = None
        self.initial = True

    def live(self):
        data = request(
            "https://www.googleapis.com/youtube/v3/videos",
            params={"key": self.key, "id": self.video, "part": "snippet,liveStreamingDetails"},
        )
        if not data.get("items"):
            raise LiveError("Video is unavailable or private", True)
        item = data["items"][0]
        if item["snippet"]["channelId"] != self.creator:
            raise LiveError("Video owner does not match the authorized creator ID", True)
        details = item.get("liveStreamingDetails", {})
        if details.get("actualEndTime"):
            raise LiveError(
                "This live stream has ended. Import an authorized recording instead.", True
            )
        if not details.get("actualStartTime"):
            return False
        self.chat = details.get("activeLiveChatId")
        if not self.chat:
            raise LiveError(
                "Live chat is disabled or unavailable; reaction detection needs live chat", True
            )
        return True

    def messages(self):
        params = {
            "key": self.key,
            "liveChatId": self.chat,
            "part": "snippet,authorDetails",
            "maxResults": 2000,
        }
        if self.page:
            params["pageToken"] = self.page
        data = request("https://www.googleapis.com/youtube/v3/liveChat/messages", params=params)
        self.page = data.get("nextPageToken")
        delay = max(1, data.get("pollingIntervalMillis", 5000) / 1000)
        if data.get("offlineAt"):
            raise LiveError("Stream chat ended", True)
        # The first response can include chat from before capture; start at the live edge.
        if self.initial:
            self.initial = False
            return [], delay
        messages = []
        for item in data.get("items", []):
            snippet = item.get("snippet", {})
            if snippet.get("type") != "textMessageEvent":
                continue
            messages.append(
                (
                    datetime.fromisoformat(
                        snippet["publishedAt"].replace("Z", "+00:00")
                    ).timestamp(),
                    item["authorDetails"]["channelId"],
                    snippet.get("displayMessage", ""),
                )
            )
        return messages, delay

    def close(self):
        pass


class TwitchLive:
    """Authenticated, read-only IRC over TLS; no anonymous or account-bypass fallback."""

    def __init__(self, row):
        s = get_settings()
        self.token = s.twitch_user_token.get_secret_value()
        self.login = s.twitch_chat_login
        self.client_id = s.twitch_client_id
        self.creator = row.creator_id
        self.channel = urlparse(row.source_url).path.strip("/")
        self.sock = None
        self.buffer = ""
        if not self.token or not self.login or not self.client_id:
            raise LiveError(
                "Configure TWITCH_CLIENT_ID, TWITCH_USER_TOKEN and TWITCH_CHAT_LOGIN before restarting.",
                True,
            )
        if not self.login.replace("_", "").isalnum():
            raise LiveError("Invalid Twitch chat login configuration", True)

    def live(self):
        headers = {"Authorization": f"Bearer {self.token}", "Client-Id": self.client_id}
        users = request(
            "https://api.twitch.tv/helix/users", headers=headers, params={"login": self.channel}
        )
        if not users.get("data") or users["data"][0]["id"] != self.creator:
            raise LiveError("Channel does not match the authorized Twitch user ID", True)
        data = request(
            "https://api.twitch.tv/helix/streams", headers=headers, params={"user_id": self.creator}
        )
        return bool(data.get("data"))

    def messages(self):
        if self.sock is None:
            raw = socket.create_connection(("irc.chat.twitch.tv", 6697), timeout=15)
            self.sock = ssl.create_default_context().wrap_socket(
                raw, server_hostname="irc.chat.twitch.tv"
            )
            self.sock.settimeout(1)
            self.sock.sendall(
                (
                    f"PASS oauth:{self.token}\r\nNICK {self.login}\r\n"
                    f"CAP REQ :twitch.tv/tags twitch.tv/commands\r\nJOIN #{self.channel}\r\n"
                ).encode()
            )
        try:
            data = self.sock.recv(65536)
        except TimeoutError:
            return [], 0.2
        if not data:
            raise LiveError("Twitch chat disconnected")
        self.buffer += data.decode("utf-8", errors="replace")
        if len(self.buffer) > 262144:
            raise LiveError("Twitch chat frame exceeded limit", True)
        messages = []
        while "\r\n" in self.buffer:
            line, self.buffer = self.buffer.split("\r\n", 1)
            if line.startswith("PING "):
                self.sock.sendall((line.replace("PING", "PONG", 1) + "\r\n").encode())
            if "Login authentication failed" in line or "Improperly formatted auth" in line:
                raise LiveError("Twitch chat authentication failed; replace the user token", True)
            if " RECONNECT" in line:
                raise LiveError("Twitch requested a reconnect")
            if " PRIVMSG " not in line or not line.startswith("@"):
                continue
            tags = dict(x.split("=", 1) for x in line.split(" ", 1)[0][1:].split(";") if "=" in x)
            if tags.get("tmi-sent-ts") and tags.get("user-id"):
                text = line.split(" PRIVMSG ", 1)[1].split(" :", 1)[-1]
                messages.append((int(tags["tmi-sent-ts"]) / 1000, tags["user-id"], text))
        return messages, 0.2

    def close(self):
        if self.sock:
            self.sock.close()
            self.sock = None
