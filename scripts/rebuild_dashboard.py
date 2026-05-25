#!/usr/bin/env python3
"""
Rebuild dashboard.html by inlining each theme + _common.js into the
<script id="themes-templates"> JSON block. Also injects strict no-cache
<meta> tags so browsers (especially iOS Safari) don't pin a stale dashboard.

Run from anywhere — paths are resolved relative to this script's location.

  python3 scripts/rebuild_dashboard.py
"""
import json
import sys
from pathlib import Path

# Paths relative to repo root (this script lives in scripts/)
REPO_ROOT = Path(__file__).resolve().parent.parent
VARIANTS_DIR = REPO_ROOT / 'variants'
DASHBOARD = REPO_ROOT / 'dashboard.html'
BACKUP = DASHBOARD.with_suffix('.html.bak_before_rebuild')
COMMON_JS = VARIANTS_DIR / '_common.js'

THEMES = ['jarvis', 'stage', 'aurora', 'press', 'glass', 'garden', 'lab']

# Read _common.js once - inline into each theme so the dashboard is fully
# self-contained (iframes inside srcdoc can't reliably fetch sibling files
# behind some path-based auth setups).
common_js = COMMON_JS.read_text(encoding='utf-8')

templates = {}
for t in THEMES:
    p = VARIANTS_DIR / f'{t}.html'
    if not p.exists():
        print(f'ERROR: {p} not found', file=sys.stderr)
        sys.exit(1)
    html = p.read_text(encoding='utf-8')
    old = '<script src="_common.js"></script>'
    if old not in html:
        print(f'WARN {t}.html: external _common.js script tag not found', file=sys.stderr)
    html = html.replace(old, f'<script>\n{common_js}\n</script>')
    templates[t] = html

content = DASHBOARD.read_text(encoding='utf-8')

start_marker = '<script id="themes-templates"'
end_marker = '</script>'

start = content.find(start_marker)
if start < 0:
    print('ERROR: <script id="themes-templates"> not found in dashboard.html', file=sys.stderr)
    sys.exit(1)

end_tag_start = content.find(end_marker, start)
if end_tag_start < 0:
    print('ERROR: closing </script> not found', file=sys.stderr)
    sys.exit(1)

end = end_tag_start + len(end_marker)
old_block = content[start:end]

# Escape </ inside JSON string so a stray "</script>" can't break HTML parsing
json_str = json.dumps(templates, ensure_ascii=False).replace('</', '\\u003c/')
new_block = f'<script id="themes-templates" type="application/json">{json_str}</script>'

new_content = content[:start] + new_block + content[end:]

# Inject strict no-cache <meta> tags so browsers (especially iOS Safari)
# don't pin an old dashboard.html
NO_CACHE_MARKER = '<!-- no-cache injection -->'
if NO_CACHE_MARKER not in new_content:
    no_cache_block = (
        '\n' + NO_CACHE_MARKER + '\n'
        '<meta http-equiv="Cache-Control" content="no-store, no-cache, must-revalidate, max-age=0" />\n'
        '<meta http-equiv="Pragma" content="no-cache" />\n'
        '<meta http-equiv="Expires" content="0" />\n'
    )
    head_idx = new_content.find('<head>')
    if head_idx >= 0:
        insert_at = head_idx + len('<head>')
        new_content = new_content[:insert_at] + no_cache_block + new_content[insert_at:]

BACKUP.write_text(content, encoding='utf-8')
DASHBOARD.write_text(new_content, encoding='utf-8')

print(f'OK | backup: {BACKUP.name}')
print(f'OK | old block: {len(old_block):,} bytes')
print(f'OK | new block: {len(new_block):,} bytes')
print(f'OK | dashboard.html: {len(content):,} -> {len(new_content):,} bytes')
