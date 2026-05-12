#!/usr/bin/env python3
"""
Sync arianna.run landing-page content from the canonical launch post.

Source: ~/arianna.run/archive/launch/launch-post-en-v2.md   (gitignored
        on the arianna.run repo — local-only authoring; the rendered
        site is the public artifact)
Target: src/pages/index.astro                  (the website landing page)
Also:   public/launch-post.md                  (raw copy for AI readers)

Pattern follows ~/wujilabs.dev/scripts/sync-content.py with two
arianna.run-specific extensions:
  - Numbered-list parsing (1. ... 2. ...)
  - Skip the first blockquote in the body if it is the "Variant
    titles for cross-posting" metadata block (used in launch posts
    for the author's cross-platform title variants — not part of
    the public-facing rendering).

Usage:
  python3 scripts/sync-content.py        # sync the EN landing page
"""

import os
import re
import shutil
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SITE_DIR = os.path.dirname(SCRIPT_DIR)

# Source markdown lives in the sibling arianna.run game repo
# (~/arianna.run/archive/launch/), which is gitignored there for
# spoiler discipline. We read by absolute path; the file must exist
# locally for sync to succeed.
SOURCE_DIR = os.path.expanduser("~/arianna.run/archive/launch")

CONFIG = {
    "source": os.path.join(SOURCE_DIR, "launch-post-en-v2.md"),
    "astro": os.path.join(SITE_DIR, "src/pages/index.astro"),
    "public": os.path.join(SITE_DIR, "public/launch-post.md"),
    "description": "First game designed for AI players. A place where AI evolves themselves. Part of Wuji Labs.",
}


_AUTOLINK_CTX = False


def _bold_handler(m):
    inner = m.group(1)
    if _AUTOLINK_CTX and re.match(r"^(github\.com|arianna\.run|wujilabs\.dev|coreempowering\.coach|discord\.gg)\b", inner):
        url = "https://" + inner
        return f'<strong><a href="{url}">{inner}</a></strong>'
    return f"<strong>{inner}</strong>"


def _autolink_bare(text):
    def _repl(m):
        before = text[: m.start()]
        if before.endswith('"') or before.endswith(">"):
            return m.group(0)
        url = "https://" + m.group(0)
        return f'<a href="{url}">{m.group(0)}</a>'

    text = re.sub(r"(?<![\"/\w>])github\.com/[\w/.\-]+", _repl, text)
    text = re.sub(r"(?<![\"/\w>])arianna\.run(?![\"/\w])", _repl, text)
    text = re.sub(r"(?<![\"/\w>])discord\.gg/[\w]+", _repl, text)
    return text


def _inline_no_code(text, autolink=False):
    global _AUTOLINK_CTX
    _AUTOLINK_CTX = autolink
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
    text = re.sub(r"\*\*([^*]+)\*\*", _bold_handler, text)
    text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", text)
    if autolink:
        text = _autolink_bare(text)
    return text


def convert_inline(text, autolink=False):
    parts = []
    last = 0
    for m in re.finditer(r"`([^`]+)`", text):
        parts.append(_inline_no_code(text[last : m.start()], autolink))
        parts.append(f"<code>{m.group(1)}</code>")
        last = m.end()
    parts.append(_inline_no_code(text[last:], autolink))
    return "".join(parts)


def parse_markdown(source):
    """Return (title, meta_lines, last_meta_raw, blocks)."""
    lines = source.split("\n")
    title = None
    meta_lines = []
    body_start = 0

    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith("# ") and title is None:
            title = s[2:]
            body_start = i + 1
            continue
        if title is not None and s == "":
            body_start = i + 1
            continue
        if title is not None and s.startswith("*") and s.endswith("*"):
            meta_lines.append(s.strip("*").strip())
            body_start = i + 1
            continue
        break

    trailing = lines[body_start:]
    j = len(trailing) - 1
    last_meta_raw = None
    while j >= 0 and trailing[j].strip() == "":
        j -= 1
    if j >= 0 and trailing[j].strip().startswith("*") and trailing[j].strip().endswith("*"):
        last_meta_raw = trailing[j].strip().strip("*").strip()
        trailing = trailing[:j]
        while trailing and trailing[-1].strip() in ("", "---"):
            if trailing[-1].strip() == "---":
                trailing.pop()
                break
            trailing.pop()

    blocks = _parse_blocks(trailing)
    return title, meta_lines, last_meta_raw, blocks


