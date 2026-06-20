#!/usr/bin/env python3
"""
Facebook Single Post Media Downloader
Interactive CLI menu -- enter a post URL, download all images + videos.
"""

import os, sys, json, re, time, random, subprocess, base64
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich.progress import (
    Progress, SpinnerColumn, TextColumn, BarColumn,
    DownloadColumn, TransferSpeedColumn, TimeRemainingColumn,
)
from rich.table import Table
from rich import box

console = Console()

BANNER = """
  ╔══════════════════════════════════════════════════════╗
  ║         Facebook Post Media Downloader              ║
  ║     Download all images & videos from a post        ║
  ╚══════════════════════════════════════════════════════╝
"""

CONCURRENT_WORKERS = 5
MAX_RETRIES = 3
RETRY_BACKOFF = [2, 5, 15]


def extract_post_id(url):
    patterns = [
        r"facebook\.com/.*?/posts/(\d+)",
        r"facebook\.com/.*?/videos/(\d+)",
        r"facebook\.com/photo\.php\?fbid=(\d+)",
        r"facebook\.com/permalink\.php\?story_fbid=(\d+)",
        r"fb\.com/(\d+)",
        r"facebook\.com/.*?/activity/(\d+)",
        r"facebook\.com/share/v/([^/]+)",
        r"facebook\.com/share/p/([^/]+)",
        r"facebook\.com/share/([^/]+)",
    ]
    for p in patterns:
        m = re.search(p, url)
        if m:
            return m.group(1)
    nums = re.findall(r"\d+", url)
    return nums[-1] if nums else None


def sanitize_filename(name, max_len=200):
    name = re.sub(r'[<>:"/\\|?*]', "_", name)
    name = re.sub(r"\s+", "_", name)
    return name[:max_len]


MIN_IMAGE_SIZE = 3000

def download_file(url, path, session, progress_task=None, retries=MAX_RETRIES):
    for attempt in range(retries):
        try:
            resp = session.get(url, stream=True, timeout=30)
            resp.raise_for_status()
            total = int(resp.headers.get("content-length", 0))
            if total and total < MIN_IMAGE_SIZE:
                return False
            with open(path, "wb") as f:
                dl = 0
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
                    if progress_task and total:
                        dl += len(chunk)
                        progress_task.update(completed=dl)
            sz = os.path.getsize(path)
            if sz < MIN_IMAGE_SIZE:
                os.remove(path)
                return False
            if total > 0 and sz < total * 0.9:
                raise IOError(f"Downloaded {sz} < expected {total}")
            return True
        except Exception as e:
            if attempt < retries - 1:
                wait = RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF) - 1)]
                time.sleep(wait)
            else:
                return False


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


def load_cookies(path):
    if not path or not os.path.exists(path):
        return None
    if path.endswith(".json"):
        with open(path) as f:
            return json.load(f)
    return path


