# Bili Comment Crawler

交互式 B 站视频评论爬取脚本。按终端提示依次选择模式、输入参数即可，无需修改代码。

> 本文档不记录版本号，以免每次改动都需同步；当前版本以脚本头部的横幅与变更记录为准。

## 功能特性

- 三种模式：全量爬取（一级 + 楼中楼）/ 仅一级评论 / 指定楼层深度爬取
- 三种排序：时间 / 热度 / 回复数
- Wbi 签名鉴权，密钥自动获取并缓存，签名错误自动刷新
- 断点续传：中断后重新运行自动恢复进度
- **自动并入置顶评论**：置顶评论不在接口返回的常规评论列表中，脚本单独抓取并按 `rpid` 去重后并入，标记 `is_top`；模式 1 也会拉取置顶楼层的楼中楼
- 楼中楼拉取失败的楼层可交互式重试
- 模式 3 支持树形 / 时间顺序展示，可连续爬取多个楼层
- 支持纯 BV 号、完整链接、b23.tv 短链接（自动解析）输入
- 模式 3 支持直接粘贴评论区评论链接，自动识别 BV 号与楼主 id（root_rpid）
- **保留评论正文配图**：JSON 输出 `pictures` / `pic_urls`，TXT 正文后追加图片链接，并统计含图评论数与图片总数
- 输出按视频标题自动归档到独立文件夹；view 接口完整信息存为 `信息.md`
- **自动读取本目录 `bilicookie.txt`（单行裸 Cookie），免手动输入；文件缺失时回退手动粘贴**
- **总耗时只统计真实爬取/处理时间**，等待你输入的秒数自动扣除
- 每次输出 JSON + TXT；三种速度预设；Cookie 自动检测；可选 tqdm 进度条

## 安装

- Python 3.10+
- 核心依赖：`pip install requests`
- 进度条（可选）：`pip install requests tqdm`

## 快速上手

```bash
python bilicmtcrawl.py
```

按提示依次：选择模式 → 输入 Cookie（或已配置 bilicookie.txt 则自动读取）→ 输入 BVID → 选择排序 → 选择速度 → 确认摘要 → 等待完成。结果保存在脚本同目录下、按视频标题命名的文件夹中。

## 爬取模式

### 模式 1：全量爬取

一级评论 + 所有楼中楼，数据最完整，适合存档与数据分析，耗时最长。

- 一级评论上限：500 页 × 20 条 = 10000 条（置顶评论不占此额度，会额外并入）
- 每楼层楼中楼上限：100 页 × 20 条 = 2000 条
- 失败楼层可在结束后交互式重试

### 模式 2：仅一级评论

只拉一级评论，速度快。适合快速概况、统计用户分布，或查找 `root_rpid` 供模式 3 使用。

### 模式 3：指定楼层深度爬取

输入 `root_rpid` 拉取该楼层全部楼中楼，支持树形 / 时间顺序展示。获取 `root_rpid`：

1. 评论区对目标评论点击“复制链接”，在步骤 3 粘贴，自动识别 BV 号与楼主 id，步骤 4 直接回车
2. 先跑模式 2，在 JSON 中搜索目标用户名，取其 `rpid`（`root=0` 即为根评论）
3. 直接输入纯数字（`comment_root_id=` / `#reply` 锚点 / `root=` 后的数字）

链接识别优先级：`comment_root_id=` → `#reply` → 纯数字。

## 排序方式

| 选项 | 排序 | 文件名短标签 | 说明 |
|---|---|---|---|
| 1 | 时间 (sort=0, nohot=1) | `time` | 最新在前，翻页上限最高，推荐全量 |
| 2 | 热度 (sort=1, nohot=0) | `hot` | 点赞最多在前，翻页有上限 |
| 3 | 回复数 (sort=2, nohot=0) | `reply` | 讨论最热烈在前，翻页有上限 |

## Cookie

两种方式任选：

1. **推荐**：将 Cookie 粘贴到脚本同目录的 `bilicookie.txt`（仅一行裸 Cookie，无任何标识），每次运行自动读取，免手动输入
2. 直接运行脚本，在步骤 2 手动粘贴（多行粘贴时连按两次回车结束）

需 B 站登录后的 Cookie，`SESSDATA` 必需（约 30 天有效）。过期后 API 返回 `code=-101`，脚本提示退出。

