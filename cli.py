from BTSpeak import dialogs 
#from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

from config import ConfigError, load_config, save_config
from api import ApiError
from mastodon import MastodonClient, authorize_in_browser, register_app
from render import (
    account_name,
    notification_links,
    notification_reply_target,
    render_notification,
    render_status,
    status_links,
    status_reply_target,
)


BACK_CHOICE = "Back"
LOAD_NEXT_CHOICE = "Load Next"


@dataclass(frozen=True)
class TimelineChoice:
    label: str
    links: list[str]
    reply_to_id: str
    reply_to_acct: str
    boost_id: str
    page_id: str


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        return menu()

    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        return args.func(args)
    except (ApiError, ConfigError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="btmastodon",
        description="A braille-first Mastodon terminal client.",
    )
    subcommands = parser.add_subparsers(required=True)

    login_parser = subcommands.add_parser("login", help="Log in to a Mastodon instance")
    login_parser.add_argument("instance", help="Instance host, for example mastodon.social")
    login_parser.set_defaults(func=login)

    whoami_parser = subcommands.add_parser("whoami", help="Show the logged-in account")
    whoami_parser.set_defaults(func=whoami)

    timeline_parser = subcommands.add_parser("timeline", help="Read the home timeline")
    timeline_parser.add_argument("--limit", type=bounded_limit, default=20)
    timeline_parser.set_defaults(func=timeline)

    notifications_parser = subcommands.add_parser("notifications", help="Read notifications")
    notifications_parser.add_argument("--limit", type=bounded_limit, default=20)
    notifications_parser.set_defaults(func=notifications)

    post_parser = subcommands.add_parser("post", help="Post a status")
    post_parser.add_argument("status", help="Status text to post")
    post_parser.add_argument(
        "--visibility",
        choices=["public", "unlisted", "private", "direct"],
        default="public",
    )
    post_parser.set_defaults(func=post)

    boost_parser = subcommands.add_parser("boost", help="Boost a status")
    boost_parser.add_argument("status_id", help="Status ID to boost")
    boost_parser.set_defaults(func=boost)

    return parser


def menu() -> int:
    while True:
        #print()
        #dialogs.showMessage("""BTMastodon menu
        #1. Login
        #2. View home timeline
        #3. View notifications
        #4. View logged-in account
        #5. Post a status
        #q. Quit""")
        try:                        
            choices=["Login","Home Timeline","Notifications","Post Status","Quit"]
            choice = dialogs.request_choice(choices,"Welcome to Mastodon")
            if choice==None:
                return 0
            choice=choice.label.strip().lower()
        except EOFError:
            print("Goodbye.")
            return 0

        if choice in {"q", "quit", "exit"}:
            dialogs.showMessage("Goodbye.")
            return 0

        try:
            if choice == "login":
                instance = dialogs.request_input("Instance host, for example mastodon.social: ")
                login(argparse.Namespace(instance=instance))
            elif choice == "home timeline":
                timeline(argparse.Namespace(limit=20))
            elif choice == "notifications":
                notifications(argparse.Namespace(limit=20))
            elif choice == "4":
                whoami(argparse.Namespace())
            elif choice == "post status":
                status = prompt_required("Status text: ")
                visibility = prompt_visibility()
                post(argparse.Namespace(status=status, visibility=visibility))
            else:
                print("Unknown choice.")
        except EOFError:
            print("Goodbye.")
            return 0
        except (ApiError, ConfigError, RuntimeError, ValueError, argparse.ArgumentTypeError) as exc:
            print(f"error: {exc}", file=sys.stderr)


def prompt(label: str) -> str:
    return dialogs.request_input(label)


def prompt_required(label: str) -> str:
    value = prompt(label).strip()
    if not value:
        raise ValueError("A value is required")
    return value


def menu_limit() -> int:
    raw = prompt("Limit 1-40, default 20: ").strip()
    if not raw:
        return 20
    return bounded_limit(raw)


def prompt_visibility() -> str:
    choices = ["Public", "Unlisted", "Private", "Direct"]
    return dialogs.request_choice(choices, "Visibility").label.strip().lower()


