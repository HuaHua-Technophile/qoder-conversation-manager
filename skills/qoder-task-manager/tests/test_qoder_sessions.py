#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""qoder_sessions.py 的端到端测试（标准库 unittest，真跑 CLI，不 mock）。

每个用例用 `tempfile.TemporaryDirectory` 建独立夹具：一份最小但结构真实的
Qoder 库（chat_sessions / workspaces / chat_session_messages / turn_file_change_*）
加一份 `~/.qoder` 副本（projects 目录），再用 `--db / --qoder-home / --backup-dir`
把脚本指过去。全程不碰本机真实库。

跑法：
    python -m unittest discover -s skills/qoder-task-manager/tests -v
"""
import argparse
import importlib.util
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(HERE)
SCRIPTS = os.path.join(SKILL_DIR, 'scripts')
SCRIPT = os.path.join(SCRIPTS, 'qoder_sessions.py')
SKILL_MD = os.path.join(SKILL_DIR, 'SKILL.md')
EXAMPLES = os.path.join(SKILL_DIR, 'examples', 'titles.example.json')

if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)
import qoder_sessions as qs          # noqa: E402  纯函数直接单测
import build_pkg                     # noqa: E402  版本号单一来源

# ---------------------------------------------------------------- 夹具常量

WS_A = 'aaaaaaaa-0000-4000-8000-000000000001'
WS_B = 'bbbbbbbb-0000-4000-8000-000000000002'
SID_1 = '11111111-1111-4111-8111-111111111111'
SID_2 = '22222222-2222-4222-8222-222222222222'
SID_PEER = '44444444-4444-4444-8444-444444444444'

SCHEMA = """
CREATE TABLE workspaces (
  workspace_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  workspace_source TEXT NOT NULL,
  root_paths_json TEXT NOT NULL,
  product_mode TEXT NOT NULL,
  extra_json TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL,
  archived INTEGER NOT NULL DEFAULT 0,
  deleted_at INTEGER
);
CREATE TABLE chat_sessions (
  session_id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  cwd TEXT NOT NULL,
  workspace_id TEXT,
  extra_json TEXT NOT NULL,
  execution_target_json TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL,
  archived INTEGER NOT NULL DEFAULT 0,
  archived_at INTEGER,
  deleted_at INTEGER
);
CREATE TABLE chat_session_messages (
  session_id TEXT NOT NULL,
  message_id TEXT NOT NULL,
  sequence INTEGER NOT NULL,
  role TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  PRIMARY KEY (session_id, message_id)
);
CREATE TABLE turn_file_change_sets (
  change_set_id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  roots_json TEXT NOT NULL,
  created_at INTEGER NOT NULL
);
CREATE TABLE turn_file_change_files (
  change_set_id TEXT NOT NULL,
  path TEXT NOT NULL,
  operation TEXT
);
"""

DEFAULT_SESSIONS = [
    {'sid': SID_1, 'title': '旧标题甲需要被替换', 'ws': 'A', 'cwd': 'A'},
    {'sid': SID_2, 'title': '旧标题乙需要被替换', 'ws': 'B', 'cwd': 'B'},
    {'sid': SID_PEER, 'title': '对端设备上的影子任务', 'ws': 'B', 'cwd': 'B', 'peer': True},
]


class Sandbox(object):
    """一个隔离的 Qoder 数据副本。"""

    def __init__(self, root, sessions=None):
        self.root = root
        self.db = os.path.join(root, 'db', 'main.sqlite')
        self.home = os.path.join(root, 'home')
        self.bk = os.path.join(root, 'bk')
        self.work = os.path.join(root, 'work')
        self.proj_a = os.path.join(self.work, 'projA')
        self.proj_b = os.path.join(self.work, 'projB')
        self.projects = os.path.join(self.home, 'projects')
        for d in (os.path.dirname(self.db), self.projects, self.bk, self.proj_a, self.proj_b):
            os.makedirs(d, exist_ok=True)
        self.dir_a = os.path.join(self.projects, qs.encode_cwd(self.proj_a))
        self.dir_b = os.path.join(self.projects, qs.encode_cwd(self.proj_b))
        self._build(DEFAULT_SESSIONS if sessions is None else sessions)

    # ---- 建库与造文件 ----
    def _build(self, sessions):
        con = sqlite3.connect(self.db)
        try:
            con.executescript(SCHEMA)
            now = 1794000000000
            for wid, name, root in ((WS_A, 'TestA', self.proj_a), (WS_B, 'TestB', self.proj_b)):
                con.execute(
                    'insert into workspaces(workspace_id,name,workspace_source,root_paths_json,'
                    'product_mode,extra_json,created_at,updated_at,archived,deleted_at) '
                    'values(?,?,?,?,?,?,?,?,0,null)',
                    (wid, name, 'local', json.dumps([root]), 'coding', '{}', now, now))
            for s in sessions:
                self._insert_session(con, s, now)
            con.commit()
        finally:
            con.close()
        # 项目记忆：A 与 B 的 MEMORY.md 内容不同，project-x.md 只在 A
        self._write(os.path.join(self.dir_a, 'memory', 'MEMORY.md'), '# projA 记忆\n- 事实一\n- 事实二\n')
        self._write(os.path.join(self.dir_a, 'memory', 'project-x.md'), '项目记忆 x\n')
        self._write(os.path.join(self.dir_b, 'memory', 'MEMORY.md'), '# projB 记忆\n- 事实乙\n')

    def _insert_session(self, con, s, now):
        peer = bool(s.get('peer'))
        extra = {'titleSource': 'provisional'}
        if peer:
            extra['peerOriginSessionId'] = 'origin-' + s['sid']
        ws_id = {'A': WS_A, 'B': WS_B}.get(s.get('ws')) if s.get('ws') else None
        cwd = {'A': self.proj_a, 'B': self.proj_b}.get(s.get('cwd'), s.get('cwd') or self.proj_a)
        et = {'mode': 'peer' if peer else 'local',
              'host': {'id': 'local', 'kind': 'local', 'label': 'Local'},
              'workspace': {'id': 'ws_dummy', 'path': cwd}}
        con.execute(
            'insert into chat_sessions(session_id,title,cwd,workspace_id,extra_json,'
            'execution_target_json,created_at,updated_at,archived,deleted_at) '
            'values(?,?,?,?,?,?,?,?,0,null)',
            (s['sid'], s['title'], cwd, ws_id,
             json.dumps(extra, ensure_ascii=False), json.dumps(et, ensure_ascii=False), now, now))
        msgs = [('user', '帮我整理一下这个任务的历史记录'),
                ('assistant', '好的，我先读一遍完整历史再定标题。')]
        for i, (role, text) in enumerate(msgs, 1):
            con.execute(
                'insert into chat_session_messages(session_id,message_id,sequence,role,'
                'payload_json,created_at) values(?,?,?,?,?,?)',
                (s['sid'], '%s-m%d' % (s['sid'][:8], i), i, role,
                 json.dumps({'parts': [{'type': 'text', 'text': text}]}, ensure_ascii=False), now))
        # 正文文件放进「按 cwd 编码」的目录，保证 doctor --deep 的目录一致性检查为绿
        proj = os.path.join(self.projects, qs.encode_cwd(cwd))
        self._write(os.path.join(proj, s['sid'] + '.jsonl'),
                    json.dumps({'message': {'content': [{'type': 'text', 'text': '正文'}]}}) + chr(10))
        if s['sid'] == SID_1:
            self._write(os.path.join(proj, s['sid'], 'sub.txt'), 'sidecar')

    @staticmethod
    def _write(path, text):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(text)

    # ---- 造产出文件与产出索引 ----
    def add_outputs(self, sid, files):
        """files: [(相对 cwd 的路径, 内容)]，同时写库里的产出索引。"""
        cwd = self.proj_a
        cs = 'cs-' + sid[:8]
        con = sqlite3.connect(self.db)
        try:
            con.execute('insert or replace into turn_file_change_sets'
                        '(change_set_id,session_id,roots_json,created_at) values(?,?,?,?)',
                        (cs, sid, json.dumps([{'id': 'primary', 'path': cwd, 'kind': 'primary'}]), 0))
            for rel, text in files:
                self._write(os.path.join(cwd, rel.replace('/', os.sep)), text)
                con.execute('insert into turn_file_change_files(change_set_id,path,operation) '
                            'values(?,?,?)', (cs, rel, 'modify'))
            con.commit()
        finally:
            con.close()

    # ---- 读库辅助 ----
    def session(self, sid):
        con = sqlite3.connect(self.db)
        con.row_factory = sqlite3.Row
        try:
            return con.execute('select * from chat_sessions where session_id=?', (sid,)).fetchone()
        finally:
            con.close()

    def workspace_ids(self):
        con = sqlite3.connect(self.db)
        try:
            return {r[0] for r in con.execute('select workspace_id from workspaces')}
        finally:
            con.close()

    def add_workspace(self, wid, name, source, root):
        """补一行工作区（用来造「同名本地 + 多个对端投影」）。"""
        con = sqlite3.connect(self.db)
        try:
            now = 1794000000000
            con.execute('insert into workspaces(workspace_id,name,workspace_source,root_paths_json,'
                        'product_mode,extra_json,created_at,updated_at,archived,deleted_at) '
                        'values(?,?,?,?,?,?,?,?,0,null)',
                        (wid, name, source, json.dumps([root]), 'coding', '{}', now, now))
            con.commit()
        finally:
            con.close()

    def batches(self, tag):
        out = []
        for name in sorted(os.listdir(self.bk), reverse=True):
            if name.startswith(tag + '-') and os.path.isfile(os.path.join(self.bk, name, 'batch.json')):
                out.append(os.path.join(self.bk, name, 'batch.json'))
        return out


class CliTestCase(unittest.TestCase):
    """每个用例一个独立夹具，CLI 通过 subprocess 真跑。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix='qtaudit-')
        self.box = Sandbox(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def new_box(self, sessions=None):
        sub = os.path.join(self._tmp.name, 'b%d' % len(os.listdir(self._tmp.name)))
        os.makedirs(sub)
        self.box = Sandbox(sub, sessions)
        return self.box

    def run_cli(self, *args, **kw):
        expect = kw.pop('expect', None)
        box = kw.pop('box', None) or self.box
        cmd = [sys.executable, SCRIPT, '--db', box.db, '--qoder-home', box.home,
               '--backup-dir', box.bk] + [str(a) for a in args]
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding='utf-8', errors='replace')
        if expect is not None:
            self.assertEqual(r.returncode, expect,
                             msg='cmd=%s\nstdout=%s\nstderr=%s' % (cmd, r.stdout, r.stderr))
        return r

    def run_json(self, *args, **kw):
        r = self.run_cli(*(tuple(args) + ('--json',)), **kw)
        return json.loads(r.stdout)     # 解析失败即说明有多份文档/混了人话