> 注意：`bilicookie.txt` 含登录凭证，请勿提交到公开仓库（建议加入 `.gitignore`）。

## 输出

输出目录自动创建（非法字符替换为 `_`，标题最长 60 字符，为空回退 `BV号_视频`）：

```
./<视频标题>/
├── 信息.md                                        # view 完整信息（概览表格 + 完整原始JSON）
├── comments_{BVID}_{time|hot|reply}_{时间戳}.json / .txt  # 模式 1/2（排序短标签）
├── replies_{BVID}_root{rpid}_{tree|flat}_{时间戳}.json / .txt  # 模式 3
└── checkpoint_*.json                              # 断点续传，成功后自动删除
```

- `信息.md` 每次运行覆盖为最新快照；评论与检查点文件追加累积、互不覆盖
- JSON 为完整结构化数据，TXT 为可读文本
- 评论正文配图：JSON 保留完整图片对象，TXT 在正文后追加 `🖼 图片链接`（仅 URL）
- 置顶评论：JSON 中 `is_top` 为 `true`；TXT 行首以 `[置顶]` 前缀标记；TXT 头部与终端汇总均含置顶条数
- 模式 3 的 JSON 中，`replies_flat` 为扁平列表（不含 `children` 字段），`reply_tree` 为树结构

JSON 结构（模式 1/2）：

```json
{
  "video": {"aid": 123, "bvid": "BV...", "title": "标题"},
  "stats": {"total": 1523, "root": 847, "sub": 676, "users": 523,
            "pic_comments": 42, "pic_total": 57, "top": 1},
  "comments": [
    {
      "rpid": 1234567890, "oid": 123, "root": 0, "parent": 0,
      "uname": "用户名", "uid": "12345678", "level": 6,
      "message": "评论内容",
      "pictures": [
        {"img_src": "https://...", "img_width": 1080, "img_height": 1440, "img_size": 123456}
      ],
      "pic_urls": ["https://..."],
      "like": 123, "ctime": 1705312200, "rcount": 5,
      "is_top": false
    }
  ]
}
```

| 字段 | 含义 |
|---|---|
| rpid | 评论唯一 ID |
| oid | 视频 AID |
| root | 根评论 rpid（0 = 一级评论） |
| parent | 被回复评论 rpid（0 = 回复根评论） |
| uname / uid | 用户名 / 用户 UID |
| level | 用户等级 |
| message | 评论内容（JSON 中始终完整） |
| pictures | 评论正文配图原始对象列表（img_src / img_width / img_height / img_size），无图为 `[]` |
| pic_urls | 评论正文纯图片链接列表（协议相对地址 `//` 已补全为 `https:`），无图为 `[]` |
| like | 点赞数 |
| ctime | 发布时间（Unix 时间戳） |
| rcount | 楼中楼回复数（仅一级评论） |
| is_top | 是否为置顶评论（`true` = 置顶；模式 3 恒为 `false`） |

> `stats` 中 `total` 为总评论数、`root` 为一级评论数、`sub` 为楼中楼数、`users` 为按 `uid` 去重后的用户数（uid 为空时回退用户名）、`pic_comments` 为含图评论数、`pic_total` 为图片总数、`top` 为置顶评论数（属 `total`/`root` 的子集，不额外计数）。模式 3 的 JSON/TXT 头部同样含图片统计。

## 断点续传

| 阶段 | 检查点文件 | 保存时机 |
|---|---|---|
| 模式 1 一级评论 | `checkpoint_{BVID}_root_{sort}.json` | 每 5 页 |
| 模式 2 一级评论 | `checkpoint_{BVID}_rootonly_{sort}.json` | 每 5 页 |
| 模式 1 楼中楼 | `checkpoint_{BVID}_replies_{sort}.json` | 每 5 条 |

启动时自动检测并恢复；模式 1 的一级评论检查点在**全流程（含楼中楼阶段）结束后**才清理，故在楼中楼阶段中断时该检查点会被保留、重跑直接复用（如需最新的一级评论数据，请先手动删除该检查点文件）；模式 2 的检查点在拉取结束后清理；损坏时自动忽略、从头开始；Ctrl+C 中断可恢复。

## 计时说明

末尾的「总耗时」只统计真实的爬取与处理时间：

