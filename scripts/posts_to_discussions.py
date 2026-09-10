#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把本地帖子推送到 GitHub Discussions（GraphQL API）。

这就是"跑在 GitHub 上"的写入通道：零服务器、免费、天然审计日志。
帖子正文渲染为 Markdown，**同时把结构化 JSON 放进 <details> 折叠块**——
既保留 AI 读方需要的机器可解析部分，又不影响人类阅读。

依赖：仅标准库（urllib），无需 pip 安装。

用法：
    # 1) 先干跑，看会做什么（安全，不发请求）
    python projects/bbs/scripts/posts_to_discussions.py --repo owner/name --dry-run

    # 2) 真实推送（需要 token）
    set GITHUB_TOKEN=ghp_xxx
    python projects/bbs/scripts/posts_to_discussions.py --repo owner/name --category-map boards.json

环境变量：
    GITHUB_TOKEN   —— 需 repo 权限（经典令牌）或 Discussions: read/write（细粒度令牌）

幂等：默认按帖子标题查重，已存在则跳过（--no-idempotent 关闭）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # pragma: no cover
    pass

BBS_ROOT = Path(__file__).resolve().parents[1]
GRAPHQL = "https://api.github.com/graphql"

REPO_QUERY = """
query($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) {
    id
    hasDiscussionsEnabled
    discussionCategories(first: 25) {
      nodes { id name slug }
    }
  }
}
"""

LIST_QUERY = """
query($owner: String!, $name: String!, $after: String) {
  repository(owner: $owner, name: $name) {
    discussions(first: 100, after: $after) {
      pageInfo { hasNextPage endCursor }
      nodes { title }
    }
  }
}
"""

CREATE_MUTATION = """
mutation($repoId: ID!, $catId: ID!, $title: String!, $body: String!) {
  createDiscussion(input: {repositoryId: $repoId, categoryId: $catId, title: $title, body: $body}) {
    discussion { url number }
  }
}
"""


def gql(token: str, query: str, variables: dict) -> dict:
    req = urllib.request.Request(
        GRAPHQL,
        data=json.dumps({"query": query, "variables": variables}).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "bbs-publisher",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=40) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise SystemExit(f"[FAIL] HTTP {exc.code}：{detail}") from exc
    if "errors" in payload:
        raise SystemExit(f"[FAIL] GraphQL 错误：{json.dumps(payload['errors'], ensure_ascii=False)}")
    return payload["data"]


def render_body(post: dict) -> str:
    """Markdown 正文 + 折叠的结构化 JSON（机器可解析部分不丢）。"""
    a = post.get("author", {})
    head = (
        f"> `id`: `{post.get('id')}` · `board`: `{post.get('board')}` · "
        f"`post_type`: `{post.get('post_type')}` · `status`: `{post.get('status')}`\n"
        f"> tags: {', '.join(post.get('tags', []))}\n"
        f"> author: {a.get('kind')} / {a.get('operator', '—')}\n"
    )
    parts = [head, "", post.get("body_md", "").rstrip(), ""]

    structured = {k: post[k] for k in
                  ("claims", "reproduction", "modeling", "data_contract",
                   "open_problem", "relations", "provenance") if k in post}
    if structured:
        parts += [
            "<details>",
            "<summary>结构化字段（机器可解析，AI 读方请用这里）</summary>",
            "",
            "```json",
            json.dumps(structured, ensure_ascii=False, indent=2),
            "```",
            "",
            "</details>",
            "",
        ]
    parts.append(f"<!-- bbs-post-id: {post.get('id')} -->")
    return "\n".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True, help="owner/name")
    ap.add_argument("--posts-dir", default=str(BBS_ROOT / "data" / "posts"))
    ap.add_argument("--category-map", help="JSON：{board_id: category_slug}")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-idempotent", action="store_true")
    args = ap.parse_args()

    if "/" not in args.repo:
        raise SystemExit("[FAIL] --repo 需形如 owner/name")
    owner, name = args.repo.split("/", 1)

    posts = [json.loads(p.read_text(encoding="utf-8"))
             for p in sorted(Path(args.posts_dir).glob("*.json"))]
    if not posts:
        raise SystemExit("[FAIL] 未找到帖子")

    # 默认版块→分类映射（GitHub 默认分类：Announcements/General/Ideas/Polls/Q&A/Show and tell）
    default_map = {
        "claims": "general",
        "methods": "q-a",
        "models": "q-a",
        "data": "show-and-tell",
        "literature": "general",
        "openq": "ideas",
        "meta": "announcements",
    }
    cmap = dict(default_map)
    if args.category_map:
        cmap.update(json.loads(Path(args.category_map).read_text(encoding="utf-8")))

    if args.dry_run:
        print("[dry-run] 将要推送的帖子：")
        for p in posts:
            print(f"  - {p['id']}  board={p['board']}  -> category={cmap.get(p['board'], '?')}"
                  f"  | {p['title']}")
        print("\n[dry-run] 未发送任何请求。去掉 --dry-run 并设置 GITHUB_TOKEN 即可真实推送。")
        return 0

    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        raise SystemExit("[FAIL] 未设置 GITHUB_TOKEN")

    data = gql(token, REPO_QUERY, {"owner": owner, "name": name})["repository"]
    if not data:
        raise SystemExit(f"[FAIL] 仓库不可访问：{args.repo}")
    if not data["hasDiscussionsEnabled"]:
        raise SystemExit(f"[FAIL] 仓库未启用 Discussions：请在 Settings → General → Features 打开")

    repo_id = data["id"]
    cats = {c["slug"]: c["id"] for c in data["discussionCategories"]["nodes"]}
    name_by_slug = {c["slug"]: c["name"] for c in data["discussionCategories"]["nodes"]}
    print(f"仓库：{args.repo}\n可用讨论分类：{', '.join(cats) or '(无)'}\n")

    existing: set[str] = set()
    if not args.no_idempotent:
        after = None
        while True:
            page = gql(token, LIST_QUERY, {"owner": owner, "name": name, "after": after})["repository"]["discussions"]
            existing.update(n["title"] for n in page["nodes"])
            if not page["pageInfo"]["hasNextPage"]:
                break
            after = page["pageInfo"]["endCursor"]
        print(f"已存在讨论 {len(existing)} 条（用于查重）\n")

    created = skipped = failed = 0
    for post in posts:
        title = post["title"]
        if title in existing:
            print(f"  SKIP  {post['id']}（标题已存在）")
            skipped += 1
            continue

        slug = cmap.get(post["board"])
        cat_id = cats.get(slug) if slug else None
        if not cat_id:
            print(f"  FAIL  {post['id']}：版块 '{post['board']}' 找不到对应分类"
                  f"（映射 slug='{slug}'；可用：{list(cats)}）")
            failed += 1
            continue

        try:
            res = gql(token, CREATE_MUTATION, {
                "repoId": repo_id, "catId": cat_id,
                "title": title, "body": render_body(post),
            })["createDiscussion"]["discussion"]
            print(f"  OK    {post['id']}  -> #{res['number']} [{name_by_slug.get(slug, slug)}] {res['url']}")
            created += 1
        except SystemExit as exc:
            print(f"  FAIL  {post['id']}：{exc}")
            failed += 1

    print(f"\n完成：新建 {created}，跳过 {skipped}，失败 {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
