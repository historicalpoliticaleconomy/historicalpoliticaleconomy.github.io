"""Browser e2e tests for the static HPE database site.

Run with:
    poetry run pytest tests/test_frontend.py -v -m frontend

Requires Playwright and Chromium:
    poetry run playwright install chromium
"""

import threading
from functools import partial
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

import pytest
from playwright.sync_api import Page, sync_playwright

DOCS = Path(__file__).parent.parent / "docs"


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def live_server() -> str:  # type: ignore[misc]
    handler = partial(SimpleHTTPRequestHandler, directory=str(DOCS))
    server = HTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"  # type: ignore[misc]
    server.shutdown()


@pytest.fixture(scope="session")
def browser_instance():  # type: ignore[misc]
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.fixture
def page(browser_instance, live_server: str) -> Page:  # type: ignore[misc]
    p = browser_instance.new_page()
    p.goto(live_server)
    p.wait_for_load_state("networkidle")
    yield p  # type: ignore[misc]
    p.close()


def _result_count(page: Page) -> int:
    text = page.locator("#results-count").inner_text()
    return int(text.split()[0])


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.frontend
def test_page_loads_and_cards_render(page: Page) -> None:
    cards = page.locator(".card")
    cards.first.wait_for()
    assert cards.count() > 0


@pytest.mark.frontend
def test_cards_have_required_fields(page: Page) -> None:
    page.locator(".card").first.wait_for()
    for card in page.locator(".card").all()[:10]:
        assert card.locator(".card-title").count() == 1
        assert card.locator(".card-authors").count() == 1


@pytest.mark.frontend
def test_result_count_matches_visible_cards(page: Page) -> None:
    page.locator(".card").first.wait_for()
    total = _result_count(page)
    assert total == page.locator(".card").count()
    assert total > 10


@pytest.mark.frontend
def test_search_filters_results(page: Page) -> None:
    page.locator(".card").first.wait_for()
    total_before = _result_count(page)

    page.locator("#search-input").fill("colonial")
    page.wait_for_timeout(400)

    total_after = _result_count(page)
    assert total_after < total_before
    assert total_after == page.locator(".card").count()

    for card in page.locator(".card").all():
        assert "colonial" in card.inner_text().lower()


@pytest.mark.frontend
def test_search_clear_restores_all(page: Page) -> None:
    page.locator(".card").first.wait_for()
    total_before = _result_count(page)

    page.locator("#search-input").fill("slavery")
    page.wait_for_timeout(400)

    page.locator("#search-input").fill("")
    page.wait_for_timeout(400)

    assert _result_count(page) == total_before


@pytest.mark.frontend
def test_heatmap_row_label_drills_down(page: Page) -> None:
    page.locator(".card").first.wait_for()

    # Pick the first subregion row label in the heatmap
    label = page.locator(".hm-row-label").first
    label_text = label.inner_text().strip()
    label.click()
    page.wait_for_timeout(400)

    # Breadcrumb should now show the subregion as current position
    current = page.locator(".hm-bc-current").inner_text().strip()
    assert current == label_text


@pytest.mark.frontend
def test_breadcrumb_back_navigation(page: Page) -> None:
    page.locator(".card").first.wait_for()
    total_before = _result_count(page)

    # Drill into the first subregion
    page.locator(".hm-row-label").first.click()
    page.wait_for_timeout(400)

    # Navigate back via breadcrumb "All continents" link
    page.locator(".hm-bc-link", has_text="All continents").click()
    page.wait_for_timeout(400)

    # Should be back at the top-level unfiltered view
    assert _result_count(page) == total_before


@pytest.mark.frontend
def test_region_tag_click_navigates_heatmap(page: Page) -> None:
    page.locator(".card").first.wait_for()

    # Find the first non-Global/Comparative region tag on a card
    tag = page.locator(".tag[data-region]").first
    region_name = tag.get_attribute("data-region")

    # Skip Global/Comparative (no drill-down)
    for t in page.locator(".tag[data-region]").all():
        rn = t.get_attribute("data-region")
        if rn != "Global/Comparative":
            tag = t
            region_name = rn
            break

    assert region_name is not None
    tag.click()
    page.wait_for_timeout(400)

    # The heatmap should have drilled down to show this region
    current = page.locator(".hm-bc-current").inner_text().strip()
    assert current == region_name


@pytest.mark.frontend
def test_heatmap_cell_click_filters_results(page: Page) -> None:
    page.locator(".card").first.wait_for()

    # Drill into a subregion to get to a view with cells
    page.locator(".hm-row-label").first.click()
    page.wait_for_timeout(400)

    total_at_subregion = _result_count(page)

    # Click the first heatmap cell
    first_cell = page.locator(".hm-cell").first
    first_cell.click()
    page.wait_for_timeout(400)

    filtered_count = _result_count(page)
    assert filtered_count <= total_at_subregion

    # Click the same cell again to deselect
    first_cell.click()
    page.wait_for_timeout(400)

    assert _result_count(page) == total_at_subregion


@pytest.mark.frontend
def test_abstract_expands_on_toggle(page: Page) -> None:
    page.locator(".card").first.wait_for()

    # Find the first card that carries an abstract; skip if the dataset has none.
    box = page.locator(".card-abstract").first
    if box.count() == 0:
        pytest.skip("no abstracts in the exported dataset")
    box.wait_for()

    assert box.get_attribute("data-collapsed") == "true"
    collapsed_rect = box.bounding_box()
    assert collapsed_rect is not None

    box.locator(".abstract-toggle").click()
    page.wait_for_timeout(100)

    assert box.get_attribute("data-collapsed") == "false"
    expanded_rect = box.bounding_box()
    assert expanded_rect is not None
    # Expanding wraps the full text, so the box should grow (or at worst stay equal
    # for a very short abstract that already fit on one line).
    assert expanded_rect["height"] >= collapsed_rect["height"]


@pytest.mark.frontend
def test_doi_search_works(page: Page) -> None:
    page.locator(".card").first.wait_for()

    # Use the first DOI actually present in the exported dataset
    first_doi = (
        page.locator(".card").first.locator(".btn-article").get_attribute("href")
    )
    assert first_doi is not None
    doi = first_doi.replace("https://doi.org/", "")

    page.locator("#search-input").fill(doi)
    page.wait_for_timeout(400)

    count = _result_count(page)
    assert count >= 1
