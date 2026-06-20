#!/usr/bin/env python3
"""
Facebook Private Group Media Downloader
Downloads all photos and videos from a private Facebook group
where you have access. Requires exported cookies from your browser.

Usage:
  python download.py --group GROUP_ID --cookies cookies.txt --output ./downloads
  python download.py --playwright --group GROUP_ID --cookies cookies.json --output ./downloads
"""

import os
import sys
import json
import time
import argparse
import logging
import re
import random
import requests
import subprocess
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote
import base64
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

try:
    from rich.console import Console
    from rich.progress import (
        Progress, SpinnerColumn, TextColumn, BarColumn,
        DownloadColumn, TransferSpeedColumn, TimeRemainingColumn,
    )
    from rich.table import Table
    from rich import box
    from rich.panel import Panel
    HAS_RICH = True
    console = Console()
except ImportError:
    HAS_RICH = False

CONCURRENT_WORKERS = 5
MAX_RETRIES = 3
RETRY_BACKOFF = [2, 5, 15]


def parse_args():
    parser = argparse.ArgumentParser(description="Download media from a private Facebook group")
    parser.add_argument("--group", required=True, help="Facebook group ID or URL")
    parser.add_argument("--cookies", required=True, help="Path to cookies file (Netscape .txt or .json)")
    parser.add_argument("--output", "-o", default="./downloads", help="Output directory")
    parser.add_argument("--playwright", action="store_true", help="Use Playwright instead of facebook-scraper")
    parser.add_argument("--pages", type=int, default=10, help="Number of pages to scrape (facebook-scraper mode)")
    parser.add_argument("--delay", type=float, default=2.0, help="Delay between requests in seconds")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    parser.add_argument("--video-quality", default="best", choices=["best", "hd", "sd"], help="Video quality preference")
    parser.add_argument("--config", help="Path to config file (JSON)")
    parser.add_argument("--workers", type=int, default=CONCURRENT_WORKERS, help="Concurrent download workers")
    parser.add_argument("--metadata", help="Export metadata to JSON file")
    parser.add_argument("--skip-existing", action="store_true", default=True, help="Skip already-downloaded files")
    args = parser.parse_args()

    if args.config and os.path.exists(args.config):
        with open(args.config) as f:
            cfg = json.load(f)
        for k, v in cfg.items():
            if k in ("group", "cookies", "output") and not getattr(args, k, None):
                setattr(args, k, v)
            elif k in ("pages", "delay", "workers") and getattr(args, k) in (None, parser.get_default(k)):
                setattr(args, k, v)
    return args


def extract_group_id(group_input):
    if group_input.startswith("http"):
        match = re.search(r"facebook\.com/groups/([^/?]+)", group_input)
        if match:
            return match.group(1)
        raise ValueError(f"Could not extract group ID from URL: {group_input}")
    return group_input


def download_file(url, output_path, session=None, retries=MAX_RETRIES):
    for attempt in range(retries):
        try:
            s = session or requests.Session()
            resp = s.get(url, stream=True, timeout=30)
            resp.raise_for_status()
            total = int(resp.headers.get("content-length", 0))
            with open(output_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            if total > 0 and os.path.getsize(output_path) < total * 0.9:
                raise IOError(f"Downloaded {os.path.getsize(output_path)} < expected {total}")
            return True
        except Exception as e:
            if attempt < retries - 1:
                wait = RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF) - 1)]
                log.debug(f"Retry {attempt+1}/{retries} for {url} in {wait}s: {e}")
                time.sleep(wait)
            else:
                log.error(f"Failed to download {url} after {retries} attempts: {e}")
                return False


def sanitize_filename(name, max_len=200):
    name = re.sub(r'[<>:"/\\|?*]', "_", name)
    name = re.sub(r'\s+', "_", name)
    return name[:max_len]


def export_metadata(metadata, path):
    with open(path, "w") as f:
        json.dump(metadata, f, indent=2, default=str)
    log.info(f"Metadata exported to {path}")