# ---------------------------------------------------------------- 1 路径编码

class TestEncodeCwd(unittest.TestCase):

    def test_drive_path(self):
        self.assertEqual(qs.encode_cwd('D:\\a\\b'), 'D--a-b')

    def test_unc_path(self):
        self.assertEqual(qs.encode_cwd('\\\\server\\share\\X'), '--server-share-X')

    def test_keeps_dots_and_underscores(self):
        self.assertEqual(qs.encode_cwd('E:\\B\\NAS_v1.2'), 'E--B-NAS_v1.2')


# ---------------------------------------------------------------- 2 筛选表达式

class TestParseFilter(unittest.TestCase):

    def test_and_chain(self):
        conds = qs.parse_filter('cwd like %NAS% and title contains 工具包')
        self.assertEqual(conds, [('cwd', 'like', '%NAS%'), ('title', 'contains', '工具包')])

    def test_alias_mapping(self):
        self.assertEqual(qs.parse_filter('workspace = NAS'), [('workspace_name', '=', 'NAS')])

    def test_empty(self):
        self.assertEqual(qs.parse_filter(''), [])

    def test_or_rejected(self):
        with self.assertRaises(qs.FilterError) as ctx:
            qs.parse_filter('title contains x or cwd like y')
        self.assertIn('or', str(ctx.exception))

    def test_paren_rejected(self):
        with self.assertRaises(qs.FilterError):
            qs.parse_filter('cwd like a and (title contains b)')

    def test_not_and_compare_rejected(self):
        with self.assertRaises(qs.FilterError):
            qs.parse_filter('not title contains x')
        with self.assertRaises(qs.FilterError):
            qs.parse_filter('title >= abc')

    def test_unknown_field_rejected(self):
        with self.assertRaises(qs.FilterError) as ctx:
            qs.parse_filter('nope contains x')
        self.assertIn('不支持的字段', str(ctx.exception))

    def test_unknown_operator_rejected(self):
        with self.assertRaises(qs.FilterError):
            qs.parse_filter('title regex x')

    def test_cli_exit_code_and_message(self):
        with tempfile.TemporaryDirectory(prefix='qtaudit-') as tmp:
            box = Sandbox(tmp)
            cmd = [sys.executable, SCRIPT, '--db', box.db, '--qoder-home', box.home,
                   '--backup-dir', box.bk, 'list',
                   '--filter', 'title contains x or cwd like y']
            r = subprocess.run(cmd, capture_output=True, text=True,
                               encoding='utf-8', errors='replace')
            self.assertEqual(r.returncode, 2)
            self.assertIn('不支持', r.stderr)
            self.assertIn('or', r.stderr)