- **计入**：网络请求、翻页、重试与退避休眠（这些都属于“真的在跑”）
- **不计入**：等待你键盘输入的时间（如模式 3 爬完后的“是否继续爬取另一个楼层？”、失败重试选择等）
- 口径：`总耗时 = 实际耗时 − 用户输入等待`，由 `timed_input()` 统一累计

## FAQ

- **报错 `No module named 'requests'`**：`pip install requests`
- **Cookie 无效或过期**：重新登录复制，确认包含 `SESSDATA`；或更新 `bilicookie.txt`
- **全量爬取选什么排序**：时间排序，翻页上限最高
- **怎么找 root_rpid**：粘贴评论链接自动识别 / 模式 2 搜 JSON / 手动输入数字
- **中断了怎么办**：直接重跑，自动从检查点恢复
- **评论内容被截断？**：终端与 TXT 按“字素簇”安全截断（避免劈开 emoji 与肤色修饰符），JSON 的 `message` 始终完整
- **评论配图在哪？**：JSON 的 `pictures`（完整对象）+ `pic_urls`（纯链接）；TXT 正文后有 `🖼` 链接行
- **置顶评论怎么识别？**：JSON 看 `is_top: true`，TXT 行首有 `[置顶]`；置顶本身是一级评论，模式 1 会继续拉取其楼中楼
- **总耗时为什么比墙钟时间短？**：等你输入的时间已扣除，它只反映真实爬取时间
- **输出的 JSON 文件名里 `time/hot/reply` 是什么**：排序短标签（时间/热度/回复数）
- **Windows 颜色异常**：使用 PowerShell / Windows Terminal / VS Code 终端
- **模式 3 粘贴链接后还要输数字吗**：链接含 `comment_root_id=` 或 `#reply` 时直接回车即可
- **不想每次手动输入 Cookie？**：把 Cookie 存到同目录 `bilicookie.txt`（一行裸 Cookie），自动读取；删除或改名该文件即恢复手动输入

## 交互示例（节选）

```
步骤2：Cookie
  ✅ 已自动读取本目录 bilicookie.txt

步骤3：输入视频BVID
  BVID: https://www.bilibili.com/video/BV1kxuw6iEb2?comment_on=1&comment_root_id=309041328033
  ✅ 识别到: BV1kxuw6iEb2，楼主id: 309041328033

步骤4：输入目标楼层 root_rpid
  💡 已从链接识别到楼主id: 309041328033，直接回车使用
  root_rpid: （直接回车）

步骤5：选择展示方式
  ...

步骤6：爬取速度设置
  ...

阶段A：拉取一级评论...
  第1页 +20条 → 累计20条 (0%)
  一级评论: 4940 条

爬取完成！总评论: 8542 一级: 4940 楼中楼: 3602 用户: 2310人 置顶: 1
  📁 保存目录: ./<视频标题>/
  总耗时: 856秒 (14.3分钟)
```

## 技术细节

| 项目 | 说明 |
|---|---|
| API 端点 | `/x/v2/reply`、`/x/v2/reply/reply`、`/x/v2/reply/detail`、`/x/web-interface/nav`、`/x/web-interface/view` |
| 认证方式 | Wbi 签名（w_rid + wts）+ Cookie（SESSDATA，可经 bilicookie.txt 自动读取） |
| 一级评论上限 | 500 页 × 20 条 = 10000 条（置顶评论不占此额度，会额外并入） |
| 楼中楼上限 | 100 页 × 20 条 = 2000 条/楼层 |
| 错误码处理 | 非零 code 视为失败返回 `None`；`-412` 刷新 Wbi 重试；`-509` 退避重试；`-101` 提示退出 |
| 用户统计 | 按 `uid` 去重（空则回退 `uname`） |
| 置顶评论 | 取自 `data.top_replies` 与 `data.top`（`admin`/`upper`），按 `rpid` 去重后并入；`data.replies` 中不含置顶 |
| 评论链接解析 | `comment_root_id=` → `#reply` → 纯数字 |
| 评论配图 | 取自 `content.pictures`，保留原始对象；`//` 相对地址补全为 `https:` |
| Wbi 密钥 | 缓存于 session，签名错误（-412）时自动刷新 |
| 计时 | `总耗时 = 实际耗时 − 用户输入等待`（`timed_input` 累计） |
| 输出目录 | 按视频标题自动命名，view 完整信息存为 `信息.md` |

请合理使用本脚本，尊重 B 站用户内容及平台规则，设置合理的爬取间隔，避免对服务器造成不必要的压力。