def try_facebook_scraper(group_id, cookies_path, output_dir, pages, delay, workers=CONCURRENT_WORKERS, skip_existing=True):
    log.info("Attempting facebook-scraper method...")
    try:
        from facebook_scraper import get_posts
    except ImportError:
        log.error("facebook-scraper not installed. Run: pip install facebook-scraper")
        return False, []

    cookies = None
    if cookies_path.endswith(".json"):
        with open(cookies_path) as f:
            cookies = json.load(f)
    else:
        cookies = cookies_path

    session = requests.Session()
    os.makedirs(output_dir, exist_ok=True)

    if HAS_RICH:
        spinner = Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), transient=True)
        spinner_task = spinner.add_task("Fetching posts via facebook-scraper...", total=None)
        spinner.__enter__()
    else:
        spinner = None

    all_media = []
    try:
        for i, post in enumerate(get_posts(
            group=group_id,
            pages=pages,
            cookies=cookies,
            options={"allow_extra_requests": False, "posts_per_page": 50},
        )):
            if not post.get("available", True):
                continue

            post_id = post.get("post_id", f"post_{i}")
            post_dir = os.path.join(output_dir, sanitize_filename(f"{post_id}"))
            os.makedirs(post_dir, exist_ok=True)

            images = post.get("images", [])
            if not images and post.get("image"):
                images = [post["image"]]

            for j, img_url in enumerate(images):
                ext = Path(urlparse(img_url).path).suffix or ".jpg"
                fname = f"{post_id}_img_{j}{ext}"
                fpath = os.path.join(post_dir, sanitize_filename(fname))
                all_media.append({
                    "url": img_url,
                    "path": fpath,
                    "type": "image",
                    "post_id": post_id,
                    "index": j,
                })

            video_url = post.get("video")
            if video_url:
                fpath = os.path.join(post_dir, f"{post_id}_video.mp4")
                all_media.append({
                    "url": video_url,
                    "path": fpath,
                    "type": "video",
                    "post_id": post_id,
                })

            if spinner:
                spinner.update(spinner_task, description=f"Scanned {i+1} posts ({len(all_media)} media found)")
    finally:
        if spinner:
            spinner.__exit__(None, None, None)

    if not all_media:
        log.warning("No media found via facebook-scraper")
        return False, []

    downloaded = download_media_list(all_media, session, delay, workers, skip_existing, "facebook-scraper")
    return downloaded > 0, all_media