def login(args: argparse.Namespace) -> int:
    credentials = register_app(args.instance)
    config = authorize_in_browser(args.instance, credentials)
    path = save_config(config)
    dialogs.showMessage(f"Logged in. Config saved to {path}")
    return 0


def whoami(_: argparse.Namespace) -> int:
    client = MastodonClient(load_config())
    account = client.verify_account()
    print(account_name(account))
    note = account.get("note")
    if note:
        from .render import plain_text

        rendered_note = plain_text(str(note))
        if rendered_note:
            print(rendered_note)
    return 0


def timeline(args: argparse.Namespace) -> int:
    client = MastodonClient(load_config())
    statuses = client.home_timeline(args.limit)
    show_home_timeline_menu(client, statuses, args.limit)
    return 0


def notifications(args: argparse.Namespace) -> int:
    client = MastodonClient(load_config())
    items = client.notifications(args.limit)
    show_timeline_menu(
        client,
        [
            timeline_choice_from_notification(item, index)
            for index, item in enumerate(items, 1)
        ],
        "Notifications",
    )
    return 0


def post(args: argparse.Namespace) -> int:
    client = MastodonClient(load_config())
    status = client.post_status(
        args.status,
        args.visibility,
        getattr(args, "in_reply_to_id", None),
    )
    dialogs.showMessage(f"Posted:\n{render_status(status)}")
    return 0


def boost(args: argparse.Namespace) -> int:
    client = MastodonClient(load_config())
    status = client.boost_status(args.status_id)
    dialogs.showMessage(f"Boosted:\n{render_status(status)}")
    return 0


def timeline_choice_from_status(status: dict, index: int) -> TimelineChoice:
    reply_to_id, reply_to_acct = status_reply_target(status)
    return TimelineChoice(
        render_status(status, index),
        status_links(status),
        reply_to_id,
        reply_to_acct,
        reply_to_id,
        str(status.get("id") or ""),
    )


def timeline_choice_from_notification(notification: dict, index: int) -> TimelineChoice:
    reply_to_id, reply_to_acct = notification_reply_target(notification)
    return TimelineChoice(
        render_notification(notification, index),
        notification_links(notification),
        reply_to_id,
        reply_to_acct,
        reply_to_id,
        "",
    )


def show_home_timeline_menu(
    client: MastodonClient,
    statuses: list[dict],
    limit: int,
) -> None:
    items = [
        timeline_choice_from_status(status, index)
        for index, status in enumerate(statuses, 1)
    ]

    while True:
        choice = request_timeline_choice(
            items,
            "Home Timeline",
            include_load_next=True,
            load_next_count=limit,
        )
        if choice is None:
            return
        if choice == LOAD_NEXT_CHOICE:
            max_id = last_page_id(items)
            if not max_id:
                dialogs.showMessage("No more timeline items to load.")
                continue

            next_statuses = client.home_timeline(limit, max_id=max_id)
            if not next_statuses:
                dialogs.showMessage("No more timeline items to load.")
                continue

            items = [
                timeline_choice_from_status(status, index)
                for index, status in enumerate(next_statuses, 1)
            ]
            continue

        open_timeline_choice(client, choice)


def show_timeline_menu(
    client: MastodonClient,
    items: list[TimelineChoice],
    title: str,
) -> None:
    while True:
        choice = request_timeline_choice(items, title)
        if choice is None:
            return
        open_timeline_choice(client, choice)


def request_timeline_choice(
    items: list[TimelineChoice],
    title: str,
    include_load_next: bool = False,
    load_next_count: int | None = None,
) -> TimelineChoice | str | None:
    if not items and not include_load_next:
        dialogs.showMessage(f"No {title.lower()} to show.")
        return None

    by_label = {(item.label or "(empty)"): item for item in items}
    choices = list(by_label)
    if include_load_next:
        if load_next_count is None:
            choices.append(LOAD_NEXT_CHOICE)
        else:
            choices.append(f"{LOAD_NEXT_CHOICE} {load_next_count}")
    choices.append(BACK_CHOICE)

    choice = dialogs.request_choice(choices, title)
    if choice is None:
        return None
    label = choice.label
    normalized = label.strip().lower()
    if normalized == BACK_CHOICE.lower():
        return None
    if normalized.startswith(LOAD_NEXT_CHOICE.lower()):
        return LOAD_NEXT_CHOICE
    return by_label.get(label)


