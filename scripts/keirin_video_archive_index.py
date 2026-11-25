"""Audit published replay buttons in previously saved KDreams HTML without opening a player."""

import argparse
import gzip
import hashlib
import json
import os
import re
import tempfile
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from lxml import html

from scripts.keirin_video_census import DETAIL, DOMAIN, monthly_key


def encode(row):
    return json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def official(url):
    bits = urlsplit(url)
    return bits.scheme == "https" and bits.netloc == "keirin.kdreams.jp"


def canonical_page(tree):
    urls = tree.xpath('//link[@rel="canonical"]/@href')
    if len(urls) != 1 or not official(urls[0]):
        return None
    return urls[0]


def declared_replay(button):
    caption = "".join(button.text_content().split())
    if caption not in ("[映像]", "映像", "ダイジェスト映像"):
        return None
    url = button.get("href", "")
    if not official(url):
        literal = re.fullmatch(
            r"\s*windowOpen\(\s*'([^']+)'\s*,\s*''\s*,\s*'[0-9,]+'\s*\)\s*;?\s*",
            button.get("onclick", ""),
        )
        if not literal:
            return None
        url = literal[1]
    key = replay_id(url)
    return (key, url) if key else None


def replay_id(url):
    if not official(url) or urlsplit(url).path != "/stadium/digest/":
        return None
    params = parse_qs(urlsplit(url).query, keep_blank_values=True)
    if any(len(params.get(k, [])) != 1 for k in ("kaisaiDate", "kyogijoCd", "raceNo")):
        return None
    day, venue, race = (params[k][0] for k in ("kaisaiDate", "kyogijoCd", "raceNo"))
    if not (
        re.fullmatch(r"[0-9]{8}", day)
        and re.fullmatch(r"[0-9]{2}", venue)
        and re.fullmatch(r"[0-9]{1,2}", race)
        and 1 <= int(race) <= 12
    ):
        return None
    try:
        date.fromisoformat(day)
    except ValueError:
        return None
    return f"{day}-{venue}-{int(race):02d}"


def control_surface(anchor, has_past_tab):
    surface = "normal_markup"
    for element in [anchor, *anchor.iterancestors()]:
        classes = set(element.get("class", "").lower().split())
        style = "".join(element.get("style", "").lower().split())
        if (
            "disabled" in element.attrib
            or "hidden" in element.attrib
            or element.get("aria-disabled") == "true"
            or element.get("aria-hidden") == "true"
            or classes & {"disabled", "is-disabled", "hide", "hidden"}
            or "display:none" in style
            or "visibility:hidden" in style
        ):
            return None
        if "none" in classes:
            if (
                element.tag != "table"
                or "past_racecard_table" not in classes
                or not has_past_tab
            ):
                return None
            surface = "public_previous_runs_tab"
    return surface


def venue_observation(path):
    """Reduce an observed venue index to a receipt binding each button to its race heading."""
    tree, digest = source_tree(path)
    page = canonical_page(tree)
    if not page or not re.fullmatch(
        r"/[a-z0-9-]+/raceresult/[0-9]{14}/", urlsplit(page).path
    ):
        raise ValueError("Expected an official venue result index.")
    facts = {}
    for header in tree.xpath(
        '//div[contains(concat(" ",normalize-space(@class)," ")," header ")]'
    ):
        titles = header.xpath('./p[@class="race"]/a[@href]')
        for button in header.xpath('.//li[@class="btn_digest"]/a'):
            target = declared_replay(button)
            if target is None or control_surface(button, False) != "normal_markup":
                continue
            key, url = target
            if len(titles) != 1 or not official(titles[0].get("href")):
                raise ValueError(
                    "Missing race detail heading for the displayed control"
                )
            details = urlsplit(titles[0].get("href")).path
            number = DETAIL.fullmatch(details)
            if (
                not number
                or monthly_key(number[1], key[:8], key[-2:]) != key
                or number[1][:14] != urlsplit(page).path.split("/")[-2]
                or key in facts
            ):
                raise ValueError("Digest target and heading disagree")
            facts[key] = url
    if not facts:
        raise ValueError("No racing replay control on the venue page")
    return {
        "source_page": page,
        "html_sha256": digest,
        "buttons_bound_to_race_headings": facts,
    }