def try_playwright(group_id, cookies_path, output_dir, delay, workers=CONCURRENT_WORKERS, skip_existing=True):
    log.info("Attempting Playwright method...")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log.error("Playwright not installed. Run: pip install playwright && playwright install chromium")
        return False, []

    cookies = None
    if cookies_path.endswith(".json"):
        with open(cookies_path) as f:
            cookies = json.load(f)
    elif cookies_path.endswith(".txt"):
        cookies = parse_netscape_cookies(cookies_path)
    else:
        log.error("Cookies file must be .json or .txt (Netscape format)")
        return False, []

    if not cookies:
        log.error("No cookies loaded")
        return False, []

    group_url = f"https://www.facebook.com/groups/{group_id}/"
    os.makedirs(output_dir, exist_ok=True)

    if HAS_RICH:
        spinner = Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), transient=True)
        spinner_task = spinner.add_task("Launching Playwright browser...", total=None)
        spinner.__enter__()
    else:
        spinner = None

    media_data = {"images": set(), "videos": []}

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            )
            context.add_cookies(cookies)
            page = context.new_page()

            # Route interceptor for video URLs
            captured_mp4_urls = set()
            def _capture_mp4(route, req):
                if '.mp4' in req.url:
                    captured_mp4_urls.add(req.url)
                route.continue_()
            page.route("**/*", _capture_mp4)

            try:
                if spinner:
                    spinner.update(spinner_task, description="Navigating to group...")

                log.info(f"Navigating to {group_url}")
                page.goto(group_url, timeout=60000, wait_until="domcontentloaded")
                time.sleep(5)

                scroll_count = 0
                max_scrolls = 30
                last_height = 0
                stale_rounds = 0

                while scroll_count < max_scrolls and stale_rounds < 3:
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    time.sleep(3 + random.uniform(1, 3))

                    new_height = page.evaluate("document.body.scrollHeight")
                    if new_height == last_height:
                        stale_rounds += 1
                    else:
                        stale_rounds = 0
                    last_height = new_height
                    scroll_count += 1
                    log.info(f"Scrolled {scroll_count}x (height: {new_height})")

                    # Extract media on each scroll
                    if spinner:
                        spinner.update(spinner_task, description=f"Scrolling ({scroll_count})...")

                    chunk_images = page.evaluate("""() => {
                        const urls = new Set();
                        document.querySelectorAll('img[src*="scontent"]').forEach(img => {
                            const src = img.src;
                            const rect = img.getBoundingClientRect();
                            if (rect.width < 80 || rect.height < 80) return;
                            if (img.closest('[role="complementary"]')) return;
                            if (img.closest('[data-pagelet*="Comment"]')) return;
                            const anchor_img = img.closest('a');
                            if (anchor_img && anchor_img.querySelector('div[class*="x1jx94hy"]')) return;
                            const cl = (img.className || '') + ' ' + (img.parentElement?.className || '');
                            if (cl.includes('emoji') || cl.includes('reaction') ||
                                cl.includes('profile') || cl.includes('avatar') ||
                                cl.includes('cover')) return;
                            if (src.includes('/rsrc.php/') || src.includes('safe_image')) return;
                            if (src.includes('/t15.5256-')) return;
                            const anchor = img.closest('a');
                            if (anchor && Math.max(rect.width, rect.height) < 300) return;
                            urls.add(src);
                        });
                        return Array.from(urls);
                    }""")
                    for url in chunk_images:
                        media_data["images"].add(url)

                    # Play visible videos to populate src (DASH/MSE)
                    for vid_el in page.query_selector_all('video'):
                        rect = vid_el.bounding_box()
                        if rect and rect['width'] > 150:
                            try:
                                page.evaluate("(v) => { v.muted = true; v.play().catch(()=>{}); }", vid_el)
                            except:
                                pass
                    time.sleep(3)

                    chunk_videos = page.evaluate("""() => {
                        const urls = [];
                        document.querySelectorAll('video').forEach(v => {
                            const src = v.src || v.currentSrc || '';
                            if (src && src.startsWith('http') && !urls.includes(src)) {
                                urls.push(src);
                            }
                        });
                        return urls;
                    }""")
                    for vurl in chunk_videos:
                        if vurl not in media_data["videos"]:
                            media_data["videos"].append(vurl)

                    # Also add route-intercepted URLs, dedup by xpv_asset_id
                    if captured_mp4_urls:
                        def _decode_efg(url):
                            try:
                                qs = parse_qs(urlparse(url).query)
                                efg = qs.get('efg', [None])[0]
                                if efg:
                                    efg = unquote(efg)
                                    padded = efg + '=' * (4 - len(efg) % 4)
                                    return json.loads(base64.urlsafe_b64decode(padded))
                            except: pass
                            return None
                        quality_order = {'m366': 0, 'm412': 1, 'm367': 2, 'm78': 3}
                        by_id = {}
                        for url in captured_mp4_urls:
                            if url.startswith('blob:'):
                                continue
                            efg_data = _decode_efg(url)
                            if efg_data:
                                tag = efg_data.get('vencode_tag', '')
                                if '_audio' in tag:
                                    continue
                            vid = None
                            if efg_data:
                                vid = str(efg_data.get('xpv_asset_id', ''))
                            if not vid:
                                try:
                                    q = urlparse(url).path.split('/')[-2]
                                    vid = str(quality_order.get(q, 99))
                                except:
                                    vid = url
                            dur = efg_data.get('duration_s', 0) if efg_data else 0
                            try:
                                q = urlparse(url).path.split('/')[-2]
                                q_score = quality_order.get(q, 99)
                            except:
                                q_score = 99
                            if vid not in by_id or q_score < by_id[vid][2]:
                                by_id[vid] = (url, dur, q_score)
                        result = list(by_id.values())
                        result.sort(key=lambda x: -x[1])
                        for url, dur, q in result:
                            if url not in media_data["videos"]:
                                media_data["videos"].append(url)
                        captured_mp4_urls.clear()

            except Exception as e:
                log.error(f"Playwright error: {e}")
            finally:
                browser_cookies = context.cookies()
                browser.close()
    finally:
        if spinner:
            spinner.__exit__(None, None, None)

    if not media_data["images"] and not media_data["videos"]:
        log.warning("No media URLs found via Playwright")
        return False, []

    session = requests.Session()
    for c in browser_cookies:
        session.cookies.set(c['name'], c['value'], domain=c['domain'], path=c.get('path', '/'))
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": group_url,
        "Origin": "https://www.facebook.com",
    })

    media_list = []
    for i, url in enumerate(media_data["images"]):
        ext = Path(urlparse(url).path).suffix or ".jpg"
        if len(ext) > 6:
            ext = ".jpg"
        fname = f"media_{i:05d}{ext}"
        fpath = os.path.join(output_dir, sanitize_filename(fname))
        media_list.append({"url": url, "path": fpath, "type": "image", "source": "playwright"})

    for i, vurl in enumerate(media_data["videos"]):
        fname = f"video_{i:03d}.mp4"
        fpath = os.path.join(output_dir, sanitize_filename(fname))
        media_list.append({"url": vurl, "path": fpath, "type": "video", "source": "playwright"})

    log.info(f"Found {len(media_data['images'])} images + {len(media_data['videos'])} videos")

    downloaded = download_media_list(media_list, session, delay, workers, skip_existing, "Playwright")
    return downloaded > 0, media_list


