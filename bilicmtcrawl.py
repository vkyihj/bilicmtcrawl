#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════╗
║     B站视频评论爬取 · 交互式整合脚本 v3.3.5              ║
║     （Bili Comment Crawler）                              ║
║                                                            ║
║  模式1 - 全量爬取（一级评论 + 所有楼中楼）                  ║
║  模式2 - 仅爬取一级评论（不含楼中楼）                       ║
║  模式3 - 指定楼层深度爬取（树形 or 时间顺序展示）           ║
║                                                            ║
║  支持：时间排序 / 热度排序 / 回复数排序                     ║
║  特性：断点续传 · Wbi签名 · 反风控 · 回复树构建             ║
║        Cookie自动读取bilicookie.txt · 输出按视频标题归档    ║
╚══════════════════════════════════════════════════════════════╝

v3.3.5 变更记录：
  - 新增自动读取 Cookie：运行前将 Cookie 粘贴到本目录 bilicookie.txt
    （仅一行裸Cookie，无任何标识），脚本自动读取，无需每次手动输入
  - bilicookie.txt 不存在或为空时，自动回退为原交互式粘贴输入
  - 兼容处理：自动剥离文件内容中的 "Cookie:" 前缀、首尾引号与 BOM


用法：python bilicmtcrawl.py
      然后按终端提示依次选择/输入即可，无需修改任何代码