def daily_targets(tree, day):
    if canonical_page(tree) != f"{DOMAIN}/raceresult/{day:%Y/%m/%d}/":
        raise ValueError(f"Calendar canonical URL mismatch on {day}")
    title = f"{day:%Y年%m月%d日} レース結果一覧"
    if title not in [" ".join(h.text_content().split()) for h in tree.xpath("//h2")]:
        raise ValueError(f"Calendar title mismatch on {day}")
    tables = tree.xpath(
        '//*[@class and contains(concat(" ", normalize-space(@class), " "), " raceinfo_table ")]'
    )
    if len(tables) != 1:
        raise ValueError(f"Unsupported calendar layout on {day}")
    rows = {}
    for table_row in tables[0].xpath(".//tr"):
        links = table_row.xpath(".//a[@href]")
        meeting = [
            l.get("href")
            for l in links
            if l.text_content().strip() == "一覧"
            and official(l.get("href"))
            and re.fullmatch(
                r"/[a-z0-9-]+/raceresult/[0-9]{14}/", urlsplit(l.get("href")).path
            )
        ]
        for anchor in links:
            url = anchor.get("href")
            target = DETAIL.fullmatch(urlsplit(url).path)
            if not target or not official(url):
                continue
            identity = target[1]
            normalized = monthly_key(identity, day.isoformat(), identity[-2:])
            if (
                len(meeting) != 1
                or f"/{identity[:14]}/" not in meeting[0]
                or normalized[:8] != day.strftime("%Y%m%d")
                or normalized in rows
            ):
                raise ValueError(f"Inconsistent event and detail links on {day}")
            rows[normalized] = (DOMAIN + urlsplit(url).path, meeting[0])
    return rows


def source_tree(path):
    data = (
        gzip.decompress(path.read_bytes())
        if path.suffix == ".gz"
        else path.read_bytes()
    )
    if not data or b"keirin.kdreams.jp" not in data:
        return None, None
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None, None
    return html.fromstring(text), hashlib.sha256(data).hexdigest()