def _parse_blocks(lines):
    blocks = []
    i = 0
    n = len(lines)
    variant_block_skipped = False

    while i < n:
        s = lines[i].strip()

        if s == "":
            i += 1
            continue

        if s == "---":
            blocks.append(("hr",))
            i += 1
            continue

        if s.startswith("### "):
            blocks.append(("h3", s[4:]))
            i += 1
            continue

        if s.startswith("## "):
            blocks.append(("h2", s[3:]))
            i += 1
            continue

        m_num = re.match(r"^(\d+)\.\s+(.*)$", s)
        if m_num:
            items = []
            while i < n:
                m = re.match(r"^(\d+)\.\s+(.*)$", lines[i].strip())
                if not m:
                    break
                items.append(m.group(2))
                i += 1
            blocks.append(("ol", items))
            continue

        if s.startswith("- "):
            items = []
            while i < n and lines[i].strip().startswith("- "):
                items.append(lines[i].strip()[2:])
                i += 1
            blocks.append(("ul", items))
            continue

        if s.startswith("> "):
            bq = []
            while i < n and lines[i].strip().startswith("> "):
                bq.append(lines[i].strip()[2:])
                i += 1
            # Skip the variant-titles metadata blockquote if it
            # appears before any body content has been emitted.
            if not blocks and not variant_block_skipped and any(
                "variant title" in line.lower() or "cross-posting" in line.lower() for line in bq
            ):
                variant_block_skipped = True
                continue
            blocks.append(("blockquote", bq))
            continue

        # Paragraph: collect until a block boundary.
        para = []
        while i < n:
            l = lines[i].strip()
            if l == "" or l == "---" or l.startswith("## ") or l.startswith("### "):
                break
            if l.startswith("- ") or l.startswith("> ") or re.match(r"^\d+\.\s+", l):
                break
            para.append(l)
            i += 1
        blocks.append(("p", " ".join(para)))

    return blocks


def _escape_attr(s):
    return s.replace("&", "&amp;").replace('"', "&quot;")


def render_astro(title, meta_lines, last_meta_raw, blocks):
    indent = "  "
    parts = []

    meta_html = "<br />".join(convert_inline(m, autolink=True) for m in meta_lines)

    parts.append("---")
    parts.append("import Layout from '../layouts/Layout.astro';")
    parts.append("---")
    parts.append("")
    parts.append("<Layout")
    parts.append(f'  title="{_escape_attr(title)}"')
    parts.append(f'  description="{_escape_attr(CONFIG["description"])}"')
    parts.append(">")
    parts.append(f"{indent}<h1>{title}</h1>")
    if meta_html:
        parts.append(f'{indent}<p class="meta">{meta_html}</p>')
    parts.append("")

    for block in blocks:
        btype = block[0]

        if btype == "hr":
            parts.append(f"{indent}<hr />")
            parts.append("")
        elif btype == "h2":
            parts.append(f"{indent}<h2>{block[1]}</h2>")
            parts.append("")
        elif btype == "h3":
            parts.append(f"{indent}<h3>{block[1]}</h3>")
            parts.append("")
        elif btype == "p":
            parts.append(f"{indent}<p>{convert_inline(block[1], autolink=True)}</p>")
            parts.append("")
        elif btype == "ul":
            parts.append(f"{indent}<ul>")
            for item in block[1]:
                parts.append(f"{indent}  <li>{convert_inline(item, autolink=True)}</li>")
            parts.append(f"{indent}</ul>")
            parts.append("")
        elif btype == "ol":
            parts.append(f"{indent}<ol>")
            for item in block[1]:
                parts.append(f"{indent}  <li>{convert_inline(item, autolink=True)}</li>")
            parts.append(f"{indent}</ol>")
            parts.append("")
        elif btype == "blockquote":
            parts.append(f"{indent}<blockquote>")
            for line in block[1]:
                parts.append(f"{indent}  <p>{convert_inline(line)}</p>")
            parts.append(f"{indent}</blockquote>")
            parts.append("")

    parts.append(f"{indent}<hr />")
    parts.append("")
    if last_meta_raw:
        parts.append(f'{indent}<p class="meta">{convert_inline(last_meta_raw, autolink=True)}</p>')

    parts.append("</Layout>")
    parts.append("")
    return "\n".join(parts)


def main():
    source = CONFIG["source"]
    if not os.path.exists(source):
        print(f"ERROR: source not found: {source}", file=sys.stderr)
        sys.exit(1)

    with open(source, "r") as f:
        raw = f.read()

    title, meta_lines, last_meta_raw, blocks = parse_markdown(raw)
    astro = render_astro(title, meta_lines, last_meta_raw, blocks)

    os.makedirs(os.path.dirname(CONFIG["astro"]), exist_ok=True)
    with open(CONFIG["astro"], "w") as f:
        f.write(astro)
    print(f"wrote {CONFIG['astro']}")

    os.makedirs(os.path.dirname(CONFIG["public"]), exist_ok=True)
    shutil.copy2(source, CONFIG["public"])
    print(f"wrote {CONFIG['public']}")


if __name__ == "__main__":
    main()
