#!/usr/bin/env python3
"""bilicmtcrawl 核心逻辑回归测试（离线）。

运行：python -m unittest discover -s tests -v

约束：不联网、不读 bilicookie.txt、不写入仓库 out/。
所有涉及目录创建的用例都把 bilicmtcrawl.OUT_ROOT 指向临时目录。
"""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import bilicmtcrawl as m  # noqa: E402

REPO_OUT = os.path.join(REPO_ROOT, 'out')


def _snapshot(path):
    """目录内容快照；目录不存在时返回 None。"""
    try:
        return sorted(os.listdir(path))
    except FileNotFoundError:
        return None


_OUT_BEFORE = None


def setUpModule():
    global _OUT_BEFORE
    _OUT_BEFORE = _snapshot(REPO_OUT)


def tearDownModule():
    """整个模块跑完后，确认真实 out/ 未被测试污染。"""
    after = _snapshot(REPO_OUT)
    if after != _OUT_BEFORE:
        raise AssertionError(
            f'测试期间仓库 out/ 内容发生变化：{_OUT_BEFORE!r} -> {after!r}')


class TestOutRoot(unittest.TestCase):
    """A 组：resolve_out_root 的优先级与路径解析。"""

    def setUp(self):
        self._saved_env = os.environ.get('BILI_OUT')
        os.environ.pop('BILI_OUT', None)

    def tearDown(self):
        if self._saved_env is None:
            os.environ.pop('BILI_OUT', None)
        else:
            os.environ['BILI_OUT'] = self._saved_env

    def test_default_is_script_dir_out(self):
        self.assertEqual(m.DEFAULT_OUT_DIR, os.path.join(REPO_ROOT, 'out'))
        self.assertEqual(m.resolve_out_root(), m.DEFAULT_OUT_DIR)

    def test_cli_beats_env(self):
        os.environ['BILI_OUT'] = '/tmp/env_dir'
        self.assertEqual(m.resolve_out_root('/tmp/cli_dir'), '/tmp/cli_dir')

    def test_env_used_without_cli(self):
        os.environ['BILI_OUT'] = '/tmp/env_dir'
        self.assertEqual(m.resolve_out_root(), '/tmp/env_dir')

    def test_blank_values_fall_back_to_default(self):
        os.environ['BILI_OUT'] = '   '
        self.assertEqual(m.resolve_out_root('  '), m.DEFAULT_OUT_DIR)

    def test_relative_path_resolved_against_cwd(self):
        saved = os.getcwd()
        tmp = tempfile.gettempdir()
        try:
            os.chdir(tmp)
            self.assertEqual(m.resolve_out_root('rel/out'),
                             os.path.join(os.getcwd(), 'rel', 'out'))
        finally:
            os.chdir(saved)

    def test_tilde_expanded(self):
        self.assertEqual(m.resolve_out_root('~/bilidata'),
                         os.path.abspath(os.path.expanduser('~/bilidata')))


class TestDirNaming(unittest.TestCase):
    """B 组：目录名清洗与输出目录创建。"""

    def setUp(self):
        self._saved_root = m.OUT_ROOT
        self._tmp = tempfile.TemporaryDirectory()
        m.OUT_ROOT = self._tmp.name

    def tearDown(self):
        m.OUT_ROOT = self._saved_root
        self._tmp.cleanup()

    def test_illegal_chars_replaced(self):
        self.assertEqual(m.sanitize_dirname('a/b:c*d?"e<f>g|h'),
                         'a_b_c_d__e_f_g_h')

    def test_trailing_dots_and_spaces_stripped(self):
        self.assertEqual(m.sanitize_dirname('标题...  '), '标题')

    def test_blank_title_returns_empty(self):
        self.assertEqual(m.sanitize_dirname('   '), '')

    def test_truncates_to_max_len(self):
        self.assertEqual(len(m.sanitize_dirname('评' * 80)), 60)

    def test_keeps_grapheme_intact_for_variation_selector(self):
        out = m.sanitize_dirname('❤️' * 40, 60)
        self.assertEqual(out, '❤️' * 30)
        self.assertEqual(len(out), 60)

    def test_keeps_zwj_sequence_intact(self):
        """ZWJ 家族 emoji 截断后仍应是完整字素簇。"""
        family = '👨‍👩‍👧‍👦'
        self.assertEqual(m.sanitize_dirname(family * 20, 60), family * 8)

    def test_ensure_output_dir_created_under_out_root(self):
        path = m.ensure_output_dir('测试: 标题', 'BV1xx411c7mD')
        self.assertEqual(path, os.path.join(self._tmp.name, '测试_ 标题'))
        self.assertTrue(os.path.isdir(path))

    def test_ensure_output_dir_falls_back_to_bvid(self):
        path = m.ensure_output_dir('   ', 'BV1xx411c7mD')
        self.assertEqual(path, os.path.join(self._tmp.name, 'BV1xx411c7mD_视频'))

    def test_ensure_output_dir_reuses_existing(self):
        first = m.ensure_output_dir('同标题', 'BV1xx411c7mD')
        marker = os.path.join(first, 'keep.txt')
        with open(marker, 'w', encoding='utf-8') as f:
            f.write('x')
        second = m.ensure_output_dir('同标题', 'BV1xx411c7mD')
        self.assertEqual(first, second)
        self.assertTrue(os.path.exists(marker), '复用目录不应清空旧文件')


