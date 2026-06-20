# Facebook Group Media Downloader

Download all photos and videos from a private Facebook group or post. Supports two download modes — a fast requests-based scraper and a headless Playwright browser for harder-to-reach content.

## Requirements

- Python 3.7+
- A Facebook account with access to the target group

## Install

```bash
pip install -r requirements.txt
python -m playwright install chromium
```

## Step 1 — Export your Facebook cookies

The tool authenticates as you by reading your browser session cookies. You need to export them while logged into Facebook.

### Chrome (recommended)

1. Install the **[Get cookies.txt LOCALLY](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc)** extension
2. Log into [facebook.com](https://www.facebook.com) in Chrome
3. Navigate to any Facebook page (e.g. your group)
4. Click the extension icon in the toolbar
5. In the dropdown, make sure **facebook.com** is selected
6. Click **Export As** → **Netscape format (.txt)**
7. Save the file as `www.facebook.com_cookies.txt` in the same folder as this tool

> The extension exports only cookies for the current site. If Facebook is open in your active tab, it will export exactly the right cookies.

### Firefox

1. Install **[cookies.txt](https://addons.mozilla.org/en-US/firefox/addon/cookies-txt/)** addon
2. Log into Facebook, then click the addon icon
3. Export → save as `www.facebook.com_cookies.txt`

### Required cookies

The tool checks that your file contains at minimum:

| Cookie | Purpose |
|--------|---------|
| `c_user` | Your Facebook user ID |
| `xs` | Session token |

If validation fails, the menu will warn you.

### Tip — export from a mixed cookie file

If your export contains cookies from many domains, filter it down:

```bash
python filter-cookies.py all_cookies.txt
# → writes www.facebook.com_cookies.txt (Facebook-only)
```

---

## Step 2 — Run

### Interactive menu

```bash
./fb-dl.sh
```

The menu lets you choose between downloading a single post or an entire group, shows cookie status, and handles installation of missing dependencies.

### CLI shortcuts

```bash
./fb-dl.sh post https://www.facebook.com/groups/.../posts/123
./fb-dl.sh group GROUP_ID
```

### Direct Python

```bash
# Download a whole group
python download.py --group GROUP_ID --cookies www.facebook.com_cookies.txt --output ./downloads

# Playwright mode (slower but more reliable for large groups)
python download.py --playwright --group GROUP_ID --cookies www.facebook.com_cookies.txt

# Download a single post
python fb-post.py --url POST_URL --cookies www.facebook.com_cookies.txt
```

---

## Output

```
downloads/
  <post_id>/
    photo_1.jpg
    photo_2.jpg
    video_1.mp4
```

Existing files are skipped on re-runs (resumable).

---

## Config file (optional)

Copy `config.example.json` to `config.json` and edit defaults:

```json
{
  "cookies": "www.facebook.com_cookies.txt",
  "output": "./downloads",
  "pages": 10,
  "delay": 2.0,
  "workers": 5
}
```

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `c_user` or `xs` missing | Re-export cookies while actively logged into Facebook |
| Downloads empty | Try `--playwright` mode |
| Rate limited | Increase `--delay` (default 2s) |
| Video download fails | Ensure `yt-dlp` is installed and up to date (`pip install -U yt-dlp`) |
