from __future__ import annotations

import re
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urlparse


TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"[ \t\r\f\v]+")
BLANK_LINE_RE = re.compile(r"\n{3,}")


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        for name, value in attrs:
            if name.lower() == "href" and value:
                self.links.append(unescape(value))


def plain_text(html: str | None) -> str:
    if not html:
        return ""
    text = html.replace("</p>", "\n").replace("<br />", "\n").replace("<br>", "\n")
    text = TAG_RE.sub("", text)
    text = unescape(text)
    text = SPACE_RE.sub(" ", text)
    text = BLANK_LINE_RE.sub("\n\n", text)
    return text.strip()


def html_links(html: str | None) -> list[str]:
    if not html:
        return []
    parser = _LinkParser()
    parser.feed(html)
    return unique_urls(parser.links)


def status_links(status: dict) -> list[str]:
    source = status.get("reblog") or status
    urls: list[str] = []
    urls.extend(html_links(str(source.get("content") or "")))

    card = source.get("card")
    if isinstance(card, dict):
        urls.append(str(card.get("url") or ""))

    attachments = source.get("media_attachments") or []
    for attachment in attachments:
        if isinstance(attachment, dict):
            urls.append(str(attachment.get("url") or attachment.get("remote_url") or ""))

    urls.append(str(source.get("url") or source.get("uri") or ""))
    return unique_urls(urls)


def notification_links(notification: dict) -> list[str]:
    status = notification.get("status")
    if isinstance(status, dict):
        return status_links(status)

    account = notification.get("account")
    if isinstance(account, dict):
        return unique_urls([str(account.get("url") or account.get("uri") or "")])
    return []


def status_reply_target(status: dict) -> tuple[str, str]:
    source = status.get("reblog") or status
    status_id = str(source.get("id") or "")
    account = source.get("account")
    if isinstance(account, dict):
        acct = str(account.get("acct") or account.get("username") or "")
    else:
        acct = ""
    return status_id, acct


def notification_reply_target(notification: dict) -> tuple[str, str]:
    status = notification.get("status")
    if isinstance(status, dict):
        return status_reply_target(status)
    return "", ""


def unique_urls(urls: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for url in urls:
        url = url.strip()
        if not is_web_url(url) or url in seen:
            continue
        seen.add(url)
        unique.append(url)
    return unique


def is_web_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def account_name(account: dict) -> str:
    display_name = plain_text(str(account.get("display_name") or ""))
    acct = str(account.get("acct") or account.get("username") or "unknown")
    if display_name:
        return f"{display_name} @{acct}"
    return f"@{acct}"


def render_status(status: dict, index: int | None = None) -> str:
    source = status.get("reblog") or status
    account = source.get("account") or {}
    prefix = f"{index}. " if index is not None else ""
    lines = [
        f"{prefix}{account_name(account)}",
        plain_text(str(source.get("content") or "")),
    ]

    spoiler = plain_text(str(source.get("spoiler_text") or ""))
    if spoiler:
        lines.insert(1, f"content warning: {spoiler}")

    attachments = source.get("media_attachments") or []
    if attachments:
        lines.append(f"attachments: {len(attachments)}")

    if status.get("reblog"):
        booster = account_name(status.get("account") or {})
        lines.append(f"boosted by {booster}")

    published = relative_time(str(source.get("created_at") or ""))
    if published:
        lines.append(f"published {published}")

    return "\n".join(line for line in lines if line).strip()


def render_notification(notification: dict, index: int | None = None) -> str:
    prefix = f"{index}. " if index is not None else ""
    kind = str(notification.get("type") or "notification")
    account = account_name(notification.get("account") or {})
    lines = [f"{prefix}{kind} from {account}"]
    status = notification.get("status")
    if isinstance(status, dict):
        lines.append(plain_text(str(status.get("content") or "")))
        published = relative_time(str(status.get("created_at") or ""))
        if published:
            lines.append(f"published {published}")
    return "\n".join(line for line in lines if line).strip()


def relative_time(value: str) -> str:
    published = parse_datetime(value)
    if published is None:
        return ""

    now = datetime.now(timezone.utc)
    seconds = int((now - published).total_seconds())
    if seconds < 0:
        return "just now"
    if seconds < 45:
        return "just now"
    if seconds < 90:
        return "about a minute ago"

    minutes = seconds // 60
    if minutes < 45:
        return f"{minutes} minutes ago"
    if minutes < 90:
        return "about an hour ago"

    hours = minutes // 60
    if hours < 24:
        return f"about {hours} hours ago"
    if hours < 42:
        return "about a day ago"

    days = hours // 24
    if days < 30:
        return f"{days} days ago"
    if days < 45:
        return "about a month ago"
    if days < 365:
        months = days // 30
        return f"{months} months ago"
    if days < 545:
        return "about a year ago"

    years = days // 365
    return f"over {years} years ago"


def parse_datetime(value: str) -> datetime | None:
    value = value.strip()
    if not value:
        return None
    if value.endswith("Z"):
        value = f"{value[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
