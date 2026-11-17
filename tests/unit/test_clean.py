import pytest

from copilot.ingest.clean import extract_patch_version, html_to_markdown
from tests.conftest import load_parse_fixture


def test_keeps_headings_and_text_drops_chrome() -> None:
    html = """
    <div class="mw-parser-output">
      <aside class="portable-infobox"><div>Infobox junk</div></aside>
      <div id="toc" class="toc">1 Overview 2 Trivia</div>
      <h2><span class="mw-headline">Overview</span><span class="mw-editsection">[edit]</span></h2>
      <p>Ash is an <a href="/wiki/Attacker">attacker</a>.<sup class="reference">[1]</sup></p>
      <div class="thumb"><img src="x.png"/>caption</div>
      <ul><li>Fast</li><li>Breaching rounds</li></ul>
      <table class="navbox"><tr><td>Navbox junk</td></tr></table>
    </div>
    """
    md = html_to_markdown(html)
    assert "## Overview" in md
    assert "Ash is an attacker." in md
    assert "- Fast" in md
    for junk in ("Infobox junk", "Trivia", "[edit]", "[1]", "caption", "Navbox junk", "x.png"):
        assert junk not in md


def test_fandom_quote_table_and_hatnote() -> None:
    html = """
    <div class="mw-parser-output">
    <small><center>For similarly named pages, see <a class="mw-disambig">Fuze (Disambig)</a>.
    </center></small>
    <p>← Patch 5.1 • • • List of Patches • • • Patch 5.3 →</p>
    <blockquote><table><tr>
      <td>“</td>
      <td><center><i>Chaos is only an enemy if you're unable to adapt.</i></center>
          <div><b>- Fuze</b></div></td>
      <td>”</td>
    </tr></table></blockquote>
    <p>Fuze is an attacker.</p>
    </div>
    """
    md = html_to_markdown(html)
    assert "similarly named" not in md
    assert "List of Patches" not in md
    assert "|" not in md and "“" not in md
    assert "> Chaos is only an enemy if you're unable to adapt. - Fuze" in md
    assert "Fuze is an attacker." in md


def test_no_runs_of_blank_lines() -> None:
    md = html_to_markdown("<p>a</p>" + "<br/>" * 10 + "<p>b</p>")
    assert "\n\n\n" not in md


@pytest.mark.parametrize("name", ["parse_ash", "parse_patch_5_1_0"])
def test_real_fandom_pages(name: str) -> None:
    page = load_parse_fixture(name)["parse"]
    md = html_to_markdown(page["text"])
    assert len(md) > 1000
    assert md.count("\n#") >= 3  # section structure survives
    assert "<" not in md[:2000]  # no leftover markup
    assert "mw-" not in md
    # cleaning removes most of the page weight (galleries, navboxes, markup)
    assert len(md) < len(page["text"]) / 2


@pytest.mark.parametrize(
    ("title", "text", "expected"),
    [
        ("Rainbow Six Siege patches/Patch 5.1.0", "", "5.1.0"),
        ("Rainbow Six Siege patches/Patch 1.1", "", "1.1"),
        ("Operation Deadly Omen", "Released in Y9S1.2 with ...", "Y9S1.2"),
        ("Ash (Siege)", "Ash is an attacker", None),
    ],
)
def test_extract_patch_version(title: str, text: str, expected: str | None) -> None:
    assert extract_patch_version(title, text) == expected
