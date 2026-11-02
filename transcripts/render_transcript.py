"""Render a Claude Code session JSONL into readable Markdown for reviewers."""

import json
import re
import sys
from pathlib import Path

src, out = Path(sys.argv[1]), Path(sys.argv[2])
HOME = str(Path.home())
MAX_LINES = 40


def clean(text: str) -> str:
    text = re.sub(r"<system-reminder>.*?</system-reminder>", "", text, flags=re.S)
    text = re.sub(r"<pasted_content[^>]*>", "", text).replace("</pasted_content>", "")
    text = re.sub(r"</?pasted_content id=\"[^\"]*\">", "", text)
    text = text.replace(HOME, "~")
    return text.strip()


def clip(text: str, n: int = MAX_LINES) -> str:
    lines = text.splitlines()
    if len(lines) <= n:
        return text
    return "\n".join(lines[:n]) + f"\n... ({len(lines) - n} more lines)"


def fence(text: str, lang: str = "") -> str:
    text = text.replace("```", "ʼʼʼ")
    return f"```{lang}\n{text}\n```"


def user_text(content):
    if isinstance(content, str):
        m = re.search(r"<command-name>(.*?)</command-name>", content, re.S)
        if m:
            args = re.search(r"<command-args>(.*?)</command-args>", content, re.S)
            a = clean(args.group(1)) if args else ""
            return f"`{m.group(1).strip()}`" + (f"\n\n{a}" if a else "")
        if "<local-command" in content or content.startswith("<command-message>"):
            return None
        return clean(content)
    parts = [clean(b.get("text", "")) for b in content if b.get("type") == "text"]
    parts = [p for p in parts if p]
    return "\n\n".join(parts) if parts else None


def tool_result_text(block):
    c = block.get("content")
    if isinstance(c, list):
        c = "\n".join(x.get("text", "") for x in c if x.get("type") == "text")
    return clean(str(c or ""))


def tool_use(block):
    name, inp = block.get("name"), block.get("input", {})
    if name == "Bash":
        head = f"**Bash** — {inp.get('description', '')}".rstrip(" —")
        return head + "\n\n" + fence(clip(clean(inp.get("command", "")), 60), "bash")
    if name in ("Write",):
        body = clean(inp.get("content", ""))
        return f"**Write** `{clean(inp.get('file_path', ''))}` ({len(body.splitlines())} lines)\n\n" + fence(
            clip(body, 25)
        )
    if name == "Edit":
        return (
            f"**Edit** `{clean(inp.get('file_path', ''))}`\n\n"
            + fence(clip("- " + clean(inp.get("old_string", "")).replace("\n", "\n- "), 12), "diff")
            + "\n"
            + fence(clip("+ " + clean(inp.get("new_string", "")).replace("\n", "\n+ "), 20), "diff")
        )
    if name == "Read":
        return f"**Read** `{clean(inp.get('file_path', ''))}`"
    if name == "Skill":
        return f"**Skill** `{inp.get('skill')}`"
    return f"**{name}**\n\n" + fence(clip(clean(json.dumps(inp, indent=2)), 20), "json")


md = [
    "# Mission Control — Claude Code session transcript",
    "",
    "Rendered from the Claude Code session log. Includes every user message, every assistant reply, and each tool "
    "call with its input; long tool outputs and file contents are truncated (`... (N more lines)`). "
    "Hidden reasoning, internal system context and harness metadata are omitted; "
    "home-directory paths are shown as `~`.",
    "",
]
turn = 0
for raw in src.read_text().splitlines():
    try:
        d = json.loads(raw)
    except ValueError:
        continue
    if d.get("isMeta") or d.get("type") not in ("user", "assistant"):
        continue
    msg = d.get("message", {})
    content = msg.get("content")
    if d["type"] == "user":
        if isinstance(content, list) and any(b.get("type") == "tool_result" for b in content):
            for b in content:
                if b.get("type") == "tool_result":
                    t = tool_result_text(b)
                    if t:
                        md += ["<details><summary>output</summary>", "", fence(clip(t)), "", "</details>", ""]
            continue
        t = user_text(content)
        if t:
            turn += 1
            md += ["---", "", f"## User ({turn})", "", t, ""]
    else:
        for b in content or []:
            if b.get("type") == "text" and b.get("text", "").strip():
                md += ["### Assistant", "", clean(b["text"]), ""]
            elif b.get("type") == "tool_use":
                md += [tool_use(b), ""]
out.write_text("\n".join(md))
print(f"{turn} user turns, {len(md)} lines, {out.stat().st_size // 1024} KB")