def download_media_list(media_list, session, delay, workers, skip_existing, source_name):
    if not media_list:
        return 0

    to_download = []
    for m in media_list:
        if skip_existing and os.path.exists(m["path"]) and os.path.getsize(m["path"]) > 0:
            continue
        to_download.append(m)

    if not to_download:
        log.info(f"All {len(media_list)} media files already exist (skipping)")
        return len(media_list)

    downloaded = 0
    failed = []

    if HAS_RICH:
        table = Table(box=box.ROUNDED)
        table.add_column("Total", justify="right", style="cyan")
        table.add_column("New", justify="right", style="green")
        table.add_column("Skipped", justify="right", style="yellow")
        table.add_row(str(len(media_list)), str(len(to_download)), str(len(media_list) - len(to_download)))
        console.print(table)

        with Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            DownloadColumn(),
            TransferSpeedColumn(),
            TimeRemainingColumn(),
        ) as progress:
            task = progress.add_task(f"Downloading {len(to_download)} files ({source_name})...", total=len(to_download))

            if workers > 1:
                with ThreadPoolExecutor(max_workers=workers) as executor:
                    fut_map = {executor.submit(download_file, m["url"], m["path"], session): m for m in to_download}
                    for fut in as_completed(fut_map):
                        m = fut_map[fut]
                        try:
                            if fut.result():
                                downloaded += 1
                            else:
                                failed.append(m["url"])
                        except Exception as e:
                            log.error(f"Error downloading {m['url']}: {e}")
                            failed.append(m["url"])
                        progress.advance(task)
                        if delay > 0:
                            time.sleep(delay)
            else:
                for m in to_download:
                    if download_file(m["url"], m["path"], session):
                        downloaded += 1
                    else:
                        failed.append(m["url"])
                    progress.advance(task)
                    if delay > 0:
                        time.sleep(delay)
    else:
        log.info(f"Downloading {len(to_download)} files ({source_name})...")

        if workers > 1:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                fut_map = {executor.submit(download_file, m["url"], m["path"], session): m for m in to_download}
                for i, fut in enumerate(as_completed(fut_map)):
                    m = fut_map[fut]
                    try:
                        if fut.result():
                            downloaded += 1
                        else:
                            failed.append(m["url"])
                    except Exception as e:
                        log.error(f"Error downloading {m['url']}: {e}")
                        failed.append(m["url"])
                    if (i + 1) % 10 == 0:
                        log.info(f"Progress: {i+1}/{len(to_download)} ({downloaded} OK)")
        else:
            for i, m in enumerate(to_download):
                if download_file(m["url"], m["path"], session):
                    downloaded += 1
                else:
                    failed.append(m["url"])
                if (i + 1) % 10 == 0:
                    log.info(f"Progress: {i+1}/{len(to_download)} ({downloaded} OK)")
                if delay > 0:
                    time.sleep(delay)

    if failed:
        log.warning(f"Failed to download {len(failed)}/{len(to_download)} files")

    log.info(f"Downloaded {downloaded} / {len(media_list)} media files via {source_name}")
    return downloaded


def parse_netscape_cookies(filepath):
    cookies = []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) >= 7:
                cookies.append({
                    "name": parts[5],
                    "value": parts[6],
                    "domain": parts[0],
                    "path": parts[2],
                    "secure": parts[3].upper() == "TRUE",
                    "httpOnly": False,
                })
    return cookies


def main():
    args = parse_args()
    if args.verbose:
        log.setLevel(logging.DEBUG)

    group_id = extract_group_id(args.group)
    output_dir = args.output
    os.makedirs(output_dir, exist_ok=True)

    all_media = []
    success = False

    if args.playwright:
        success, all_media = try_playwright(
            group_id, args.cookies, output_dir, args.delay,
            workers=args.workers, skip_existing=args.skip_existing,
        )
    else:
        success_s, media_s = try_facebook_scraper(
            group_id, args.cookies, output_dir, args.pages, args.delay,
            workers=args.workers, skip_existing=args.skip_existing,
        )
        if success_s:
            success = True
            all_media.extend(media_s)
        else:
            log.warning("facebook-scraper failed or found no media. Trying Playwright fallback...")
            try:
                success_p, media_p = try_playwright(
                    group_id, args.cookies, output_dir, args.delay,
                    workers=args.workers, skip_existing=args.skip_existing,
                )
                if success_p:
                    success = True
                    all_media.extend(media_p)
            except ImportError:
                log.error("Playwright not available. Install with: pip install playwright && playwright install chromium")

    if args.metadata and all_media:
        export_data = {
            "group_id": group_id,
            "downloaded_at": datetime.now().isoformat(),
            "total_files": len(all_media),
            "output_dir": os.path.abspath(output_dir),
            "args": vars(args),
            "media": all_media,
        }
        export_metadata(export_data, args.metadata)

    if success:
        log.info(f"Media saved to: {os.path.abspath(output_dir)}")
    else:
        log.warning("No media downloaded. Check your cookies file and group access.")
        sys.exit(1)


if __name__ == "__main__":
    main()
