# 日常维护手册：拉 issue → 修 → 提交 → 关闭

本文件是给仓库维护者（也就是你）用的操作手册，不讲原理，只给可直接执行的命令。

---

## 零、一次性准备（只做一次）

### 0.1 让 `gh` 认到你自己的账号

`gh` 已经装好了（`GitHub.cli 2.104.0`），但还没登录。**推荐用浏览器登录，token 不经过任何人、不落盘到聊天记录**：

```bash
gh auth login
```

按提示选：

| 提问 | 选择 |
|---|---|
| What account do you want to log into? | `GitHub.com` |
| What is your preferred protocol for Git operations? | `HTTPS` |
| Authenticate Git with your GitHub credentials? | `Yes` |
| How would you like to authenticate? | **`Login with a web browser`** |

然后把终端显示的 8 位一次性代码填进弹出的网页即可。完成后验证：

```bash
gh auth status
gh api user --jq .login      # 应输出 peterbao906-droid
```

> 登录成功后凭据保存在系统凭据管理器里，**之后的 `gh` 命令和 `git push` 都不再需要 token**。
> 这也是为什么推荐这一步：以后每次修 issue 都不用再问任何人要 token。

### 0.2 确认工作区干净

```bash
cd "D:/喜马拉雅工作/Workbuddy/dumate-api-relay"
git status
```

---

## 一、拉取并查看 issue

### 1.1 列出所有待处理 issue

```bash
# 只看开着的
gh issue list

# 按标签过滤
gh issue list --label bug

# 看已关闭的
gh issue list --state closed --limit 30

# 带更多字段
gh issue list --state open --json number,title,labels,author,createdAt \
  --template '{{range .}}#{{.number}}  {{.title}}  [{{range .labels}}{{.name}} {{end}}]{{"\n"}}{{end}}'
```

### 1.2 读某个 issue 的完整内容

```bash
gh issue view 1                    # 编号看列表
gh issue view 1 --comments         # 连评论一起看
gh issue view 1 --web              # 直接在浏览器打开
```

### 1.3 在本地开一个分支来修

**不要直接在 `main` 上改。** 每个 issue 一个分支：

```bash
git checkout main
git pull                                  # 先把远端最新拉下来
git checkout -b fix/issue-1-启动失败       # 分支名带上 issue 号，方便回溯
```

---

## 二、修完之后的提交与关联

### 2.1 提交（关键：用 closing keyword 自动关联）

```bash
git add -A
git commit -m "fix: 修掉启动时端口占用未被检测到的问题

原来 start.py 只在启动后探活，端口被占用时抛的是裸 OS 错误。
现在启动前先 bind 试一次，失败给出明确提示。

Fixes #1"
```

`Fixes #1` 这个写法很重要：

- 先 **push + PR + merge** 到 `main` → GitHub 会自动关闭 issue #1
- 直接 push 到 `main` → 同样会自动关闭

可用的关键词（大小写不敏感，效果相同）：

| 写法 | 效果 |
|---|---|
| `Fixes #1` / `Fixed #1` / `Fix #1` | 合并时自动关闭 |
| `Closes #1` / `Closed #1` / `Close #1` | 合并时自动关闭 |
| `Resolves #1` / `Resolved #1` | 合并时自动关闭 |
| `Refs #1` / `See #1` | **只关联，不关闭**（还在做的时候用这个） |

一次关多个：`Fixes #1, #2, #3`（每个都要带 `#`，不能写成 `Fixes #1-3`）。

> 如果只想关联不想关，用 `Refs #1`；改完想手动关，见第四节。

### 2.2 推送

```bash
git push -u origin fix/issue-1-启动失败
```

如果用了 0.1 的 `gh auth login`，这里**不需要任何 token**。

### 2.3 开 PR 并关联 issue

```bash
gh pr create --fill --base main
```

`--fill` 会自动用 commit 信息当标题和正文（所以 commit 里的 `Fixes #1` 会被带进 PR）。
也可以手动写：

```bash
gh pr create \
  --title "fix: 启动前检测端口占用" \
  --body "修复 #1。变更点：...  \n\nFixes #1"
```

### 2.4 自己合并（个人仓库无需等 review）

```bash
gh pr merge --squash --delete-branch
```

合并后 issue 自动关闭，本地切回 `main`：

```bash
git checkout main && git pull
```

---

## 三、小改动快速流程（不起 PR）

只改几行、自己仓库、不需要留 PR 记录时，可以省掉 PR：