# ---------------------------------------------------------------- 3 标题校验

class TestValidateTitle(unittest.TestCase):

    @staticmethod
    def _t(n):
        """拼一个刚好 n 字符、带合法前缀的标题。"""
        prefix = '[开发] '
        return prefix + 'x' * (n - len(prefix))

    def test_length_boundaries(self):
        self.assertTrue(qs.validate_title(self._t(11))[1])       # 过短
        self.assertEqual(qs.validate_title(self._t(12))[1], [])   # 下边界合法
        self.assertEqual(qs.validate_title(self._t(30))[1], [])   # 上边界合法
        self.assertTrue(qs.validate_title(self._t(31))[1])        # 过长

    def test_error_message_mentions_chars(self):
        _, errs = qs.validate_title('短')
        self.assertTrue(any('字符' in e for e in errs))

    def test_prefix_required(self):
        bad = '没有分类前缀但足够长的标题'
        self.assertTrue(qs.validate_title(bad, require_prefix=True)[1])
        self.assertEqual(qs.validate_title('[网络] ' + bad, require_prefix=True)[1], [])

    def test_forbidden_chars(self):
        for bad in ('标题里有问号？', '标题里有句号。', '标题里有"引号"', 'a/b'):
            self.assertTrue(qs.validate_title(bad)[1], msg=bad)

    def test_empty(self):
        self.assertTrue(qs.validate_title('   ')[1])


# ---------------------------------------------------------------- 4 示例文件

class TestExampleTitles(unittest.TestCase):

    def test_examples_pass_with_defaults(self):
        with open(EXAMPLES, encoding='utf-8') as f:
            data = json.load(f)
        self.assertGreaterEqual(len(data), 3)
        for it in data:
            composed = (it.get('new_title') or '').strip()
            cat = str(it.get('category') or '').strip()
            if cat and not re.match(r'^\[[^\[\]]{1,8}\]', composed):
                composed = '[%s] %s' % (cat, composed)
            _, errs = qs.validate_title(composed, require_prefix=False)
            self.assertEqual(errs, [], msg='%s -> %s' % (composed, errs))
            self.assertGreaterEqual(len(composed), 12)
            self.assertLessEqual(len(composed), 30)

    def test_cli_accepts_examples_without_length_flags(self):
        with tempfile.TemporaryDirectory(prefix='qtaudit-') as tmp:
            box = Sandbox(tmp)
            con = sqlite3.connect(box.db)
            try:                        # 让示例里的 sid 在库里存在
                for sid in ('e3d0af7b-8f30-40a9-a5aa-08b000dc0b3d',
                            '2dd673fa-0000-4000-8000-000000000000',
                            '90227446-0000-4000-8000-000000000000'):
                    con.execute('insert into chat_sessions(session_id,title,cwd,workspace_id,'
                                'extra_json,execution_target_json,created_at,updated_at,archived) '
                                'values(?,?,?,null,?,?,?,?,0)',
                                (sid, '旧标题', box.proj_a, '{"titleSource":"provisional"}',
                                 '{"mode":"local"}', 1, 1))
                con.commit()
            finally:
                con.close()
            r = subprocess.run([sys.executable, SCRIPT, '--db', box.db, '--qoder-home', box.home,
                                '--backup-dir', box.bk, 'rename', '--import', EXAMPLES, '--json'],
                               capture_output=True, text=True, encoding='utf-8', errors='replace')
            data = json.loads(r.stdout)
            self.assertEqual(data['skipped'], [], msg=r.stdout)


# ---------------------------------------------------------------- 5/6 rename

class TestRename(CliTestCase):

    TITLES = [
        {'sid': SID_1, 'new_title': '甲任务改名后的新标题足够长', 'category': '测试'},
        {'sid': SID_2, 'new_title': '乙任务改名后的新标题也够长', 'category': '测试'},
    ]

    def _write_titles(self, name='titles.json'):
        path = os.path.join(self.box.root, name)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(self.TITLES, f, ensure_ascii=False)
        return path

    def test_export_import_roundtrip(self):
        out_dir = os.path.join(self.box.root, 'exp')
        self.run_cli('rename', '--export', '--out', out_dir, expect=0)
        index = os.path.join(out_dir, 'index.json')
        self.assertTrue(os.path.isfile(index))
        with open(index, encoding='utf-8') as f:
            items = json.load(f)
        self.assertTrue(any(x['sid'] == SID_1 for x in items))
        self.assertFalse(any(x['sid'] == SID_PEER for x in items))   # 影子任务不导出

        before = self.box.session(SID_1)
        titles = self._write_titles()
        self.run_cli('rename', '--import', titles, '--apply', expect=0)

        after = self.box.session(SID_1)
        meta = json.loads(after['extra_json'])
        self.assertEqual(after['title'], '[测试] 甲任务改名后的新标题足够长')
        self.assertEqual(meta['titleSource'], 'custom')
        self.assertTrue(meta['titleResolved'])
        self.assertEqual(meta['titleRevision'],
                         int(json.loads(before['extra_json']).get('titleRevision') or 0) + 1)
        self.assertIn('qoderCm', meta)
        self.assertEqual(meta['qoderCm']['title'], after['title'])

    def test_json_is_single_document(self):
        titles = self._write_titles()
        dry = self.run_json('rename', '--import', titles, expect=0)
        self.assertFalse(dry['applied'])
        self.assertEqual(len(dry['plan']), 2)
        self.assertEqual(sorted(dry), ['applied', 'backup', 'plan', 'results',
                                       'skipped', 'touched', 'warnings'])

        done = self.run_json('rename', '--import', titles, '--apply', expect=0)
        self.assertTrue(done['applied'])
        self.assertTrue(done['backup'])
        self.assertEqual(len(done['results']), 2)
        self.assertTrue(all(r['status'] == 'ok' for r in done['results']))
        self.assertEqual(self.box.session(SID_1)['title'], '[测试] 甲任务改名后的新标题足够长')

    def test_export_json_empty_result_is_valid(self):
        data = self.run_json('rename', '--export', '--filter', 'title contains 绝对不存在的词',
                             '--out', os.path.join(self.box.root, 'exp0'), expect=0)
        self.assertEqual(data['count'], 0)
        self.assertEqual(data['items'], [])
        self.assertIsNone(data['out_dir'])
        self.assertIn('warnings', data)

    def test_short_id_prefix_ambiguity_is_reported(self):
        # 两条任务前 8 位相同：短 ID 必须拒绝，不能乱改
        dup_sid = SID_1[:8] + '-9999-4999-8999-999999999999'
        box = self.new_box([
            {'sid': SID_1, 'title': '旧标题甲需要被替换', 'ws': 'A', 'cwd': 'A'},
            {'sid': dup_sid, 'title': '旧标题丙需要被替换', 'ws': 'A', 'cwd': 'A'},
        ])
        path = os.path.join(box.root, 'dup.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump([{'sid': SID_1[:8], 'new_title': '前缀撞车时不应该被写入掉'}], f,
                      ensure_ascii=False)
        data = self.run_json('rename', '--import', path, '--apply', box=box, expect=0)
        self.assertEqual(data['results'], [])
        self.assertTrue(any('前缀不唯一' in s['reason'] for s in data['skipped']))
        self.assertEqual(box.session(SID_1)['title'], '旧标题甲需要被替换')
        self.assertEqual(box.session(dup_sid)['title'], '旧标题丙需要被替换')


