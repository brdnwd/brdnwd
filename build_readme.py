#!/usr/bin/env python3
"""
Build the dynamic portions of the brdnwd profile README.

The GitHub Action supplies GITHUB_TOKEN. No third-party Python packages
are required.
"""

from __future__ import annotations

import email.utils
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

USERNAME = "brdnwd"
README = Path("readme.md")
PROJECT_DIR = Path("profile/projects")
YOUTUBE_HANDLE = "BrandyBeeers"
YOUTUBE_URL = f"https://www.youtube.com/@{YOUTUBE_HANDLE}"
WORK_WITH_ME_URL = "https://brdnwd.github.io/contact"
GITHUB_API = "https://api.github.com"
STATS_BASE = "https://github-stats-extended.vercel.app/api/pin/"

TOKEN = os.environ.get("GITHUB_TOKEN", "")
HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "brdnwd-profile-readme",
}
if TOKEN:
    HEADERS["Authorization"] = f"Bearer {TOKEN}"


def get_json(url: str, retries: int = 3):
    last_error = None
    for attempt in range(retries):
        try:
            request = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            time.sleep(2 ** attempt)
    raise RuntimeError(f"Could not fetch {url}: {last_error}")


def get_bytes(url: str, retries: int = 3):
    last_error = None
    headers = {
        "User-Agent": "brdnwd-profile-readme",
        "Accept": "image/svg+xml,text/xml,application/xml,text/plain,*/*",
    }
    for attempt in range(retries):
        try:
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.read()
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            time.sleep(2 ** attempt)
    raise RuntimeError(f"Could not fetch {url}: {last_error}")


