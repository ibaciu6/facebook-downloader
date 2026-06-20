#!/usr/bin/env python3
"""
Extract Facebook-only cookies from a mixed Netscape cookie dump.
Usage: python filter-cookies.py <mixed_cookies.txt> [output.txt]
"""

import sys, re

def extract_facebook_cookies(inpath, outpath=None):
    fb_domains = (".facebook.com", "facebook.com", ".fbcdn.net")
    fb_cookies = []
    other = []

    with open(inpath) as f:
        for line in f:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                if stripped.startswith("# "):
                    other.append(line)
                continue
            parts = stripped.split("\t")
            if len(parts) >= 2 and parts[0].startswith("."):
                domain = parts[0]
            elif len(parts) >= 2:
                domain = parts[0]
            else:
                other.append(line)
                continue

            if any(domain == d or domain.endswith(d) for d in fb_domains):
                fb_cookies.append(line)

    if not outpath:
        outpath = re.sub(r"(\.txt)$", r".facebook\1", inpath)
        if outpath == inpath:
            outpath = "facebook_cookies.txt"

    with open(outpath, "w") as f:
        f.write("# Netscape HTTP Cookie File\n")
        f.write("# https://curl.haxx.se/rfc/cookie_spec.html\n")
        f.write("# Extracted from: " + inpath + "\n")
        f.write("# Only Facebook cookies\n\n")
        f.writelines(fb_cookies)

    print(f"Extracted {len(fb_cookies)} Facebook cookies → {outpath}")
    print(f"  (excluded {len([l for l in open(inpath) if l.strip() and not l.startswith('#')]) - len(fb_cookies)} non-Facebook cookies)")
    return outpath


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    extract_facebook_cookies(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