# ---------------------------------------------------------------- 7 move

class TestMove(CliTestCase):

    def _prepare_outputs(self):
        """两个不同子目录的同名文件——A1 的回归场景。"""
        self.box.add_outputs(SID_1, [
            ('out/x/log.txt', 'XXXXXXXXXX'),
            ('out/y/log.txt', 'YYYYYYYYYYYYYYYYYYYY'),
        ])

    def test_move_files_memory_backup_and_orphan(self):
        self._prepare_outputs()
        batch_before = len(self.box.batches('move'))

        r = self.run_cli('move', '--to', 'TestB', '--ids', SID_1[:8], '--apply', expect=0)
        self.assertIn('记忆 新增1', r.stdout)          # C7：copied 也要报

        # A1：同名文件各自留存，内容不能串
        batches = self.box.batches('move')
        self.assertEqual(len(batches), batch_before + 1)
        base = os.path.dirname(batches[0])
        b_x = os.path.join(base, 'files', SID_1[:8], 'output', 'out', 'x', 'log.txt')
        b_y = os.path.join(base, 'files', SID_1[:8], 'output', 'out', 'y', 'log.txt')
        self.assertTrue(os.path.isfile(b_x), msg=base)
        self.assertTrue(os.path.isfile(b_y), msg=base)
        with open(b_x, encoding='utf-8') as f:
            self.assertEqual(f.read(), 'XXXXXXXXXX')
        with open(b_y, encoding='utf-8') as f:
            self.assertEqual(f.read(), 'YYYYYYYYYYYYYYYYYYYY')

        # 文件真的搬到了新工作区
        self.assertTrue(os.path.isfile(os.path.join(self.box.proj_b, 'out', 'x', 'log.txt')))
        self.assertTrue(os.path.isfile(os.path.join(self.box.proj_b, 'out', 'y', 'log.txt')))
        self.assertTrue(os.path.isfile(os.path.join(self.box.dir_b, SID_1 + '.jsonl')))
        self.assertTrue(os.path.isdir(os.path.join(self.box.dir_b, SID_1)))

        # A3：搬空后源项目目录被删，且写进 batch.json 的 removed_dirs
        self.assertFalse(os.path.exists(self.box.dir_a))
        with open(batches[0], encoding='utf-8') as f:
            batch = json.load(f)
        self.assertTrue(batch['removed_dirs'])
        entry = [x for x in batch['items'] if x.get('session_id') == SID_1][0]
        self.assertEqual(entry['memory_report']['copied'], ['project-x.md'])
        self.assertTrue(entry['memory_report']['merged'])

        # 库里的归属与 cwd 都改了
        row = self.box.session(SID_1)
        self.assertEqual(row['workspace_id'], WS_B)
        self.assertEqual(row['cwd'], self.box.proj_b)

    def test_move_json_single_document(self):
        self._prepare_outputs()
        dry = self.run_json('move', '--to', 'TestB', '--ids', SID_1[:8], expect=0)
        self.assertFalse(dry['applied'])
        self.assertEqual(len(dry['plan']), 1)
        self.assertEqual(dry['results'], [])
        self.assertEqual(sorted(dry), ['applied', 'backup', 'plan', 'removed_dirs',
                                       'results', 'target', 'warnings'])
        self.assertEqual(dry['target']['name'], 'TestB')
        self.assertEqual(self.box.session(SID_1)['workspace_id'], WS_A)   # 干跑不写

        done = self.run_json('move', '--to', 'TestB', '--ids', SID_1[:8], '--apply', expect=0)
        self.assertTrue(done['applied'])
        self.assertTrue(done['backup'])
        self.assertEqual([r['status'] for r in done['results']], ['ok'])
        self.assertEqual(len(done['removed_dirs']), 1)

    def test_move_json_empty_plan_is_valid(self):
        data = self.run_json('move', '--to', 'TestB', '--ids', SID_2[:8], expect=0)
        self.assertEqual(data['plan'], [])
        self.assertFalse(data['applied'])
        self.assertEqual(data['removed_dirs'], [])

    def test_skip_in_target_can_be_turned_off(self):
        on = self.run_json('move', '--to', 'TestB', '--ids', SID_2[:8], expect=0)
        self.assertEqual(on['plan'], [])
        off = self.run_json('move', '--to', 'TestB', '--ids', SID_2[:8],
                            '--no-skip-in-target', expect=0)
        self.assertEqual(len(off['plan']), 1)


# ---------------------------------------------------------------- 8 rollback

class TestRollback(CliTestCase):

    def test_batch_restores_row_files_and_drops_created_workspace(self):
        new_root = os.path.join(self.box.root, 'brand-new')
        # move --create：会新建一个工作区行，回滚必须把它删掉（D4）
        self.run_cli('move', '--to', new_root, '--create', '--allow-missing',
                     '--ids', SID_1[:8], '--apply', expect=0)
        created = [w for w in self.box.workspace_ids() if w not in (WS_A, WS_B)]
        self.assertEqual(len(created), 1)
        self.assertEqual(self.box.session(SID_1)['workspace_id'], created[0])

        batches = self.box.batches('move')
        self.assertTrue(batches)
        with open(batches[0], encoding='utf-8') as f:
            batch = json.load(f)
        self.assertTrue(any(x.get('op') == 'insert' and x.get('table') == 'workspaces'
                            for x in batch['items']))

        data = self.run_json('rollback', '--batch', batches[0], '--yes', '--apply', expect=0)
        self.assertEqual(data['failed'], 0)
        self.assertEqual(data['restored'], len(data['items']))

        row = self.box.session(SID_1)
        self.assertEqual(row['workspace_id'], WS_A)
        self.assertEqual(row['cwd'], self.box.proj_a)
        self.assertNotIn(created[0], self.box.workspace_ids())    # 新建的工作区行已删
        self.assertTrue(os.path.isfile(os.path.join(self.box.dir_a, SID_1 + '.jsonl')))

    def test_rollback_manifest_missing_json(self):
        # 清单不存在 → JSON_MODE 下 stdout 也必须是合法 JSON（不能是半截人话）
        r = self.run_cli('rollback', '--manifest', os.path.join(self.box.bk, 'nope.json'), '--json')
        self.assertEqual(r.returncode, 2)
        payload = json.loads(r.stdout)
        self.assertIn('error', payload)
        self.assertEqual(payload['exit'], 2)

    def test_rollback_batch_dry_run_json(self):
        # 真清单 + 不带 --apply：必须是合法单文档，且一个字都不写
        new_root = os.path.join(self.box.root, 'dry-run-target')
        self.run_cli('move', '--to', new_root, '--create', '--allow-missing',
                     '--ids', SID_1[:8], '--apply', expect=0)
        batches = self.box.batches('move')
        self.assertTrue(batches)
        before = self.box.session(SID_1)

        data = self.run_json('rollback', '--batch', batches[0], '--yes', expect=0)
        self.assertEqual(data['restored'], 0)
        self.assertEqual(data['failed'], 0)
        self.assertEqual(data['items'], [])
        self.assertFalse(data['applied'])

        after = self.box.session(SID_1)          # 干跑不改库
        self.assertEqual(after['workspace_id'], before['workspace_id'])
        self.assertEqual(after['cwd'], before['cwd'])


