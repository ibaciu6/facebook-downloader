open, task: continue building the facebook group downloader

Project: `/home/ursu/tools/facebook-downloader/`

## What's Done

1. **`RESEARCH.md`** -- Full research doc
2. **`download.py`** -- Two-tier group downloader (facebook-scraper + Playwright)
3. **`fb-post.py`** -- Interactive single-post downloader with Rich UI
4. **Deps installed** in WSL
5. **Playwright Chromium** installed
6. **Cookie parser fixed** -- `parse_netscape_cookies` had wrong field mapping
7. **Duplicate import removed** from inside function body
8. **Playwright DOM extraction improved** -- targets post containers first

## What Needs to Be Done

### 1. Get cookies from browser
- Export from browser after logging into Facebook
- Chrome: "Get cookies.txt LOCALLY" extension -> save as `cookies.txt`
- Firefox: "Cookie Quick Manager" addon
- Key cookies: `c_user`, `xs`, `datr`, `sb`, `fr`

### 2. Test
```bash
# Single post mode (interactive)
python fb-post.py

# Group mode
python download.py --group GROUP_ID --cookies cookies.txt --output ./downloads
```

### 3. Architecture
```
facebook-downloader/
  download.py          # group downloader (CLI args)
  fb-post.py           # single post downloader (interactive menu)
  RESEARCH.md
  CONTINUE.md
  cookies.txt          # user provides
  cookies.json
  downloads/
```

### 4. Key challenges
- Private group access: cookies MUST include `c_user` and `xs`
- Rate limiting: delays built in (2-5s)
- Video: yt-dlp handles HLS streams
- Expiring CDN URLs: download promptly

### 5. Extras (optional)
- tqdm progress bar
- Resume capability
- Concurrent downloads
- Metadata export (JSON)
- Config file support