def try_scraper(url, cookies_path, output_dir):
    from facebook_scraper import get_posts

    cookies = load_cookies(cookies_path)
    session = requests.Session()

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), transient=True) as progress:
        progress.add_task("Fetching post via facebook-scraper...", total=None)
        posts = list(get_posts(post_urls=[url], cookies=cookies, options={"allow_extra_requests": False}))

    if not posts:
        return False

    post = posts[0]
    post_id = post.get("post_id") or extract_post_id(url) or "post"
    post_dir = os.path.join(output_dir, sanitize_filename(post_id))
    os.makedirs(post_dir, exist_ok=True)

    images = post.get("images") or ([post["image"]] if post.get("image") else [])
    video_url = post.get("video")

    if not images and not video_url:
        console.print("[yellow]No media found via facebook-scraper.[/]")
        return False

    table = Table(box=box.ROUNDED)
    table.add_column("Type", style="cyan")
    table.add_column("Count", justify="right")
    if images:
        table.add_row("Images", str(len(images)))
    if video_url:
        table.add_row("Videos", "1")
    console.print(table)

    total_files = len(images) + (1 if video_url else 0)
    downloaded = 0
    media_meta = []

    with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(), DownloadColumn(), TransferSpeedColumn(), TimeRemainingColumn(),
    ) as progress:
        task = progress.add_task(f"Downloading {len(images)} images...", total=len(images))

        image_items = []
        for j, img_url in enumerate(images):
            ext = Path(urlparse(img_url).path).suffix or ".jpg"
            fname = f"{post_id}_{j:03d}{ext}"
            fpath = os.path.join(post_dir, sanitize_filename(fname))
            image_items.append({"url": img_url, "path": fpath, "index": j})

        with ThreadPoolExecutor(max_workers=CONCURRENT_WORKERS) as executor:
            fut_map = {}
            for item in image_items:
                if os.path.exists(item["path"]) and os.path.getsize(item["path"]) > 0:
                    downloaded += 1
                    progress.advance(task)
                    continue
                fut = executor.submit(download_file, item["url"], item["path"], session)
                fut_map[fut] = item

            for fut in as_completed(fut_map):
                item = fut_map[fut]
                try:
                    if fut.result():
                        downloaded += 1
                        media_meta.append({
                            "url": item["url"], "path": item["path"],
                            "type": "image", "index": item["index"],
                        })
                except:
                    pass
                progress.advance(task)

        if video_url:
            task2 = progress.add_task("Downloading video...", total=1)
            fpath = os.path.join(post_dir, f"{post_id}_video.mp4")
            if not os.path.exists(fpath) or os.path.getsize(fpath) == 0:
                try:
                    subprocess.run(
                        ["yt-dlp", "-o", fpath, "--quiet", video_url],
                        check=True, capture_output=True,
                    )
                    downloaded += 1
                    media_meta.append({"url": video_url, "path": fpath, "type": "video"})
                except subprocess.CalledProcessError as e:
                    console.print(f"[red]Video download failed:[/] {e.stderr.decode()}")
            progress.advance(task2)

    console.print(Panel(
        f"[green]Done![/] Downloaded [bold]{downloaded}[/]/{total_files} files to:\n[blue]{post_dir}[/]",
        box=box.ROUNDED,
    ))

    meta_path = os.path.join(post_dir, "_metadata.json")
    with open(meta_path, "w") as f:
        json.dump({
            "post_id": post_id,
            "downloaded_at": datetime.now().isoformat(),
            "total": total_files,
            "downloaded": downloaded,
            "files": media_meta,
        }, f, indent=2)

    return downloaded > 0