# ---------------------------------------------------------------- 9 doctor

class TestDoctor(CliTestCase):

    BASE_CHECKS = ['数据库', 'WAL 状态', '表结构', 'Qoder 进程', '工作区路径', '影子任务', '备份']
    DEEP_CHECKS = ['任务文件', '目录一致性', '项目记忆', '产出索引', '孤立项目目录']

    def test_deep_all_green_after_backup(self):
        self.run_cli('backup', expect=0)
        data = self.run_json('doctor', '--deep', expect=0)
        names = [c['check'] for c in data['checks']]
        # 断言项数与项名，避免「checks 变成空数组也算绿」
        self.assertEqual(len(data['checks']), 12,
                         msg=json.dumps(data['checks'], ensure_ascii=False, indent=2))
        self.assertEqual(names, self.BASE_CHECKS + self.DEEP_CHECKS)
        self.assertEqual([c['check'] for c in data['checks'] if not c['ok']], [],
                         msg=json.dumps(data['checks'], ensure_ascii=False, indent=2))

    def test_backup_check_suggests_first_backup_but_passes(self):
        # 「有数据但从未备份」只提示、不判失败（否则新装用户第一眼就是 !!/exit 1）
        before = self.run_json('doctor', expect=0)
        backup_check = [c for c in before['checks'] if c['check'] == '备份'][0]
        self.assertTrue(backup_check['ok'], msg=backup_check)
        self.assertIn('建议先跑一次 backup', backup_check['detail'])
        # 备份之后仍为 OK
        self.run_cli('backup', expect=0)
        after = self.run_json('doctor', expect=0)
        self.assertTrue([c for c in after['checks'] if c['check'] == '备份'][0]['ok'])

    def test_deep_reports_orphan_project_dir(self):
        orphan = os.path.join(self.box.projects, 'C--orphan-empty')
        os.makedirs(orphan, exist_ok=True)
        self.run_cli('backup', expect=0)
        data = self.run_json('doctor', '--deep')
        checks = {c['check']: c for c in data['checks']}
        self.assertIn('孤立项目目录', checks)
        self.assertFalse(checks['孤立项目目录']['ok'])
        self.assertIn('orphan-empty', checks['孤立项目目录']['detail'])


# ---------------------------------------------------------------- 10 版本号 + frontmatter
#
# v1.7.0 的 SKILL.md 把 `description_en` 写成一段未加引号的 plain scalar，中间带着
# 半角冒号 + 空格（`... on a daily schedule: any task ...`）。YAML 规范里 plain
# scalar 不允许出现 `: `——它会被当成嵌套 mapping 的开头，于是 WorkBuddy 开放平台
# 上传时报 `frontmatter 无法解析 / mapping values are not allowed in this context`
# 直接拒包。SkillHub 只按正则取 camelCase 字段、从不跑 YAML 解析，所以这个雷从
# v1.6.0 起就埋在包里，直到第一次上传 WorkBuddy 才炸。
#
# 下面用最小判据把这类写法焊死，纯标准库实现，不给测试套件引入 PyYAML 依赖。

FM_FENCE = '---'
FM_KEY = re.compile(r'^([A-Za-z_][\w-]*):\s*(.*)$')

try:                     # 严格解析只在装了 PyYAML 的环境里跑，不给测试套件加硬依赖
    import yaml
except ImportError:      # CI / 干净环境：相关用例 skipped，手搓断言仍然兜底
    yaml = None


def frontmatter_lines():
    """返回 SKILL.md frontmatter 的每一行（第一个 --- 与第二个 --- 之间，不含分隔线）。"""
    with open(SKILL_MD, encoding='utf-8') as f:
        text = f.read()
    lines = text.replace('\r\n', '\n').replace('\r', '\n').split('\n')
    if not lines or lines[0].strip() != FM_FENCE:
        raise AssertionError('SKILL.md 必须以 --- 开头：WorkBuddy 只认带 frontmatter 的包')
    for i in range(1, len(lines)):
        if lines[i].strip() == FM_FENCE:
            return lines[1:i]
    raise AssertionError('SKILL.md frontmatter 缺少结束的 ---')


def frontmatter_text():
    """frontmatter 的原始文本（真解析器直接吃这一份，与平台读到的内容一致）。"""
    return '\n'.join(frontmatter_lines())


def _unquote(value):
    """剥掉成对外层引号；引号内的转义按 YAML 单/双引号规则还原。"""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        inner = value[1:-1]
        if value[0] == '"':
            return inner.replace('\\"', '"').replace('\\\\', '\\')
        return inner.replace("''", "'")
    return value


def frontmatter_map():
    """把 frontmatter 解析成 dict：标量是 str，block sequence（`  - x`）是 list[str]。

    值统一剥掉成对外层引号，否则长度断言会被引号带偏；flow sequence
    （`tags: [a, b]`）保持原字符串，交给 `as_items()` 拆。
    """
    fm = {}
    current = None
    for line in frontmatter_lines():
        if not line.strip():
            continue                      # 空行
        if line.startswith((' ', '\t')):
            if current is None:
                raise AssertionError(f'frontmatter 出现没有归属键的序列项：{line!r}')
            if not isinstance(fm[current], list):
                fm[current] = []
            fm[current].append(_unquote(re.sub(r'^-\s+', '', line.strip())))
            continue
        m = FM_KEY.match(line)
        if not m:
            raise AssertionError(f'frontmatter 顶层行不是 key: value 形状：{line!r}')
        current = m.group(1)
        fm[current] = _unquote(m.group(2).strip())
    return fm