class TestParsers(unittest.TestCase):
    """C 组：不依赖网络的纯解析函数。"""

    def test_parse_cookie(self):
        self.assertEqual(m.parse_cookie('a=1; b=2=3; ; c='),
                         {'a': '1', 'b': '2=3', 'c': ''})

    def test_get_mixin_key_golden(self):
        # 黄金值取自 v3.3.15 实测输出，用于发现置换表/取位逻辑被改动
        orig = ('7cd084941338484aae1ad9425b84077c'
                '4932caff0ff746eab6f01bf08b70ac45')
        self.assertEqual(m.get_mixin_key(orig),
                         'ea1db124af3c7062474693fa704f4ff8')

    def test_extract_message(self):
        self.assertEqual(m.extract_message({'content': {'message': 'hi'}}), 'hi')
        self.assertEqual(m.extract_message({'content': 'raw'}), 'raw')
        self.assertEqual(m.extract_message({}), '')

    def test_extract_pictures_completes_protocol(self):
        pic = {'img_src': '//i0.hdslb.com/a.jpg', 'img_width': 100}
        pictures, urls = m.extract_pictures({'content': {'pictures': [pic]}})
        self.assertEqual(pictures[0]['img_src'], 'https://i0.hdslb.com/a.jpg')
        self.assertEqual(pictures[0]['img_width'], 100)
        self.assertEqual(urls, ['https://i0.hdslb.com/a.jpg'])

    def test_extract_pictures_without_content_dict(self):
        self.assertEqual(m.extract_pictures({'content': 'no'}), ([], []))

    def test_extract_bvid_pure_and_link(self):
        self.assertEqual(m.extract_bvid('BV1xx411c7mD'), 'BV1xx411c7mD')
        self.assertEqual(
            m.extract_bvid('https://www.bilibili.com/video/BV1xx411c7mD?p=1'),
            'BV1xx411c7mD')

    def test_extract_bvid_incomplete_returns_none(self):
        self.assertIsNone(m.extract_bvid('BV1xx'))

    def test_extract_root_rpid_three_forms(self):
        self.assertEqual(m.extract_root_rpid('comment_root_id=12345'), 12345)
        self.assertEqual(
            m.extract_root_rpid(
                'https://www.bilibili.com/video/BV1xx411c7mD#reply67890'),
            67890)
        self.assertEqual(m.extract_root_rpid('98765'), 98765)
        self.assertIsNone(m.extract_root_rpid('abc'))


