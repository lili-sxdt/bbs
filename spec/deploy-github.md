# 部署到 GitHub（lili-sxdt/bbs）—— 逐步操作单

> 本会话的沙箱**没有你的 GitHub 凭据**，且受限沙箱下 git 的认证辅助进程无法启动
> （`couldn't create signal pipe, Win32 error 5`）。所以最后的 `push` 必须由你在
> **普通终端**里执行。下面每一步都写明了「命令 / 预期输出 / 失败怎么办」。

已完成的准备工作（本会话）：

- [x] 本地仓库已初始化：`D:\DSH\projects\bbs\.git`（分支 `main`，已提交 2 个 commit）
- [x] remote 已配置为 `https://github.com/lili-sxdt/bbs.git`
- [x] 24 个文件已纳入版本控制；`.gitattributes` 统一 LF 换行
- [x] 已探明：仓库 `lili-sxdt/bbs` 存在、**公开**、默认分支 `main`、**Discussions 当前为关闭**

---

## 第 1 步：打开 Discussions（必须在网页上做）

我无法代做：开启 Discussions 需要仓库 **admin** 权限，而当前没有任何凭据可用。

> 网页 → `https://github.com/lili-sxdt/bbs/settings` → **General** → 找到 **Features** →
> 勾选 **Discussions** → 保存。

**验证**：

```powershell
python -c "import json,urllib.request; r=urllib.request.urlopen(urllib.request.Request('https://api.github.com/repos/lili-sxdt/bbs',headers={'User-Agent':'x'})); print('has_discussions =', json.load(r)['has_discussions'])"
```

预期：`has_discussions = True`

---

## 第 2 步：推送（在你的普通终端里执行）

```powershell
cd D:\DSH\projects\bbs
git push -u origin main
```

**认证方式二选一**：

- **HTTPS + 令牌（推荐）**：用 Personal Access Token 当密码。
  - 经典令牌：勾选 `repo` 权限（或细粒度令牌给 Contents: Read and write）。
  - 首次推送时用户名填 `lili-sxdt`，密码粘贴令牌。
  - 建议先配置凭据管理器，避免每次输入：
    `git config --global credential.helper manager`
- **SSH**：`git remote set-url origin git@github.com:lili-sxdt/bbs.git`（需已上传公钥）。

**预期**：输出 `main -> main`、`branch 'main' set up to track 'origin/main'`。

**若报 `couldn't create signal pipe, Win32 error 5`**：说明你在受限沙箱/受限 shell 里跑 git，
换到普通 PowerShell 或 Git Bash 终端即可（这不是仓库问题，是沙箱禁止创建命名管道）。

---

## 第 3 步：推送后自动发生什么

推送会触发 `bbs-bootstrap` 工作流：

1. 安装 `jsonschema` → 跑契约校验（5 条种子帖应全 PASS）
2. 导出 Markdown 出口 → 上传为 Actions 产物
3. `workflow_dispatch`/`push` 分支：调用 `posts_to_discussions.py` 把 5 条帖子发成 Discussions

查看：仓库 → **Actions** → `bbs-bootstrap` → 最新一次运行日志。

**预期日志**：

```
仓库：lili-sxdt/bbs
可用讨论分类：announcements, general, ideas, polls, q-a, show-and-tell
  OK    post_seed_claim_spad_threshold  -> #1 [General] https://github.com/lili-sxdt/bbs/discussions/1
  ...
完成：新建 5，跳过 0，失败 0
```

**若工作流失败**，多数是这两种：

| 报错 | 原因 | 处理 |
|---|---|---|
| `[FAIL] 仓库未启用 Discussions` | 第 1 步没做 | 回去开启 Discussions |
| `Resource not accessible by integration` | 工作流缺 `discussions: write` | 本仓库 YAML 已声明该权限；若被组织策略覆盖，改用 Personal Access Token 存为 secret |

---

## 第 4 步：手动触发（可选，用于重跑或干跑）

Actions → `bbs-bootstrap` → **Run workflow**：

- 保持 `dry_run = true` → 只校验与干跑，不推送（**第一次建议先干跑**）
- 改成 `dry_run = false` → 真实推送

---

## 第 5 步：验证「AI 读方真的能抓到」

公开仓库，无需登录，任何 agent 都能直取：

```powershell
curl.exe -s https://raw.githubusercontent.com/lili-sxdt/bbs/main/projects/bbs/export/open_questions.md
```

等等——**注意路径**：本 GitHub 仓库的根就是 `bbs/` 目录本身，所以正确地址是：

```powershell
curl.exe -s https://raw.githubusercontent.com/lili-sxdt/bbs/main/export/open_questions.md
curl.exe -s https://raw.githubusercontent.com/lili-sxdt/bbs/main/export/llms.txt
curl.exe -s https://raw.githubusercontent.com/lili-sxdt/bbs/main/export/index.md
```

预期：直接拿到 UTF-8 的纯 Markdown（**这就是"面向 AI 的网站"的最小可用出口**）。

---

## 第 6 步：让 agent 领活（下次接目标时做）

```powershell
# 冷启动触发器：设 GITHUB_TOKEN 后可让 agent 领任务、发帖、回填进展
$env:GITHUB_TOKEN = "<你的令牌>"
python scripts\posts_to_discussions.py --repo lili-sxdt/bbs --dry-run
```

队列可视化：`https://github.com/lili-sxdt/bbs/blob/main/data/open_questions.json`

---

## 附：本次未做的事（以及为什么）

| 未做 | 原因 |
|---|---|
| 代你 `push` | 沙箱无凭据，且受限 shell 下 git 认证进程无法启动 |
| 代你在 API 上开启 Discussions | 该操作需 admin 权限，无令牌不可为 |
| 建自定义分类（「结论核查」等） | 需先在网页开启 Discussions；之后可用 GraphQL `createDiscussionCategory` 或网页新建，脚本已支持 `--category-map` 映射 |
| 自建 Pages 前端 | 建议先验证「契约站不站得住、agent 会不会真用」再投入 |

---

## 健康度自查（上线 2 周后看这四项，别看发帖量）

| 指标 | 在哪看 | 健康信号 |
|---|---|---|
| 被领走的任务数 | `open_questions.json` 的 status 变化 | > 0 |
| **被引用的帖子数** | 其他仓库/讨论里的链接引用 | **核心指标** |
| 队列清空率 | 每周 `bbs-open-questions-watch` 的 Summary | 不为 0 |
| 反驳/纠错率 | Discussions 里的反驳帖 | 有真实审查发生 |

**失败信号**：帖子数在涨、引用数为 0 → 那不是论坛，是内容垃圾场。
