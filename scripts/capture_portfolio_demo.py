#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

from playwright.sync_api import Page, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_OUT = ROOT / "artifacts" / "portfolio-demo"


PUBLIC_PAGES = [
    ("01-opac-home.png", "/", ".lc-tour-card"),
    ("02-opac-search-results.png", "/search/?q=%E7%9F%A5%E8%AD%98%E7%B5%84%E7%B9%94", "[data-tour-id='opac-result-list']"),
    ("03-opac-record-detail.png", None, "main"),
    ("04-authority-browse.png", "/authorities/?q=%E7%9F%A5%E8%AD%98", "main"),
    ("05-repository-public.png", "/repository/", "main"),
]

STAFF_PAGES = [
    ("06-staff-marc-imports.png", "/staff/cataloging/imports/", "[data-tour-id='cataloging-import-list']"),
    ("07-staff-marc-batch.png", None, "[data-tour-id='cataloging-batch-records']"),
    ("08-staff-marc-review.png", None, "[data-tour-id='marc-review-mapping']"),
    ("09-staff-authority-list.png", "/staff/authorities/?q=%E7%9F%A5%E8%AD%98", "[data-tour-id='authority-results']"),
    ("10-staff-circulation-desk.png", "/staff/circulation/?patron_barcode=LC-P0001&item_barcode=LC-DEMO-I001", "[data-tour-id='circulation-lookup']"),
    ("11-staff-patron-detail.png", None, "main"),
    ("12-staff-acquisitions.png", "/staff/acquisitions/orders/", "[data-tour-id='acquisitions-orders']"),
    ("13-staff-serials.png", "/staff/serials/", "main"),
    ("14-staff-erm.png", "/staff/erm/resources/", "[data-tour-id='erm-resource-list']"),
    ("15-staff-repository.png", "/staff/repository/", "[data-tour-id='repository-staff-list']"),
    ("16-staff-analytics.png", "/staff/analytics/", "[data-tour-id='analytics-dashboard']"),
    ("17-staff-data-quality.png", "/staff/data-quality/", "[data-tour-id='data-quality-header']"),
    ("18-staff-audit.png", "/staff/audit/", "main"),
]


def absolute(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}{path}"


def wait_and_shoot(page: Page, base_url: str, path: str, selector: str, target: Path) -> None:
    page.goto(absolute(base_url, path), wait_until="networkidle")
    page.wait_for_selector(selector, timeout=10_000)
    page.wait_for_timeout(700)
    target.parent.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(target), full_page=True)


def discover_first_record(page: Page, base_url: str) -> str:
    page.goto(absolute(base_url, "/search/?q=%E7%9F%A5%E8%AD%98%E7%B5%84%E7%B9%94"), wait_until="networkidle")
    link = page.locator("a[href*='/records/']").first
    if link.count() == 0:
        return "/search/?q=%E7%9F%A5%E8%AD%98%E7%B5%84%E7%B9%94"
    href = link.get_attribute("href")
    return href or "/search/?q=%E7%9F%A5%E8%AD%98%E7%B5%84%E7%B9%94"


def discover_staff_links(page: Page, base_url: str) -> dict[str, str]:
    links: dict[str, str] = {}
    page.goto(absolute(base_url, "/staff/cataloging/imports/"), wait_until="networkidle")
    batch = page.locator("a[href*='/staff/cataloging/imports/']").filter(has_text="demo-marc-batch").first
    if batch.count() == 0:
        batch = page.locator("a[href*='/staff/cataloging/imports/']").first
    links["batch"] = batch.get_attribute("href") if batch.count() else "/staff/cataloging/imports/"

    page.goto(absolute(base_url, links["batch"]), wait_until="networkidle")
    review = page.locator("a[href*='/staff/cataloging/import-records/']").first
    links["review"] = review.get_attribute("href") if review.count() else links["batch"]

    page.goto(absolute(base_url, "/staff/patrons/"), wait_until="networkidle")
    patron = page.locator("a[href*='/staff/patrons/']").filter(has_text="LC-P0001").first
    if patron.count() == 0:
        patron = page.locator("a[href*='/staff/patrons/']").first
    links["patron"] = patron.get_attribute("href") if patron.count() else "/staff/patrons/"
    return links