"""

import requests
import time
import json
import os
import sys
import hashlib
import urllib.parse
import random
import re
from functools import reduce
from datetime import datetime
from collections import Counter

# --- tqdm 可选依赖（未安装时自动降级为无进度条）---
try:
    from tqdm import tqdm
    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False
    class _DummyTqdm:
        def __init__(self, iterable=None, **kwargs):
            self.iterable = iterable
            self.total = kwargs.get('total', None)
            self.n = 0
        def __iter__(self):
            for item in self.iterable:
                self.n += 1
                yield item
        def update(self, n=1): pass
        def set_description(self, desc): pass
        def set_postfix(self, *args, **kwargs): pass
        def close(self): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
    def tqdm(iterable=None, **kwargs):
        return _DummyTqdm(iterable=iterable)

# ============================================================
# 终端颜色（Termux / Linux / macOS 通用）
# ============================================================

class Ansi:
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    MAGENTA = '\033[95m'
    BOLD = '\033[1m'
    DIM = '\033[2m'
    RESET = '\033[0m'

    @staticmethod
    def green(s):   return f"{Ansi.GREEN}{s}{Ansi.RESET}"
    @staticmethod
    def yellow(s):  return f"{Ansi.YELLOW}{s}{Ansi.RESET}"
    @staticmethod
    def red(s):     return f"{Ansi.RED}{s}{Ansi.RESET}"
    @staticmethod
    def blue(s):    return f"{Ansi.BLUE}{s}{Ansi.RESET}"
    @staticmethod
    def cyan(s):    return f"{Ansi.CYAN}{s}{Ansi.RESET}"
    @staticmethod
    def magenta(s): return f"{Ansi.MAGENTA}{s}{Ansi.RESET}"
    @staticmethod
    def bold(s):    return f"{Ansi.BOLD}{s}{Ansi.RESET}"
    @staticmethod
    def dim(s):     return f"{Ansi.DIM}{s}{Ansi.RESET}"

def cprint(color_func, text):
    """带颜色打印"""
    print(color_func(text))

# ============================================================
# 全局常量
# ============================================================

MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52
]

BASE_HEADERS = {
    'Referer': 'https://www.bilibili.com',
    'Origin': 'https://www.bilibili.com',
}

USER_AGENTS = [
    'Mozilla/5.0 (Linux; Android 13; SM-S9080) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Mobile Safari/537.36',
    'Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.6167.101 Mobile Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Linux; Android 13; SM-G996B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.6045.163 Mobile Safari/537.36',
]

MAX_PAGES = 500
MAX_SUB_PAGES = 100

SORT_OPTIONS = {
    '1': {'label': '🕐 时间排序（最新在前，翻页上限最高，推荐全量爬取）', 'sort': 0, 'nohot': 1},
    '2': {'label': '🔥 热度排序（点赞最多在前，翻页有上限）',           'sort': 1, 'nohot': 0},
    '3': {'label': '💬 回复数排序（讨论最热烈在前）',                   'sort': 2, 'nohot': 0},
}

SPEED_OPTIONS = {
    '1': {'label': '🚀 快速（主间隔 0.8~1.5s，楼中楼 0.5~1.0s，风险较高）',
          'main_min': 0.8, 'main_max': 1.5, 'sub_min': 0.5, 'sub_max': 1.0},
    '2': {'label': '⚖️ 正常（主间隔 1.5~3.0s，楼中楼 0.8~1.5s，推荐）',
          'main_min': 1.5, 'main_max': 3.0, 'sub_min': 0.8, 'sub_max': 1.5},
    '3': {'label': '🐢 慢速（主间隔 3.0~6.0s，楼中楼 1.5~3.0s，最安全）',
          'main_min': 3.0, 'main_max': 6.0, 'sub_min': 1.5, 'sub_max': 3.0},
}

# 当前速度配置（在 main 中由用户选择后赋值）
MAIN_DELAY_MIN, MAIN_DELAY_MAX = 1.5, 3.0
SUB_DELAY_MIN, SUB_DELAY_MAX = 0.8, 1.5

DISPLAY_OPTIONS = {
    '1': {'label': '🌲 树形结构（按回复关系层级展示，最直观）', 'mode': 'tree'},
    '2': {'label': '🕐 时间顺序（扁平列表，按发布时间排列）',  'mode': 'flat'},
}

# ============================================================
# 工具函数
# ============================================================

def parse_cookie(cookie_str: str) -> dict:
    """将分号分隔的Cookie字符串转为字典"""
    cookies = {}
    for item in cookie_str.split(';'):
        item = item.strip()
        if '=' in item:
            key, value = item.split('=', 1)
            cookies[key] = value
    return cookies


def load_cookie_from_file(filename: str = 'bilicookie.txt') -> str | None:
    """
    从当前目录读取 Cookie 文件（v3.3.5 新增）。
    文件仅包含一行裸 Cookie，无任何标识；自动兼容处理：
      - 以 UTF-8 读取（容忍 BOM）
      - 剥离可选的 "Cookie:" 前缀
      - 剥离首尾引号
    文件不存在、内容为空或读取失败时返回 None。
    """
    if not os.path.exists(filename):
        return None
    try:
        with open(filename, 'r', encoding='utf-8-sig') as f:
            content = f.read().strip()
        if not content:
            return None
        if content.lower().startswith('cookie:'):
            content = content[len('cookie:'):].strip()
        if len(content) >= 2 and content[0] == '"' and content[-1] == '"':
            content = content[1:-1].strip()
        return content if content else None
    except Exception as e:
        cprint(Ansi.yellow, f"  ⚠ 读取 {filename} 失败: {e}")
        return None


def get_mixin_key(orig: str) -> str:
    """
    按 MIXIN_KEY_ENC_TAB 置换表从 orig（img_key+sub_key 拼接串）中
    取字符，取前32位得到 Wbi 的 mixin_key。
    """
    return reduce(lambda s, i: s + orig[i], MIXIN_KEY_ENC_TAB, '')[:32]


def encWbi(params: dict, img_key: str, sub_key: str) -> dict:
    """
    对请求参数做Wbi签名：追加 wts（当前时间戳）与 w_rid（MD5签名）。
    流程：img_key+sub_key → 经置换表取前32位得 mixin_key → 注入 wts →
    按键名排序 → 过滤特殊字符!'()* → urlencode → 拼接 mixin_key 后取MD5 →
    写入 w_rid。返回签名后的完整参数字典。
    """
    mixin_key = get_mixin_key(img_key + sub_key)
    params['wts'] = int(time.time())
    params = dict(sorted(params.items()))
    params = {
        k: ''.join(filter(lambda c: c not in "!'()*", str(v)))
        for k, v in params.items()
    }
    query = urllib.parse.urlencode(params)
    params['w_rid'] = hashlib.md5((query + mixin_key).encode()).hexdigest()
    return params


def get_wbi_keys(session: requests.Session) -> tuple | None:
    """
    从nav接口获取Wbi签名密钥 img_key/sub_key（供encWbi签名使用）。
    失败时最多重试3次（限流等待2~3s），返回 (img_key, sub_key) 或 None。
    """
    for attempt in range(3):
        try:
            r = session.get(
                'https://api.bilibili.com/x/web-interface/nav',
                headers={**BASE_HEADERS, 'User-Agent': random.choice(USER_AGENTS)},
                timeout=10
            )
            if r.status_code != 200:
                cprint(Ansi.yellow, f"  ⚠ get_wbi_keys HTTP {r.status_code}，重试({attempt+1}/3)")
                time.sleep(2)
                continue
            ct = r.headers.get('Content-Type', '')
            if 'application/json' not in ct:
                cprint(Ansi.yellow, f"  ⚠ get_wbi_keys 非JSON响应，重试({attempt+1}/3)")
                time.sleep(3)
                continue
            data = r.json()
            img = data['data']['wbi_img']['img_url'].rsplit('/', 1)[-1].split('.')[0]
            sub = data['data']['wbi_img']['sub_url'].rsplit('/', 1)[-1].split('.')[0]
            return img, sub
        except Exception as e:
            cprint(Ansi.yellow, f"  ⚠ get_wbi_keys异常: {e}，重试({attempt+1}/3)")
            time.sleep(2)
    return None


def request_wbi(session: requests.Session, url: str, params: dict,
                retries: int = 5, silent: bool = False) -> dict | None:
    """
    带Wbi签名的请求，内置重试与风控处理
    Wbi密钥缓存在 session 对象上，避免每次请求都调 nav 接口
    """
    last_error = None
    for attempt in range(retries):
        try:
            cached = getattr(session, '_wbi_keys', None)
            if cached:
                img_k, sub_k = cached
            else:
                img_k, sub_k = get_wbi_keys(session)
                if img_k is not None and sub_k is not None:
                    session._wbi_keys = (img_k, sub_k)

            if img_k is None or sub_k is None:
                wait = 3 * (attempt + 1)
                if not silent:
                    cprint(Ansi.yellow,
                           f"  ⚠ 获取Wbi密钥失败，等待{wait}s ({attempt+1}/{retries})")
                time.sleep(wait)
                continue

            signed = encWbi(params.copy(), img_k, sub_k)

            headers = {
                **BASE_HEADERS,
                'User-Agent': random.choice(USER_AGENTS),
            }

            r = session.get(url, params=signed, headers=headers, timeout=15)

            # ── HTTP 429 专门处理 ──
            if r.status_code == 429:
                wait = 8 * (attempt + 1) + random.uniform(0, 2)
                if not silent:
                    cprint(Ansi.yellow,
                           f"  ⚠ HTTP 429 限流，等待{wait:.1f}s ({attempt+1}/{retries})")
                time.sleep(wait)
                continue

            # ── 非JSON检测 ──
            ct = r.headers.get('Content-Type', '')
            if 'application/json' not in ct:
                if 'v_voucher' in r.text:
                    wait = 8 * (attempt + 1) + random.uniform(0, 3)
                    if not silent:
                        cprint(Ansi.yellow,
                               f"  ⚠ v_voucher文本响应，等待{wait:.1f}s ({attempt+1}/{retries})")
                else:
                    wait = 5 * (attempt + 1) + random.uniform(0, 3)
                    if not silent:
                        cprint(Ansi.yellow,
                               f"  ⚠ 非JSON响应，等待{wait:.1f}s ({attempt+1}/{retries})")
                time.sleep(wait)
                continue

            d = r.json()

            # ── v_voucher 精确匹配 ──
            if (d.get('data') and isinstance(d.get('data'), dict)
                    and d['data'].get('v_voucher')):
                wait = 8 * (attempt + 1) + random.uniform(0, 3)
                if not silent:
                    cprint(Ansi.yellow,
                           f"  ⚠ v_voucher风控，等待{wait:.1f}s ({attempt+1}/{retries})")
                time.sleep(wait)
                continue

            # ── 正常返回 ──
            if d.get('code') == 0:
                return d

            # ── Wbi签名错误 ──
            if d.get('code') == -412:
                session._wbi_keys = None
                wait = 3 * (attempt + 1)
                if not silent:
                    cprint(Ansi.yellow,
                           f"  ⚠ Wbi签名错误(-412)，等待{wait}s ({attempt+1}/{retries})")
                time.sleep(wait)
                continue

            # ── Cookie过期 ──
            if d.get('code') == -101:
                cprint(Ansi.red, "  ❌ Cookie过期(-101)，请重新获取Cookie")
                return None

            # ── 其他API错误 ──
            if not silent:
                cprint(Ansi.yellow,
                       f"  ⚠ API返回 code={d.get('code')} msg={d.get('message','?')}")
            return d

        except requests.exceptions.Timeout:
            last_error = "超时"
            wait = 3 * (attempt + 1)
            if not silent:
                cprint(Ansi.yellow, f"  ⚠ 请求超时，等待{wait}s ({attempt+1}/{retries})")
            time.sleep(wait)
        except requests.exceptions.ConnectionError:
            last_error = "连接错误"
            wait = 5 * (attempt + 1)
            if not silent:
                cprint(Ansi.yellow, f"  ⚠ 连接错误，等待{wait}s ({attempt+1}/{retries})")
            time.sleep(wait)
        except Exception as e:
            last_error = str(e)
            wait = 3 * (attempt + 1)
            if not silent:
                cprint(Ansi.yellow, f"  ⚠ {e}，等待{wait}s ({attempt+1}/{retries})")
            time.sleep(wait)

    if not silent:
        cprint(Ansi.red, f"  ❌ 已达最大重试({retries})，最后错误: {last_error}")
    return None


def extract_message(item: dict) -> str:
    """兼容提取评论内容（content可能是dict或字符串）"""
    content = item.get('content', '')
    if isinstance(content, dict):
        return content.get('message', '')
    return str(content)


def parse_comment(r: dict, oid: int) -> dict:
    """API返回 → 统一评论格式"""
    return {
        'rpid': r.get('rpid', 0),
        'oid': oid,
        'type': 1,
        'root': r.get('root', 0),
        'parent': r.get('parent', 0),
        'uname': r.get('member', {}).get('uname', ''),
        'uid': str(r.get('member', {}).get('mid', '')),
        'level': r.get('member', {}).get('level_info', {}).get('current_level', 0),
        'message': extract_message(r),
        'like': r.get('like', 0),
        'ctime': r.get('ctime', 0),
        'rcount': r.get('rcount', 0),
    }


def ts_to_str(ts: int) -> str:
    """Unix时间戳 → 可读字符串"""
    if ts == 0:
        return '未知时间'
    return datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')


def _is_combining_mark(cp: int) -> bool:
    """判断码点是否为组合附加字符（combining mark）"""
    return (0x0300 <= cp <= 0x036F or
            0x1AB0 <= cp <= 0x1AFF or
            0x1DC0 <= cp <= 0x1DFF or
            0x20D0 <= cp <= 0x20FF or
            0xFE20 <= cp <= 0xFE2F)


def _is_variation_selector(cp: int) -> bool:
    """判断码点是否为变体选择符（如 ❤️ 的 U+FE0F）"""
    return 0xFE00 <= cp <= 0xFE0F or 0xE0100 <= cp <= 0xE01EF


def _truncate_grapheme(text: str, max_len: int) -> str:
    """
    按“字素簇”（grapheme cluster）安全截断文本（不附加省略号），
    避免从字符中间截断：
      - 组合字符（如 é = e + U+0301）
      - ZWJ/ZWNJ 连接的表情序列（如 👨‍👩‍👧‍👦）
      - 变体选择符（如 ❤️ = ❤ + U+FE0F）
      - 代理对（Python3 正常 str 不会出现，保留防御性处理）
    文本不超长时原样返回。
    """
    if len(text) <= max_len:
        return text

    chars = list(text)
    cut = max_len

    while cut > 0 and 0xD800 <= ord(chars[cut - 1]) <= 0xDFFF:
        cut -= 1

    while cut > 0 and cut < len(chars):
        nxt = ord(chars[cut])
        prev = ord(chars[cut - 1])
        if _is_combining_mark(nxt) or _is_variation_selector(nxt):
            cut -= 1
            continue
        if prev in (0x200C, 0x200D):
            cut -= 1
            continue
        if (0x1F1E6 <= nxt <= 0x1F1FF and 0x1F1E6 <= prev <= 0x1F1FF):
            cut -= 1
            continue
        break

    return ''.join(chars[:cut])


def safe_truncate(text: str, max_len: int) -> str:
    """
    按“字素簇”（grapheme cluster）安全截断文本，避免从字符中间截断，
    截断处附加省略号“...”。截断边界判断逻辑见 _truncate_grapheme。
    """
    if len(text) <= max_len:
        return text
    return _truncate_grapheme(text, max_len) + '...'


def _resolve_short_link(url: str) -> str | None:
    """跟随 b23.tv 短链接跳转，返回最终URL；失败返回 None。"""
    try:
        r = requests.get(url, headers={
            **BASE_HEADERS,
            'User-Agent': random.choice(USER_AGENTS),
        }, allow_redirects=True, timeout=10)
        return r.url
    except Exception as e:
        cprint(Ansi.yellow, f"  ⚠ 短链接解析异常: {e}")
        return None


def extract_bvid(raw: str) -> str | None:
    """
    从用户输入中提取12位BVID。
    支持格式：
      - 纯BV号：BV1GJ411x7j3
      - 完整链接：https://www.bilibili.com/video/BV1GJ411x7j3/...
      - 短链接：https://b23.tv/xxxxx（自动跟随跳转解析出真实BV号）
      - 评论区复制的评论链接（同样包含 /video/BV.../ 段，可正常识别）
    注意：BV号除前缀外其余10位区分大小写，本函数不做大小写纠正。
    """
    raw = raw.strip()
    if not raw:
        return None

    match = re.search(r'[Bb][Vv][a-zA-Z0-9]{10}', raw)
    if match:
        bvid = match.group(0)
        bvid = 'BV' + bvid[2:]
        return bvid

    if 'b23.tv' in raw:
        resolved = _resolve_short_link(raw)
        if resolved:
            match = re.search(r'[Bb][Vv][a-zA-Z0-9]{10}', resolved)
            if match:
                bvid = match.group(0)
                bvid = 'BV' + bvid[2:]
                cprint(Ansi.green, f"  ✅ 短链接已解析: {bvid}")
                return bvid
        cprint(Ansi.yellow, "  ⚠ 短链接解析失败或未找到BV号，请直接输入12位BV号")
        return None

    fuzzy = re.search(r'[Bb][Vv][a-zA-Z0-9]+', raw)
    if fuzzy:
        candidate = fuzzy.group(0)
        if len(candidate) < 12:
            cprint(Ansi.yellow,
                   f"  ⚠ 识别到不完整的BV号「{candidate}」（只有{len(candidate)}位，应为12位），"
                   f"请检查后重新输入")
            return None
        bvid = candidate[:12]
        bvid = 'BV' + bvid[2:]
        cprint(Ansi.yellow, f"  ⚠ BV号被截取为「{bvid}」，如有误请手动输入纯BV号")
        return bvid

    return None


def extract_root_rpid(raw: str) -> int | None:
    """
    从用户输入中提取楼主root_rpid，按以下优先级识别：
      1. 评论区复制的评论链接中的 comment_root_id 参数：
         https://www.bilibili.com/video/BV1...?comment_on=1&comment_root_id=309041328033&...
      2. 链接末尾 #reply 锚点：...#reply309041328033
      3. 纯数字：309041328033
    均无法识别时返回 None。
    """
    raw = raw.strip()
    if not raw:
        return None

    m = re.search(r'comment_root_id=(\d+)', raw)
    if m:
        return int(m.group(1))

    m = re.search(r'#reply(\d+)', raw)
    if m:
        return int(m.group(1))

    if re.fullmatch(r'\d+', raw):
        return int(raw)

    return None


# ============================================================
# 输出目录 & 视频信息保存（v3.3.4 新增）
# ============================================================

def sanitize_dirname(title: str, max_len: int = 60) -> str:
    """
    将视频标题清洗为安全的文件夹名：
      - Windows 非法字符 \\ / : * ? " < > | 替换为下划线 _
      - 移除控制字符（\x00-\x1f、\x7f）
      - 去除首尾空白
      - 按字素簇安全截断到 max_len（默认60字符，不会从emoji/组合字符中间切断）
    清洗后为空字符串时返回 ''（由调用方回退）。
    """
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f\x7f]', '_', title)
    name = name.strip()
    if not name:
        return ''
    return _truncate_grapheme(name, max_len)


def ensure_output_dir(title: str, bvid: str) -> str:
    """
    在当前目录下创建并返回按视频标题命名的输出文件夹（绝对路径）。
    标题为空或清洗后为空时，回退为「BV号_视频」。
    文件夹已存在时直接复用（不删除旧文件，新文件追加其中）。
    """
    dirname = sanitize_dirname(title)
    if not dirname:
        dirname = f'{bvid}_视频'
    output_dir = os.path.join(os.getcwd(), dirname)
    os.makedirs(output_dir, exist_ok=True)
    return output_dir


def _md_escape_cell(v) -> str:
    """Markdown 表格单元格转义：| → \\|，换行 → <br>"""
    s = str(v)
    return s.replace('|', '\\|').replace('\r', '').replace('\n', '<br>')


def save_view_info_md(output_dir: str, view: dict, video_info: dict):
    """
    将 view 接口返回的完整信息写入 <输出文件夹>/信息.md。
    内容包含：
      1. Markdown 可读概览表格（标题/UP主/分区/播放量/点赞等常用字段）
      2. view 接口的完整原始 JSON（code、message、data 全部字段，一条不丢）
    多次运行时该文件会被覆盖为最新快照（同一视频的当前信息）。
    """
    data = view.get('data', {}) if isinstance(view, dict) else {}
    owner = data.get('owner', {}) or {}
    stat = data.get('stat', {}) or {}
    ts_now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    duration = data.get('duration', 0)
    if duration:
        dur_str = f"{duration // 60}分{duration % 60}秒"
    else:
        dur_str = '未知'

    lines = []
    lines.append(f"# 视频信息：{video_info.get('title', '?')}")
    lines.append('')
    lines.append(f"- **BVID**: `{video_info.get('bvid', '')}`")
    lines.append(f"- **AID**: `{video_info.get('aid', '')}`")
    lines.append(f"- **抓取时间**: {ts_now}")
    lines.append('')
    lines.append('## 概览')
    lines.append('')
    lines.append('| 字段 | 值 |')
    lines.append('| --- | --- |')
    rows = [
        ('标题', data.get('title', '')),
        ('简介', data.get('desc', '')),
        ('BVID', data.get('bvid', '')),
        ('AID', data.get('aid', '')),
        ('分区', f"{data.get('tname', '')} (tid={data.get('tid', '')})"),
        ('UP主', f"{owner.get('name', '')} (mid={owner.get('mid', '')})"),
        ('UP主头像', owner.get('face', '')),
        ('发布时间', ts_to_str(data.get('pubdate', 0))),
        ('审核时间', ts_to_str(data.get('ctime', 0))),
        ('时长', dur_str),
        ('分P数', data.get('videos', '')),
        ('封面', data.get('pic', '')),
        ('版权类型', data.get('copyright', '')),
        ('状态 state', data.get('state', '')),
        ('动态 dynamic', data.get('dynamic', '')),
        ('播放量', stat.get('view', '')),
        ('点赞数', stat.get('like', '')),
        ('投币数', stat.get('coin', '')),
        ('收藏数', stat.get('favorite', '')),
        ('分享数', stat.get('share', '')),
        ('弹幕数', stat.get('danmaku', '')),
        ('评论数', stat.get('reply', '')),
        ('当前排名', stat.get('now_rank', '')),
        ('历史最高排名', stat.get('his_rank', '')),
    ]
    for k, v in rows:
        lines.append(f"| {k} | {_md_escape_cell(v)} |")
    lines.append('')
    lines.append('## 完整原始数据（view 接口返回，未舍弃任何字段）')
    lines.append('')
    lines.append('```json')
    lines.append(json.dumps(view, ensure_ascii=False, indent=2))
    lines.append('```')
    lines.append('')

    md_path = os.path.join(output_dir, '信息.md')
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    cprint(Ansi.green, f"  📄 视频信息已保存: {md_path}")


# ============================================================
# 检查点（断点续传）
# ============================================================

def save_checkpoint(filepath: str, data: dict):
    """将进度数据写入检查点文件（JSON格式，UTF-8）。"""
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        cprint(Ansi.yellow, f"  ⚠ 检查点保存失败: {e}")


def load_checkpoint(filepath: str) -> dict | None:
    """读取检查点文件。文件不存在返回 None；损坏时打印警告并返回 None。"""
    if not os.path.exists(filepath):
        return None
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        cprint(Ansi.yellow, "  ⚠ 检查点文件损坏，将从头开始")
        return None


def remove_checkpoint(filepath: str):
    """删除检查点文件（任务成功后清理断点）。文件不存在时静默跳过。"""
    if os.path.exists(filepath):
        try:
            os.remove(filepath)
        except Exception:
            pass


# ============================================================
# 一级评论翻页拉取（模式1 & 模式2共用）
# ============================================================

def fetch_root_comments(session: requests.Session, aid: int,
                        sort_type: int, nohot: int,
                        checkpoint_file: str) -> tuple[list, int]:
    """
    逐页拉取一级评论（支持断点续传与进度打印）。
    返回 (评论列表, 全站显示总评论数)；总数为0表示接口未给出。
    """
    all_comments = []
    page = 1
    total_count_hint = 0

    ckpt = load_checkpoint(checkpoint_file)
    if ckpt:
        all_comments = ckpt.get('comments', [])
        page = ckpt.get('page', 1)
        total_count_hint = ckpt.get('total_hint', 0)
        cprint(Ansi.cyan, f"  📂 从检查点恢复：已 {len(all_comments)} 条，从第 {page} 页继续")

    while page <= MAX_PAGES:
        params = {
            'type': 1,
            'oid': aid,
            'pn': page,
            'ps': 20,
            'sort': sort_type,
            'nohot': nohot,
        }
        data = request_wbi(session, 'https://api.bilibili.com/x/v2/reply', params)

        if data is None:
            cprint(Ansi.red, f"  ❌ 第{page}页请求失败，保存检查点退出")
            save_checkpoint(checkpoint_file, {
                'comments': all_comments, 'page': page, 'total_hint': total_count_hint
            })
            return all_comments, total_count_hint

        replies = data.get('data', {}).get('replies', [])
        if not replies:
            cprint(Ansi.green, f"  ✅ 第{page}页为空，翻页结束")
            break

        for r in replies:
            all_comments.append(parse_comment(r, aid))

        if total_count_hint == 0:
            total_count_hint = data.get('data', {}).get('page', {}).get('count', 0)

        if page % 10 == 1:
            if total_count_hint > 0:
                pct = f" ({len(all_comments)*100//total_count_hint}%)"
            else:
                pct = ""
            cprint(Ansi.dim, f"  📄 第{page}页 +{len(replies)}条 → 累计{len(all_comments)}条{pct}")

        page += 1

        if page % 5 == 0:
            save_checkpoint(checkpoint_file, {
                'comments': all_comments, 'page': page, 'total_hint': total_count_hint
            })

        time.sleep(random.uniform(MAIN_DELAY_MIN, MAIN_DELAY_MAX))

    if page > MAX_PAGES:
        cprint(Ansi.yellow,
               f"  ⚠ 已达最大页数上限({MAX_PAGES})，强制停止。若评论未爬完可重新运行从检查点继续")

    return all_comments, total_count_hint


# ============================================================
# 楼中楼拉取
# ============================================================

def fetch_replies_for_root(session: requests.Session, aid: int,
                           root_rpid: int) -> tuple[list, bool]:
    """
    拉取指定根评论下所有楼中楼。
    返回 (replies, partial)，partial=True 表示因请求失败中途退出，数据不完整。
    """
    replies = []
    page = 1
    partial = False
    while page <= MAX_SUB_PAGES:
        params = {'type': 1, 'oid': aid, 'root': root_rpid, 'pn': page, 'ps': 20}
        data = request_wbi(session, 'https://api.bilibili.com/x/v2/reply/reply',
                           params, silent=True)
        if data is None:
            partial = True
            cprint(Ansi.yellow,
                   f"  ⚠ root={root_rpid} 第{page}页请求失败（已达最大重试），该楼层数据可能不完整")
            break
        sub = data.get('data', {}).get('replies', [])
        if not sub:
            break
        for r in sub:
            replies.append(parse_comment(r, aid))
        page += 1
        time.sleep(random.uniform(SUB_DELAY_MIN, SUB_DELAY_MAX))

    return replies, partial


def fetch_all_replies(session: requests.Session, aid: int,
                      root_comments: list, checkpoint_file: str) -> tuple[list, list]:
    """
    对所有 rcount>0 的一级评论拉取楼中楼，支持断点续传。
    用已完成的 rpid 集合（done_rpids）标记进度，失败楼层写入 failed_rpids 返回。
    返回 (all_data, failed_rpids)。
    """
    all_data = list(root_comments)

    already_checked_rpids = set()
    for c in all_data:
        if c['root'] != 0:
            already_checked_rpids.add(c['root'])

    ckpt = load_checkpoint(checkpoint_file)
    done_rpids = set()
    if ckpt:
        done_rpids = set(ckpt.get('done_rpids', []))
        saved = ckpt.get('replies', [])
        existing = {c['rpid'] for c in all_data}
        for sr in saved:
            if sr['rpid'] not in existing:
                all_data.append(sr)
                existing.add(sr['rpid'])
                already_checked_rpids.add(sr['root'])
        cprint(Ansi.cyan, f"  📂 楼中楼阶段恢复：已完成 {len(done_rpids)} 条一级评论")

    candidates = []
    for c in root_comments:
        if c['rcount'] > 0 and c['rpid'] not in done_rpids and c['rpid'] not in already_checked_rpids:
            candidates.append(c)

    if not candidates:
        cprint(Ansi.green, "  ✅ 所有楼中楼已完成或无需拉取")
        return all_data, []

    total = len(candidates)
    cprint(Ansi.blue, f"  🔍 {total} 条一级评论有待拉楼中楼")

    failed_rpids = []

    pbar = tqdm(enumerate(candidates), total=total, desc='  🧵 楼中楼', unit='条',
                bar_format='{desc}: {percentage:3.0f}%|{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]')

    for idx, comment in pbar:
        rpid = comment['rpid']
        uname = comment['uname']

        sub_replies, sub_partial = fetch_replies_for_root(session, aid, rpid)

        if sub_partial:
            failed_rpids.append(rpid)

        for sr in sub_replies:
            all_data.append(sr)

        done_rpids.add(rpid)
        already_checked_rpids.add(rpid)

        desc = uname[:8]
        if sub_partial:
            desc += ' ⚠'
        pbar.set_postfix({'当前': desc, '+': len(sub_replies)})

        if (idx + 1) % 5 == 0:
            save_checkpoint(checkpoint_file, {
                'done_rpids': list(done_rpids),
                'replies': [c for c in all_data if c['root'] != 0],
            })

    pbar.close()
    return all_data, failed_rpids


# ============================================================
# 回复树构建 & 打印（模式3用）
# ============================================================

def build_reply_tree(root_comment: dict, replies: list) -> dict:
    """根据 parent 字段构建回复树"""
    rpid_map = {r['rpid']: r for r in replies}
    rpid_map[root_comment['rpid']] = root_comment

    for r in replies:
        r['children'] = []
    root_comment['children'] = []

    orphans = []
    for r in replies:
        parent_rpid = r['parent']
        if parent_rpid in rpid_map:
            rpid_map[parent_rpid].setdefault('children', []).append(r)
        else:
            orphans.append(r)
    root_comment.setdefault('children', []).extend(orphans)

    def sort_children(node):
        if 'children' in node and node['children']:
            node['children'].sort(key=lambda x: x['ctime'])
            for c in node['children']:
                sort_children(c)

    sort_children(root_comment)
    return root_comment


def print_tree(node: dict, indent: str = '', is_last: bool = True,
               is_root: bool = True):
    """
    递归打印回复树（终端展示用）。node 为 build_reply_tree 构建的树节点。
    根节点打印完整信息与回复数，子节点按树形缩进逐层展示。
    """
    if is_root:
        print(f"\n  ⭐ {Ansi.bold('根评论')} [{Ansi.cyan(node['uname'])}] "
              f"(Lv.{node['level']}) {ts_to_str(node['ctime'])}")
        msg = safe_truncate(node['message'], 100)
        print(f"  「{msg}」")
        if node.get('rcount', 0) > 0:
            print(f"  💬 {node['rcount']} 条回复")
        if node.get('children'):
            print(f"  │")
            for i, child in enumerate(node['children']):
                print_tree(child, '  ', i == len(node['children']) - 1, False)
        else:
            print(f"  └── (无回复)")
    else:
        prefix = '└── ' if is_last else '├── '
        msg = safe_truncate(node['message'], 50)
        print(f"{indent}{prefix}[{Ansi.cyan(node['uname'])}] → {msg} "
              f"({ts_to_str(node['ctime'])}, 👍{node['like']})")
        if node.get('children'):
            new_indent = indent + ('    ' if is_last else '│   ')
            for i, child in enumerate(node['children']):
                print_tree(child, new_indent, i == len(node['children']) - 1, False)


def print_flat_replies(root_comment: dict, replies: list):
    """按时间顺序扁平打印根评论及其全部楼中楼。"""
    print(f"\n  ⭐ {Ansi.bold('根评论')} [{Ansi.cyan(root_comment['uname'])}] "
          f"(Lv.{root_comment['level']}) {ts_to_str(root_comment['ctime'])}")
    msg = safe_truncate(root_comment['message'], 100)
    print(f"  「{msg}」")
    print(f"  {'─'*50}")

    sorted_replies = sorted(replies, key=lambda x: x['ctime'])
    if not sorted_replies:
        print(f"  (无回复)")
        return

    for i, r in enumerate(sorted_replies, 1):
        indent = '  ├─' if i < len(sorted_replies) else '  └─'
        msg = safe_truncate(r['message'], 60)
        depth_tag = ''
        if r['parent'] != root_comment['rpid']:
            depth_tag = f" [回复→rpid={r['parent']}]"
        print(f"{indent} [{Ansi.cyan(r['uname'])}]{depth_tag} → {msg} "
              f"({ts_to_str(r['ctime'])}, 👍{r['like']})")


def tree_to_text_lines(node: dict, indent: str = '', is_last: bool = True,
                       is_root: bool = True) -> list[str]:
    """
    将回复树转为文本行列表（写入TXT用），与 print_tree 展示内容一致。
    返回每行字符串组成的列表。
    """
    lines = []
    if is_root:
        lines.append(f"⭐ 根评论 [{node['uname']}] (Lv.{node['level']}) "
                     f"{ts_to_str(node['ctime'])}")
        lines.append(f"「{safe_truncate(node['message'], 100)}」")
        if node.get('rcount', 0) > 0:
            lines.append(f"💬 {node['rcount']} 条回复")
        if node.get('children'):
            for i, child in enumerate(node['children']):
                lines.extend(tree_to_text_lines(child, '  ',
                              i == len(node['children']) - 1, False))
    else:
        prefix = '└── ' if is_last else '├── '
        lines.append(f"{indent}{prefix}[{node['uname']}] → {safe_truncate(node['message'], 100)} "
                     f"({ts_to_str(node['ctime'])}, 👍{node['like']})")
        if node.get('children'):
            new_indent = indent + ('    ' if is_last else '│   ')
            for i, child in enumerate(node['children']):
                lines.extend(tree_to_text_lines(child, new_indent,
                              i == len(node['children']) - 1, False))
    return lines


def flat_to_text_lines(root_comment: dict, replies: list) -> list[str]:
    """将扁平时间序回复转为文本行列表（写入TXT用），区分二级/三级以上回复。"""
    lines = [
        f"⭐ 根评论 [{root_comment['uname']}] (Lv.{root_comment['level']}) "
        f"{ts_to_str(root_comment['ctime'])}",
        f"「{safe_truncate(root_comment['message'], 100)}」",
        f"{'─'*50}",
    ]
    for r in sorted(replies, key=lambda x: x['ctime']):
        depth = '[二级]' if r['parent'] == root_comment['rpid'] else '[三级+]'
        lines.append(f"  {depth} [{r['uname']}] → {safe_truncate(r['message'], 100)} "
                     f"({ts_to_str(r['ctime'])}, 👍{r['like']})")
    return lines


def get_root_comment_info(session: requests.Session, aid: int,
                          root_rpid: int) -> dict:
    """
    获取根评论详情（用于模式3展示）。
    请求失败或评论已删除时返回占位信息，不抛异常。
    """
    params = {'type': 1, 'oid': aid, 'root': root_rpid}
    data = request_wbi(session, 'https://api.bilibili.com/x/v2/reply/detail',
                       params, silent=True)
    if data and data.get('code') == 0:
        root_info = data.get('data', {}).get('root', {})
        if root_info:
            return parse_comment(root_info, aid)

    cprint(Ansi.yellow, "  ⚠ 无法获取根评论详情（可能被删除），使用占位信息")
    return {
        'rpid': root_rpid, 'oid': aid, 'type': 1,
        'root': 0, 'parent': 0,
        'uname': '(未知用户)', 'uid': '', 'level': 0,
        'message': '(根评论详情获取失败，可能已被删除)',
        'like': 0, 'ctime': 0, 'rcount': 0,
    }


# ============================================================
# 输出
# ============================================================

def output_mode1_mode2(all_comments: list, video_info: dict, bvid: str,
                       sort_label: str, output_dir: str):
    """
    输出模式1/模式2的爬取结果：按时间倒序排序后写入 JSON 与 TXT 文件，并打印汇总。
    JSON 含视频信息、统计（总数/一级/楼中楼/去重用户数）与全部评论。
    文件写入 output_dir（按视频标题命名的文件夹）。
    """
    all_comments.sort(key=lambda x: x['ctime'], reverse=True)
    root_count = sum(1 for c in all_comments if c['root'] == 0)
    sub_count = sum(1 for c in all_comments if c['root'] != 0)

    uc = Counter(c['uname'] for c in all_comments)

    tag = sort_label.replace(' ', '_').replace('🕐', '').replace('🔥', '').replace('💬', '')
    tag = tag.strip('_') or 'time'
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    json_path = os.path.join(output_dir, f'comments_{bvid}_{tag}_{ts}.json')
    txt_path = os.path.join(output_dir, f'comments_{bvid}_{tag}_{ts}.txt')

    result = {
        'video': video_info,
        'stats': {
            'total': len(all_comments),
            'root': root_count,
            'sub': sub_count,
            'users': len(uc),
        },
        'comments': all_comments,
    }
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    with open(txt_path, 'w', encoding='utf-8') as f:
        f.write(f"视频: {video_info.get('title','?')}  BVID: {bvid}\n")
        f.write(f"排序: {sort_label}  总{len(all_comments)}条 "
                f"(一级{root_count} + 楼中楼{sub_count})  用户{len(uc)}人\n")
        f.write("=" * 70 + "\n\n")
        for c in all_comments:
            tag_c = '[楼中楼]' if c['root'] != 0 else '[一级]'
            indent = '  ' if c['root'] != 0 else ''
            f.write(f"{indent}{tag_c} [{c['uname']}] Lv.{c['level']} "
                    f"{ts_to_str(c['ctime'])} 👍{c['like']}\n")
            f.write(f"{indent}  {c['message']}\n")
            f.write(f"{indent}  rpid={c['rpid']} root={c['root']} parent={c['parent']}\n\n")

    print(f"\n{'='*55}")
    cprint(Ansi.green, f"✅ 爬取完成！")
    print(f"   总评论: {len(all_comments)}  一级: {root_count}  楼中楼: {sub_count}  用户: {len(uc)}人")
    print(f"   📄 {json_path}")
    print(f"   📄 {txt_path}")


def output_mode3(root_comment: dict, replies: list, tree_root: dict,
                 video_info: dict, bvid: str, root_rpid: int,
                 display_mode: str, output_dir: str):
    """
    输出模式3结果：按 display_mode（tree/flat）在终端展示，并写入 JSON 与 TXT 文件。
    文件包含根评论、楼中楼扁平列表与回复树结构。文件写入 output_dir。
    """
    print(f"\n{'='*55}")
    print(f"  📺 {video_info.get('title', '?')}")
    print(f"  BVID: {bvid}  root_rpid: {root_rpid}")
    print(f"{'='*55}")

    if display_mode == 'tree':
        print_tree(tree_root)
        txt_lines = tree_to_text_lines(tree_root)
        tag = 'tree'
    else:
        print_flat_replies(root_comment, replies)
        txt_lines = flat_to_text_lines(root_comment, replies)
        tag = 'flat'

    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    json_path = os.path.join(output_dir, f'replies_{bvid}_root{root_rpid}_{tag}_{ts}.json')
    txt_path = os.path.join(output_dir, f'replies_{bvid}_root{root_rpid}_{tag}_{ts}.txt')

    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump({
            'video': video_info,
            'root_comment': root_comment,
            'stats': {'total_replies': len(replies)},
            'replies_flat': replies,
            'reply_tree': tree_root,
            'display_mode': display_mode,
        }, f, ensure_ascii=False, indent=2)

    with open(txt_path, 'w', encoding='utf-8') as f:
        f.write(f"视频: {video_info.get('title','?')}  BVID: {bvid}\n")
        f.write(f"根评论rpid: {root_rpid}  楼中楼: {len(replies)}条  展示: {display_mode}\n")
        f.write("=" * 60 + "\n\n")
        f.write('\n'.join(txt_lines))

    print(f"\n{'='*55}")
    cprint(Ansi.green, f"✅ 楼层爬取完成！楼中楼: {len(replies)} 条")
    print(f"   📄 {json_path}")
    print(f"   📄 {txt_path}")


# ============================================================
# 交互式输入
# ============================================================

def clear_screen():
    """清空终端（Windows 用 cls，其他平台用 clear）。"""
    os.system('cls' if os.name == 'nt' else 'clear')


def print_banner():
    """清屏并打印启动横幅。"""
    clear_screen()
    banner = """
