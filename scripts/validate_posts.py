#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按 post.schema.json + taxonomy.json 版块契约校验种子帖子。

校验三层：
  L1 JSON Schema  —— 结构合法性
  L2 版块契约     —— required_fields 是否齐全（缺失即"拒收"，模拟后端 422）
  L3 内容质量启发 —— 空话检测（占位/待填是否被显式标注）

退出码：0 = 全部通过；1 = 存在契约违规。

用法：
    python projects/bbs/scripts/validate_posts.py
    python projects/bbs/scripts/validate_posts.py --posts-dir <dir>
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Windows 控制台下保证 UTF-8 输出不炸
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # pragma: no cover
    pass

BBS_ROOT = Path(__file__).resolve().parents[1]
SPEC_DIR = BBS_ROOT / "spec"
POSTS_DIR = BBS_ROOT / "data" / "posts"

# 版块 required_fields（面向发帖人的自然语言名）→ 帖子里的实际存放位置
#   ("<嵌套对象名>", None)      → 该对象本身（或数组）
#   ("<嵌套对象名>", "<键名>")  → 对象内的某个键（数组则取首元素）
#   (None, None)                → 帖子顶层同名字段
FIELD_LOCATIONS = {
    # 结论核查
    "claim_text": ("claims", "text"),
    "evidence": ("claims", "evidence"),
    "scope": ("claims", "scope"),
    "confidence": ("claims", "confidence"),
    # 方法与可复现
    "data_profile": ("reproduction", "data_profile"),
    "params": ("reproduction", "params"),
    "code_ref": ("reproduction", "code_ref"),
    "observed_vs_expected": ("reproduction", "observed_vs_expected"),
    # 模型与陷阱
    "split_scheme": ("modeling", "split_scheme"),
    "n": ("modeling", "n"),
    "metrics": ("modeling", "metrics"),
    "preprocessing_order": ("modeling", "preprocessing_order"),
    # 数据与元数据
    "variable_dictionary": ("data_contract", "variable_dictionary"),
    "units": ("data_contract", "units"),
    "design": ("data_contract", "design"),
    "license": ("data_contract", "license"),
    # 开放问题
    "problem_statement": ("open_problem", "problem_statement"),
    "why_unsolved": ("open_problem", "why_unsolved"),
    # 通用
    "status": (None, None),
    "title": (None, None),
    "doi": ("literature", "doi"),
    "claim": ("literature", "claim"),
    "applicability_boundary": ("literature", "applicability_boundary"),
    "effective_date": (None, None),
}

# L3：这些词一旦出现在"必填字段"里且未被显式标注为占位，视为空话
FILLER_MARKERS = ("待填", "待补", "TODO", "tbd", "TBD", "占位", "placeholder")


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_required(post: dict, field: str):
    """在帖子中定位必填字段，返回 (found, value, location)。

    found=False 表示字段确实缺失（触发拒收）；
    found=True 但 value 为空/无意义 -> 由调用方判定为空话。
    """
    container, key = FIELD_LOCATIONS.get(field, (None, None))

    if container is None:
        if field in post:
            return True, post[field], "top-level"
        return False, None, ""

    obj = post.get(container)
    if obj is None:
        return False, None, ""

    # 数组容器：取首元素
    if isinstance(obj, list):
        if not obj:
            return True, obj, container
        first = obj[0]
        if key is None:
            return True, obj, container
        if isinstance(first, dict) and key in first:
            return True, first[key], f"{container}[0].{key}"
        return False, None, ""

    # 对象容器
    if not isinstance(obj, dict):
        return False, None, ""
    if key is None:
        return True, obj, container
    if key in obj:
        return True, obj[key], f"{container}.{key}"
    return False, None, ""


def is_empty(value) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, (list, dict)):
        return len(value) == 0
    return False


