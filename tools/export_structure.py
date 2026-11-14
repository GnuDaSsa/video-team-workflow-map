#!/usr/bin/env python3
"""Export the rendered map (index.html) to docs/STRUCTURE.md so text-only agents can read it.

Renders the page with headless Chrome (so JS-built text is included), then walks the
camera steps in order and converts each sheet to Markdown.
Usage: python3 tools/export_structure.py
"""
import copy, re, subprocess, pathlib, sys
from bs4 import BeautifulSoup, NavigableString, Tag

ROOT = pathlib.Path(__file__).resolve().parent.parent
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
DIAGRAM_IDS = ("beats", "wave", "edit")  # SVG 도식: 글자를 한 줄로 옮긴다

def render() -> str:
    url = (ROOT / "index.html").as_uri() + "?clean"
    out = subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--virtual-time-budget=4000",
                          "--dump-dom", url], capture_output=True, text=True, timeout=120)
    if not out.stdout.strip():
        sys.exit("render failed: " + out.stderr[-400:])
    return out.stdout

def steps(src: str):
    block = src[src.index("const steps = ["):src.index("];", src.index("const steps = ["))]
    for m in re.finditer(r"\{([^{}]*label: '([^']*)'[^{}]*)\}", block):
        body, label = m.group(1), m.group(2)
        sid = re.search(r"id: '([^']+)'", body)
        part = re.search(r"part: '([ab])'", body)
        yield (sid.group(1) if sid else None, part.group(1) if part else None, label, "deep: 1" in body)

def clean(t: str) -> str:
    return re.sub(r"\s+", " ", t).strip()

def diagram_md(svg: Tag) -> str:
    """Fold an SVG diagram's <text> into one line. Digit runs go to the nearest label by y."""
    items = [(float(t.get("y") or 0), clean(t.get_text(" "))) for t in svg.find_all("text")]
    items = [(y, s) for y, s in items if s]
    labels = [(y, s) for y, s in items if not s.isdigit()]
    nums = [(y, int(s)) for y, s in items if s.isdigit()]
    if not labels:
        return "도식: " + " · ".join(s for _, s in items)
    attached = {i: [] for i in range(len(labels))}
    for y, n in nums:
        i = min(range(len(labels)), key=lambda k: abs(labels[k][0] - y))
        attached[i].append(n)
    parts = []
    for i, (_, s) in enumerate(labels):
        ns = sorted(attached[i])
        if ns and ns == list(range(ns[0], ns[-1] + 1)):
            s += f" [{ns[0]}–{ns[-1]}]"
        elif ns:
            s += " [" + ", ".join(map(str, ns)) + "]"
        parts.append(s)
    return "도식: " + " · ".join(parts)

def without(node: Tag, *selectors: str) -> Tag:
    """Copy a subtree and drop the matching parts (used to split one sheet into two pages)."""
    c = copy.copy(node)
    for sel in selectors:
        for n in c.select(sel):
            n.decompose()
    return c

def table_md(tb: Tag) -> str:
    rows = []
    for tr in tb.find_all("tr"):
        cells = [clean(c.get_text(" ")) for c in tr.find_all(["th", "td"])]
        if cells:
            rows.append(cells)
    if not rows:
        return ""
    n = max(len(r) for r in rows)
    rows = [r + [""] * (n - len(r)) for r in rows]
    head = rows[0] if tb.find("th") else [""] * n
    body = rows[1:] if tb.find("th") else rows
    md = "| " + " | ".join(head) + " |\n|" + "---|" * n + "\n"
    md += "".join("| " + " | ".join(c.replace("|", "/") for c in r) + " |\n" for r in body)
    return md

