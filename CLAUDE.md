# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the tool

```bash
# Interactive menu
./fb-dl.sh

# CLI
./fb-dl.sh post <URL>
./fb-dl.sh group <GROUP_ID>

# Direct Python
python download.py --group GROUP_ID --cookies www.facebook.com_cookies.txt --output ./downloads
python fb-post.py --url POST_URL --cookies www.facebook.com_cookies.txt
python filter-cookies.py mixed_cookies.txt   # extract FB-only cookies
```

## Install dependencies

```bash
pip install -r requirements.txt
python -m playwright install chromium
```

## Architecture

Three entry points:

**`fb-dl.sh`** — Bash interactive menu. Handles cookie validation, dep checking, and dispatches to the two Python scripts.

**`download.py`** — Group downloader. Two modes: `facebook_scraper.get_posts()` (fast, requests-based) with auto-fallback to Playwright (headless Chromium scroll+extract). Concurrent downloads via `ThreadPoolExecutor`.

**`fb-post.py`** — Single post downloader. Playwright-only: intercepts XHR to extract image/video CDN URLs, deduplicates by `xpv_asset_id` for DASH/MSE videos.

**`filter-cookies.py`** — Utility to strip non-Facebook cookies from a full browser export.

## Cookie validation

`fb-dl.sh::validate_cookies()` checks for `c_user` + `xs` in both Netscape `.txt` and `.json` formats. Priority: `www.facebook.com_cookies.txt` > `cookies.json` > `cookies.txt`.

## Key implementation notes

- Image filter: skips small/thumbnail images (`MIN_IMAGE_SIZE = 3000` bytes) and narrow layout elements (`x1jx94hy` class)
- Video dedup: groups by `xpv_asset_id` to avoid downloading multiple quality variants of the same clip; skips audio-only tracks
- Route interception in Playwright (`fb-post.py`) captures `api/graphql` responses containing CDN URLs — more reliable than DOM scraping
- All downloads are resumable: skip-if-exists checked by filename before fetching