class TestCheckpoint(unittest.TestCase):
    """D 组：检查点读写（本地文件，不联网）。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self._tmp.name, 'checkpoint.json')

    def tearDown(self):
        self._tmp.cleanup()

    def test_save_then_load_roundtrip(self):
        data = {'page': 3, 'comments': [{'rpid': 1, 'message': '你好'}],
                'truncated': False}
        m.save_checkpoint(self.path, data)
        self.assertTrue(os.path.exists(self.path))
        self.assertEqual(m.load_checkpoint(self.path), data)

    def test_load_missing_returns_none(self):
        self.assertIsNone(m.load_checkpoint(self.path))

    def test_load_corrupted_returns_none(self):
        with open(self.path, 'w', encoding='utf-8') as f:
            f.write('{not json')
        self.assertIsNone(m.load_checkpoint(self.path))


class TestWbi(unittest.TestCase):
    """Wbi 签名：冻结时间后可复现。"""

    def test_signature_fields_and_filtering(self):
        with mock.patch.object(m.time, 'time', return_value=1700000000):
            out = m.encWbi({'z': 'b', 'a': 'x!y'}, 'k' * 32, 's' * 32)
        self.assertEqual(out['wts'], '1700000000')   # 签名前值统一转字符串
        self.assertEqual(out['a'], 'xy')          # ! 被过滤
        self.assertRegex(out['w_rid'], r'^[0-9a-f]{32}$')

    def test_signature_changes_with_params(self):
        with mock.patch.object(m.time, 'time', return_value=1700000000):
            a = m.encWbi({'a': '1'}, 'k' * 32, 's' * 32)
            b = m.encWbi({'a': '2'}, 'k' * 32, 's' * 32)
        self.assertNotEqual(a['w_rid'], b['w_rid'])


class TestCommentParsing(unittest.TestCase):
    """parse_comment：API 字段 → 统一格式。"""

    def test_full_item(self):
        raw = {
            'rpid': 111, 'root': 0, 'parent': 0, 'like': 7,
            'ctime': 1700000000, 'rcount': 3,
            'member': {'uname': '张三', 'mid': 42,
                       'level_info': {'current_level': 5}},
            'content': {'message': 'hi',
                        'pictures': [{'img_src': '//x/y.jpg'}]},
        }
        c = m.parse_comment(raw, oid=9)
        self.assertEqual(c['rpid'], 111)
        self.assertEqual(c['oid'], 9)
        self.assertEqual(c['type'], 1)
        self.assertEqual(c['uid'], '42')
        self.assertEqual(c['level'], 5)
        self.assertEqual(c['message'], 'hi')
        self.assertEqual(c['pic_urls'], ['https://x/y.jpg'])
        self.assertFalse(c['is_top'])

    def test_missing_fields_use_defaults(self):
        c = m.parse_comment({}, oid=1)
        self.assertEqual(c['rpid'], 0)
        self.assertEqual(c['uname'], '')
        self.assertEqual(c['uid'], '')
        self.assertEqual(c['level'], 0)
        self.assertEqual(c['message'], '')
        self.assertEqual(c['pictures'], [])
        self.assertEqual(c['like'], 0)

    def test_top_flag_passed_through(self):
        self.assertTrue(m.parse_comment({'rpid': 1}, 1, is_top=True)['is_top'])


class TestReplyTree(unittest.TestCase):
    """build_reply_tree：父子关系、孤儿、按时间排序。"""

    def setUp(self):
        self.root = {'rpid': 1, 'ctime': 100}
        self.replies = [
            {'rpid': 3, 'parent': 2, 'ctime': 30},
            {'rpid': 2, 'parent': 1, 'ctime': 20},
            {'rpid': 4, 'parent': 999, 'ctime': 40},
            {'rpid': 5, 'parent': 1, 'ctime': 10},
        ]

    def test_children_sorted_and_nested(self):
        tree = m.build_reply_tree(self.root, self.replies)
        self.assertEqual([c['rpid'] for c in tree['children']], [5, 2, 4])
        self.assertEqual([c['rpid'] for c in tree['children'][1]['children']], [3])

    def test_orphan_attached_to_root(self):
        tree = m.build_reply_tree(self.root, self.replies)
        self.assertIn(4, [c['rpid'] for c in tree['children']])


class TestTextRendering(unittest.TestCase):
    """树形 / 扁平文本输出。"""

    def setUp(self):
        self.root = {'rpid': 1, 'uname': 'UP', 'level': 6,
                     'ctime': 1700000000, 'message': 'root',
                     'pic_urls': [], 'rcount': 2}
        self.replies = [
            {'rpid': 2, 'parent': 1, 'uname': 'A', 'message': 'r2',
             'ctime': 1700000010, 'like': 1, 'pic_urls': []},
            {'rpid': 3, 'parent': 2, 'uname': 'B', 'message': 'r3',
             'ctime': 1700000020, 'like': 0, 'pic_urls': []},
        ]
        self.tree = m.build_reply_tree(self.root, self.replies)

    def test_tree_lines_markers(self):
        joined = '\n'.join(m.tree_to_text_lines(self.tree))
        self.assertIn('⭐ 根评论 [UP]', joined)
        self.assertIn('└── [A]', joined)
        self.assertIn('[B]', joined)

    def test_flat_lines_depth_labels(self):
        joined = '\n'.join(m.flat_to_text_lines(self.root, self.replies))
        self.assertIn('[二级] [A]', joined)
        self.assertIn('[三级+] [B]', joined)


class TestTruncateAndEta(unittest.TestCase):
    """safe_truncate 与 _fmt_eta。"""

    def test_safe_truncate_short_and_long(self):
        self.assertEqual(m.safe_truncate('abc', 10), 'abc')
        self.assertEqual(m.safe_truncate('a' * 20, 5), 'aaaaa...')

    def test_safe_truncate_keeps_zwj_cluster(self):
        family = '👨‍👩‍👧‍👦'
        self.assertEqual(m.safe_truncate(family * 20, 60),
                         family * 8 + '...')

    def test_fmt_eta(self):
        self.assertEqual(m._fmt_eta(45), '45s')
        self.assertEqual(m._fmt_eta(200), '3m20s')
        self.assertEqual(m._fmt_eta(3900), '1h05m')
        self.assertEqual(m._fmt_eta(-5), '0s')


class TestReplyJournal(unittest.TestCase):
    """楼中楼增量检查点（JSONL）。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.cp = os.path.join(self._tmp.name, 'checkpoint.json')

    def tearDown(self):
        self._tmp.cleanup()

    def test_append_and_load_two_floors(self):
        m._append_reply_journal(self.cp, 111, [{'rpid': 1}])
        m._append_reply_journal(self.cp, 222, [{'rpid': 2}])
        done, replies = m._load_reply_journal(self.cp)
        self.assertEqual(done, {111, 222})
        self.assertEqual([r['rpid'] for r in replies], [1, 2])

    def test_corrupted_last_line_is_skipped(self):
        m._append_reply_journal(self.cp, 111, [{'rpid': 1}])
        with open(m._reply_journal_path(self.cp), 'a', encoding='utf-8') as f:
            f.write('{broken\n')
        done, replies = m._load_reply_journal(self.cp)
        self.assertEqual(done, {111})
        self.assertEqual(len(replies), 1)


