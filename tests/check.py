#!/usr/bin/env python3
"""Content and link consistency checks for the Arbeitsrechtsforum site.

Checks the site's own 40 pages (index.html, archiv.html, impressum.html and
the 37 Vortrag pages under pdf/<year>/) for the two kinds of mistakes that
have actually bitten this project before:

  * a link, image, stylesheet or PDF reference that points at a file which
    does not exist - or that only exists with different capitalisation. The
    site is served from a case-sensitive filesystem, so "WIener" and "Wiener"
    are two different files there even though Windows treats them as one.

  * the tables on index.html/archiv.html drifting out of sync with the
    Vortrag page they link to: a different topic, a different speaker, or a
    <title> that was never updated when the <h1> was (this is exactly what
    let four 2025 pages carry a 2024 title for nine months - the title tag
    is invisible when proofreading the rendered page).

Deliberately standard-library only (re, os, html, html.parser,
urllib.parse) so this runs on a bare ubuntu-latest GitHub Actions runner
(a case-sensitive filesystem - the whole point of running it there) and on
a plain Windows machine alike: no pip install, no npm, no html5lib/lxml.

Usage: python tests/check.py
Exit code 0 and a short summary when everything is clean; exit code 1 and
one line per problem otherwise. Every line names the file and the value
that is wrong, so the message alone is enough to fix the problem.
"""

import glob
import html
import os
import posixpath
import re
import sys
import urllib.parse
from html.parser import HTMLParser

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The 1st Symposium (2015) predates the online archive and was never added
# to archiv.html - there is no digital record of it on this site at all, so
# no amount of parsing archiv.html can ever recover it. That is why the
# expected number is years_listed + 2, and not + 1 as first assumed.
#
# Checked against every commit that touched index.html: the difference is 2
# in every completed state, from "4. Symposium" with 2 years listed in
# Feb 2018 through "12." with 10 years in Sep 2026. Two past commits sat at
# 3 instead - Feb 2021 ("7." with 4 years) and Oct 2022 ("8." with 5) -
# because the new Symposium was announced on the start page before the
# previous year had been moved into the archive. So this check does go red
# in that window; making both edits in one commit, the way 6b2775b did for
# 2026, keeps it green.
UNARCHIVED_SYMPOSIUMS = 1

# Deliberate editorial decisions, confirmed by the site owner, where the
# table text (index.html/archiv.html "Thema" column) intentionally differs
# from the Vortrag page's own <h1>. Keyed by (year, page's <h1> text) so the
# exception only ever matches the one page it was written for. Do not widen
# this list without the site owner confirming a new deviation is deliberate.
EXCEPTIONS = {
    (2019, "Spanisches Arbeits-(zeit)recht"):
        "table additionally says '(Vortragssprache Englisch)', the page does not",
    (2021, "Einstweiliger Rechtsschutz im Arbeitsrecht"):
        "table shortens it to 'Einstweilige Verfügungen und Arbeitsrecht'",
}

EXTERNAL_PREFIXES = ("http://", "https://", "//", "mailto:", "tel:")

problems = []


def report(message):
    problems.append(message)


def normalize(text):
    """Entity-decoded, whitespace-collapsed text for comparisons."""
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def exists_case_sensitive(path):
    """Case-sensitive existence check - do NOT use os.path.exists().

    On Windows (and macOS's default filesystem) os.path.exists() answers the
    same question for "WIener" and "Wiener" and would miss exactly the bug
    this check exists to catch, because the site is served from a
    case-sensitive filesystem. Walk each path segment against
    os.listdir() of its parent instead.
    """
    cur = "."
    for part in os.path.normpath(path).split(os.sep):
        if part in (".", ".."):
            cur = os.path.join(cur, part)
            continue
        try:
            entries = os.listdir(cur)
        except (FileNotFoundError, NotADirectoryError):
            return False
        if part not in entries:
            return False
        cur = os.path.join(cur, part)
    return True


def is_external(value):
    return value.lower().startswith(EXTERNAL_PREFIXES)


def resolve_link(page, value):
    """Resolve an href/src/data value found on `page` to a repo-relative path.

    Returns None when the value is empty after stripping fragment/query
    (i.e. it was a same-page anchor like "#top" or "?x=1").
    """
    value = urllib.parse.unquote(value)
    value = value.split("#", 1)[0]
    value = value.split("?", 1)[0]
    if value == "":
        return None
    base_dir = posixpath.dirname(page)
    return posixpath.normpath(posixpath.join(base_dir, value))