def login(page: Page, base_url: str) -> None:
    page.goto(absolute(base_url, "/accounts/login/"), wait_until="networkidle")
    if page.locator("input[name='username']").count() == 0:
        return
    page.fill("input[name='username']", "demo_staff")
    page.fill("input[name='password']", "demo_staff_pass")
    page.click("button[type='submit'], input[type='submit']")
    page.wait_for_load_state("networkidle")


def ensure_staff_page(page: Page, base_url: str, path: str) -> None:
    page.goto(absolute(base_url, path), wait_until="networkidle")
    if page.locator("input[name='username']").count() > 0:
        page.fill("input[name='username']", "demo_staff")
        page.fill("input[name='password']", "demo_staff_pass")
        page.click("button[type='submit'], input[type='submit']")
        page.wait_for_load_state("networkidle")


def record_walkthrough(page: Page, base_url: str) -> None:
    flow = [
        "/",
        "/search/?q=%E7%9F%A5%E8%AD%98%E7%B5%84%E7%B9%94",
        "/staff/cataloging/imports/",
        "/staff/circulation/?patron_barcode=LC-P0001&item_barcode=LC-DEMO-I001",
        "/staff/authorities/?q=%E7%9F%A5%E8%AD%98",
        "/staff/acquisitions/orders/",
        "/staff/erm/resources/",
        "/staff/data-quality/",
    ]
    for path in flow:
        page.goto(absolute(base_url, path), wait_until="networkidle")
        page.wait_for_timeout(1_000)
        for _ in range(2):
            next_button = page.locator("[data-tour-next]").first
            if next_button.count() > 0 and next_button.is_visible():
                next_button.click()
                page.wait_for_timeout(700)


def extract_poster(video_dir: Path, poster: Path, fallback: Path) -> None:
    videos = sorted(video_dir.glob("*.webm"))
    poster.parent.mkdir(parents=True, exist_ok=True)
    if videos and shutil.which("ffmpeg"):
        subprocess.run(
            ["ffmpeg", "-y", "-ss", "00:00:01", "-i", str(videos[0]), "-frames:v", "1", str(poster)],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    if not poster.exists() and fallback.exists():
        shutil.copy2(fallback, poster)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    screenshots = args.out / "screenshots"
    videos = args.out / "videos"
    poster = videos / "posters" / "libracore-guided-tour.webp"
    shutil.rmtree(args.out, ignore_errors=True)
    screenshots.mkdir(parents=True, exist_ok=True)
    videos.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1000}, record_video_dir=str(videos))
        page = context.new_page()

        record_path = discover_first_record(page, args.base_url)
        PUBLIC_PAGES[2] = ("03-opac-record-detail.png", record_path, "main")

        for filename, path, selector in PUBLIC_PAGES:
            assert path is not None
            wait_and_shoot(page, args.base_url, path, selector, screenshots / filename)

        login(page, args.base_url)
        links = discover_staff_links(page, args.base_url)
        staff_pages = []
        for filename, path, selector in STAFF_PAGES:
            if filename == "07-staff-marc-batch.png":
                path = links["batch"]
            elif filename == "08-staff-marc-review.png":
                path = links["review"]
            elif filename == "11-staff-patron-detail.png":
                path = links["patron"]
            assert path is not None
            staff_pages.append((filename, path, selector))

        for filename, path, selector in staff_pages:
            wait_and_shoot(page, args.base_url, path, selector, screenshots / filename)

        page.set_viewport_size({"width": 390, "height": 844})
        wait_and_shoot(page, args.base_url, "/", "[data-tour-id='opac-search-hero']", screenshots / "19-mobile-opac.png")
        ensure_staff_page(page, args.base_url, "/staff/circulation/")
        page.wait_for_selector("main", timeout=10_000)
        page.wait_for_timeout(700)
        page.screenshot(path=str(screenshots / "20-mobile-staff-circulation.png"), full_page=True)

        page.set_viewport_size({"width": 1440, "height": 1000})
        record_walkthrough(page, args.base_url)
        context.close()
        browser.close()

    first_screenshot = screenshots / "01-opac-home.png"
    extract_poster(videos, poster, first_screenshot)
    print(f"Screenshots: {len(list(screenshots.glob('*.png')))}")
    print(f"Videos: {len(list(videos.glob('*.webm')))}")
    print(f"Poster: {poster}")


if __name__ == "__main__":
    main()