def parse_github_date(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def format_activity_date(value: str) -> str:
    dt = parse_github_date(value).astimezone()
    return dt.strftime("%m/%d %H:%M")


def github_repo_url(full_name: str) -> str:
    return f"https://github.com/{full_name}"


def get_all_owned_repositories():
    """Return all public, non-fork repositories owned by the profile."""
    repos = []
    page = 1

    while True:
        url = (
            f"{GITHUB_API}/users/{USERNAME}/repos"
            f"?type=owner&sort=created&direction=asc&per_page=100&page={page}"
        )
        batch = get_json(url)
        if not batch:
            break

        for repo in batch:
            if repo.get("fork"):
                continue
            if repo.get("private"):
                continue
            if repo.get("name") == USERNAME:
                continue
            repos.append(repo)

        if len(batch) < 100:
            break
        page += 1

    return repos


def github_search_count(query: str, endpoint: str) -> int:
    """Return GitHub's total_count for a search without downloading results."""
    encoded = urllib.parse.quote_plus(query)
    data = get_json(f"{GITHUB_API}/search/{endpoint}?q={encoded}&per_page=1")
    return int(data.get("total_count", 0))


def profile_stats_markdown(all_repos):
    """Build the all-time profile sentence from live GitHub API counts."""
    commits = github_search_count(f"author:{USERNAME}", "commits")
    issues = github_search_count(f"author:{USERNAME} type:issue", "issues")
    pull_requests = github_search_count(f"author:{USERNAME} type:pr", "issues")

    stars = sum(int(repo.get("stargazers_count", 0)) for repo in all_repos)
    projects = len(all_repos)

    return (
        f"Since joining GitHub, I've made **{commits:,}** commits, "
        f"raised **{issues:,}** issues, and submitted **{pull_requests:,}** pull requests "
        f"— earning **{stars:,}** stars across **{projects:,}** personal projects. "
        f"[Work with me]({WORK_WITH_ME_URL})."
    )


def get_recent_repositories():
    url = (
        f"{GITHUB_API}/users/{USERNAME}/repos"
        "?type=owner&sort=pushed&direction=desc&per_page=100"
    )
    repos = get_json(url)

    result = []
    for repo in repos:
        if repo.get("fork") or repo.get("archived"):
            continue
        if repo.get("name") == USERNAME:
            continue
        result.append(repo)
        if len(result) == 6:
            break

    return result


def project_markdown(repos):
    PROJECT_DIR.mkdir(parents=True, exist_ok=True)

    # Remove old generated cards so a deleted/older project cannot remain.
    for old in PROJECT_DIR.glob("*.svg"):
        old.unlink()

    if not repos:
        return "_No recent public projects found._"

    cells = []
    for index, repo in enumerate(repos, start=1):
        owner = repo["owner"]["login"]
        name = repo["name"]

        params = urllib.parse.urlencode(
            {
                "username": owner,
                "repo": name,
                "show_owner": "true",
                "hide_border": "true",
                "bg_color": "0D1117",
                "title_color": "58A6FF",
                "text_color": "C9D1D9",
                "icon_color": "58A6FF",
                "description_lines_count": "2",
            }
        )

        svg_url = f"{STATS_BASE}?{params}"
        svg_path = PROJECT_DIR / f"{index}.svg"

        try:
            svg_path.write_bytes(get_bytes(svg_url))
        except RuntimeError as exc:
            print(f"Warning: project card {name} could not be generated: {exc}")
            continue

        cells.append(
            f'<a href="{github_repo_url(repo["full_name"])}">'
            f'<img src="./profile/projects/{index}.svg" '
            f'width="400" alt="{name}"></a>'
        )

    if not cells:
        return "_Project cards could not be generated during this run._"

    # Two cards per row. GitHub handles the inline HTML naturally.
    rows = []
    for i in range(0, len(cells), 2):
        rows.append(" ".join(cells[i:i + 2]))

    return "\n\n".join(
        f'<div align="center">\n{row}\n</div>' for row in rows
    )


def event_text(event: dict) -> str | None:
    event_type = event.get("type")
    repo = event.get("repo", {}).get("name")
    payload = event.get("payload", {})

    if not repo:
        return None

    repo_url = github_repo_url(repo)
    linked_repo = f"[{repo}]({repo_url})"
    created = event.get("created_at")
    if not created:
        return None

    date = format_activity_date(created)

    if event_type == "PushEvent":
        commits = payload.get("commits") or []
        amount = len(commits)
        branch = payload.get("ref", "").replace("refs/heads/", "")
        if branch:
            branch_url = f"{repo_url}/tree/{urllib.parse.quote(branch, safe='')}"
            branch_link = f"[`{branch}`]({branch_url})"
            return (
                f"`[{date}]` [📝](https://github.com/brdnwd/brdnwd/raw/main/profile/icons/commit.png) "
                f"Made `{amount}` commit{'s' if amount != 1 else ''} in "
                f"{linked_repo} on {branch_link}"
            )
        return (
            f"`[{date}]` 📝 Made `{amount}` commit{'s' if amount != 1 else ''} "
            f"in {linked_repo}"
        )

    if event_type == "WatchEvent":
        return (
            f"`[{date}]` [⭐](https://github.com/cheesits456/github-activity-readme/raw/master/icons/star.png) "
            f"Starred {linked_repo}"
        )

    if event_type == "CreateEvent":
        ref_type = payload.get("ref_type")
        ref = payload.get("ref")
        if ref_type == "branch" and ref:
            branch_url = f"{repo_url}/tree/{urllib.parse.quote(ref, safe='')}"
            return (
                f"`[{date}]` [📂](https://github.com/cheesits456/github-activity-readme/raw/master/icons/create-branch.png) "
                f"Created branch [`{ref}`]({branch_url}) in {linked_repo}"
            )
        if ref_type == "repository":
            return f"`[{date}]` 📦 Created repository {linked_repo}"

    if event_type == "ForkEvent":
        fork = payload.get("forkee", {}).get("html_url")
        if fork:
            return f"`[{date}]` 🍴 Forked {linked_repo}"
        return f"`[{date}]` 🍴 Forked {linked_repo}"

    if event_type == "ReleaseEvent":
        release = payload.get("release", {})
        tag = release.get("tag_name", "release")
        url = release.get("html_url", repo_url)
        return f"`[{date}]` 🚀 Published [`{tag}`]({url}) in {linked_repo}"

    if event_type == "IssuesEvent":
        issue = payload.get("issue", {})
        number = issue.get("number")
        action = payload.get("action", "updated")
        if number:
            url = issue.get("html_url", repo_url)
            return f"`[{date}]` 🐛 {action.title()} issue [#{number}]({url}) in {linked_repo}"

    if event_type == "PullRequestEvent":
        pr = payload.get("pull_request", {})
        number = pr.get("number")
        action = payload.get("action", "updated")
        if number:
            url = pr.get("html_url", repo_url)
            return f"`[{date}]` 🔀 {action.title()} PR [#{number}]({url}) in {linked_repo}"

    return None


def activity_markdown():
    events = get_json(
        f"{GITHUB_API}/users/{USERNAME}/events/public?per_page=100"
    )

    lines = []
    for event in events:
        line = event_text(event)
        if line:
            lines.append(line)
        if len(lines) >= 10:
            break

    if not lines:
        return "_No recent public GitHub activity found._"

    return "\n".join(lines)


def find_youtube_channel_id():
    # Resolve the handle from YouTube's public channel page. This avoids
    # requiring a Google/YouTube API key.
    page_url = f"https://www.youtube.com/@{YOUTUBE_HANDLE}"
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept-Language": "en-US,en;q=0.9",
    }
    request = urllib.request.Request(page_url, headers=headers)

    with urllib.request.urlopen(request, timeout=30) as response:
        html = response.read().decode("utf-8", errors="ignore")

    patterns = [
        r'"channelId":"(UC[^"]+)"',
        r'"externalId":"(UC[^"]+)"',
        r'<meta itemprop="channelId" content="(UC[^"]+)"',
    ]

    for pattern in patterns:
        match = re.search(pattern, html)
        if match:
            return match.group(1)

    raise RuntimeError(
        f"Could not resolve the YouTube channel ID for @{YOUTUBE_HANDLE}."
    )