def as_items(value, key=''):
    """把「block sequence 列表」或「flow sequence 字符串」统一成字符串列表。"""
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.startswith('[') and value.endswith(']'):
        inner = value[1:-1].strip()
        return [_unquote(x.strip()) for x in inner.split(',')] if inner else []
    raise AssertionError(f'{key} 不是序列（既非 block sequence 也非 flow sequence）：{value!r}')


def skill_md_version():
    """SKILL.md 的 version 值（版本号三处一致的其中一处，供两处测试复用）。"""
    return frontmatter_map()['version']


class TestVersion(unittest.TestCase):

    def test_single_source_of_truth(self):
        with open(SCRIPT, encoding='utf-8') as f:
            script_version = re.search(r"^VERSION = '([^']+)'", f.read(), re.M).group(1)
        skill_version = skill_md_version()
        self.assertEqual(script_version, build_pkg.VERSION)
        self.assertEqual(script_version, skill_version)
        self.assertEqual(script_version, '1.7.1')


class TestSkillFrontmatter(unittest.TestCase):
    """SKILL.md 的 frontmatter 必须能被严格的 YAML 解析器吃下去。

    这是 WorkBuddy 开放平台上传的前置条件：解析失败直接拒包。SkillHub 侧不跑
    YAML、只看正则，所以只有这一组用例能兜住「包能发出去但传不上去」。
    """

    # 平台侧真正会读的 19 个键：WorkBuddy 的头部卡片还吃 summary / iconUrl，
    # SkillHub 吃 slug / displayName / category / homepage / tags，示例列表两边都渲染。
    REQUIRED_SCALAR = [
        'name', 'version',
        'display_name', 'display_name_zh', 'display_name_en',
        'description', 'description_zh', 'description_en',
        'slug', 'displayName', 'summary', 'iconUrl',
        'category', 'homepage', 'author', 'license',
    ]
    REQUIRED_BLOCK_SEQ = ['examples_zh', 'examples_en']
    REQUIRED_FLOW_SEQ = ['tags']
    REQUIRED = REQUIRED_SCALAR + REQUIRED_BLOCK_SEQ + REQUIRED_FLOW_SEQ
    EXPECTED_KEYS = 19

    def _assert_plain_scalar_safe(self, value, line):
        """未加引号的值：不许有 `: `、制表符、` #`；也不许用 YAML 指示符开头。"""
        if not value:
            return                        # 空值合法：后面跟 block sequence
        if value[0] in ('"', "'"):
            self.assertEqual(value[0], value[-1], f'引号未闭合：{line!r}')
            return
        self.assertNotIn(
            ': ', value,
            f'未加引号的值里出现「半角冒号 + 空格」，YAML 会当成嵌套 mapping '
            f'（v1.7.0 就是在这里被 WorkBuddy 拒包）：{line!r}')
        self.assertNotIn('\t', value, f'值里不能有制表符：{line!r}')
        self.assertNotIn(' #', value, f'值里的「空格 + #」会被当成注释截断：{line!r}')
        self.assertFalse(value.endswith(':'), f'未加引号的值不能以冒号结尾：{line!r}')
        if value.startswith('['):
            self.assertTrue(value.endswith(']'), f'flow sequence 未闭合（缺 ]）：{line!r}')
        if value.startswith('#'):
            self.fail(f'未加引号的值不能以 # 开头（整行会被当注释）：{line!r}')
        # 以下四类是 QA 点出的漏网写法：手搓规则集外会静默改语义，真解析器若没装就没人兜
        if value[0] in '&*!%@`':
            self.fail(f'值不能以 YAML 指示符 {value[0]!r} 开头'
                      f'（会被当锚点/别名/标签/指令）：{line!r}')
        if value.startswith('- '):
            self.fail(f'值不能以 "- " 开头（会被当成序列项）：{line!r}')
        if value in ('|', '>', '|-', '>-', '|+', '>+'):
            self.fail(f'值不能是块标量指示符 {value!r}（多行写法会改变 frontmatter 结构）：{line!r}')
        if value.startswith('? '):
            self.fail(f'值不能以 "? " 开头（复杂键指示符）：{line!r}')

    def test_frontmatter_parses_as_mapping(self):
        """顶层是 mapping，且每个未加引号的值都不含 `: `（本次 Bug 的最小充分判据）。"""
        seen = set()
        for line in frontmatter_lines():
            if not line.strip():
                continue
            if line.startswith((' ', '\t')):
                if line.strip().startswith('?'):
                    self.fail(f'frontmatter 不支持复杂键（? 前缀）：{line!r}')
                # block sequence 的条目：剥掉 "- " 再按标量规则校验
                item = re.sub(r'^-\s+', '', line.strip())
                self._assert_plain_scalar_safe(item, line)
                continue
            m = FM_KEY.match(line)
            self.assertIsNotNone(
                m, f'frontmatter 顶层行无法解析为 key: value（含裸冒号、? 复杂键或缩进错乱）：'
                   f'{line!r}')
            key = m.group(1)
            self.assertNotIn(key, seen, f'frontmatter 键重复，YAML 会静默取最后一个：{key}')
            seen.add(key)
            self._assert_plain_scalar_safe(m.group(2).strip(), line)
        self.assertIn('name', seen)
        self.assertIn('version', seen)

    def test_frontmatter_fence_is_single_pair(self):
        """围栏必须恰好一对、第一个 --- 在首行（三段式会让解析器错位）。"""
        with open(SKILL_MD, encoding='utf-8') as f:
            text = f.read()
        self.assertGreaterEqual(text.count(FM_FENCE), 2, 'frontmatter 围栏至少要有开头与结尾')
        lines = text.replace('\r\n', '\n').replace('\r', '\n').split('\n')
        self.assertEqual(lines[0].strip(), FM_FENCE, 'SKILL.md 第一行必须是 ---')
        fences = [i + 1 for i, line in enumerate(lines) if line.strip() == FM_FENCE]
        self.assertEqual(
            len(fences), 2,
            f'frontmatter 围栏应恰好一对，实际 {len(fences)} 处（行号 {fences}）：'
            f'多出来的 --- 会被解析器当成第二个文档或新 frontmatter')

    @unittest.skipUnless(yaml, '未安装 PyYAML，跳过严格解析断言')
    def test_frontmatter_parses_with_real_yaml(self):
        """真解析器兜底：锚点/别名/标签/块标量/复杂键等手搓规则集覆盖不到的类型。"""
        data = yaml.safe_load(frontmatter_text())
        self.assertIsNotNone(data, 'yaml.safe_load 返回 None：frontmatter 没被当成 mapping')
        self.assertIsInstance(
            data, dict, f'yaml.safe_load 解出的是 {type(data).__name__}，不是 mapping')
        self.assertEqual(
            len(data), self.EXPECTED_KEYS,
            f'frontmatter 键数应为 {self.EXPECTED_KEYS}，实际 {len(data)}：{sorted(data)}')
        self.assertEqual(sorted(data), sorted(self.REQUIRED), '解析出的键集与必需字段集不一致')
        self.assertEqual(data['version'], qs.VERSION)

    def test_required_fields_present(self):
        """两边市场要读的 19 个键都在、类型对、内容非空。"""
        fm = frontmatter_map()
        self.assertEqual(len(self.REQUIRED), 19, '必需字段集固定 19 个')
        self.assertEqual(len(self.REQUIRED), len(set(self.REQUIRED)), '必需字段集不能有重复')

        for key in self.REQUIRED_SCALAR:
            self.assertIn(key, fm, f'frontmatter 缺字段：{key}')
            self.assertIsInstance(fm[key], str, f'{key} 应为标量字符串，实际 {fm[key]!r}')
            self.assertTrue(fm[key].strip(), f'frontmatter 字段为空：{key}')

        # 展示文案会直接渲染到 WorkBuddy / SkillHub 页面，太短多半是占位符
        for key in ('display_name_zh', 'display_name_en', 'description_zh', 'description_en'):
            self.assertGreaterEqual(len(fm[key]), 8, f'{key} 太短，疑似占位符：{fm[key]!r}')

        # 示例列表：两边市场都在页面上逐条渲染
        for key in self.REQUIRED_BLOCK_SEQ:
            self.assertIn(key, fm, f'frontmatter 缺字段：{key}')
            items = as_items(fm[key], key)
            self.assertEqual(len(items), 4, f'{key} 应有 4 条示例，实际 {len(items)}：{items!r}')
            for i, item in enumerate(items):
                self.assertIsInstance(item, str, f'{key}[{i}] 应为字符串')
                self.assertTrue(item.strip(), f'{key}[{i}] 是空字符串')

        # 标签：SkillHub 首页用它做筛选与分类
        for key in self.REQUIRED_FLOW_SEQ:
            self.assertIn(key, fm, f'frontmatter 缺字段：{key}')
            items = as_items(fm[key], key)
            self.assertGreaterEqual(
                len(items), 3, f'{key} 至少 3 项，实际 {len(items)}：{items!r}')
            for i, item in enumerate(items):
                self.assertTrue(item.strip(), f'{key}[{i}] 是空字符串')

    def test_version_matches_script(self):
        """SKILL.md 的 version 与主脚本 VERSION 一致（三处一致由 TestVersion 兜住）。"""
        self.assertEqual(skill_md_version(), qs.VERSION)
        self.assertEqual(skill_md_version(), build_pkg.VERSION)