def try_playwright(url, cookies_path, output_dir):
    from playwright.sync_api import sync_playwright

    cookies = None
    if cookies_path:
        if cookies_path.endswith(".json"):
            with open(cookies_path) as f:
                cookies = json.load(f)
        elif cookies_path.endswith(".txt"):
            cookies = parse_netscape_cookies(cookies_path)

    post_id = extract_post_id(url) or "post"
    post_dir = os.path.join(output_dir, sanitize_filename(post_id))
    os.makedirs(post_dir, exist_ok=True)

    media_urls = {"images": [], "videos": []}
    captured_mp4_urls = set()

    def _capture_video(route, req):
        if '.mp4' in req.url:
            captured_mp4_urls.add(req.url)
        route.continue_()

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), transient=True) as progress:
        progress.add_task("Launching headless browser...", total=None)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            )
            if cookies:
                context.add_cookies(cookies)
            page = context.new_page()
            page.route("**/*", _capture_video)
            try:
                progress.add_task("Navigating to post...", total=None)
                page.goto(url, timeout=90000, wait_until="domcontentloaded")
                time.sleep(5)

                final_url = page.url
                is_reel = "/reel/" in final_url

                if is_reel:
                    progress.add_task("Reel detected, capturing video stream...", total=None)
                    try:
                        page.click("video", timeout=5000)
                    except:
                        page.evaluate("() => { const v = document.querySelector('video'); if(v) v.play().catch(()=>{}); }")
                    time.sleep(5)
                else:
                    try:
                        sm = page.query_selector("text=See more")
                        if sm:
                            sm.click()
                            time.sleep(2)
                    except:
                        pass
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    time.sleep(3)
                    page.evaluate("window.scrollTo(0, 0)")
                    time.sleep(2)

                # Extract images: exclude sidebar, comments, profile pics, video posters, reel suggestions
                images = page.evaluate("""() => {
                    const urls = new Set();
                    document.querySelectorAll('img[src*="scontent"]').forEach(img => {
                        const src = img.src;
                        const rect = img.getBoundingClientRect();
                        if (rect.width < 80 || rect.height < 80) return;
                        if (img.closest('[role="complementary"]')) return;
                        if (img.closest('[data-pagelet*="Comment"]')) return;
                        const anchor_a = img.closest('a');
                        if (anchor_a && anchor_a.querySelector('div[class*="x1jx94hy"]')) return;
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
                for url in images:
                    media_urls["images"].append(url)

                # Play each video element to populate src (videos use MSE/DASH)
                for vid_el in page.query_selector_all('video'):
                    rect = vid_el.bounding_box()
                    if rect and rect['width'] > 50:
                        try:
                            page.evaluate("(v) => { v.muted = true; v.play().catch(()=>{}); }", vid_el)
                        except:
                            pass
                time.sleep(4)

                # Extract videos from DOM
                videos_info = page.evaluate("""() => {
                    return Array.from(document.querySelectorAll('video')).map(v => ({
                        src: v.src.slice(0,3000), currentSrc: v.currentSrc.slice(0,3000),
                    })).filter(v => v.src && v.src.startsWith('http'));
                }""")
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
                all_urls = set(v['src'] for v in videos_info)
                all_urls.update(v for v in captured_mp4_urls if not v.startswith('blob:'))
                # Dedup: group by xpv_asset_id, skip audio tracks, pick best quality
                quality_order = {'m366': 0, 'm412': 1, 'm367': 2, 'm78': 3}
                by_id = {}
                for url in all_urls:
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
                    media_urls["videos"].append(url)

            except Exception as e:
                console.print(f"[red]Playwright error:[/] {e}")
            finally:
                browser_cookies = context.cookies()
                browser.close()

    total = len(media_urls["images"]) + len(media_urls["videos"])
    if total == 0:
        console.print("[yellow]No media URLs found via Playwright.[/]")
        return False

    console.print(f"[cyan]Found {len(media_urls['images'])} images + {len(media_urls['videos'])} videos[/]")

    session = requests.Session()
    for c in browser_cookies:
        session.cookies.set(c['name'], c['value'], domain=c['domain'], path=c.get('path', '/'))
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": url,
        "Origin": "https://www.facebook.com",
    })

    downloaded = 0
    media_meta = []

    with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(), DownloadColumn(), TransferSpeedColumn(), TimeRemainingColumn(),
    ) as progress:
        all_items = []
        for i, img_url in enumerate(media_urls["images"]):
            ext = Path(urlparse(img_url).path).suffix or ".jpg"
            if len(ext) > 6:
                ext = ".jpg"
            fname = f"{post_id}_{i:03d}{ext}"
            fpath = os.path.join(post_dir, sanitize_filename(fname))
            all_items.append({"url": img_url, "path": fpath, "type": "image", "index": i})

        for i, vid_url in enumerate(media_urls["videos"]):
            fname = f"{post_id}_video_{i:03d}.mp4"
            fpath = os.path.join(post_dir, sanitize_filename(fname))
            all_items.append({"url": vid_url, "path": fpath, "type": "video", "index": i})

        task = progress.add_task(f"Downloading {len(all_items)} files...", total=len(all_items))
        with ThreadPoolExecutor(max_workers=CONCURRENT_WORKERS) as executor:
            fut_map = {}
            for item in all_items:
                if os.path.exists(item["path"]) and os.path.getsize(item["path"]) > 0:
                    downloaded += 1
                    progress.advance(task)
                    continue
                fut = executor.submit(download_file, item["url"], item["path"], session)
                fut_map[fut] = item

            for fut in as_completed(fut_map):
                item = fut_map[fut]
                try:
                    if fut.result():
                        downloaded += 1
                        media_meta.append(item)
                except:
                    pass
                progress.advance(task)

    console.print(Panel(
        f"[green]Done![/] Downloaded [bold]{downloaded}[/]/{len(all_items)} files to:\n[blue]{post_dir}[/]",
        box=box.ROUNDED,
    ))

    meta_path = os.path.join(post_dir, "_metadata.json")
    with open(meta_path, "w") as f:
        json.dump({
            "post_id": post_id,
            "downloaded_at": datetime.now().isoformat(),
            "total_urls": total,
            "downloaded": downloaded,
            "files": media_meta,
        }, f, indent=2)

    return downloaded > 0


def try_ytdlp(url, cookies_path, output_dir):
    post_id = extract_post_id(url) or "post"
    post_dir = os.path.join(output_dir, sanitize_filename(post_id))
    os.makedirs(post_dir, exist_ok=True)

    try:
        probe = ["yt-dlp", "--flat-playlist", "--dump-json", url]
        if cookies_path and os.path.exists(cookies_path):
            probe = ["yt-dlp", "--flat-playlist", "--cookies", cookies_path, "--dump-json", url]
        result = subprocess.run(probe, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return False
        data = json.loads(result.stdout.strip().split("\n")[0])
        title = sanitize_filename(data.get("title", post_id))
        fname = f"{title}.mp4"
        fpath = os.path.join(post_dir, fname)

        base_cmd = ["yt-dlp", "--flat-playlist", "-o", fpath, "-f", "hd+bestaudio/sd+bestaudio/bestvideo+bestaudio", "--merge-output-format", "mp4", url]
        if cookies_path and os.path.exists(cookies_path):
            base_cmd = ["yt-dlp", "--flat-playlist", "--cookies", cookies_path, "-o", fpath, "-f", "hd+bestaudio/sd+bestaudio/bestvideo+bestaudio", "--merge-output-format", "mp4", url]

        delays = [5, 10, 15, 20, 30]
        for attempt, wait in enumerate(delays):
            out = subprocess.run(base_cmd, capture_output=True, text=True, timeout=180)
            if out.returncode == 0 and os.path.exists(fpath) and os.path.getsize(fpath) >= 500:
                console.print(f"[green]Downloaded:[/] {os.path.basename(fpath)}")
                return True
            if attempt < len(delays) - 1:
                console.print(f"[dim]yt-dlp failed (attempt {attempt+1}/{len(delays)}), retrying in {wait}s...[/]")
                time.sleep(wait)
        return False
    except Exception as e:
        return False


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Download media from a Facebook post")
    parser.add_argument("--url", help="Post URL (omit for interactive menu)")
    parser.add_argument("--cookies", help="Path to cookies file")
    parser.add_argument("--output", "-o", default="./downloads", help="Output directory")
    parser.add_argument("--method", choices=["auto", "scraper", "playwright", "ytdlp"], default="auto")
    parser.add_argument("--config", help="Path to config file (JSON)")
    parser.add_argument("--workers", type=int, default=CONCURRENT_WORKERS, help="Concurrent download workers")
    args = parser.parse_args()

    if args.config and os.path.exists(args.config):
        with open(args.config) as f:
            cfg = json.load(f)
        for k, v in cfg.items():
            if not getattr(args, k, None):
                setattr(args, k, v)

    if args.url:
        cookies_path = args.cookies if (args.cookies and os.path.exists(args.cookies)) else None
        output_dir = args.output
        method = args.method
        success = run_download(args.url, cookies_path, output_dir, method)
        sys.exit(0 if success else 1)

    console.print(BANNER, style="bold cyan")

    cookies_path = None
    if Confirm.ask("Use cookies file for auth?", default=True):
        default_cookie = "cookies.txt"
        if not os.path.exists(default_cookie):
            default_cookie = "cookies.json"
            if not os.path.exists(default_cookie):
                default_cookie = ""
        cookies_path = Prompt.ask("Path to cookies file", default=default_cookie or None)
        if cookies_path and not os.path.exists(cookies_path):
            console.print("[yellow]File not found -- continuing without cookies.[/]")
            cookies_path = None

    while True:
        url = Prompt.ask("\n[bold]Enter Facebook post URL[/]")
        if not url.strip():
            continue

        console.print()

        output_dir = f"./downloads/{extract_post_id(url) or 'post'}"
        output_dir = Prompt.ask("Output directory", default=output_dir)

        method = Prompt.ask("Download method", choices=["scraper", "playwright", "ytdlp", "auto"], default="auto")
        run_download(url, cookies_path, output_dir, method)

        if not Confirm.ask("\nDownload another post?", default=True):
            break

    console.print("\n[bold green]Goodbye![/]")


def run_download(url, cookies_path, output_dir, method):
    success = False
    is_reel = "/share/v/" in url

    if method == "ytdlp":
        console.print("[dim]Trying yt-dlp...[/]")
        success = try_ytdlp(url, cookies_path, output_dir)
    elif method == "playwright":
        console.print("[dim]Trying Playwright...[/]")
        success = try_playwright(url, cookies_path, output_dir)
    elif method == "scraper":
        console.print("[dim]Trying facebook-scraper...[/]")
        success = try_scraper(url, cookies_path, output_dir)
    else:
        if is_reel:
            console.print("[dim]Detected Reel\n  yt-dlp for video...[/]")
            success = try_ytdlp(url, cookies_path, output_dir)
        else:
            try:
                console.print("[dim]facebook-scraper for images...[/]")
                if try_scraper(url, cookies_path, output_dir):
                    success = True
            except ImportError:
                console.print("[yellow]facebook-scraper not installed[/]")
            except Exception as e:
                console.print(f"[yellow]facebook-scraper: {e}[/]")

            if not is_reel:
                console.print("[dim]yt-dlp for video...[/]")
                if try_ytdlp(url, cookies_path, output_dir):
                    success = True

        console.print("[dim]Playwright for any remaining media...[/]")
        try:
            if try_playwright(url, cookies_path, output_dir):
                success = True
        except ImportError:
            console.print("[red]Playwright not installed.[/]")
        except Exception as e:
            console.print(f"[red]Playwright failed:[/] {e}")

    if not success:
        console.print("[red]Failed to download media from this post.[/]")
    return success


if __name__ == "__main__":
    main()