```bash
git checkout main
git pull
# ...改代码...
git add -A
git commit -m "fix: xxx

Fixes #3"
git push origin main
```

push 到默认分支后 issue 同样会因 `Fixes #3` 自动关闭。

---

## 四、不关 issue 的操作

### 4.1 手动关闭（不用代码关联）

```bash
gh issue close 3
gh issue close 3 --reason "not planned"       # 标记为不修
gh issue close 3 -c "已在 06055b9 修复，验证通过。"   # 关闭并留评论
```

### 4.2 回复 issue（不关）

```bash
gh issue comment 3 --body "已确认是客户端 1.0.92 引入的变更，正在修。"
gh issue comment 3 --body "能贴一下 \`python scripts/client.py --doctor\` 的输出吗？"
```

### 4.3 改标签 / 指派 / 加里程碑

```bash
gh issue edit 3 --add-label "bug" --add-label "confirmed"
gh issue edit 3 --remove-label "needs-triage"
gh issue edit 3 --add-assignee @me
gh issue edit 3 --milestone "v0.2"
gh issue reopen 3               # 重新打开
```

### 4.4 建 issue（自己记录 TODO 也用它）

```bash
gh issue create --title "支持 macOS" --body "需要重写进程环境变量读取..." --label enhancement
gh issue create --title "..." --body-file /tmp/body.md      # 长正文用文件
```

---

## 五、一次处理多个 issue 的推荐姿势

```bash
# 1. 看清单，挑一个
gh issue list --state open

# 2. 边看边改：先本地开分支
git checkout main && git pull
git checkout -b fix/issue-7

# 3. 改完提交（只关联不关，便于分多次提交）
git commit -am "refactor: 抽离端口探测逻辑

Refs #7"

# 4. 全部改完，最后一次提交带上关闭关键词，或直接手动关
git commit --allow-empty -m "chore: 收尾

Fixes #7"
```

> `git commit --allow-empty` 是个实用技巧：代码都提交完了，但还想留一条带 `Fixes #7` 的提交来触发自动关闭。

---

## 六、给 issue 打标签时本项目建议用哪几个

| 标签 | 含义 |
|---|---|
| `bug` | 确认是缺陷 |
| `needs-triage` | 新提交，待分类（模板默认打这个） |
| `enhancement` | 功能建议 |
| `client-version` | 因 DuMate 客户端升级导致失效 |
| `docs` | 文档问题 |
| `wontfix` | 明确不修 |
| `duplicate` | 与已有 issue 重复 |

批量建标签（如果仓库里没有）：

```bash
for l in "bug:d73a4a" "enhancement:a2eeef" "needs-triage:ededed" \
         "client-version:fbca04" "docs:0075ca" "wontfix:ffffff" "duplicate:cfd3d7"; do
  gh label create "${l%%:*}" --color "${l##*:}" --force
done
```

---

## 七、安全红线（务必遵守）

1. **issue 里绝不能贴 token / cookie / `auth.json` 内容**。本项目模板已经加了勾选项，但你回复别人时也要盯住，必要时编辑掉对方贴的敏感内容。
2. **修 issue 前先看是不是「客户端升级导致」**。这类问题（标签 `client-version`）往往不是代码 bug，而是 DuMate 内部结构变了，需要在 README 里更新版本说明。
3. **不要在 issue 里贴内网 IP 或内网穿透地址**。
4. 涉及安全漏洞（凭据泄露、鉴权绕过）的，**引导对方走 Security Advisory**，不要在原 issue 里公开讨论细节。

---

## 八、排障

| 现象 | 原因 / 解法 |
|---|---|
| `gh: command not found` | PATH 没有 `/c/Program Files/GitHub CLI`，重开终端，或 `export PATH="$PATH:/c/Program Files/GitHub CLI"` |
| `gh` 报 `API rate limit exceeded` | 未认证。执行 `gh auth login` |
| `git push` 要密码 | 没配凭据。`gh auth login` 时选 `Authenticate Git with your GitHub credentials? Yes`，或 `gh auth setup-git` |
| `gh pr merge` 报 `not mergeable` | 有冲突。`git checkout main && git pull`，在分支上 `git merge main` 解决后重推 |
| `Fixes #1` 没自动关 issue | 关键词必须在**被合并进默认分支的 commit 或 PR 描述**里；只写在 PR 评论里无效 |
| 想看某条 issue 的所有关联 PR | `gh issue view 1 --json projectItems,title` 或网页右侧 |
