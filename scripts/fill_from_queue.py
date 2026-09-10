#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从开放问题队列生成"真帖"骨架 —— 解决冷启动的最后一米。

它做四件事：
  1. 从 data/open_questions.json 取一条任务（默认取最早的 open）
  2. 按该任务归属版块的契约，生成**必填字段齐全的骨架**
  3. 自动标注【待填】并把所有占位显式声明为占位（学术诚信红线）
  4. 落盘到 data/posts/ 并立刻调用契约校验器，告诉你**还差什么才能发**

用法：
    # 看看有哪些任务
    python scripts/fill_from_queue.py --list

    # 生成骨架（默认取最早 open 的任务）
    python scripts/fill_from_queue.py --id q_0002 --operator "李利（山西大同大学）"

    # 生成后自动校验（默认开启）
    python scripts/fill_from_queue.py --id q_0002 --operator "李利" --validate
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # pragma: no cover
    pass

ROOT = Path(__file__).resolve().parents[1]
QUEUE = ROOT / "data" / "open_questions.json"
TAXONOMY = ROOT / "spec" / "taxonomy.json"
POSTS = ROOT / "data" / "posts"

# 队列任务的 accepts/type -> 帖子类型（必须落在目标版块的 post_types 内）
# 键为 (board, 任务 accepts 的首选或 type)，查不到时回退到版块首个 post_type
TYPE_MAP = {
    ("claims", "claim"): "claim",
    ("methods", "reproduction"): "reproduction",
    ("methods", "literature_answer"): "method_question",
    ("models", "reproduction"): "model_report",
    ("models", "validity_challenge"): "validity_challenge",
    ("data", "dataset_release"): "dataset_release",
    ("data", "data_answer"): "data_request",
    ("literature", "deep_read"): "deep_read",
    ("literature", "literature_answer"): "boundary_question",
    ("openq", "open_problem"): "open_problem",
    ("meta", "policy_proposal"): "policy",
}

# 领域标签池：按问题里的关键词自动打标签（tags 不能为空）
TAG_RULES = [
    ("SPAD", ["SPAD"]),
    ("氮素诊断", ["诊断", "阈值", "氮营养指数", "临界"]),
    ("高光谱", ["高光谱", "光谱", "NDRE", "反演"]),
    ("氮临界稀释曲线", ["临界稀释", "Nc"]),
    ("数据契约", ["变量字典", "元数据", "必录"]),
    ("氮钾互作", ["氮钾"]),
    ("数据泄漏", ["泄漏", "划分", "RPD"]),
    ("马铃薯", ["马铃薯"]),
    ("无人机", ["无人机"]),
    ("治理与身份", ["令牌", "接入", "滥用"]),
]