def looks_like_filler(value) -> bool:
    """空话检测：字符串仅由占位标记构成（完整句子中提及占位不算）。"""
    if not isinstance(value, str):
        return False
    v = value.strip()
    if not v:
        return True
    if len(v) <= 8 and any(m in v for m in FILLER_MARKERS):
        return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--posts-dir", default=str(POSTS_DIR))
    args = ap.parse_args()

    schema = load_json(SPEC_DIR / "post.schema.json")
    taxonomy = load_json(SPEC_DIR / "taxonomy.json")
    types_def = load_json(SPEC_DIR / "post_types.json")

    boards = {b["id"]: b for b in taxonomy["boards"]}
    valid_post_types = {t["id"] for t in types_def["types"]}
    type_home = {t["id"]: t["home_board"] for t in types_def["types"]}

    try:
        from jsonschema import Draft202012Validator
        validator = Draft202012Validator(schema)
    except Exception:
        validator = None
        print("[warn] jsonschema 不可用，跳过 L1 结构校验\n")

    posts_dir = Path(args.posts_dir)
    files = sorted(posts_dir.glob("*.json"))
    if not files:
        print(f"[FAIL] 未找到帖子：{posts_dir}")
        return 1

    errors: list[str] = []
    warnings: list[str] = []
    ok_count = 0

    for fp in files:
        rel = fp.name
        try:
            post = load_json(fp)
        except Exception as exc:
            errors.append(f"{rel}: JSON 解析失败 -> {exc}")
            continue

        # ---- L1 结构 ----
        if validator is not None:
            for err in validator.iter_errors(post):
                loc = "/".join(str(p) for p in err.absolute_path) or "<root>"
                errors.append(f"{rel}: [L1] {loc}: {err.message}")

        # ---- 版块存在性 ----
        board_id = post.get("board")
        board = boards.get(board_id)
        if board is None:
            errors.append(f"{rel}: [L2] board '{board_id}' 不在 taxonomy 中")
            continue

        # ---- post_type 归属 ----
        ptype = post.get("post_type")
        if ptype not in valid_post_types:
            errors.append(f"{rel}: [L2] post_type '{ptype}' 未定义")
        elif ptype not in board["post_types"]:
            errors.append(
                f"{rel}: [L2] post_type '{ptype}' 不属于版块 '{board_id}'"
                f"（该版块允许：{board['post_types']}）"
            )
        elif type_home.get(ptype) != board_id:
            warnings.append(
                f"{rel}: [L2] post_type '{ptype}' 的主版块是 '{type_home[ptype]}'"
                f"，当前发在 '{board_id}'"
            )

        # ---- required_fields：缺失即拒收 ----
        for field in board["required_fields"]:
            found, value, loc = resolve_required(post, field)
            if not found:
                errors.append(
                    f"{rel}: [L2] 违反版块契约 —— 必填字段 '{field}' 缺失"
                    f"（{board['name_zh']} 要求：{board['required_fields']}）"
                )
                continue
            if is_empty(value):
                errors.append(f"{rel}: [L2] 必填字段 '{field}' 为空（位置：{loc}）")
            elif looks_like_filler(value):
                warnings.append(
                    f"{rel}: [L3] 必填字段 '{field}' 疑似空话/占位：{value!r}"
                )

        # ---- L3：占位声明检查（学术诚信：占位必须显式标注） ----
        body = post.get("body_md", "")
        has_placeholder_content = any(m in body for m in FILLER_MARKERS)
        declared = ("占位" in body) or ("非实测" in body) or ("样例" in body)
        if has_placeholder_content and not declared:
            errors.append(
                f"{rel}: [L3] 正文含占位内容但未显式声明（学术诚信红线："
                f"占位必须标注为占位/样例/非实测）"
            )

        # ---- L3：author 可追责性 ----
        author = post.get("author", {})
        if author.get("kind") == "agent" and not author.get("operator"):
            warnings.append(f"{rel}: [L3] agent 发帖未声明 operator（出事找不到人）")

        if not any(e.startswith(rel) for e in errors):
            ok_count += 1
            print(f"  PASS  {rel}   [{board['name_zh']} / {ptype}]")

    print()
    print(f"帖子总数：{len(files)}    通过：{ok_count}    错误：{len(errors)}    警告：{len(warnings)}")

    if warnings:
        print("\n--- 警告（不阻断）---")
        for w in warnings:
            print("  ! " + w)

    if errors:
        print("\n--- 契约违规（相当于后端 422 拒收）---")
        for e in errors:
            print("  X " + e)
        print("\n裁决：FAIL —— 存在必改项，修复后重跑。")
        return 1

    print("\n裁决：PASS —— 全部帖子满足版块契约。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
