# Facebook Group Media Downloader - Research & Plan

## Recommendation: Use WSL (Ubuntu)

**Ubuntu is strongly recommended** over native Windows for this task:

1. Most scraping tools target Linux first (gallery-dl, yt-dlp, etc.)
2. Playwright/Selenium browser automation is more stable on Linux
3. `gallery-dl` has a native apt package on Ubuntu
4. Better dependency management (apt vs pip conflicts)
5. Cron jobs for automated downloads
6. Community scripts target Linux paths/envs

---

## Approaches Found (ranked by reliability)

### Approach 1: gallery-dl (best for individual media URLs)
- **Repo**: https://github.com/mikf/gallery-dl
- **Install**: `pip install gallery-dl` or `sudo apt install gallery-dl`
- **FB Support**: Yes - has a Facebook extractor for photos (`facebook/photo`)
- **Auth**: Supports cookies from browser (`--cookies-from-browser firefox`) or cookies file
- **Pros**: Battle-tested, 18k+ stars, handles pagination, retries, metadata
- **Cons**: Only handles individual photo URLs and albums, NOT group feed scrolling
- **Verdict**: Good for downloading specific known photo URLs, not for bulk group scraping

### Approach 2: facebook-scraper library (kevinzg) - lightweight
- **Repo**: https://github.com/kevinzg/facebook-scraper
- **Install**: `pip install facebook-scraper`
- **FB Support**: Full - pages, groups, profiles, posts, comments
- **Group Support**: Yes via `group=` parameter + `cookies=` for auth
- **Media**: Returns `images[]` (list of URLs) and `video` per post
- **Pros**: Lightweight (requests-based, no browser), fast, good API
- **Cons**: Unmaintained since 2022 (~400 open issues), may break with FB DOM changes. README notes "Group scraping may return only one page and not work on private groups"
- **Verdict**: Try first, fall back to Playwright if it fails

### Approach 3: Playwright (headless browser) - most reliable
- **Install**: `pip install playwright && playwright install chromium`
- **How**: Launch real browser, inject cookies, navigate group, scroll, extract media
- **Pros**: Most reliable for private groups, handles dynamic content, undetectable
- **Cons**: Heavier (needs browser binary), slower, more complex setup
- **Verdict**: Best for private groups with guaranteed access

### Approach 4: Selenium (alternative browser automation)
- Similar to Playwright but older. Playwright is preferred in 2026.

---

## Architecture Plan

### Phase 1: Try facebook-scraper (fast path)
```
User exports cookies.txt from browser
  -> facebook-scraper with group ID + cookies
  -> Returns posts with image/video URLs
  -> Download media with requests/yt-dlp
```

### Phase 2: Fallback to Playwright (reliable path)
```
User exports cookies.json from browser
  -> Playwright injects cookies into Chromium
  -> Navigate to group, scroll to load posts
  -> Extract all <img> and <video> sources
  -> Download media files
```

### Phase 3: gallery-dl for individual URLs
```
After Phases 1/2 produce a list of URLs:
  -> pipe URLs to gallery-dl for robust downloading
  -> gallery-dl handles retries, naming, metadata
```

---

## Required Tools (Ubuntu apt)

```bash
# Core
sudo apt install python3 python3-pip
pip install facebook-scraper playwright yt-dlp requests beautifulsoup4

# gallery-dl (optional, for robust downloading)
sudo apt install gallery-dl
# or: pip install gallery-dl

# Playwright browser
playwright install chromium

# Browser cookie exporters (user must install in browser):
# Chrome: "Get cookies.txt LOCALLY" extension
# Firefox: "Cookie Quick Manager" addon
```

## Cookie Export Format

The user needs to export cookies from their browser after logging into Facebook.

**Netscape format (cookies.txt):** Used by facebook-scraper and curl/wget
```
.facebook.com	TRUE	/	TRUE	0	c_user	100000123456789
.facebook.com	TRUE	/	TRUE	0	xs	42%3AABCDEF12345
```

**JSON format (cookies.json):** Used by Playwright
```json
[
  {"name": "c_user", "value": "100000123456789", "domain": ".facebook.com", "path": "/", "httpOnly": false, "secure": true},
  {"name": "xs", "value": "42%3AABCDEF12345", "domain": ".facebook.com", "path": "/", "httpOnly": true, "secure": true}
]
```

Key cookies needed: `c_user`, `xs`, `datr`, `sb`, `fr`

---

## Implementation Script

See `download.py` and `fb-post.py` in this directory. Usage:

```bash
# Interactive single post download
python fb-post.py

# Group download
python download.py --group YOUR_GROUP_ID --cookies cookies.txt --output ./downloads
```

## Notes
- Facebook aggressively rate-limits. Add delays between requests.
- Videos are served as HLS streams (.m3u8) and need ffmpeg or yt-dlp to download.
- High-resolution photos are served from `scontent.*.fbcdn.net` - these URLs expire.
- Respect group privacy - only download from groups you own/have permission for.