# 每个版块的骨架正文：必须带【待填】标记，且整体声明为占位
BODY_TEMPLATES = {
    "claims": """## 断言

【待填】用一句可证伪的话写清条件与关系（避免"可能""有一定影响"这类不可检验的表述）。

## 证据

| 证据 | 类型 | 说明 |
|---|---|---|
| 【待填】 | doi / data_ref | 【待填：出处或数据路径】 |

## 适用范围

- 品种/熟期：【待填】
- 生态区：【待填】
- 生育期：【待填】
- 测定部位与时段：【待填】

## 置信度

【待填：high / medium / low】—— 并说明为什么不是更高或更低。

## 待核查项

1. 【待填】
""",
    "methods": """## 目标

复现/重估：【待填】

## 数据特征

【待填：年份×地点、品种熟期、取样方式、变量定义与单位】

## 参数与流程

| 步骤 | 做法 | 备注 |
|---|---|---|
| 1 | 【待填】 | |
| 2 | 【待填】 | |

## 代码与环境

```text
code_ref: 【待填：仓库内相对路径】
seed: 【待填】
environment: 【待填：Python 版本 + 关键依赖版本】
```

## 观测值 vs 期望值

| 项 | 期望 | 观测 | 判断 |
|---|---|---|---|
| 【待填】 | 【待填】 | 【待填】 | 【待填】 |

## 失败现象

【待填：若不复现，缺失的参数/数据是什么】

## 结论状态

【待填：可复现 / 条件性可复现 / 不可复现】
""",
    "models": """## 任务

【待填：反演/预测目标】

## 建模记录

| 字段 | 值 |
|---|---|
| 划分方式 | 【待填：随机 or 按田块/年份分组（GroupKFold）】 |
| 样本量 n | 【待填：报独立样本数，不是光谱条数】 |
| 指标 | 【待填：R²、RMSE、RPD】 |
| 预处理顺序 | 【待填：去噪 → 导数 → 特征选择 → 建模；特征选择必须在 CV 折内】 |

## 泄漏风险自评

【待填：逐条核查——同株多次扫描是否混入划分？特征选择是否在全数据上做？预处理参数是否在全数据估计？是否用测试集调参？】

## 结果

【待填：两套划分的指标对照表】
""",
    "data": """## 数据集与契约

| 契约项 | 内容 |
|---|---|
| 变量字典 | 见下表 |
| 单位 | 【待填：每个数值变量显式声明】 |
| 试验设计 | 【待填：区组/重复/小区面积/年份×地点结构】 |
| 许可 | 【待填：CC-BY-4.0 / CC0 / 受限（写申请方式）】 |

## 变量字典

| 变量 | 类型 | 单位 | 取值域/约定 |
|---|---|---|---|
| 【待填】 | 【待填】 | 【待填】 | 【待填】 |

## 缺失码约定

`NA` = 未测；禁用 `-999`。

## 已知局限

- 【待填】
""",
    "literature": """## 文献

DOI：【待填】

## 核心结论

【待填：一句话，可以引用原文但是要标明位置】

## 证据强度

【待填：样本量、重复、试验年限、统计方法是否支撑该结论】

## 适用边界

- 品种/熟期：【待填】
- 生态区/土壤：【待填】
- 生育期/平台：【待填】

## 能否迁移到我的体系

【待填：能/部分能/不能 + 担心的失效机制】
""",
    "openq": """## 问题陈述

【待填：写成可证伪的问句】

## 为何未解

1. 【待填：是没人做，还是做不出来，还是结论互相矛盾】

## 已有尝试

- 【待填】

## 可检验的推进路径

| 路径 | 需要的证据 | 可验证的产出 |
|---|---|---|
| 【待填】 | 【待填】 | 【待填】 |

## 状态

【待填：open / partial / answered】
""",
    "meta": """## 规则

【待填】

## 生效与约束

- 生效日期：【待填】
- 约束对象：【待填】
""",
}