def evidence(queue_file, calendar, document_files, supplement=None):
    total = Counter(
        calendar_races_with_explicit_replay_link=0,
        archived_documents_with_target_links=0,
    )
    expected = {}
    venue_pages = set()
    days = defaultdict(set)
    for line in queue_file.read_text().splitlines():
        r = json.loads(line)
        if r["stage"] == "source":
            key = r["race_id"]
            if key in expected:
                raise ValueError(f"Duplicate queue ID: {key}")
            expected[key] = r["race_detail_url"]
            days[date.fromisoformat(r["race_date"])].add(key)
    proofs = {}
    for day, keys in sorted(days.items()):
        tree, digest = source_tree(calendar / f"{day}.html.gz")
        group = daily_targets(tree, day)
        daily_buttons = dict(
            filter(None, (declared_replay(a) for a in tree.xpath("//a[@href]")))
        )
        for key in keys:
            url, meeting = group[key]
            if expected[key] != url:
                raise ValueError(f"Saved calendar and queue URL disagree for {key}")
            proofs[key] = {
                "race_id": key,
                "daily_calendar_sha256": digest,
                "venue_result_index": meeting,
                "published_replay_references": {},
            }
            venue_pages.add(meeting)
            if key in daily_buttons:
                proofs[key]["published_replay_references"][digest] = {
                    "url": daily_buttons[key],
                    "surface": "normal_markup",
                }
                total["calendar_races_with_explicit_replay_link"] += 1
        total["saved_calendar_days"] += 1
    seen = set()
    for file in document_files:
        tree, digest = source_tree(file)
        if tree is None or digest in seen:
            continue
        url = canonical_page(tree)
        if not url or not (
            DETAIL.fullmatch(urlsplit(url).path)
            or re.fullmatch(r"/[a-z0-9-]+/raceresult/[0-9]{14}/", urlsplit(url).path)
        ):
            continue
        seen.add(digest)
        found = False
        tab_text = [
            "".join(a.text_content().split())
            for a in tree.xpath(
                '//ul[contains(concat(" ",normalize-space(@class)," ")," racecard_nav ")]/li/a'
            )
        ]
        has_past_tab = "今場所・前場所・前々場所出走レース成績" in tab_text
        for anchor in tree.xpath("//a[@href or @onclick]"):
            recognized = declared_replay(anchor)
            if not recognized:
                continue
            key, replay = recognized
            if key in proofs and (surface := control_surface(anchor, has_past_tab)):
                refs = proofs[key]["published_replay_references"]
                if digest not in refs or surface == "normal_markup":
                    refs[digest] = {"url": replay, "surface": surface}
                found = True
        total["archived_documents_with_target_links"] += int(found)
    total["archived_target_races_with_published_replay_link"] = sum(
        bool(r["published_replay_references"]) for r in proofs.values()
    )
    if supplement is not None:
        digest = supplement["html_sha256"]
        if not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise ValueError("Invalid supplemental source digest")
        for key, url in supplement["buttons_bound_to_race_headings"].items():
            if (
                replay_id(url) != key
                or key not in proofs
                or proofs[key]["venue_result_index"] != supplement["source_page"]
            ):
                raise ValueError(
                    "Independent venue observation disagrees with the saved daily index"
                )
            total["separate_venue_races_already_in_archive"] += bool(
                proofs[key]["published_replay_references"]
            )
            total["separate_venue_target_races"] += 1
            proofs[key]["published_replay_references"][digest] = {
                "url": url,
                "surface": "normal_markup",
            }
    total["saved_official_detail_or_venue_documents"] = len(seen)
    total["target_races_with_link_in_normal_markup"] = sum(
        any(
            link["surface"] == "normal_markup"
            for link in r["published_replay_references"].values()
        )
        for r in proofs.values()
    )
    total["target_races_with_link_only_in_past_runs_tab"] = sum(
        bool(r["published_replay_references"])
        and all(
            link["surface"] == "public_previous_runs_tab"
            for link in r["published_replay_references"].values()
        )
        for r in proofs.values()
    )
    total["target_races"] = len(proofs)
    total["venue_indices_covering_targets"] = len(venue_pages)
    total["target_races_with_published_replay_link"] = sum(
        bool(r["published_replay_references"]) for r in proofs.values()
    )
    total["target_races_with_only_calendar_detail"] = (
        len(proofs) - total["target_races_with_published_replay_link"]
    )
    return proofs, dict(total)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--queue", type=Path, required=True)
    p.add_argument("--calendar", type=Path, required=True)
    p.add_argument(
        "--venue-observation",
        type=Path,
        help="An independent, normalized receipt from venue_observation",
    )
    p.add_argument(
        "--local-document-list",
        type=Path,
        required=True,
        help="Newline-separated paths of previously captured HTML or HTML.gz",
    )
    p.add_argument(
        "--receipts", type=Path, required=True, help="Create-once private gzip JSONL"
    )
    args = p.parse_args()
    os.umask(0o077)
    docs = [
        Path(p) for p in args.local_document_list.read_text().splitlines() if p.strip()
    ]
    observation = (
        json.loads(args.venue_observation.read_text())
        if args.venue_observation
        else None
    )
    rows, summary = evidence(args.queue, args.calendar, docs, observation)
    with tempfile.NamedTemporaryFile(dir=args.receipts.parent, delete=False) as tmp:
        try:
            with gzip.GzipFile(filename="", mode="wb", fileobj=tmp, mtime=0) as dest:
                for row in sorted(rows.values(), key=lambda r: r["race_id"]):
                    dest.write((encode(row) + "\n").encode())
            tmp.flush()
            os.link(tmp.name, args.receipts)
        finally:
            Path(tmp.name).unlink(missing_ok=True)
    summary["receipts_sha256"] = hashlib.sha256(args.receipts.read_bytes()).hexdigest()
    summary["source_queue_sha256"] = hashlib.sha256(args.queue.read_bytes()).hexdigest()
    print(encode(summary))


if __name__ == "__main__":
    main()