def youtube_markdown():
    try:
        channel_id = find_youtube_channel_id()
        feed_url = (
            "https://www.youtube.com/feeds/videos.xml?"
            f"channel_id={urllib.parse.quote(channel_id)}"
        )

        request = urllib.request.Request(
            feed_url,
            headers={"User-Agent": "brdnwd-profile-readme"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            data = response.read()

        root = ET.fromstring(data)
        ns = {
            "atom": "http://www.w3.org/2005/Atom",
            "yt": "http://www.youtube.com/xml/schemas/2015",
        }

        videos = []
        for entry in root.findall("atom:entry", ns)[:5]:
            title = entry.findtext("atom:title", default="", namespaces=ns)
            video_id = entry.findtext("yt:videoId", default="", namespaces=ns)

            if title and video_id:
                videos.append(
                    f"- [{title}](https://www.youtube.com/watch?v={video_id})"
                )

        if videos:
            return "\n".join(videos)

    except Exception as exc:
        print(f"Warning: YouTube update skipped: {exc}")

    # Keeping the section valid is preferable to deleting it if YouTube
    # temporarily blocks a workflow request.
    return "- [Visit my YouTube channel](https://www.youtube.com/@BrandyBeeers)"


def replace_section(text: str, name: str, content: str) -> str:
    start = f"<!-- {name}:START -->"
    end = f"<!-- {name}:END -->"

    pattern = re.compile(
        re.escape(start) + r".*?" + re.escape(end),
        re.DOTALL,
    )

    replacement = f"{start}\n{content.strip()}\n{end}"

    if not pattern.search(text):
        raise RuntimeError(f"Missing README markers for {name}.")

    return pattern.sub(replacement, text, count=1)


def main():
    readme = README.read_text(encoding="utf-8")

    all_repos = get_all_owned_repositories()
    repos = get_recent_repositories()

    readme = replace_section(
        readme,
        "PROFILE_STATS",
        profile_stats_markdown(all_repos),
    )

    readme = replace_section(
        readme,
        "PROJECTS",
        project_markdown(repos),
    )

    readme = replace_section(
        readme,
        "ACTIVITY",
        activity_markdown(),
    )

    readme = replace_section(
        readme,
        "YOUTUBE",
        youtube_markdown(),
    )

    # BLOG is deliberately not touched. There is no public API/RSS feed
    # available from the user's website yet.
    README.write_text(readme, encoding="utf-8", newline="\n")

    print("Profile README updated successfully.")


if __name__ == "__main__":
    main()