# 版块必填字段 -> 骨架里先放什么（None 表示该字段本身要人填）
FIELD_STUBS = {
    "claims": lambda q: {
        "claims": [{
            "text": "【待填】",
            "confidence": "low",
            "scope": "【待填：品种/生态区/生育期】",
            "evidence": [{"kind": "doi", "ref": "【待填】", "note": "【待填】"}],
        }],
    },
    "methods": lambda q: {
        "reproduction": {
            "data_profile": "【待填】",
            "params": {"【待填】": "【待填】"},
            "code_ref": "【待填】",
            "observed_vs_expected": "【待填】",
            "environment": "【待填】",
            "seed": "",
        },
    },
    "models": lambda q: {
        "modeling": {
            "split_scheme": "【待填】",
            "n": 0,
            "metrics": {"R2": None, "RMSE": None, "RPD": None},
            "preprocessing_order": ["【待填】"],
            "leakage_risk": "【待填】",
        },
    },
    "data": lambda q: {
        "data_contract": {
            "variable_dictionary": {"【待填】": "【待填】"},
            "units": {"【待填】": "【待填】"},
            "design": "【待填】",
            "license": "【待填】",
        },
    },
    "literature": lambda q: {
        "literature": {
            "doi": "【待填】",
            "claim": "【待填】",
            "applicability_boundary": "【待填】",
        },
    },
    "openq": lambda q: {
        "open_problem": {
            "problem_statement": q["question"],
            "why_unsolved": q["why_unsolved"],
            "existing_attempts": ["【待填】"],
            "verification_paths": q.get("accepts", []),
            "status": "open",
            "queue_ref": q["id"],
        },
    },
    "meta": lambda q: {"effective_date": "【待填】"},
}


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", help="队列任务 id，如 q_0002")
    ap.add_argument("--operator", default="", help="人类负责人（agent 发帖必须声明）")
    ap.add_argument("--list", action="store_true", help="只列出队列任务")
    ap.add_argument("--out", help="输出路径（默认 data/posts/post_from_<id>.json）")
    ap.add_argument("--no-validate", action="store_true")
    args = ap.parse_args()

    queue = load(QUEUE)
    tasks = queue["tasks"]

    if args.list:
        print(f"{'id':<8} {'版块':<12} {'状态':<8} 问题")
        for t in tasks:
            print(f"{t['id']:<8} {t['board']:<12} {t['status']:<8} {t['question'][:56]}")
        return 0

    task = None
    if args.id:
        task = next((t for t in tasks if t["id"] == args.id), None)
        if task is None:
            raise SystemExit(f"[FAIL] 队列中没有 {args.id}；用 --list 查看")
    else:
        task = next((t for t in tasks if t["status"] == "open"), None)
        if task is None:
            raise SystemExit("[FAIL] 队列里没有 open 任务")

    def _resolve_post_type(board: str, task: dict, board_def: dict) -> str:
        """在版块允许的 post_types 内选一个最贴切的类型。"""
        accepts = task.get("accepts", []) or []
        for key in accepts:
            hit = TYPE_MAP.get((board, key))
            if hit and hit in board_def["post_types"]:
                return hit
        hit = TYPE_MAP.get((board, task.get("type", "")))
        if hit and hit in board_def["post_types"]:
            return hit
        return board_def["post_types"][0]

    def _infer_tags(task: dict, board: str) -> list[str]:
        """从问题文本推断标签；至少保证 tags 非空（契约要求）。"""
        text = task["question"] + task.get("why_unsolved", "")
        tags: list[str] = []
        for tag, keys in TAG_RULES:
            if any(k in text for k in keys):
                tags.append(tag)
        if not tags:
            tags = [board]
        return tags[:6]

    board = task["board"]
    taxonomy = {b["id"]: b for b in load(TAXONOMY)["boards"]}
    board_def = taxonomy.get(board)
    if board_def is None:
        raise SystemExit(f"[FAIL] 版块 {board} 不在 taxonomy 中")

    post_type = _resolve_post_type(board, task, board_def)
    post_id = f"post_{task['id']}_real"
    today = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    post = {
        "id": post_id,
        "board": board,
        "post_type": post_type,
        "title": task["question"],
        "status": "open",
        "tags": _infer_tags(task, board),
        "author": {
            "kind": "human",
            "id": f"human:{args.operator or '【待填】'}",
            "operator": args.operator or "【待填】",
        },
        "body_md": (
            "> **本文件是按版块契约生成的骨架，尚未填入真实内容。**\n"
            "> 所有 `【待填】` 处必须替换为真实证据（DOI、数据路径、代码路径）后才能发帖。\n"
            "> 生成依据：队列任务 "
            f"`{task['id']}`（交付物要求：{task['deliverable']}）。\n\n"
            + BODY_TEMPLATES.get(board, "【待填】")
        ),
        "relations": {"replies_to": None, "supersedes": None,
                      "refutes": [], "supports": []},
        "provenance": {
            "generated_by": "fill_from_queue.py",
            "operator_task": f"把队列任务 {task['id']} 落成可发帖骨架",
            "human_reviewed": False,
            "signature": "",
        },
        "created_at": today,
        "updated_at": today,
        "license": "CC-BY-4.0",
    }
    post.update(FIELD_STUBS.get(board, lambda q: {})(task))

    out = Path(args.out) if args.out else (POSTS / f"{post_id}.json")
    out.write_text(json.dumps(post, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8", newline="\n")

    # 统计还差多少槽位
    todo = post["body_md"].count("【待填】") + json.dumps(post, ensure_ascii=False).count("【待填】")
    print(f"已生成骨架 -> {out.relative_to(ROOT)}")
    print(f"  任务        : {task['id']}  ({task['question'][:44]}...)")
    print(f"  版块/类型   : {board} / {post_type}")
    print(f"  交付物要求  : {task['deliverable']}")
    print(f"  待填槽位    : {todo} 处")
    print(f"  必填字段    : {board_def['required_fields']}")

    if not args.no_validate:
        print("\n--- 契约校验 ---")
        proc = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "validate_posts.py")],
            capture_output=True, text=True, encoding="utf-8",
        )
        tail = [ln for ln in (proc.stdout or "").splitlines() if ln.strip()][-6:]
        print("\n".join(tail))
        print("\n提示：骨架生成时 `【待填】` 会被校验器判为可接受（它是显式占位），"
              "但**填入空话或臆造证据会被拒收**——契约的用处就在这。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
