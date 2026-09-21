#!/usr/bin/env python3
"""Pure-Python HTML validity checks for the Arbeitsrechtsforum site.

Checks the site's own 40 pages (index.html, archiv.html, impressum.html and
the 37 Vortrag pages under pdf/<year>/) for the kinds of markup mistakes that
have actually bitten this project before: an <a> "closed" with a self-closing
slash instead of </a>, a table with <thead> written twice instead of closed,
a stray </div> that closes a container early and pushes later markup outside
it, and pages where <html>/<head> are missing or out of place. Never checks
the vendored css/js/fonts (Bootstrap, jQuery).

Deliberately standard-library only (html.parser, pathlib) so this runs on a
bare ubuntu-latest GitHub Actions runner and on a plain Windows machine
alike: no pip install, no Java, no Docker, no html5lib.

The Nu HTML Checker (vnu, either the vnu.jar or the validator.w3.org API) is
the far more thorough option - full HTML5 conformance, attribute validity,
ARIA rules and so on - but it needs a JVM (or Docker to run one), which is
exactly the dependency this script avoids. If a JVM/Docker is ever available
in CI, running vnu in addition to this script would be strictly stronger;
this script does not add it anywhere, that choice belongs to whoever wires
up the workflow.

Usage: python tests/check_html.py
Exit code 0 and a short summary when everything is clean; exit code 1 and
one line per problem (file:line: description) otherwise.
"""

import sys
from html.parser import HTMLParser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Elements whose open/close balance we track. These are exactly the ones
# that have actually gone wrong here: an unbalanced <div> (a surplus </div>
# closed the container early and pushed the footer outside it), a doubled
# <thead>, an <a> "closed" with a slash, and pages missing <html>/<body>.
BALANCED_TAGS = {"div", "a", "thead", "tbody", "table", "html", "body"}

# HTML void elements: self-closing syntax on these is harmless (and simply
# ignored by browsers either way) because they never have a closing tag.
VOID_ELEMENTS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}


def find_target_files():
    """The project's own pages: the root pages and the 37 Vortrag pages.

    Never the vendored css/js/fonts/media, and never the PDF slides under
    pdf/<year>/pdf/ (those aren't HTML at all).
    """
    files = sorted(REPO_ROOT.glob("*.html"))
    files += sorted(REPO_ROOT.glob("pdf/*/*.html"))
    return files


class PageChecker(HTMLParser):
    def __init__(self, filename):
        super().__init__(convert_charrefs=True)
        self.filename = filename
        self.problems = []
        self.opens = {tag: 0 for tag in BALANCED_TAGS}
        self.closes = {tag: 0 for tag in BALANCED_TAGS}
        self.all_starttags = []  # tag names in document order
        self.table_stack = []  # [{"theads": int, "pos": (line, col)}, ...]
        self.html_attrs = None
        self.first_tag_seen = None

    # -- helpers ----------------------------------------------------
    def _where(self):
        line, _col = self.getpos()
        return f"{self.filename}:{line}"

    def _record_start(self, tag, attrs):
        if self.first_tag_seen is None:
            self.first_tag_seen = tag
            if tag == "html":
                self.html_attrs = dict(attrs)
        self.all_starttags.append(tag)

        if tag in BALANCED_TAGS:
            self.opens[tag] += 1

        if tag == "table":
            self.table_stack.append({"theads": 0, "pos": self.getpos()})
        elif tag == "thead" and self.table_stack:
            self.table_stack[-1]["theads"] += 1

        if tag == "a":
            attr_names = {name for name, _value in attrs}
            if "href" not in attr_names:
                self.problems.append(f"{self._where()}: <a> without href")

    # -- HTMLParser overrides ----------------------------------------
    def handle_starttag(self, tag, attrs):
        self._record_start(tag, attrs)

    def handle_startendtag(self, tag, attrs):
        # Self-closing syntax, e.g. <a href="x" />. HTML5 parsers ignore the
        # trailing slash on anything but a void (or foreign) element, so
        # this is NOT the same as <a href="x"></a> - it never actually
        # closes the tag. This is exactly the "20 anchors closed with
        # <a />" bug archiv.html used to have.
        if tag not in VOID_ELEMENTS:
            self.problems.append(
                f"{self._where()}: self-closing syntax used on <{tag}> "
                f"(<{tag} .../> does not close it; use <{tag}...></{tag}>)"
            )
        self._record_start(tag, attrs)
        # Deliberately not calling handle_endtag: a self-closed non-void
        # element does not really close, so - like a real browser - we
        # count it as an unmatched open, which also surfaces as a tag
        # imbalance below.

    def handle_endtag(self, tag):
        if tag in BALANCED_TAGS:
            self.closes[tag] += 1
        if tag == "table" and self.table_stack:
            frame = self.table_stack.pop()
            if frame["theads"] != 1:
                line, _col = frame["pos"]
                self.problems.append(
                    f"{self.filename}:{line}: <table> has "
                    f"{frame['theads']} <thead> element(s), expected "
                    f"exactly 1"
                )

    # -- final checks, run once the whole document has been fed ------
    def finish(self):
        for tag in sorted(BALANCED_TAGS):
            if self.opens[tag] != self.closes[tag]:
                self.problems.append(
                    f"{self.filename}: <{tag}> opened {self.opens[tag]} "
                    f"time(s) but closed {self.closes[tag]} time(s)"
                )

        for frame in self.table_stack:
            line, _col = frame["pos"]
            self.problems.append(f"{self.filename}:{line}: <table> is never closed")

        if self.first_tag_seen != "html":
            self.problems.append(
                f"{self.filename}: <html> is not the document element "
                f"(first element found: <{self.first_tag_seen}>)"
            )
            return

        if not self.html_attrs or self.html_attrs.get("lang") != "de":
            self.problems.append(f'{self.filename}: <html> is missing lang="de"')

        if len(self.all_starttags) < 2 or self.all_starttags[1] != "head":
            second = self.all_starttags[1] if len(self.all_starttags) > 1 else "(none)"
            self.problems.append(
                f"{self.filename}: <head> is not the first child of <html> "
                f"(found <{second}> instead)"
            )


def check_file(path):
    rel_name = str(path.relative_to(REPO_ROOT)).replace("\\", "/")
    checker = PageChecker(rel_name)
    text = path.read_text(encoding="utf-8")
    checker.feed(text)
    checker.close()
    checker.finish()
    return checker.problems


def main():
    files = find_target_files()
    if not files:
        print("No HTML files found to check - something is wrong with the paths")
        return 1

    all_problems = []
    for path in files:
        all_problems.extend(check_file(path))

    for problem in all_problems:
        print(problem)

    if all_problems:
        print(f"\n{len(all_problems)} problem(s) found in {len(files)} file(s) checked")
        return 1

    print(f"OK - {len(files)} page(s) checked, no problems found")
    print(
        "(Pure-Python heuristic checks only, no external dependency. The Nu "
        "HTML Checker (vnu) is the more thorough option but needs a JVM or "
        "Docker, which is why this dependency-free variant exists instead.)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