# ---------------------------------------------------------------- list / workspace

class TestSafetyBoundaries(unittest.TestCase):
    """A2 的安全闸门与 A1 的备份落盘边界。"""

    DEFAULT_DB = (qs.qoder_db_candidates()
                  or [r'C:\Users\HuaHua\AppData\Roaming\com.qoder.app.stable\main.sqlite'])[0]

    @unittest.skipUnless(os.name == 'nt', '大小写不敏感是 Windows 路径语义')
    def test_is_custom_db_ignores_case(self):
        # 同一个库换个写法（全小写）仍是默认库 —— 否则 CUSTOM_DB 误判为副本，
        # 整库覆盖硬拦 / gate_running / post_write_hint 三处保护会一起失效。
        self.assertFalse(qs.is_custom_db(self.DEFAULT_DB.lower(), self.DEFAULT_DB))
        self.assertFalse(qs.is_custom_db(self.DEFAULT_DB, self.DEFAULT_DB))

    def test_is_custom_db_different_path(self):
        self.assertTrue(qs.is_custom_db(r'D:\copy\main.sqlite', self.DEFAULT_DB))

    def test_is_custom_db_without_default(self):
        # 探测不到默认库时，只要传了 --db 就算副本
        self.assertTrue(qs.is_custom_db(r'D:\copy\main.sqlite', None))

    def test_is_custom_db_without_arg(self):
        self.assertFalse(qs.is_custom_db(None, self.DEFAULT_DB))

    def test_backup_path_drive_relative_rel_does_not_escape(self):
        # rel=D:x.txt 是盘相对路径，os.path.join 会把它退化成 'D:x.txt' 写到备份根之外
        with tempfile.TemporaryDirectory(prefix='qtbk-') as tmp:
            base = os.path.join(tmp, 'set')
            src = os.path.join(tmp, 'src.txt')
            with open(src, 'w', encoding='utf-8') as f:
                f.write('X')
            sid = 'abcdef12-0000-4000-8000-000000000000'
            bucket = os.path.join(base, 'files', sid[:8], 'output')
            dst = qs.backup_path(src, base, sid, 'output', 'D:x.txt')
            self.assertTrue(os.path.abspath(dst).startswith(os.path.abspath(bucket) + os.sep),
                            msg='备份落到了备份目录之外: %s' % dst)
            self.assertTrue(os.path.isfile(dst))
            if os.name == 'nt':
                # 回退成 basename + 绝对路径 sha1 前 8 位
                stem, ext = os.path.splitext(os.path.basename(src))
                self.assertRegex(os.path.basename(dst),
                                 r'^%s-[0-9a-f]{8}%s$' % (re.escape(stem), re.escape(ext)))

    def test_backup_path_keeps_relative_hierarchy(self):
        # 守卫不能把正常相对路径也挡了：目录层级必须保留
        with tempfile.TemporaryDirectory(prefix='qtbk-') as tmp:
            base = os.path.join(tmp, 'set')
            src = os.path.join(tmp, 'proj', 'out', 'x', 'log.txt')
            os.makedirs(os.path.dirname(src), exist_ok=True)
            with open(src, 'w', encoding='utf-8') as f:
                f.write('X')
            sid = 'abcdef12-0000-4000-8000-000000000000'
            dst = qs.backup_path(src, base, sid, 'output', os.path.join('out', 'x', 'log.txt'))
            want = os.path.join(base, 'files', sid[:8], 'output', 'out', 'x', 'log.txt')
            self.assertEqual(os.path.normcase(dst), os.path.normcase(want))
            with open(dst, encoding='utf-8') as f:
                self.assertEqual(f.read(), 'X')