def block_md(node: Tag) -> str:
    out = []
    def walk(el):
        if isinstance(el, NavigableString) or not isinstance(el, Tag):
            return
        cls = el.get("class") or []
        if el.name == "svg" and el.get("id") in DIAGRAM_IDS:
            out.append(diagram_md(el)); return
        if el.name in ("svg", "script", "style") or "mark" in cls:
            return
        if "strike" in cls:
            out.append(f"~~{clean(el.get_text(' '))}~~ (화면에서 빨간 취소선)"); return
        if el.name == "table":
            out.append(table_md(el)); return
        if "tree" in cls:
            out.append("```\n" + el.get_text() + "\n```"); return
        if "k" in cls:
            out.append(f"\n**{clean(el.get_text(' '))}**"); return
        if any(c in cls for c in ("chips", "tags", "gates")):
            out.append("- " + " · ".join(clean(s.get_text(' ')) for s in el.find_all(['span'], recursive=False) or [el])); return
        if "kc" in cls:
            links = []
            for d in el.find_all("div", recursive=False):
                lab = d.find("small")
                kws = []
                for b in d.find_all("b"):
                    t = clean(b.get_text(" "))
                    if t: kws.append(t)
                links.append(f"{clean(lab.get_text()) if lab else ''} [{' · '.join(kws)}]")
            out.append("**키워드 사슬** " + " → ".join(links)); return
        if "mt4" in cls:
            st = el.find(class_="strike")
            t = clean(el.get_text(" "))
            if st: t = t.replace(clean(st.get_text(" ")), "~~" + clean(st.get_text(" ")) + "~~")
            out.append(t); return
        if "sflow" in cls:
            out.append(" → ".join("[" + clean(d.get_text(' ')) + "]" for d in el.find_all("div", recursive=False))); return
        if "pair" in cls:
            for f in el.find_all("figure"):
                img = f.find("img"); vid = f.find("video"); tag = f.find("b"); cap = f.find("figcaption")
                src = f"영상 `{vid['src']}`" if vid else f"`{img['src']}`" if img else ""
                out.append(f"- {clean(tag.get_text()) if tag else ''}: {src} {clean(cap.get_text()) if cap else ''}")
            return
        if el.name == "figure":
            img = el.find("img"); vid = el.find("video"); cap = el.find("figcaption"); tag = el.find("b")
            media = (f"그림 `{img['src']}`" if img else "") + (f" + 영상 `{vid['src']}`" if vid else "")
            out.append(f"- {media or '그림'} {('[' + clean(tag.get_text()) + '] ') if tag else ''}{clean(cap.get_text()) if cap else ''}"); return
        if el.name == "audio":
            out.append(f"- 소리 `{el.get('src', '')}`"); return
        if el.name == "p" and el.find(class_="strike"):
            out.append(" ".join(f"~~{clean(x.get_text(' '))}~~" for x in el.find_all(class_="strike")) + " (화면에서 빨간 취소선)"); return
        if el.name in ("p", "h3") or any(c in cls for c in ("fbox", "ct", "ch", "lead", "lead6", "h4", "msg2", "seq")):
            t = clean(el.get_text(" "))
            if t: out.append(("- " if el.parent and set(el.parent.get('class') or []) & {"ol", "tl", "trace"} else "") + t)
            return
        kids = [k for k in el.children if isinstance(k, Tag)]
        if any(isinstance(c, NavigableString) and c.strip() for c in el.children):
            t = clean(el.get_text(" "))
            if t: out.append(t)
            return
        if not kids:
            t = clean(el.get_text(" "))
            if t: out.append(t)
            return
        for k in kids:
            walk(k)
    walk(node)
    return "\n".join(x for x in out if x).strip()

def main():
    html = render()
    soup = BeautifulSoup(html, "html.parser")
    for s in soup.select(".snd"): s.decompose()
    for s in soup.select(".zh, .ring"): s.decompose()
    src = (ROOT / "index.html").read_text()
    md = ["# 영상팀 워크플로우 — 텍스트 버전", "",
          "> `index.html`을 렌더링해 자동 추출한 문서. 직접 고치지 말고 `python3 tools/export_structure.py`로 다시 만든다.",
          "> 순서는 화면의 카메라 단계 순서와 같다. 앞쪽이 발표 경로, `[부록]` 표시는 발표 모드에서 건너뛰는 시트(D 키로 진입).", ""]
    seen = set()
    for sid, part, label, deep in steps(src):
        if not sid or (sid, part) in seen:
            continue
        seen.add((sid, part))
        el = soup.find(id=sid)
        if el is None:
            continue
        dt = el.find(class_="dt")
        df = el.find(class_="df")
        md.append(f"## {label}{'  `[부록]`' if deep else ''}")
        md.append(f"<!-- id: {sid}{' ' + part if part else ''} -->")
        if dt is not None:
            r = dt.select_one(".dh .r")
            if r: md.append(f"*{clean(r.get_text(' '))}*")
            body = dt.find(class_="body")
            if sid == "s4" and body is not None:
                # 04 is one sheet shown as two pages: ① = 참조 + 사슬·변천 띠, ② = 동작과 결과
                body = without(body, ".v4b") if part == "a" else without(body, ".kc", ".mt4", ".v4a")
            md.append(block_md(body if body is not None else dt))
            if df: md.append(f"\n<sub>비고: {clean(df.find('span').get_text(' '))}</sub>")
        else:
            md.append(block_md(el))
        md.append("")
    (ROOT / "docs" / "STRUCTURE.md").write_text("\n".join(md) + "\n")
    print("wrote docs/STRUCTURE.md", len(seen), "sections")

if __name__ == "__main__":
    main()