class PageParser(HTMLParser):
    """Pulls out everything the checks below need from one page."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.raw_links = []  # (tag, attr, raw_value)
        self.title_texts = []
        self.h1_texts = []
        self.h4_texts = []
        self.year_headers = []  # ints, one per <h4> that starts with a year
        self.desc_count = 0
        self.canonical_count = 0
        self.ogurl_count = 0
        self.rows = []  # {"cells": [...], "href": str|None, "year": int|None}

        self._capture_target = None
        self._capture_buf = None
        self._in_tr = False
        self._current_cells = None
        self._current_cell_buf = None
        self._current_row_href = None
        self._current_year = None

    def handle_starttag(self, tag, attrs):
        attrs_d = dict(attrs)

        for key in ("href", "src", "data"):
            if key in attrs_d and attrs_d[key] is not None:
                self.raw_links.append((tag, key, attrs_d[key]))

        if tag in ("title", "h1", "h4"):
            self._capture_target = tag
            self._capture_buf = []
        elif tag == "tr":
            self._in_tr = True
            self._current_cells = []
            self._current_row_href = None
        elif tag == "td":
            self._current_cell_buf = []
        elif tag == "a":
            if self._in_tr and "href" in attrs_d:
                self._current_row_href = attrs_d["href"]
        elif tag == "meta":
            if attrs_d.get("name") == "description":
                self.desc_count += 1
            if attrs_d.get("property") == "og:url":
                self.ogurl_count += 1
        elif tag == "link":
            if attrs_d.get("rel") == "canonical":
                self.canonical_count += 1

    def handle_data(self, data):
        if self._capture_buf is not None:
            self._capture_buf.append(data)
        if self._current_cell_buf is not None:
            self._current_cell_buf.append(data)

    def handle_endtag(self, tag):
        if tag in ("title", "h1", "h4") and self._capture_target == tag:
            text = normalize("".join(self._capture_buf))
            if tag == "title":
                self.title_texts.append(text)
            elif tag == "h1":
                self.h1_texts.append(text)
            elif tag == "h4":
                self.h4_texts.append(text)
                m = re.match(r"^(\d{4})\b", text)
                if m:
                    self._current_year = int(m.group(1))
                    self.year_headers.append(self._current_year)
            self._capture_target = None
            self._capture_buf = None
        elif tag == "td":
            text = normalize("".join(self._current_cell_buf or []))
            self._current_cells.append(text)
            self._current_cell_buf = None
        elif tag == "tr":
            if self._current_cells:
                self.rows.append({
                    "cells": self._current_cells,
                    "href": self._current_row_href,
                    "year": self._current_year,
                })
            self._in_tr = False
            self._current_cells = None
            self._current_row_href = None


def discover_pages():
    pages = ["index.html", "archiv.html", "impressum.html"]
    pdf_pages = sorted(
        os.path.relpath(p, REPO_ROOT).replace(os.sep, "/")
        for p in glob.glob(os.path.join(REPO_ROOT, "pdf", "*", "*.html"))
    )
    pages += pdf_pages
    return pages


def read(page):
    with open(os.path.join(REPO_ROOT, *page.split("/")), encoding="utf-8") as f:
        return f.read()


def parse_all(pages):
    data = {}
    for page in pages:
        parser = PageParser()
        parser.feed(read(page))
        parser.close()
        data[page] = parser
    return data


# ---------------------------------------------------------------------------
# Stage 1 - links and files
# ---------------------------------------------------------------------------

def check_links_exist(pages, data):
    for page in pages:
        for tag, attr, value in data[page].raw_links:
            if is_external(value):
                continue
            target = resolve_link(page, value)
            if target is None:
                continue
            if not exists_case_sensitive(target):
                report(
                    f"{page}: <{tag} {attr}=\"{value}\"> points at "
                    f"'{target}', which does not exist (check capitalisation)"
                )


def check_pdfs(pages, data):
    # Every PDF actually on disk under pdf/<year>/pdf/.
    real_pdfs = set()
    for path in glob.glob(os.path.join(REPO_ROOT, "pdf", "*", "pdf", "*.pdf")):
        rel = os.path.relpath(path, REPO_ROOT).replace(os.sep, "/")
        real_pdfs.add(rel)

    referenced_by = {}  # pdf target -> set of pages referencing it
    for page in pages:
        seen_on_this_page = set()
        for tag, attr, value in data[page].raw_links:
            if attr not in ("data", "href"):
                continue
            if is_external(value):
                continue
            if not value.lower().split("#", 1)[0].split("?", 1)[0].endswith(".pdf"):
                continue
            target = resolve_link(page, value)
            if target is None or target in seen_on_this_page:
                continue
            seen_on_this_page.add(target)
            referenced_by.setdefault(target, set()).add(page)

    for pdf in sorted(real_pdfs):
        pages_using_it = referenced_by.get(pdf, set())
        if not pages_using_it:
            report(f"{pdf}: exists on disk but is not linked from any page (orphaned PDF)")
        elif len(pages_using_it) > 1:
            report(
                f"{pdf}: linked from {len(pages_using_it)} pages "
                f"({', '.join(sorted(pages_using_it))}), expected exactly 1"
            )

    for target, pages_using_it in referenced_by.items():
        if target not in real_pdfs:
            for page in sorted(pages_using_it):
                report(f"{page}: links to '{target}', which does not exist on disk")


def check_mailto_and_http(pages, data):
    for page in pages:
        for tag, attr, value in data[page].raw_links:
            if attr != "href":
                continue
            if "@" in value and not value.lower().startswith("mailto:"):
                report(f"{page}: <{tag} href=\"{value}\"> contains '@' but does not start with 'mailto:'")
            if value.lower().startswith("http://"):
                report(f"{page}: <{tag} href=\"{value}\"> uses http:// where https:// works")


# ---------------------------------------------------------------------------
# Stage 2 - consistency between the tables and the Vortrag pages
# ---------------------------------------------------------------------------

def check_title_matches_h1(pages, data):
    for page in pages:
        if page in ("index.html", "archiv.html", "impressum.html"):
            continue
        d = data[page]
        title = d.title_texts[0] if len(d.title_texts) == 1 else None
        h1 = d.h1_texts[0] if len(d.h1_texts) == 1 else None
        if title is not None and h1 is not None and title != h1:
            report(f"{page}: <title>'{title}'</title> does not match <h1>'{h1}'</h1>")


def check_table_rows(pages, data):
    for source in ("index.html", "archiv.html"):
        for row in data[source].rows:
            href = row["href"]
            if not href or is_external(href):
                continue
            target = resolve_link(source, href)
            if target is None or not target.startswith("pdf/") or target not in data:
                # Not a link to a Vortrag page, or already flagged as a
                # broken link by check_links_exist() above.
                continue
            if len(row["cells"]) < 2:
                continue

            thema, vortragende = row["cells"][0], row["cells"][1]
            target_data = data[target]
            target_h1 = target_data.h1_texts[0] if len(target_data.h1_texts) == 1 else None
            target_h4 = target_data.h4_texts[0] if target_data.h4_texts else None
            if target_h4 is not None:
                target_h4 = re.sub(r"^-\s*", "", target_h4)

            m = re.match(r"^pdf/(\d{4})/", target)
            href_year = int(m.group(1)) if m else None

            if target_h1 is not None:
                exception = EXCEPTIONS.get((href_year, target_h1))
                if thema != target_h1 and exception is None:
                    report(
                        f"{source}: row Thema '{thema}' does not match "
                        f"{target} <h1>'{target_h1}'"
                    )

            if target_h4 is not None and vortragende != target_h4:
                report(
                    f"{source}: row Vortragende/r '{vortragende}' does not match "
                    f"{target} <h4>'{target_h4}'"
                )

            if row["year"] is not None and href_year is not None and row["year"] != href_year:
                report(
                    f"{source}: link '{href}' sits under the <h4>{row['year']}</h4> "
                    f"section but points at a {href_year} page"
                )


def check_seo_basics(pages, data):
    for page in pages:
        d = data[page]
        if len(d.h1_texts) != 1:
            report(f"{page}: has {len(d.h1_texts)} <h1> elements, expected exactly 1")
        if len(d.title_texts) != 1:
            report(f"{page}: has {len(d.title_texts)} <title> elements, expected exactly 1")
        if d.desc_count != 1:
            report(f"{page}: has {d.desc_count} meta description tag(s), expected exactly 1")
        if d.canonical_count != 1:
            report(f"{page}: has {d.canonical_count} canonical link(s), expected exactly 1")
        if d.ogurl_count != 1:
            report(f"{page}: has {d.ogurl_count} og:url tag(s), expected exactly 1")

    titles = {}
    for page in pages:
        d = data[page]
        if len(d.title_texts) == 1:
            titles.setdefault(d.title_texts[0], []).append(page)
    for title, owners in titles.items():
        if len(owners) > 1:
            report(f"Title '{title}' is used by {len(owners)} pages: {', '.join(owners)}")


def check_symposium_number_and_date(data):
    index_h1 = data["index.html"].h1_texts
    if len(index_h1) != 1:
        return  # already reported by check_seo_basics
    m = re.match(r"^(\d+)\.\s*Symposium", index_h1[0])
    if not m:
        report(f"index.html: <h1>'{index_h1[0]}' does not start with a symposium number")
        return
    symposium_number = int(m.group(1))
    archived_years = len(data["archiv.html"].year_headers)
    expected_number = archived_years + 1 + UNARCHIVED_SYMPOSIUMS
    if symposium_number != expected_number:
        report(
            f"index.html: <h1> says '{symposium_number}. Symposium', but archiv.html "
            f"lists {archived_years} year(s) ({UNARCHIVED_SYMPOSIUMS} earlier Symposium(s) "
            f"never archived), so the number should be {expected_number}"
        )

    index_html = read("index.html")
    dates = {}

    desc_m = re.search(r'name="description"\s+content="[^"]*?am (\d{1,2}\.\d{1,2}\.\d{4})', index_html)
    if desc_m:
        dates["meta description"] = desc_m.group(1)

    dz_m = re.search(r"Datum und Zeit:</h4>\s*(\d{1,2}\.\d{1,2}\.\d{4})", index_html)
    if dz_m:
        dates["'Datum und Zeit' block"] = dz_m.group(1)

    for i, tt_m in enumerate(re.finditer(r'title="Wird nach dem (\d{1,2}\.\d{1,2}\.\d{4}) veröffentlicht"', index_html), start=1):
        dates[f"tooltip #{i}"] = tt_m.group(1)

    if dates:
        distinct = set(dates.values())
        if len(distinct) > 1:
            details = ", ".join(f"{where}='{when}'" for where, when in dates.items())
            report(f"index.html: the event date is not consistent across the page: {details}")


def check_contact_details(data):
    index_html = read("index.html")
    impressum_html = read("impressum.html")

    idx_phone_m = re.search(r"Telefon:\s*([^<\n]+)", index_html)
    imp_phone_m = re.search(r"Tel\.:\s*([^<\n]+)", impressum_html)
    if idx_phone_m and imp_phone_m:
        idx_phone = idx_phone_m.group(1).strip()
        imp_phone = imp_phone_m.group(1).strip()
        if idx_phone != imp_phone:
            report(
                f"Phone number differs: index.html has '{idx_phone}', "
                f"impressum.html has '{imp_phone}' (compared verbatim, character-for-character)"
            )

    idx_emails = set(re.findall(r'href="mailto:([^"]+)"', index_html))
    imp_emails = set(re.findall(r'href="mailto:([^"]+)"', impressum_html))
    missing = idx_emails - imp_emails
    for email in sorted(missing):
        report(
            f"E-mail address differs: index.html links 'mailto:{email}', which does "
            f"not appear character-identical anywhere in impressum.html"
        )


def main():
    pages = discover_pages()
    if len(pages) != 40:
        report(f"Expected 40 pages, found {len(pages)} - update this script or check the file layout")

    data = parse_all(pages)

    check_links_exist(pages, data)
    check_pdfs(pages, data)
    check_mailto_and_http(pages, data)

    check_title_matches_h1(pages, data)
    check_table_rows(pages, data)
    check_seo_basics(pages, data)
    check_symposium_number_and_date(data)
    check_contact_details(data)

    for problem in problems:
        print(problem)

    if problems:
        print(f"\n{len(problems)} problem(s) found across {len(pages)} page(s) checked")
        return 1

    pdf_count = len(glob.glob(os.path.join(REPO_ROOT, "pdf", "*", "pdf", "*.pdf")))
    print(f"OK - {len(pages)} page(s) and {pdf_count} PDF(s) checked, no problems found")
    return 0


if __name__ == "__main__":
    sys.exit(main())