class TestInfoMd(unittest.TestCase):
    """信息.md 生成与备注追加。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = self._tmp.name
        self.view = {
            'code': 0, 'message': '0',
            'data': {
                'title': 'T', 'desc': 'a|b', 'bvid': 'BV1',
                'duration': 125, 'pubdate': 0,
                'owner': {'name': 'UP', 'mid': 7},
                'stat': {'view': 100},
            },
        }
        self.info = {'title': 'T', 'bvid': 'BV1xx411c7mD', 'aid': 9}

    def tearDown(self):
        self._tmp.cleanup()

    def read(self):
        with open(os.path.join(self.dir, '信息.md'), encoding='utf-8') as f:
            return f.read()

    def test_write_overview_and_raw_json(self):
        with redirect_stdout(io.StringIO()):
            m.save_view_info_md(self.dir, self.view, self.info)
        content = self.read()
        self.assertIn('# 视频信息：T', content)
        self.assertIn('`BV1xx411c7mD`', content)
        self.assertIn('2分5秒', content)
        self.assertIn('a\\|b', content)
        self.assertIn('"code": 0', content)

    def test_append_note_and_missing_file(self):
        m.append_info_md_note(self.dir, '没文件时不应创建')
        self.assertFalse(os.path.exists(os.path.join(self.dir, '信息.md')))

        with redirect_stdout(io.StringIO()):
            m.save_view_info_md(self.dir, self.view, self.info)
        m.append_info_md_note(self.dir, '截断说明')
        self.assertIn('## 本次抓取备注', self.read())
        self.assertIn('截断说明', self.read())


class TestOutputFiles(unittest.TestCase):
    """模式 1/2 落盘：文件名、统计、TXT 标记。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = self._tmp.name
        self.comments = [
            {'rpid': 1, 'root': 0, 'uname': 'A', 'uid': '1', 'level': 3,
             'message': 'm1', 'ctime': 100, 'like': 1, 'parent': 0,
             'pic_urls': [], 'is_top': True},
            {'rpid': 2, 'root': 1, 'uname': 'B', 'uid': '2', 'level': 1,
             'message': 'm2', 'ctime': 200, 'like': 0, 'parent': 1,
             'pic_urls': ['https://x/1.jpg'], 'is_top': False},
        ]

    def tearDown(self):
        self._tmp.cleanup()

    def test_files_and_stats(self):
        with mock.patch.object(m, '_now_ts_tag', return_value='20260101_000000'), \
                redirect_stdout(io.StringIO()):
            m.output_mode1_mode2(self.comments, {'title': 'T'}, 'BV1',
                                 '按时间', self.dir, 'time')
        json_path = os.path.join(self.dir, 'comments_BV1_time_20260101_000000.json')
        txt_path = os.path.join(self.dir, 'comments_BV1_time_20260101_000000.txt')
        self.assertTrue(os.path.exists(json_path))
        self.assertTrue(os.path.exists(txt_path))

        with open(json_path, encoding='utf-8') as f:
            data = json.load(f)
        self.assertEqual(data['stats']['total'], 2)
        self.assertEqual(data['stats']['root'], 1)
        self.assertEqual(data['stats']['sub'], 1)
        self.assertEqual(data['stats']['users'], 2)
        self.assertEqual(data['stats']['pic_total'], 1)
        self.assertEqual(data['stats']['top'], 1)
        self.assertEqual(data['comments'][0]['rpid'], 2)   # 按时间倒序

    def test_txt_markers(self):
        with mock.patch.object(m, '_now_ts_tag', return_value='20260101_000000'), \
                redirect_stdout(io.StringIO()):
            m.output_mode1_mode2(self.comments, {'title': 'T'}, 'BV1',
                                 '按时间', self.dir, 'time')
        txt_path = os.path.join(self.dir, 'comments_BV1_time_20260101_000000.txt')
        with open(txt_path, encoding='utf-8') as f:
            content = f.read()
        self.assertIn('[置顶][一级]', content)
        self.assertIn('[楼中楼]', content)
        self.assertIn('🖼 https://x/1.jpg', content)