class TestRollbackHotGuard(unittest.TestCase):
    """A2：整库覆盖在 Qoder 运行中必须硬拦。

    subprocess 没法伪造「Qoder 正在运行」，所以这里 import 被测模块直接调
    `cmd_rollback()`，用 mock 把 `qoder_running()` 打成 2，并临时把
    `CUSTOM_DB` 置 False 模拟真实库。
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix='qtguard-')
        self.box = Sandbox(self._tmp.name)
        self._saved = (qs.CUSTOM_DB, qs.BACKUP_ROOT, qs.JSON_MODE)
        qs.CUSTOM_DB = False              # 关键：模拟真实库，闸门必须生效
        qs.BACKUP_ROOT = self.box.bk      # 别把备份写到仓库目录
        qs.JSON_MODE = False

    def tearDown(self):
        qs.CUSTOM_DB, qs.BACKUP_ROOT, qs.JSON_MODE = self._saved
        self._tmp.cleanup()

    def _snapshot(self):
        d = os.path.join(self.box.bk, 'db')
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, 'main.sqlite.bak-manual-test')
        shutil.copyfile(self.box.db, p)
        return p

    @staticmethod
    def _args(**kw):
        base = dict(backup=None, manifest=None, batch=None, yes=True, apply_flag=True,
                    require_closed=False, force_hot=False, json=False)
        base.update(kw)
        return argparse.Namespace(**base)

    def test_backup_rollback_blocked_while_qoder_running(self):
        src = self._snapshot()
        con = qs.connect(self.box.db)
        try:
            with mock.patch.object(qs, 'qoder_running', return_value=2):
                with self.assertRaises(SystemExit) as cm:
                    qs.cmd_rollback(self._args(backup=src), con, self.box.db)
            self.assertEqual(cm.exception.code, 3)
        finally:
            con.close()

    def test_force_hot_passes_guard(self):
        src = self._snapshot()
        con = qs.connect(self.box.db)
        try:
            with mock.patch.object(qs, 'qoder_running', return_value=2):
                rc = qs.cmd_rollback(self._args(backup=src, force_hot=True), con, self.box.db)
            self.assertEqual(rc, 0)       # 显式 --force-hot 才放行
        finally:
            con.close()


class TestListAndWorkspace(CliTestCase):

    @staticmethod
    def _hint_count(text):
        """从「另有 N 条影子任务未显示」里取 N；没有该行为 0。"""
        m = re.search(r'另有 (\d+) 条影子任务未显示', text)
        return int(m.group(1)) if m else 0

    def test_list_hides_peer_but_hints(self):
        r = self.run_cli('list', expect=0)
        self.assertNotIn(SID_PEER[:8], r.stdout)
        self.assertIn('影子任务未显示', r.stdout)
        self.assertIn('--include-peer', r.stdout)
        data = self.run_json('list', expect=0)
        self.assertIsInstance(data, list)
        self.assertFalse(any(x['peer'] for x in data))

    def test_list_hint_count_ignores_limit(self):
        # 回归：提示数必须是「同一筛选范围内的影子数」，不能是「全库总数 − 结果数」。
        # 夹具里恰好 1 条影子，所以任何 --limit 下提示都该是 1（旧口径 --limit 1 会报 2）。
        for extra in ([], ['--limit', '1'], ['--limit', '2']):
            r = self.run_cli('list', *extra, expect=0)
            self.assertEqual(self._hint_count(r.stdout), 1, msg='%s\n%s' % (extra, r.stdout))

    def test_list_hint_scoped_by_keyword_only_peer(self):
        # 关键词只命中影子：结果为空，但本该提示「有 1 条影子被隐藏」
        # 旧口径在这里会报「3 − 0 = 3」。
        r = self.run_cli('list', '--keyword', '对端', expect=0)
        self.assertIn('没有匹配的任务', r.stdout)
        self.assertEqual(self._hint_count(r.stdout), 1, msg=r.stdout)

    def test_list_hint_absent_when_scope_has_no_peer(self):
        # 关键词只命中本地任务：该范围内没有影子，不应出现提示
        r = self.run_cli('list', '--keyword', '甲任务', expect=0)
        self.assertNotIn('影子任务未显示', r.stdout)
        self.assertEqual(self._hint_count(r.stdout), 0)

    def test_list_hint_scoped_by_workspace(self):
        # TestB 下有 1 条影子；旧口径会报「3 − 1 = 2」
        r = self.run_cli('list', '--workspace', 'TestB', expect=0)
        self.assertEqual(self._hint_count(r.stdout), 1, msg=r.stdout)
        # TestA 下没有影子 → 不提示
        r = self.run_cli('list', '--workspace', 'TestA', expect=0)
        self.assertNotIn('影子任务未显示', r.stdout)
        self.assertEqual(self._hint_count(r.stdout), 0)

    def test_workspace_list_has_device_column(self):
        r = self.run_cli('workspace', 'list', expect=0)
        self.assertIn('设备', r.stdout)
        self.assertIn('本机', r.stdout)
        data = self.run_json('workspace', 'list', expect=0)
        self.assertIsInstance(data, list)
        self.assertTrue(all('device' in x for x in data))

    def test_workspace_list_distinguishes_same_name_peers(self):
        # 本地一份 + 两台对端各一份，同名三行必须能靠 device 区分
        self.box.add_workspace('cccccccc-0000-4000-8000-000000000001', '野草云4C8G',
                               'peer:f659e85d-f535-447b-a3e9-e44f03dc9db', r'D:\B\野草云4C8G')
        self.box.add_workspace('dddddddd-0000-4000-8000-000000000002', '野草云4C8G',
                               'peer:c174a08a-e2d4-493f-b6a3-7c980bc2381', r'D:\B\野草云4C8G')
        self.box.add_workspace('eeeeeeee-0000-4000-8000-000000000003', '野草云4C8G',
                               'local', r'D:\B\野草云4C8G')
        data = self.run_json('workspace', 'list', expect=0)
        rows = [x for x in data if x['name'] == '野草云4C8G']
        self.assertEqual(len(rows), 3)
        self.assertEqual({x['device'] for x in rows}, {'f659e85d', 'c174a08a', '本机'})
        peers = [x for x in rows if x['device'] != '本机']
        self.assertNotEqual(peers[0]['device'], peers[1]['device'])

    def test_retarget_warns_about_repair(self):
        new_root = os.path.join(self.box.root, 'retargeted')
        os.makedirs(new_root, exist_ok=True)
        r = self.run_cli('workspace', 'retarget', '--name', 'TestA',
                         '--path', new_root, '--apply', expect=0)
        self.assertIn('repair', r.stdout)
        self.assertIn('项目记忆', r.stdout)
        data = self.run_json('workspace', 'retarget', '--name', 'TestA',
                             '--path', new_root, '--apply', expect=0)
        self.assertIn('repair', data['note'])

    def test_workspace_new_json_single_document(self):
        path = os.path.join(self.box.root, 'ws-new')
        os.makedirs(path, exist_ok=True)
        dry = self.run_json('workspace', 'new', '--name', 'NewWs', '--path', path, expect=0)
        self.assertFalse(dry['applied'])
        done = self.run_json('workspace', 'new', '--name', 'NewWs', '--path', path,
                             '--apply', expect=0)
        self.assertTrue(done['applied'])
        self.assertIn(done['id'], self.box.workspace_ids())


if __name__ == '__main__':
    unittest.main()