def last_page_id(items: list[TimelineChoice]) -> str:
    for item in reversed(items):
        if item.page_id:
            return item.page_id
    return ""


def open_timeline_choice(client: MastodonClient, item: TimelineChoice) -> None:
    actions = []
    if item.links:
        actions.append("Open Link")
    if item.reply_to_id:
        actions.append("Reply")
    if item.boost_id:
        actions.append("Boost")
    actions.extend(["View Conversation", BACK_CHOICE])

    choice = dialogs.request_choice(actions, "Toot Actions")
    if choice is None:
        return
    choice = choice.label.strip().lower()
    if choice == "open link":
        open_timeline_links(item.links)
    elif choice == "reply":
        reply_to_toot(item)
    elif choice == "boost":
        boost_toot(client, item)
    elif choice == "view conversation":
        view_conversation(client, item)


def open_timeline_links(links: list[str]) -> None:
    if not links:
        return
    if len(links) == 1:
        open_url_in_desktop(links[0])
        return

    choices = links + [BACK_CHOICE]
    while True:
        choice = dialogs.request_choice(choices, "Open Link")
        if choice is None:
            return
        choice = choice.label
        if choice.strip().lower() == BACK_CHOICE.lower():
            return
        
        open_url_in_desktop(choice)


def reply_to_toot(item: TimelineChoice) -> None:
    if not item.reply_to_id:
        dialogs.showMessage("This item cannot be replied to.")
        return

    mention = account_mention(item.reply_to_acct)
    reply = prompt_required(f"Reply {mention}: " if mention else "Reply: ")
    if mention and not reply_mentions_account(reply, mention):
        reply = f"{mention} {reply}"
    visibility = prompt_visibility()
    post(
        argparse.Namespace(
            status=reply,
            visibility=visibility,
            in_reply_to_id=item.reply_to_id,
        )
    )


def boost_toot(client: MastodonClient, item: TimelineChoice) -> None:
    if not item.boost_id:
        dialogs.showMessage("This item cannot be boosted.")
        return

    status = client.boost_status(item.boost_id)
    dialogs.showMessage(f"Boosted:\n{render_status(status)}")


def account_mention(acct: str) -> str:
    acct = acct.strip().lstrip("@")
    if not acct:
        return ""
    return f"@{acct}"


def reply_mentions_account(reply: str, mention: str) -> bool:
    return mention.lower() in reply.lower().split()


def view_conversation(client: MastodonClient, item: TimelineChoice) -> None:
    if not item.reply_to_id:
        dialogs.showMessage(item.label)
        return

    context = client.status_context(item.reply_to_id)
    ancestors = context_statuses(context, "ancestors")
    descendants = context_statuses(context, "descendants")

    conversation_items: list[TimelineChoice] = []
    conversation_items.extend(
        timeline_choice_from_status(status, index)
        for index, status in enumerate(ancestors, 1)
    )
    conversation_items.append(item)
    conversation_items.extend(
        timeline_choice_from_status(status, index)
        for index, status in enumerate(descendants, len(conversation_items) + 1)
    )

    show_timeline_menu(client, conversation_items, "Conversation")


def context_statuses(context: dict, key: str) -> list[dict]:
    statuses = context.get(key)
    if not isinstance(statuses, list):
        return []
    return [status for status in statuses if isinstance(status, dict)]


def open_url_in_desktop(url: str) -> None:
    try:
        from BTSpeak import terminal, web_search

        dialogs.stopActivityIndicator()
        dialogs.clearScreen()
        dialogs.show_message("Opening link in desktop mode.")
        terminal.switch_and_wait(terminal.TARGET_DESKTOP)
        web_search.open_url(url)
    except ImportError:
        print(url)


def bounded_limit(raw: str) -> int:
    try:
        value = int(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("limit must be a number") from exc
    if value < 1 or value > 40:
        raise argparse.ArgumentTypeError("limit must be between 1 and 40")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
