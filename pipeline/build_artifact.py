#!/usr/bin/env python3
"""Bundle app/ into a single-file page for publishing as a claude.ai Artifact.

The Artifact host wraps the file in its own document skeleton, so the output is
the page body only, with the stylesheet and scripts inlined. Data files are
published alongside it and fetched by relative path, exactly as on GitHub Pages.
"""
import os
import re

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
APP = os.path.join(ROOT, "app")
OUT = os.path.join(ROOT, "dist")


def main():
    html = open(os.path.join(APP, "index.html")).read()
    body = html.split("<!--ARTIFACT-START-->")[1].split("<!--ARTIFACT-END-->")[0]
    css = open(os.path.join(APP, "styles.css")).read()
    js = "".join(open(os.path.join(APP, f)).read() + "\n" for f in ("charts.js", "app.js"))
    body = re.sub(r'<script src="[^"]+"></script>\s*', "", body)
    title = re.search(r"<title>(.*?)</title>", html).group(1)
    page = (f"<title>{title}</title>\n"
            '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Figtree:wght@400;500;600;700&display=swap">\n'
            f"<style>\n{css}\n</style>\n{body.strip()}\n<script>\n{js}</script>\n")
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "index.html"), "w") as fh:
        fh.write(page)
    print("wrote", os.path.join(OUT, "index.html"), len(page), "bytes")


if __name__ == "__main__":
    main()
