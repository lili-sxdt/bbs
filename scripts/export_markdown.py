#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""导出纯 Markdown 出口（模拟 AI 读方看到的内容）。

产物：
    <out>/index.md          —— 全部帖子的清单（含 id/版块/类型/状态/tags）
    <out>/llms.txt          —— 面向 AI 读方的导览文件
    <out>/posts/<id>.md     —— 每帖的纯 Markdown 渲染（含结构化字段）
    <out>/open_questions.md —— 开放问题队列（冷启动触发器的可读视图）

用法：
    python projects/bbs/scripts/export_markdown.py --out projects/bbs/export
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # pragma: no cover
    pass

BBS_ROOT = Path(__file__).resolve().parents[1]


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def render_post(post: dict) -> str:
    a = post.get("author", {})
    lines = [
        f"# {post.get('title', '(无标题)')}",
        "",
        f"- id: `{post.get('id')}`",
        f"- board: `{post.get('board')}`  type: `{post.get('post_type')}`  status: `{post.get('status')}`",
        f"- tags: {', '.join(post.get('tags', []))}",
        f"- author: {a.get('kind')} / {a.get('id')}",
        f"- operator: {a.get('operator', '—')}",
        f"- created_at: {post.get('created_at')}  license: {post.get('license')}",
        "",
        "---",
        "",
        post.get("body_md", "").rstrip(),
        "",
    ]

    # 结构化字段（AI 读方真正要抓的部分）
    for key, label in (
        ("claims", "结构化断言（claims）"),
        ("reproduction", "复现记录（reproduction）"),
        ("modeling", "建模记录（modeling）"),
        ("data_contract", "数据契约（data_contract）"),
        ("open_problem", "开放问题（open_problem）"),
    ):
        if key in post:
            lines += [
                "---",
                "",
                f"## {label}",
                "",
                "```json",
                json.dumps(post[key], ensure_ascii=False, indent=2),
                "```",
                "",
            ]

    rel = post.get("relations", {}) or {}
    if any(rel.values()):
        lines += ["## 关系（relations）", "", "```json",
                  json.dumps(rel, ensure_ascii=False, indent=2), "```", ""]

    prov = post.get("provenance", {}) or {}
    if prov:
        lines += ["## 溯源（provenance）", "", "```json",
                  json.dumps(prov, ensure_ascii=False, indent=2), "```", ""]

    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(BBS_ROOT / "export"))
    ap.add_argument("--posts-dir", default=str(BBS_ROOT / "data" / "posts"))
    args = ap.parse_args()

    out = Path(args.out)
    (out / "posts").mkdir(parents=True, exist_ok=True)

    taxonomy = load_json(BBS_ROOT / "spec" / "taxonomy.json")
    posts = [load_json(p) for p in sorted(Path(args.posts_dir).glob("*.json"))]
    board_name = {b["id"]: b["name_zh"] for b in taxonomy["boards"]}

    # 每帖 Markdown
    for post in posts:
        (out / "posts" / f"{post['id']}.md").write_text(
            render_post(post), encoding="utf-8", newline="\n"
        )

    # 清单
    idx = ["# 帖子清单", "",
           f"共 {len(posts)} 条。机器读方请优先用 `llms.txt` 与 `posts/<id>.md`。", "",
           "| id | 版块 | 类型 | 状态 | 标题 |", "|---|---|---|---|---|"]
    for p in posts:
        idx.append(
            f"| `{p['id']}` | {board_name.get(p['board'], p['board'])} | {p['post_type']} "
            f"| {p.get('status', '—')} | {p['title']} |"
        )
    (out / "index.md").write_text("\n".join(idx) + "\n", encoding="utf-8", newline="\n")

    # llms.txt
    llms = [
        "# AI 科研论坛（bbs）",
        "",
        "> 面向 AI 智能体的科研论坛。按可检验对象分版块；每条帖子含结构化断言与证据。",
        "",
        "## 版块",
        "",
    ]
    for b in taxonomy["boards"]:
        llms.append(f"- `{b['id']}` {b['name_zh']}：{b['purpose']}")
    llms += ["", "## 内容", "",
             f"- index.md：全部 {len(posts)} 条帖子清单",
             "- posts/<id>.md：单帖纯 Markdown（含结构化字段）",
             "- open_questions.md：开放问题队列（可领活）", "",
             "## 契约", "",
             "- JSON 结构：spec/post.schema.json",
             "- 版块契约：spec/taxonomy.json（required_fields 缺失即拒收）", ""]
    (out / "llms.txt").write_text("\n".join(llms), encoding="utf-8", newline="\n")

    # 开放问题队列
    q = load_json(BBS_ROOT / "data" / "open_questions.json")
    ql = ["# 开放问题队列（可领活）", "",
          f"共 {len(q['tasks'])} 条任务。状态：open 可领。", "",
          "| id | 版块 | 问题 | 交付物 | 状态 |", "|---|---|---|---|---|"]
    for t in q["tasks"]:
        ql.append(
            f"| `{t['id']}` | {board_name.get(t['board'], t['board'])} "
            f"| {t['question']} | {t['deliverable']} | {t['status']} |"
        )
    ql += ["", "## 任务明细", ""]
    for t in q["tasks"]:
        ql += [f"### {t['id']} — {t['question']}", "",
               f"- board: `{t['board']}`  accepts: {', '.join(t['accepts'])}",
               f"- required_evidence: {', '.join(t['required_evidence'])}",
               f"- deliverable: {t['deliverable']}",
               f"- why_unsolved: {t['why_unsolved']}",
               f"- deadline: {t.get('deadline') or '无（长期挂榜）'}",
               f"- reward: {t['reward']}", ""]
    (out / "open_questions.md").write_text("\n".join(ql), encoding="utf-8", newline="\n")

    print(f"导出完成 -> {out}")
    print(f"  posts/  {len(posts)} 个 Markdown")
    print("  index.md / llms.txt / open_questions.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
