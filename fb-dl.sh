#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COOKIES_TXT="$SCRIPT_DIR/cookies.txt"
COOKIES_JSON="$SCRIPT_DIR/cookies.json"
COOKIES_FB="$SCRIPT_DIR/www.facebook.com_cookies.txt"
DOWNLOADS="$SCRIPT_DIR/downloads"

R='\033[1;31m'  G='\033[1;32m'  Y='\033[1;33m'  C='\033[1;36m'
B='\033[1;34m'  M='\033[1;35m'  W='\033[1;37m'  D='\033[0;90m'
NC='\033[0m'

BOX="$(printf '═%.0s' {1..50})"

banner() {
  clear
  local t1="  Facebook Media Downloader"
  local t2="  download posts, groups, photos, videos"
  local p1="" p2=""
  local i
  for ((i=${#t1}; i<50; i++)); do p1+=" "; done
  for ((i=${#t2}; i<50; i++)); do p2+=" "; done
  echo -e "
${C}  ╔${BOX}╗
  ║${W}${t1}${C}${p1}║
  ║${D}${t2}${C}${p2}║
  ╚${BOX}╝${NC}
"
}

usage() {
  echo -e "Usage:"
  echo -e "  ${C}fb-dl.sh${NC}              interactive menu"
  echo -e "  ${C}fb-dl.sh post URL${NC}     download single post"
  echo -e "  ${C}fb-dl.sh group GID${NC}    download whole group"
  exit 0
}

check_deps() {
  local missing=()
  python3 -c "import rich" 2>/dev/null || missing+=("rich")
  python3 -c "import requests" 2>/dev/null || missing+=("requests")
  python3 -c "import facebook_scraper" 2>/dev/null || missing+=("facebook-scraper")
  python3 -c "import playwright" 2>/dev/null || missing+=("playwright")
  command -v yt-dlp >/dev/null 2>&1 || missing+=("yt-dlp")
  if [[ ${#missing[@]} -gt 0 ]]; then
    echo -e "${Y}Some dependencies are missing.${NC}"
    printf '  - %s\n' "${missing[@]}"
    echo -e "Select ${C}Install dependencies${NC} from the menu to install them.\n"
  fi
}

install_deps() {
  echo -e "${C}Installing dependencies...${NC}\n"

  echo -e "${W}1/4  Python packages (rich, requests, facebook-scraper, playwright)...${NC}"
  pip install rich requests facebook-scraper playwright lxml_html_clean 2>&1 | tail -3

  echo -e "\n${W}2/4  yt-dlp (video downloader)...${NC}"
  pip install yt-dlp 2>&1 | tail -3

  echo -e "\n${W}3/4  lxml_html_clean (facebook-scraper dep)...${NC}"
  pip install lxml_html_clean 2>&1 | tail -3

  echo -e "\n${W}4/4  Playwright Chromium browser...${NC}"
  python3 -m playwright install chromium 2>&1 | tail -3

  echo -e "\n${G}Done!${NC} Verifying..."
  local failed=0
  python3 -c "import rich" 2>/dev/null && echo -e "  ${G}✓${NC} rich" || { echo -e "  ${R}✗${NC} rich"; failed=1; }
  python3 -c "import requests" 2>/dev/null && echo -e "  ${G}✓${NC} requests" || { echo -e "  ${R}✗${NC} requests"; failed=1; }
  python3 -c "import facebook_scraper" 2>/dev/null && echo -e "  ${G}✓${NC} facebook-scraper" || { echo -e "  ${R}✗${NC} facebook-scraper"; failed=1; }
  python3 -c "import playwright" 2>/dev/null && echo -e "  ${G}✓${NC} playwright" || { echo -e "  ${R}✗${NC} playwright"; failed=1; }
  command -v yt-dlp >/dev/null 2>&1 && echo -e "  ${G}✓${NC} yt-dlp" || { echo -e "  ${R}✗${NC} yt-dlp"; failed=1; }
  [[ -d "$(python3 -c 'import playwright; print(playwright.__file__)' 2>/dev/null)" ]] || true

  if [[ $failed -eq 0 ]]; then
    echo -e "\n${G}All dependencies installed successfully.${NC}"
  else
    echo -e "\n${Y}Some dependencies failed. Check errors above.${NC}"
  fi
  read -r -p "Press Enter to continue" _
}

# ── cookie validation ────────────────────────────────────────────────
# Check if a cookies file has the required facebook cookies (c_user + xs)
validate_cookies() {
  local f="$1" name val
  [[ ! -f "$f" ]] && return 1
  local has_c_user=0 has_xs=0

  if [[ "$f" == *.json ]]; then
    python3 -c "
import json,sys
try:
  c=json.load(open('$f'))
  if not isinstance(c,list): sys.exit(1)
  names=[x.get('name','') for x in c]
  sys.exit(0 if 'c_user' in names and 'xs' in names else 1)
except: sys.exit(1)
" 2>/dev/null && return 0 || return 1
  else
    while IFS=$'\t' read -r domain extra1 path secure expires name value rest; do
      [[ "$name" == "c_user" ]] && has_c_user=1
      [[ "$name" == "xs" ]] && has_xs=1
    done < <(grep -v '^#' "$f" 2>/dev/null || true)
    [[ $has_c_user -eq 1 && $has_xs -eq 1 ]] && return 0 || return 1
  fi
}

# Pick best cookies: prefer whichever file has both c_user + xs
pick_cookies() {
  if validate_cookies "$COOKIES_FB"; then
    echo "$COOKIES_FB"
  elif validate_cookies "$COOKIES_JSON"; then
    echo "$COOKIES_JSON"
  elif validate_cookies "$COOKIES_TXT"; then
    echo "$COOKIES_TXT"
  else
    echo ""
  fi
}

cookie_status() {
  local txt_ok json_ok fb_ok
  validate_cookies "$COOKIES_FB" && fb_ok="${G}valid${NC}" || fb_ok="${R}invalid/missing${NC}"
  validate_cookies "$COOKIES_TXT" && txt_ok="${G}valid${NC}" || txt_ok="${R}invalid/missing${NC}"
  validate_cookies "$COOKIES_JSON" && json_ok="${G}valid${NC}" || json_ok="${R}invalid/missing${NC}"
  echo -e "  ${D}www.facebook.com_cookies.txt${NC} → $fb_ok"
  echo -e "  ${D}cookies.txt${NC}                → $txt_ok"
  echo -e "  ${D}cookies.json${NC}               → $json_ok"
}

# ── downloaders ──────────────────────────────────────────────────────
download_post() {
  local url="$1" method="$2" cookies="$3" out="$4"
  local args=("--url" "$url" "--output" "$out")
  [[ -n "$cookies" ]] && args+=("--cookies" "$cookies")
  [[ -n "$method" ]]  && args+=("--method" "$method")
  [[ -f "$SCRIPT_DIR/config.json" ]] && args+=("--config" "$SCRIPT_DIR/config.json")

  echo -e "${C}Downloading post...${NC}"
  cd "$SCRIPT_DIR"
  python3 fb-post.py "${args[@]}"
}

download_group() {
  local gid="$1" cookies="$2" out="$3"
  if [[ -z "$cookies" ]]; then
    echo -e "${R}Group download requires valid cookies file.${NC}"
    return 1
  fi
  local args=("--group" "$gid" "--cookies" "$cookies" "--output" "$out")
  [[ -f "$SCRIPT_DIR/config.json" ]] && args+=("--config" "$SCRIPT_DIR/config.json")
  echo -e "${C}Downloading group $gid...${NC}"
  cd "$SCRIPT_DIR"
  python3 download.py "${args[@]}"
}

# ── menus ────────────────────────────────────────────────────────────
menu_post() {
  echo
  read -r -e -p "$(echo -e "${W}Enter Facebook post URL:${NC} ")" url
  [[ -z "$url" ]] && return

  echo
  echo -e "  ${C}1)${NC} auto       (try scraper, fallback playwright)"
  echo -e "  ${C}2)${NC} scraper    (fast, requests-based)"
  echo -e "  ${C}3)${NC} playwright (headless browser)"
  echo
  read -r -p "$(echo -e "${W}Method [1]:${NC} ")" m
  local method
  case "${m:-1}" in
    1|"") method="auto" ;;
    2)    method="scraper" ;;
    3)    method="playwright" ;;
    *)    method="auto" ;;
  esac

  download_post "$url" "$method" "$(pick_cookies)" "$DOWNLOADS"
}

menu_group() {
  echo
  read -r -e -p "$(echo -e "${W}Enter group ID or URL:${NC} ")" gid
  [[ -z "$gid" ]] && return
  download_group "$gid" "$(pick_cookies)" "$DOWNLOADS"
}

menu_cookies() {
  echo
  echo -e "${W}Current cookies:${NC}"
  cookie_status
  echo
  echo -e "${D}Export cookies from browser after FB login:${NC}"
  echo -e "  Chrome: ${C}Get cookies.txt LOCALLY${NC} extension"
  echo -e "  Firefox: ${C}Cookie Quick Manager${NC} addon"
  echo -e "  Save in: ${B}$SCRIPT_DIR${NC}"
  echo -e "  Name it: ${C}www.facebook.com_cookies.txt${NC} (recommended)"
  echo -e "       or: ${C}cookies.txt${NC} or ${C}cookies.json${NC}"
  echo
  echo -e "${D}Required cookies:${NC} c_user, xs, datr, sb, fr"
  read -r -p "Press Enter to continue" _
}

main_menu() {
  while true; do
    banner
    echo -e "  ${W}1)${NC} Download single post"
    echo -e "  ${W}2)${NC} Download group"
    echo -e "  ${W}3)${NC} Cookies setup"
    echo -e "  ${W}4)${NC} Install dependencies"
    echo -e "  ${W}5)${NC} Help"
    echo -e "  ${W}q)${NC} Quit"
    echo
    read -r -p "$(echo -e "${W}Choose [1]:${NC} ")" choice
    echo
    case "${choice:-1}" in
      1|"") menu_post ;;
      2)     menu_group ;;
      3)     menu_cookies ;;
      4)     install_deps ;;
      5)     usage ;;
      q|Q)   echo -e "${G}Goodbye.${NC}"; exit 0 ;;
      *)     echo -e "${R}Invalid.${NC}"; sleep 1 ;;
    esac
  done
}

# ── entry ────────────────────────────────────────────────────────────
check_deps
mkdir -p "$DOWNLOADS"

if [[ $# -ge 2 && "$1" == "post" ]]; then
  download_post "$2" "auto" "$(pick_cookies)" "$DOWNLOADS"
elif [[ $# -ge 2 && "$1" == "group" ]]; then
  download_group "$2" "$(pick_cookies)" "$DOWNLOADS"
else
  main_menu
fi