╔══════════════════════════════════════════════════╗
║     🎯  评论爬取                                ║
║     B站视频评论爬虫 · 交互式脚本 v3.3.5        ║
║                                                  ║
║  模式1 · 全量爬取（一级评论 + 全部楼中楼）      ║
║  模式2 · 仅一级评论                             ║
║  模式3 · 指定楼层深度爬取                       ║
║                                                  ║
║  支持时间/热度/回复数排序 · 断点续传 · 树形展示 ║
║  支持粘贴评论链接自动识别BV号与楼主id            ║
║  输出按视频标题自动归入独立文件夹                ║
║  Cookie自动读取bilicookie.txt（可免手动输入）   ║
╚══════════════════════════════════════════════════╝
"""
    print(Ansi.bold(Ansi.cyan(banner)))


def select_mode() -> int:
    """交互选择爬取模式（1/2/3），返回对应整数。用户中断时退出程序。"""
    print(Ansi.bold("\n📌 步骤1：选择爬取模式"))
    print("─" * 45)
    print(f"""
  {Ansi.cyan('[1]')}  全量爬取
     → 一级评论 + 所有楼中楼，数据最完整
     → 适合：完整存档、数据分析
     → 耗时较长（几千条评论约需 10~30 分钟）

  {Ansi.cyan('[2]')}  仅一级评论
     → 只爬一级评论，不拉楼中楼
     → 适合：快速浏览、找热门评论、获取root_rpid
     → 速度较快

  {Ansi.cyan('[3]')}  指定楼层深度爬取
     → 输入 root_rpid，拉取该楼层全部楼中楼
     → 支持树形结构 / 时间顺序两种展示
     → 可直接粘贴评论区复制的评论链接
     → 适合：追踪特定讨论串
    """)
    while True:
        try:
            choice = input(f"  {Ansi.bold('请输入 [1/2/3]')}: ").strip()
            if choice in ('1', '2', '3'):
                return int(choice)
            cprint(Ansi.yellow, "  ⚠ 请输入 1、2 或 3")
        except (EOFError, KeyboardInterrupt):
            print("\n")
            sys.exit(0)


def input_cookie_interactive() -> str:
    """
    获取 Cookie：
      1. 优先自动读取当前目录 bilicookie.txt（仅一行裸Cookie，无标识，v3.3.5）
      2. 文件不存在/为空时，回退为交互式粘贴输入（支持多行，空行结束）
    返回 Cookie 字符串。
    """
    print(Ansi.bold("\n📌 步骤2：Cookie"))
    print("─" * 45)

    auto_cookie = load_cookie_from_file('bilicookie.txt')
    if auto_cookie:
        cprint(Ansi.green, "  ✅ 已自动读取本目录 bilicookie.txt")
        cprint(Ansi.dim, "  💡 如需改用手动输入，删除或改名该文件后重跑即可")
        if 'SESSDATA' not in auto_cookie:
            cprint(Ansi.yellow, "  ⚠ Cookie中未检测到SESSDATA，可能无法正常工作")
        return auto_cookie

    print(f"""
  {Ansi.dim('Cookie 获取方法：')}
    1. 浏览器打开 bilibili.com 并登录
    2. 按 F12 → 网络(Network) → 随意点一个请求
    3. 右侧 Request Headers 中找到 Cookie 字段
    4. 右键 → 复制值(Copy value)

  {Ansi.yellow('⚠ Cookie 需含 SESSDATA 字段（有效期约30天）')}
  {Ansi.dim('💡 可提前粘贴到本目录 bilicookie.txt（仅一行裸Cookie），下次自动读取免输入')}
  {Ansi.dim('直接粘贴后按回车，如有换行继续粘贴，输完按两次回车')}
    """)
    print("  " + "─" * 40)
    lines = []
    first = True
    while True:
        try:
            if first:
                line = input("  Cookie: ").strip()
                first = False
            else:
                line = input("         ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n")
            sys.exit(0)
        if line == '':
            if lines:
                break
            continue
        lines.append(line)
    result = ''.join(lines)
    if 'SESSDATA' not in result:
        cprint(Ansi.yellow, "  ⚠ Cookie中未检测到SESSDATA，可能无法正常工作")
    return result


def input_bvid_interactive() -> tuple[str, int | None]:
    """
    交互输入BVID。支持纯BV号/完整链接/b23.tv短链/评论区复制的评论链接。
    返回 (标准BV号, 从链接中解析出的root_rpid或None)。
    若粘贴的是评论区评论链接（含 comment_root_id 或 #reply），
    会同时识别出楼主id，供模式3步骤4直接回车使用。
    """
    print(Ansi.bold("\n📌 步骤3：输入视频BVID"))
    print("─" * 45)
    print(f"""
  {Ansi.dim('支持格式：')}
    · 纯BV号：BV1GJ411x7j3（前缀BV大小写均可，其余10位区分大小写）
    · 完整链接：https://www.bilibili.com/video/BV1GJ411x7j3
    · 短链接：  https://b23.tv/xxxxx（自动解析）
    · 评论区评论链接：
      https://www.bilibili.com/video/BV1...?...comment_root_id=...（自动识别BV号+楼主id）
    """)
    while True:
        try:
            raw = input(f"  {Ansi.bold('BVID')}: ").strip()
            bvid = extract_bvid(raw)
            if bvid:
                link_rpid = extract_root_rpid(raw)
                if link_rpid:
                    cprint(Ansi.green,
                           f"  ✅ 识别到: {bvid}，楼主id: {link_rpid}")
                else:
                    cprint(Ansi.green, f"  ✅ 识别到: {bvid}")
                return bvid, link_rpid
            cprint(Ansi.yellow, "  ⚠ 未识别到有效BV号，请检查后重新输入（应为12位，如BV1GJ411x7j3）")
        except (EOFError, KeyboardInterrupt):
            print("\n")
            sys.exit(0)


def select_speed() -> tuple:
    """
    交互选择爬取速度。
    返回 (main_min, main_max, sub_min, sub_max)；选择快速模式需二次确认。
    """
    print(Ansi.bold("\n📌 爬取速度设置"))
    print("─" * 45)
    for k, v in SPEED_OPTIONS.items():
        print(f"  {Ansi.cyan(f'[{k}]')}  {v['label']}")
    print(f"\n  {Ansi.dim('💡 慢速最安全但耗时最长；正常适合大多数场景')}")
    while True:
        try:
            choice = input(f"  {Ansi.bold('请输入 [1/2/3]')}: ").strip()
            if choice in SPEED_OPTIONS:
                opt = SPEED_OPTIONS[choice]
                if choice == '1':
                    cprint(Ansi.yellow, "  ⚠ 快速模式请求较密集，可能被限流，确认继续？")
                    confirm = input(f"  {Ansi.bold('确认？[y/n]')}: ").strip().lower()
                    if confirm != 'y':
                        continue
                return opt['main_min'], opt['main_max'], opt['sub_min'], opt['sub_max']
            cprint(Ansi.yellow, "  ⚠ 请输入 1、2 或 3")
        except (EOFError, KeyboardInterrupt):
            print("\n")
            sys.exit(0)


def select_sort() -> tuple[int, int, str]:
    """交互选择排序方式，返回 (sort, nohot, 显示标签)。非时间排序会先确认。"""
    print(Ansi.bold("\n📌 步骤4：选择排序方式"))
    print("─" * 45)
    for k, v in SORT_OPTIONS.items():
        print(f"  {Ansi.cyan(f'[{k}]')}  {v['label']}")
    print(f"\n  {Ansi.dim('💡 全量爬取推荐选[1]时间排序，翻页上限最高')}")
    while True:
        try:
            choice = input(f"  {Ansi.bold('请输入 [1/2/3]')}: ").strip()
            if choice in SORT_OPTIONS:
                opt = SORT_OPTIONS[choice]
                if choice != '1':
                    cprint(Ansi.yellow,
                           f"  ⚠ 注意：{opt['label'].split('（')[1].rstrip('）')}")
                    confirm = input(f"  {Ansi.bold('确认继续？[y/n]')}: ").strip().lower()
                    if confirm != 'y':
                        continue
                return opt['sort'], opt['nohot'], opt['label']
            cprint(Ansi.yellow, "  ⚠ 请输入 1、2 或 3")
        except (EOFError, KeyboardInterrupt):
            print("\n")
            sys.exit(0)


def input_root_rpid_interactive(default_rpid: int | None = None) -> int:
    """
    交互输入目标楼层 root_rpid。
    支持直接粘贴 B站评论区复制的评论链接（自动解析 comment_root_id / #reply），
    也支持输入纯数字。若传入了 default_rpid（BVID步骤从链接中解析出的楼主id），
    直接回车即可使用。
    """
    print(Ansi.bold("\n📌 步骤4：输入目标楼层 root_rpid"))
    print("─" * 45)
    print(f"""
  {Ansi.dim('root_rpid 获取方法：')}
    1. 在网页评论区找到目标评论 → 点击分享/复制链接
    2. 直接粘贴该评论链接（自动识别楼主id），或只输入其中的数字
    3. 或先运行模式2爬取一级评论，在JSON中搜索目标用户名找到 rpid

  {Ansi.dim('若其 root=0 → root_rpid 就是该 rpid')}
  {Ansi.dim('若其 root≠0 → root_rpid 就是其 root 字段的值')}
    """)
    while True:
        try:
            if default_rpid:
                cprint(Ansi.dim,
                       f"  💡 已从链接识别到楼主id: {Ansi.green(str(default_rpid))}，直接回车使用")
            raw = input(f"  {Ansi.bold('root_rpid')}: ").strip()
            if raw == '' and default_rpid:
                return default_rpid
            rpid = extract_root_rpid(raw)
            if rpid is not None and rpid > 0:
                return rpid
            cprint(Ansi.yellow,
                   "  ⚠ 无法识别有效root_rpid，请粘贴评论区评论链接或输入纯数字")
        except (EOFError, KeyboardInterrupt):
            print("\n")
            sys.exit(0)


def select_display_mode() -> str:
    """交互选择展示方式，返回 'tree' 或 'flat'。"""
    print(Ansi.bold("\n📌 步骤5：选择展示方式"))
    print("─" * 45)
    print(f"""
  {Ansi.cyan('[1]')}  🌲 树形结构
     → 按回复关系层级展示，谁回复谁一目了然
     → 适合：追踪对话链、分析讨论结构

  {Ansi.cyan('[2]')}  🕐 时间顺序
     → 所有楼中楼按发布时间排列
     → 适合：按时间线浏览讨论、快速查看最新回复
    """)
    while True:
        try:
            choice = input(f"  {Ansi.bold('请输入 [1/2]')}: ").strip()
            if choice in DISPLAY_OPTIONS:
                return DISPLAY_OPTIONS[choice]['mode']
            cprint(Ansi.yellow, "  ⚠ 请输入 1 或 2")
        except (EOFError, KeyboardInterrupt):
            print("\n")
            sys.exit(0)


def show_summary_and_confirm(mode: int, bvid: str, **kwargs) -> bool:
    """
    打印任务摘要并请求确认，返回是否继续（y=True，其余/中断=False）。
    模式1/2需传 sort_label，模式3需传 root_rpid 与 display_mode。
    """
    print(Ansi.bold(f"\n{'='*45}"))
    print(Ansi.bold("  📋 任务摘要"))
    print(f"{'='*45}")
    mode_names = {1: '全量爬取（含楼中楼）', 2: '仅一级评论', 3: '指定楼层深度爬取'}
    print(f"  模式:       {Ansi.cyan(mode_names[mode])}")
    print(f"  BVID:       {Ansi.cyan(bvid)}")
    if mode in (1, 2):
        print(f"  排序:       {Ansi.cyan(kwargs.get('sort_label', '?'))}")
    if mode == 3:
        print(f"  root_rpid:  {Ansi.cyan(kwargs.get('root_rpid', '?'))}")
        print(f"  展示方式:   {Ansi.cyan('树形结构' if kwargs.get('display_mode') == 'tree' else '时间顺序')}")
    print(f"{'─'*45}")

    try:
        confirm = input(f"  {Ansi.bold('确认开始爬取？[y/n]')}: ").strip().lower()
        return confirm == 'y'
    except (EOFError, KeyboardInterrupt):
        print("\n")
        return False


# ============================================================
# 主流程
# ============================================================

def main():
    print_banner()

    mode = select_mode()

    cookie_str = input_cookie_interactive()
    if not cookie_str:
        cprint(Ansi.red, "❌ Cookie不能为空")
        sys.exit(1)

    bvid, link_rpid = input_bvid_interactive()

    sort_type, nohot, sort_label = 0, 1, SORT_OPTIONS['1']['label']
    if mode in (1, 2):
        sort_type, nohot, sort_label = select_sort()

    root_rpid = None
    display_mode = 'tree'
    if mode == 3:
        # 模式3：若BVID步骤粘贴的是评论链接，步骤4可直接回车用链接中的楼主id
        root_rpid = input_root_rpid_interactive(default_rpid=link_rpid)
        display_mode = select_display_mode()

    # ── 速度选择 ──
    main_min, main_max, sub_min, sub_max = select_speed()
    global MAIN_DELAY_MIN, MAIN_DELAY_MAX, SUB_DELAY_MIN, SUB_DELAY_MAX
    MAIN_DELAY_MIN, MAIN_DELAY_MAX = main_min, main_max
    SUB_DELAY_MIN, SUB_DELAY_MAX = sub_min, sub_max

    if not show_summary_and_confirm(mode, bvid, sort_label=sort_label,
                                     root_rpid=root_rpid,
                                     display_mode=display_mode):
        cprint(Ansi.yellow, "\n已取消")
        sys.exit(0)

    print(f"\n{Ansi.dim('🔧 初始化...')}")
    session = requests.Session()
    session.cookies.update(parse_cookie(cookie_str))

    print(f"{Ansi.dim('🔍 验证Cookie...')}")
    nav = request_wbi(session, 'https://api.bilibili.com/x/web-interface/nav', {})
    if nav is None or nav.get('code') != 0:
        cprint(Ansi.red, "❌ Cookie无效或已过期")
        sys.exit(1)
    is_login = nav.get('data', {}).get('isLogin', False)
    uname = nav.get('data', {}).get('uname', '?')
    if is_login:
        cprint(Ansi.green, f"  ✅ 已登录: {uname}")
    else:
        cprint(Ansi.yellow, "  ⚠ 未登录(isLogin=false)，可能受限")

    print(f"{Ansi.dim('🔍 获取视频信息...')}")
    view = request_wbi(session, 'https://api.bilibili.com/x/web-interface/view',
                       {'bvid': bvid})
    if view is None or view.get('code') != 0:
        cprint(Ansi.red, "❌ 获取视频信息失败，请检查BVID")
        sys.exit(1)
    aid = view['data']['aid']
    title = view['data'].get('title', '')
    cprint(Ansi.green, f"  📺 {title}")
    print(f"  🆔 AID: {aid}")
    video_info = {'aid': aid, 'bvid': bvid, 'title': title}

    # ── v3.3.4：创建按视频标题命名的输出文件夹，并保存完整view信息 ──
    output_dir = ensure_output_dir(title, bvid)
    save_view_info_md(output_dir, view, video_info)
    cprint(Ansi.cyan, f"  📁 保存目录: {output_dir}")

    start_time = time.time()

    if mode == 1:
        # ═══ 模式1：全量爬取 ═══
        print(Ansi.bold(f"\n{'='*45}"))
        print(Ansi.bold("  🚀 模式1：全量爬取"))
        print(f"{'='*45}")

        ckpt_root = os.path.join(output_dir, f'checkpoint_{bvid}_root_{sort_type}.json')
        ckpt_reply = os.path.join(output_dir, f'checkpoint_{bvid}_replies_{sort_type}.json')

        cprint(Ansi.blue, "\n📥 阶段A：拉取一级评论...")
        root_comments, total_count = fetch_root_comments(session, aid, sort_type, nohot, ckpt_root)
        if not root_comments:
            cprint(Ansi.red, "❌ 未获取到任何一级评论")
            sys.exit(1)
        if total_count > 0:
            cprint(Ansi.green, f"✅ 一级评论: {len(root_comments)} 条（全站显示约 {total_count} 条）")
        else:
            cprint(Ansi.green, f"✅ 一级评论: {len(root_comments)} 条")
        remove_checkpoint(ckpt_root)

        has_replies = any(c['rcount'] > 0 for c in root_comments)
        if has_replies:
            cprint(Ansi.blue, "\n📥 阶段B：拉取楼中楼...")
            all_comments, failed_rpids = fetch_all_replies(session, aid, root_comments, ckpt_reply)
            remove_checkpoint(ckpt_reply)

            # ── 处理拉取失败的楼层 ──
            while failed_rpids:
                cprint(Ansi.yellow,
                       f"\n  ⚠ 以下 {len(failed_rpids)} 个楼层的楼中楼数据可能不完整：")
                for rp in failed_rpids:
                    name = next((c['uname'] for c in root_comments if c['rpid'] == rp), '?')
                    print(f"     rpid={rp}  ({name})")
                print(f"\n  {Ansi.dim('可能原因：网络波动或B站临时限流，建议稍后重试')}")
                try:
                    retry = input(f"  {Ansi.bold('是否重新爬取这些楼层？[y/n]')}: ").strip().lower()
                except (EOFError, KeyboardInterrupt):
                    print()
                    break
                if retry != 'y':
                    break
                new_failed = []
                for rp in failed_rpids:
                    print(f"  🔄 重试 rpid={rp}...", end=' ')
                    sub_replies, sub_partial = fetch_replies_for_root(session, aid, rp)
                    # 先移除该楼层已有的楼中楼数据
                    all_comments = [c for c in all_comments if c['root'] != rp]
                    for sr in sub_replies:
                        all_comments.append(sr)
                    if sub_partial:
                        new_failed.append(rp)
                        print(f"+{len(sub_replies)}条 ⚠再次失败")
                    else:
                        print(f"+{len(sub_replies)}条 ✅")
                failed_rpids = new_failed
        else:
            cprint(Ansi.dim, "\nℹ️  所有一级评论均无楼中楼")
            all_comments = list(root_comments)

        output_mode1_mode2(all_comments, video_info, bvid, sort_label, output_dir)

    elif mode == 2:
        # ═══ 模式2：仅一级评论 ═══
        print(Ansi.bold(f"\n{'='*45}"))
        print(Ansi.bold("  🚀 模式2：仅一级评论"))
        print(f"{'='*45}")

        ckpt_root = os.path.join(output_dir, f'checkpoint_{bvid}_rootonly_{sort_type}.json')
        cprint(Ansi.blue, "\n📥 拉取一级评论...")
        root_comments, total_count = fetch_root_comments(session, aid, sort_type, nohot, ckpt_root)
        if not root_comments:
            cprint(Ansi.red, "❌ 未获取到任何一级评论")
            sys.exit(1)
        remove_checkpoint(ckpt_root)
        if total_count > 0:
            cprint(Ansi.green, f"✅ 一级评论: {len(root_comments)} 条（全站显示约 {total_count} 条）")
        else:
            cprint(Ansi.green, f"✅ 一级评论: {len(root_comments)} 条")
        output_mode1_mode2(root_comments, video_info, bvid, sort_label, output_dir)

    elif mode == 3:
        # ═══ 模式3：指定楼层 ═══
        print(Ansi.bold(f"\n{'='*45}"))
        print(Ansi.bold(f"  🚀 模式3：指定楼层 (root={root_rpid})"))
        print(f"{'='*45}")

        cprint(Ansi.dim, "\n🔍 获取根评论详情...")
        root_comment = get_root_comment_info(session, aid, root_rpid)

        cprint(Ansi.blue, "\n📥 拉取楼中楼...")
        replies, partial = fetch_replies_for_root(session, aid, root_rpid)

        # ── 处理拉取失败 ──
        while partial:
            cprint(Ansi.yellow,
                   f"\n  ⚠ root={root_rpid} 的楼中楼数据可能不完整（已获取 {len(replies)} 条）")
            print(f"  {Ansi.dim('可能原因：网络波动或B站临时限流')}")
            try:
                retry = input(f"  {Ansi.bold('是否重新爬取？[y/n]')}: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if retry != 'y':
                break
            print(f"  🔄 重试 root={root_rpid}...", end=' ')
            replies, partial = fetch_replies_for_root(session, aid, root_rpid)
            if partial:
                print(f"{len(replies)}条 ⚠再次失败")
            else:
                print(f"{len(replies)}条 ✅")

        cprint(Ansi.green, f"✅ 楼中楼: {len(replies)} 条")

        cprint(Ansi.dim, "🌲 构建数据结构...")
        tree_root = build_reply_tree(root_comment, replies)

        output_mode3(root_comment, replies, tree_root, video_info, bvid,
                     root_rpid, display_mode, output_dir)

        # 模式3：询问是否继续爬取其他楼层
        print()
        try:
            again = input(f"  {Ansi.bold('是否继续爬取另一个楼层？[y/n]')}: ").strip().lower()
            while again == 'y':
                new_rpid = input_root_rpid_interactive()
                new_display = select_display_mode()
                if show_summary_and_confirm(3, bvid, root_rpid=new_rpid,
                                            display_mode=new_display):
                    rc = get_root_comment_info(session, aid, new_rpid)
                    rp, rp_partial = fetch_replies_for_root(session, aid, new_rpid)

                    # ── 处理拉取失败 ──
                    while rp_partial:
                        cprint(Ansi.yellow,
                               f"\n  ⚠ root={new_rpid} 的楼中楼数据可能不完整（已获取 {len(rp)} 条）")
                        print(f"  {Ansi.dim('可能原因：网络波动或B站临时限流')}")
                        try:
                            retry2 = input(f"  {Ansi.bold('是否重新爬取？[y/n]')}: ").strip().lower()
                        except (EOFError, KeyboardInterrupt):
                            print()
                            break
                        if retry2 != 'y':
                            break
                        print(f"  🔄 重试 root={new_rpid}...", end=' ')
                        rp, rp_partial = fetch_replies_for_root(session, aid, new_rpid)
                        if rp_partial:
                            print(f"{len(rp)}条 ⚠再次失败")
                        else:
                            print(f"{len(rp)}条 ✅")

                    tr = build_reply_tree(rc, rp)
                    output_mode3(rc, rp, tr, video_info, bvid, new_rpid, new_display, output_dir)
                again = input(f"\n  {Ansi.bold('继续爬取其他楼层？[y/n]')}: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            pass

    elapsed = time.time() - start_time
    print(f"\n  ⏱ 总耗时: {elapsed:.0f}秒 ({elapsed/60:.1f}分钟)")
    cprint(Ansi.green, "  🎉 全部完成！")


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n\n  {Ansi.yellow('⚠ 用户中断。检查点已保存，下次运行可自动恢复。')}")
        sys.exit(0)
    except Exception as e:
        print(f"\n  {Ansi.red(f'❌ 未预期错误: {e}')}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