class TestCookieFile(unittest.TestCase):
    """Cookie 文件读取与清洗。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self._tmp.name, 'bilicookie.txt')

    def tearDown(self):
        self._tmp.cleanup()

    def test_strips_prefix_bom_and_quotes(self):
        with open(self.path, 'w', encoding='utf-8-sig') as f:
            f.write('  Cookie: "SESSDATA=abc"  \n')
        self.assertEqual(m.load_cookie_from_file(self.path), 'SESSDATA=abc')

    def test_missing_and_empty_return_none(self):
        self.assertIsNone(m.load_cookie_from_file(self.path))
        open(self.path, 'w').close()
        self.assertIsNone(m.load_cookie_from_file(self.path))


class TestShortLink(unittest.TestCase):
    """b23.tv 分支：mock 掉网络。"""

    def test_resolved_link_yields_bvid(self):
        with mock.patch.object(
                m, '_resolve_short_link',
                return_value='https://www.bilibili.com/video/BV1xx411c7mD'), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(m.extract_bvid('https://b23.tv/abc'),
                             'BV1xx411c7mD')


class TestMiscParsers(unittest.TestCase):
    """其他纯函数边界。"""

    def test_rpid_prefers_comment_root_id(self):
        raw = ('https://www.bilibili.com/video/BV1?comment_root_id=111'
               '&x=1#reply222')
        self.assertEqual(m.extract_root_rpid(raw), 111)

    def test_ts_to_str_zero_and_format(self):
        self.assertEqual(m.ts_to_str(0), '未知时间')
        self.assertRegex(m.ts_to_str(1700000000),
                         r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$')

    def test_md_escape_cell(self):
        self.assertEqual(m._md_escape_cell('a|b\nc'), 'a\\|b<br>c')


class TestTopItems(unittest.TestCase):
    """置顶评论提取：两种形态 + 去重。"""

    def test_extracts_and_dedupes(self):
        data = {'data': {
            'top_replies': [{'rpid': 1}, {'rpid': 1}],
            'top': {'admin': {'rpid': 2}, 'upper': {'rpid': 3}},
        }}
        self.assertEqual([x['rpid'] for x in m._extract_top_items(data)],
                         [1, 2, 3])

    def test_empty_payload(self):
        self.assertEqual(m._extract_top_items({}), [])
        self.assertEqual(m._extract_top_items({'data': None}), [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
