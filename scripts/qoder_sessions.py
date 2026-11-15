#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Qoder 会话管理：列出 / 重命名 / 迁移工作区 / 管理工作区 / 备份回滚 / 体检。

只依赖 Python 3.9+ 标准库。只操作 Qoder 本地数据（Windows）。
所有写操作默认 dry-run，必须显式 --apply 才落盘；落盘前自动整库备份。
"""
import argparse
import glob
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import uuid
from datetime import datetime

VERSION = '1.0.0'
BACKUP_KEEP = 10

# ---------------------------------------------------------------- 路径与基础

def qoder_db_candidates():
    """Windows 上 Qoder 主库的候选路径，按可能性排序。"""
    appdata = os.environ.get('APPDATA') or ''
    local = os.environ.get('LOCALAPPDATA') or ''
    cands = []
    if appdata:
        for profile in ('com.qoder.app.stable', 'Qoder', 'qoder', 'com.qoder.app.insider'):
            cands.append(os.path.join(appdata, profile, 'main.sqlite'))
    if local:
        cands.append(os.path.join(local, 'Qoder', 'main.sqlite'))
    return cands


def resolve_db(explicit=None):
    if explicit:
        if not os.path.isfile(explicit):
            die(f'指定的数据库不存在: {explicit}')
        return os.path.abspath(explicit)
    for p in qoder_db_candidates():
        if os.path.isfile(p):
            return os.path.abspath(p)
    die('未找到 Qoder 数据库。请用 --db 指定 main.sqlite 的路径。')


def now_ms():
    return int(time.time() * 1000)


def fmt_ms(ms):
    if not ms:
        return '-'
    try:
        return datetime.fromtimestamp(int(ms) / 1000).strftime('%Y-%m-%d %H:%M')
    except Exception:
        return str(ms)


def out(msg=''):
    print(msg)


def die(msg, code=2):
    print(f'[ERROR] {msg}', file=sys.stderr)
    sys.exit(code)


def connect(db_path, write=False):
    if write:
        con = sqlite3.connect(db_path, timeout=8)
    else:
        con = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True, timeout=8)
    con.row_factory = sqlite3.Row
    return con


def qoder_running():
    """返回正在运行的 Qoder 进程数（Windows 用 tasklist）。"""
    if os.name != 'nt':
        return 0
    try:
        r = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq Qoder.exe'],
                           capture_output=True, text=True, errors='ignore', timeout=15)
        return max(0, (r.stdout or '').lower().count('qoder.exe'))
    except Exception:
        return 0


CUSTOM_DB = False   # --db 指向非默认库（副本）时为 True，此时不要求 Qoder 退出


def require_closed(force=False):
    if CUSTOM_DB:
        return
    n = qoder_running()
    if n and not force:
        die(f'检测到 {n} 个 Qoder 进程在运行。请完全退出 Qoder 后重试，'
            f'或确认风险后加 --force。', 3)
    if n and force:
        out(f'[WARN] Qoder 仍在运行（{n} 个进程），按 --force 继续写入。')


# ---------------------------------------------------------------- 数据访问

REQUIRED_COLUMNS = {
    'chat_sessions': ['session_id', 'title', 'cwd', 'workspace_id', 'extra_json',
                      'execution_target_json', 'created_at', 'updated_at', 'archived', 'deleted_at'],
    'workspaces': ['workspace_id', 'name', 'workspace_source', 'root_paths_json'],
}


def table_columns(con, table):
    try:
        return [r[1] for r in con.execute(f'PRAGMA table_info({table})')]
    except sqlite3.Error:
        return []


def load_json(text, default=None):
    try:
        v = json.loads(text or '{}')
        return v if isinstance(v, (dict, list)) else (default if default is not None else {})
    except Exception:
        return default if default is not None else {}


def workspace_roots(row):
    try:
        v = json.loads(row['root_paths_json'] or '[]')
        return [str(x) for x in v] if isinstance(v, list) else []
    except Exception:
        return []


def primary_root(row):
    roots = workspace_roots(row)
    return roots[0] if roots else ''


def load_workspaces(con, include_deleted=False):
    sql = 'select * from workspaces'
    if not include_deleted and 'deleted_at' in table_columns(con, 'workspaces'):
        sql += ' where deleted_at is null'
    return list(con.execute(sql + ' order by updated_at desc'))


def find_workspace(con, key, include_deleted=False, local_only=False):
    """按 UUID / 名称 / 根路径 匹配。

    同名时优先返回唯一的本地工作区（peer 投影不能作为操作对象）；
    仍有多个候选则返回 None + 候选列表，由调用方要求用户指定。
    """
    ws = load_workspaces(con, include_deleted)
    if local_only:
        ws = [w for w in ws if (w['workspace_source'] or '').startswith('local')]
    key_norm = key.strip()
    exact = [w for w in ws if w['workspace_id'] == key_norm]
    if exact:
        return exact[0], []

    def pick(cands):
        if len(cands) == 1:
            return cands[0], []
        locals_ = [w for w in cands if (w['workspace_source'] or '').startswith('local')]
        if len(locals_) == 1:
            return locals_[0], []
        return None, cands

    by_name = [w for w in ws if (w['name'] or '') == key_norm]
    if by_name:
        return pick(by_name)

    norm_path = os.path.normcase(os.path.normpath(key_norm.replace('/', os.sep)))
    by_path = [w for w in ws
               if any(os.path.normcase(os.path.normpath(r.replace('/', os.sep))) == norm_path
                      for r in workspace_roots(w))]
    if by_path:
        return pick(by_path)
    return None, []


def local_workspaces(con):
    return [w for w in load_workspaces(con) if (w['workspace_source'] or '').startswith('local')]


def session_rows(con, include_deleted=False, include_peer=True):
    cols = table_columns(con, 'chat_sessions')
    need = ['session_id', 'title', 'cwd', 'workspace_id', 'created_at', 'updated_at',
            'archived', 'deleted_at', 'extra_json', 'execution_target_json']
    sel = ', '.join(c for c in need if c in cols)
    rows = list(con.execute(f'select {sel} from chat_sessions order by updated_at desc'))
    out_rows = []
    for r in rows:
        d = dict(r)
        d.setdefault('deleted_at', None)
        d.setdefault('archived', 0)
        d.setdefault('workspace_id', None)
        d['_peer'] = is_peer_type(r, d)
        if not include_deleted and d.get('deleted_at'):
            continue
        if not include_peer and d['_peer']:
            continue
        out_rows.append(d)
    return out_rows


def is_peer_type(row, d):
    try:
        e = json.loads(d.get('extra_json') or '{}')
    except Exception:
        e = {}
    if e.get('peerOriginSessionId'):
        return True
    try:
        et = json.loads(d.get('execution_target_json') or '{}')
    except Exception:
        et = {}
    return et.get('mode') == 'peer'


def message_stats(con):
    try:
        return {r[0]: (r[1], r[2]) for r in con.execute(
            'select session_id, count(*), sum(case when role="user" then 1 else 0 end) '
            'from chat_session_messages group by session_id')}
    except sqlite3.Error:
        return {}


# ---------------------------------------------------------------- 筛选表达式

_OPS = ('contains', 'like', 'startswith', 'endswith', '=', '!=')

FIELD_ALIASES = {
    'title': 'title', 'cwd': 'cwd', 'workspace': 'workspace_name',
    'workspace_name': 'workspace_name', 'id': 'session_id', 'sid': 'session_id',
    'status': 'status',
}


class FilterError(Exception):
    pass


def parse_filter(expr):
    """解析形如 `cwd like %NAS% and title contains 工具包` 的安全子集。"""
    if not expr:
        return []
    parts = re.split(r'\s+and\s+', expr, flags=re.I)
    conds = []
    for p in parts:
        m = re.match(r'^\s*([A-Za-z_]+)\s*(contains|like|startswith|endswith|=|!=)\s*(.+?)\s*$',
                     p, flags=re.I)
        if not m:
            raise FilterError(f'无法解析条件片段: {p!r}')
        field, op, val = m.group(1).lower(), m.group(2).lower(), m.group(3).strip()
        if field not in FIELD_ALIASES:
            raise FilterError(f'不支持的字段: {field}（可用: {", ".join(sorted(FIELD_ALIASES))}）')
        if len(val) >= 2 and val[0] == val[-1] and val[0] in '"\'':
            val = val[1:-1]
        conds.append((FIELD_ALIASES[field], op, val))
    return conds


def apply_filter(rows, conds):
    def getv(row, field):
        if field == 'workspace_name':
            return row.get('_ws_name') or ''
        if field == 'status':
            if row.get('deleted_at'):
                return 'deleted'
            return 'archived' if row.get('archived') else 'active'
        return str(row.get(field) or '')

    out = []
    for r in rows:
        ok = True
        for field, op, val in conds:
            v = getv(r, field)
            vl = v.lower()
            vv = val.lower()
            if op == 'contains':
                ok = vv in vl
            elif op == 'like':
                pat = '^' + re.escape(vv).replace(r'\%', '.*').replace('%', '.*').replace('_', '.') + '$'
                ok = re.match(pat, vl) is not None
            elif op == 'startswith':
                ok = vl.startswith(vv)
            elif op == 'endswith':
                ok = vl.endswith(vv)
            elif op == '=':
                ok = vl == vv
            elif op == '!=':
                ok = vl != vv
            if not ok:
                break
        if ok:
            out.append(r)
    return out


# ---------------------------------------------------------------- 备份

def backup_dir(db_path):
    return os.path.dirname(db_path)


def list_backups(db_path):
    pattern = db_path + '.bak-*'
    items = []
    for p in glob.glob(pattern):
        items.append((os.path.getmtime(p), p))
    items.sort(reverse=True)
    return [p for _, p in items]


def make_backup(db_path, tag='manual'):
    ts = time.strftime('%Y%m%d-%H%M%S')
    dst = f'{db_path}.bak-{tag}-{ts}'
    n = 1
    while os.path.exists(dst):
        dst = f'{db_path}.bak-{tag}-{ts}-{n}'
        n += 1
    src = sqlite3.connect(db_path)
    try:
        tgt = sqlite3.connect(dst)
        with tgt:
            src.backup(tgt)
        tgt.close()
    finally:
        src.close()
    prune_backups(db_path)
    return dst


def prune_backups(db_path, keep=BACKUP_KEEP):
    files = list_backups(db_path)
    for p in files[keep:]:
        try:
            os.remove(p)
        except OSError:
            pass


# ---------------------------------------------------------------- doctor

CHECK_NAMES = ['数据库', 'WAL 状态', '表结构', 'Qoder 进程', '工作区路径', '影子会话', '备份']


def cmd_doctor(args, con, db_path):
    results = []

    def add(name, ok, detail):
        results.append({'check': name, 'ok': ok, 'detail': detail})

    # 1 数据库
    try:
        n_sess = con.execute('select count(*) from chat_sessions').fetchone()[0]
        add('数据库', True, f'可读，会话 {n_sess} 条')
    except sqlite3.Error as ex:
        add('数据库', False, str(ex))

    # 2 WAL
    wal = db_path + '-wal'
    if os.path.exists(wal):
        size = os.path.getsize(wal)
        add('WAL 状态', True, f'-wal 存在，{size/1024:.0f} KB（可能有未合并写入）')
    else:
        add('WAL 状态', True, '无 -wal，已 checkpoint')

    # 3 表结构
    missing = []
    for tbl, cols in REQUIRED_COLUMNS.items():
        have = table_columns(con, tbl)
        if not have:
            missing.append(f'缺表 {tbl}')
            continue
        for c in cols:
            if c not in have:
                missing.append(f'{tbl}.{c}')
    add('表结构', not missing, '必需字段齐全' if not missing else '缺失: ' + ', '.join(missing[:6]))

    # 4 进程
    n = qoder_running()
    add('Qoder 进程', n == 0, '未运行，可安全写入' if n == 0 else f'{n} 个进程，写操作会被拒绝')

    # 5 工作区路径
    ws = load_workspaces(con)
    local = [w for w in ws if (w['workspace_source'] or '').startswith('local')]
    bad = [w['name'] for w in local if primary_root(w) and not os.path.exists(primary_root(w))]
    add('工作区路径', not bad,
        f'本地工作区 {len(local)} 个，路径均可达' if not bad else f'不可达: {", ".join(bad[:4])}')

    # 6 影子会话
    try:
        rows = list(con.execute('select session_id, extra_json, execution_target_json from chat_sessions'))
        peers = sum(1 for r in rows if is_peer_type(r, {'extra_json': r['extra_json'],
                                                        'execution_target_json': r['execution_target_json']}))
        ratio = (peers / len(rows) * 100) if rows else 0
        add('影子会话', True, f'{peers}/{len(rows)} 条（{ratio:.0f}%），迁移与改名会自动跳过')
    except sqlite3.Error as ex:
        add('影子会话', False, str(ex))

    # 7 备份
    bks = list_backups(db_path)
    if bks:
        age_h = (time.time() - os.path.getmtime(bks[0])) / 3600
        add('备份', True, f'{len(bks)} 份，最近 {bks[0].split(os.sep)[-1]}（{age_h:.1f} 小时前）')
    else:
        add('备份', False, '尚无备份，首次写入会自动创建')

    if args.json:
        print(json.dumps({'db': db_path, 'version': VERSION, 'checks': results}, ensure_ascii=False, indent=2))
        return 0 if all(r['ok'] for r in results) else 1

    out(f'Qoder 数据库: {db_path}')
    out(f'技能版本: {VERSION}')
    out('')
    for r in results:
        out(f"  [{'OK' if r['ok'] else '!!'}] {r['check']:<10} {r['detail']}")
    out('')
    bad = [r for r in results if not r['ok']]
    out('体检通过' if not bad else f'有 {len(bad)} 项需要注意')
    return 0 if not bad else 1


# ---------------------------------------------------------------- list

def cmd_list(args, con, db_path):
    ws_map = {w['workspace_id']: w['name'] for w in load_workspaces(con, include_deleted=True)}
    stats = message_stats(con)
    rows = session_rows(con, include_deleted=args.include_deleted, include_peer=args.include_peer)

    if args.workspace:
        ws, cands = find_workspace(con, args.workspace, include_deleted=True)
        if not ws:
            if cands:
                die('工作区名不唯一，请用 --workspace 指定其中之一的 UUID：\n' +
                    '\n'.join(f"  {w['workspace_id']}  {w['name']}  {primary_root(w)}" for w in cands))
            die(f'未找到工作区: {args.workspace}')
        rows = [r for r in rows if r['workspace_id'] == ws['workspace_id']]

    for r in rows:
        r['_ws_name'] = ws_map.get(r['workspace_id'], '') or ''

    if args.filter:
        try:
            rows = apply_filter(rows, parse_filter(args.filter))
        except FilterError as ex:
            die(str(ex))

    if args.cwd:
        rows = [r for r in rows if args.cwd.lower() in (r['cwd'] or '').lower()]
    if args.keyword:
        kw = args.keyword.lower()
        rows = [r for r in rows if kw in (r['title'] or '').lower()]
    if args.since:
        try:
            cutoff = int(datetime.strptime(args.since, '%Y-%m-%d').timestamp() * 1000)
        except ValueError:
            die('--since 需要 YYYY-MM-DD 格式')
        rows = [r for r in rows if (r['updated_at'] or 0) >= cutoff]
    if args.limit:
        rows = rows[:args.limit]

    if args.json:
        payload = [{'sid': r['session_id'], 'title': r['title'], 'cwd': r['cwd'],
                    'workspace': r['_ws_name'], 'workspace_id': r['workspace_id'],
                    'archived': bool(r['archived']), 'deleted': bool(r['deleted_at']),
                    'peer': r['_peer'], 'updated_at': r['updated_at'],
                    'messages': stats.get(r['session_id'], (0, 0))[0]}
                   for r in rows]
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if not rows:
        out('没有匹配的会话')
        return 0
    out(f'共 {len(rows)} 条')
    out('')
    out(f"{'ID':<10} {'消息':>4} {'状态':<6} {'工作区':<20} 标题")
    out('-' * 92)
    for r in rows:
        flag = '已删' if r['deleted_at'] else ('归档' if r['archived'] else '')
        if r['_peer']:
            flag = (flag + '+影子').lstrip('+')
        wsname = r['_ws_name'] or '无工作区'
        out(f"{r['session_id'][:8]:<10} {stats.get(r['session_id'], (0, 0))[0]:>4} "
            f"{flag:<6} {wsname[:20]:<20} {(r['title'] or '')[:44]}")
    return 0


# ---------------------------------------------------------------- rename

FORBIDDEN = set('"“”\'‘’《》<>。？?！!\n\r\t/\\|')


def validate_title(t):
    t = (t or '').strip()
    errs = []
    if not t:
        errs.append('空标题')
    if any(c in FORBIDDEN for c in t):
        errs.append('含非法字符（引号/书名号/句号/问号/换行/路径分隔符）')
    if len(t) > 40:
        errs.append(f'过长（{len(t)} 字符）')
    if len(t) < 2:
        errs.append('过短')
    return t, errs


def render_transcript(con, sid, user_cap=4000, assist_cap=1500):
    turns = []
    try:
        msgs = con.execute('select sequence, role, payload_json from chat_session_messages '
                           'where session_id=? order by sequence', (sid,))
    except sqlite3.Error:
        return '(无消息表)'
    for m in msgs:
        if m['role'] not in ('user', 'assistant'):
            continue
        txt, tools = extract_parts(m['payload_json'])
        if len(txt) < 2 and not tools:
            continue
        turns.append((m['role'], txt, tools))
    if not turns:
        return '(无正文)'
    lines = []
    ui = 0
    for role, txt, tools in turns:
        if role == 'user':
            ui += 1
            lines.append(f'\n--- 用户第{ui}轮 ---\n{cap(txt, user_cap)}')
        else:
            suffix = f'〔含 {tools} 次工具调用〕' if tools else ''
            lines.append(f'[助手] {cap(txt, assist_cap)}{suffix}')
    return '\n'.join(lines)


TOOL_LABEL = {'Bash': '执行命令', 'Read': '读文件', 'Write': '写文件', 'Edit': '改文件',
              'Grep': '搜索', 'Glob': '找文件', 'WebFetch': '抓网页', 'WebSearch': '联网搜索'}


def extract_parts(payload):
    try:
        d = json.loads(payload or '{}')
    except Exception:
        return '', 0
    buf, tools = [], 0
    for p in d.get('parts') or []:
        ty = p.get('type')
        if ty == 'text':
            buf.append(p.get('text') or '')
        elif ty == 'tool_call':
            tc = p.get('toolCall') or {}
            nm = tc.get('name') or p.get('name') or ''
            if nm:
                tools += 1
                buf.append(f'〔{TOOL_LABEL.get(nm, "调用工具")}·{nm}〕')
    txt = '\n'.join(x for x in buf if x)
    txt = re.sub(r'\n{3,}', '\n\n', txt).strip()
    return txt, tools


def cap(t, n):
    t = t or ''
    if len(t) <= n:
        return t
    head = t[:int(n * 0.72)].rstrip()
    tail = t[-int(n * 0.28):].lstrip()
    return f'{head}\n…〔中间省略 {len(t)-n} 字〕…\n{tail}'


def cmd_rename(args, con, db_path):
    if args.export:
        return rename_export(args, con, db_path)
    if args.import_file:
        return rename_apply(args, con, db_path)
    die('请指定 rename --export 或 rename --import <titles.json>')


def rename_export(args, con, db_path):
    ws_map = {w['workspace_id']: w for w in load_workspaces(con, include_deleted=True)}
    stats = message_stats(con)
    rows = session_rows(con, include_deleted=False, include_peer=False)

    if args.ids:
        want = {s.strip() for s in args.ids.split(',') if s.strip()}
        rows = [r for r in rows if any(r['session_id'].startswith(w) for w in want)]
    for r in rows:
        w = ws_map.get(r['workspace_id'])
        r['_ws_name'] = w['name'] if w else ''
    if args.filter:
        try:
            rows = apply_filter(rows, parse_filter(args.filter))
        except FilterError as ex:
            die(str(ex))
    if args.limit:
        rows = rows[:args.limit]

    if not rows:
        out('没有匹配的会话')
        return 0

    outdir = args.out or os.path.join(os.getcwd(), 'qoder-rename-export')
    os.makedirs(outdir, exist_ok=True)
    index = []
    for r in rows:
        e = load_json(r['extra_json'])
        msgs, users = stats.get(r['session_id'], (0, 0))
        body = [
            f"SESSION_ID: {r['session_id']}",
            f"CURRENT_TITLE: {(r['title'] or '').strip()}",
            f"TITLE_SOURCE: {e.get('titleSource', '')}",
            f"WORKSPACE: {r['_ws_name'] or '(无工作区)'}",
            f"CWD: {r['cwd']}",
            f"UPDATED_AT: {fmt_ms(r['updated_at'])}",
            f"MSG_COUNT: {msgs}",
            f"USER_TURNS: {users}",
            '===== 完整对话历史（时间顺序）=====',
            render_transcript(con, r['session_id'], args.user_cap, args.assist_cap),
        ]
        path = os.path.join(outdir, r['session_id'][:8] + '.txt')
        with open(path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(body))
        index.append({'sid': r['session_id'], 'short': r['session_id'][:8],
                      'title': (r['title'] or '').strip(), 'title_source': e.get('titleSource'),
                      'workspace': r['_ws_name'], 'messages': msgs, 'user_turns': users,
                      'bytes': os.path.getsize(path)})

    with open(os.path.join(outdir, 'index.json'), 'w', encoding='utf-8') as f:
        json.dump(index, f, ensure_ascii=False, indent=2)

    if args.json:
        print(json.dumps({'out_dir': outdir, 'count': len(index), 'items': index}, ensure_ascii=False, indent=2))
        return 0
    out(f'已导出 {len(index)} 个会话的完整历史 -> {outdir}')
    out(f'索引文件: {os.path.join(outdir, "index.json")}')
    out('')
    out('下一步：让 agent 读这些 .txt，生成 titles.json（[{"sid": "...", "new_title": "..."}]），')
    out('然后用 rename --import titles.json --apply 写回。')
    return 0


def rename_apply(args, con, db_path):
    path = args.import_file
    if not os.path.isfile(path):
        die(f'标题文件不存在: {path}')
    with open(path, encoding='utf-8') as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as ex:
            die(f'标题文件不是合法 JSON: {ex}')
    if isinstance(data, dict) and 'items' in data:
        data = data['items']
    if not isinstance(data, list):
        die('标题文件应为数组：[{"sid": "...", "new_title": "..."}]')

    all_rows = session_rows(con, include_deleted=True, include_peer=True)
    by_short = {r['session_id'][:8]: r for r in all_rows}
    full_ids = {r['session_id'] for r in all_rows}

    plan, skipped = [], []
    for it in data:
        sid = str(it.get('sid') or '').strip()
        if not sid:
            skipped.append(('-', '缺少 sid', ''))
            continue
        if len(sid) >= 36:
            if sid not in full_ids:
                skipped.append((sid[:8], '库中不存在', ''))
                continue
            row = by_short[sid[:8]]
        else:
            row = by_short.get(sid)
            if not row:
                skipped.append((sid[:8], '库中不存在', ''))
                continue
        if row['_peer']:
            skipped.append((sid[:8], '影子会话（正文在另一台设备），已拒绝', ''))
            continue
        if row['deleted_at']:
            skipped.append((sid[:8], '会话已删除，已跳过', ''))
            continue
        title, errs = validate_title(it.get('new_title'))
        if errs:
            skipped.append((sid[:8], '；'.join(errs), title))
            continue
        if title == (row['title'] or '').strip():
            skipped.append((sid[:8], '与现标题相同', title))
            continue
        plan.append((row['session_id'], row['title'], title))

    dup = {}
    for _, _, t in plan:
        dup[t] = dup.get(t, 0) + 1

    if args.json:
        print(json.dumps({'plan': [{'sid': s, 'old': o, 'new': n} for s, o, n in plan],
                          'skipped': [{'sid': s, 'reason': r} for s, r, _ in skipped],
                          'duplicates': [k for k, v in dup.items() if v > 1]},
                         ensure_ascii=False, indent=2))
        if not args.apply_flag:
            return 0

    if not args.json:
        out(f'待写入 {len(plan)} 条，跳过 {len(skipped)} 条')
        if any(v > 1 for v in dup.values()):
            out('')
            out('[WARN] 存在重复标题：' + '、'.join(k for k, v in dup.items() if v > 1))
        out('')
        for sid, old, new in plan:
            out(f'  {sid[:8]}  旧: {(old or "")[:40]}')
            out(f'            新: {new}')
        if skipped:
            out('')
            out('--- 跳过 ---')
            for sid, reason, t in skipped:
                out(f'  {sid}  {reason}' + (f'  | {t[:30]}' if t else ''))

    if not args.apply_flag:
        out('')
        out('[DRY-RUN] 未写入。确认后加 --apply 落盘。')
        return 0

    require_closed(args.force)
    bk = make_backup(db_path, 'rename')
    out(f'已备份: {os.path.basename(bk)}')

    w = connect(db_path, write=True)
    try:
        with w:
            for sid, _, new in plan:
                row = w.execute('select extra_json from chat_sessions where session_id=?', (sid,)).fetchone()
                e = load_json(row['extra_json'] if row else '{}')
                e['titleResolved'] = True
                e['titleSource'] = 'custom'
                e['titleRevision'] = int(e.get('titleRevision') or 0) + 1
                w.execute('update chat_sessions set title=?, extra_json=? where session_id=?',
                          (new, json.dumps(e, ensure_ascii=False, separators=(',', ':')), sid))
    finally:
        w.close()
    out(f'已写入 {len(plan)} 条标题')
    return 0


# ---------------------------------------------------------------- move

def infer_et_id(con, target_ws_id, target_root):
    """优先复用目标工作区已有会话的 execution_target_json.workspace.id。"""
    ids = {}
    for r in con.execute('select execution_target_json from chat_sessions where workspace_id=?', (target_ws_id,)):
        et = load_json(r[0])
        wid = (et.get('workspace') or {}).get('id')
        if wid:
            ids[wid] = ids.get(wid, 0) + 1
    if ids:
        return max(ids.items(), key=lambda x: x[1])[0], True
    return target_ws_id, False


def cmd_move(args, con, db_path):
    ws, cands = find_workspace(con, args.to, include_deleted=False, local_only=True)
    if not ws:
        if cands:
            die('目标工作区名不唯一，请改用 UUID：\n' +
                '\n'.join(f"  {w['workspace_id']}  {w['name']}  {primary_root(w)}" for w in cands))
        die(f'未找到目标工作区: {args.to}（可用 workspace new 创建）')
    if not (ws['workspace_source'] or '').startswith('local'):
        die(f'目标工作区是另一台设备的投影（{ws["workspace_source"]}），本机不能作为迁移目标')
    root = primary_root(ws)
    if not root:
        die('目标工作区没有根路径')

    et_id, reused = infer_et_id(con, ws['workspace_id'], root)
    stats = message_stats(con)
    rows = session_rows(con, include_deleted=False, include_peer=False)
    rows = [r for r in rows if r['workspace_id'] != ws['workspace_id']] if args.skip_in_target else rows

    if args.ids:
        want = [s.strip() for s in args.ids.split(',') if s.strip()]
        rows = [r for r in rows if any(r['session_id'].startswith(w) for w in want)]
    if args.filter:
        try:
            rows = apply_filter(rows, parse_filter(args.filter))
        except FilterError as ex:
            die(str(ex))

    plan = [r for r in rows if r['workspace_id'] != ws['workspace_id']]

    if not plan:
        out('没有需要迁移的会话')
        return 0

    if args.json:
        print(json.dumps({'target': {'id': ws['workspace_id'], 'name': ws['name'], 'root': root,
                                     'et_id': et_id, 'et_id_reused': reused},
                          'plan': [{'sid': r['session_id'], 'title': r['title'], 'from': r['cwd']} for r in plan],
                          'applied': bool(args.apply_flag)}, ensure_ascii=False, indent=2))
        if not args.apply_flag:
            return 0
    else:
        out(f"目标: {ws['name']}  ({root})")
        out(f"执行标识: {et_id}" + ('（复用该工作区已有值）' if reused else '（新工作区，使用 UUID）'))
        out('')
        out(f'待迁移 {len(plan)} 条：')
        for r in plan:
            out(f"  {r['session_id'][:8]}  {(r['title'] or '')[:38]}")
            out(f"      {r['cwd']}  ->  {root}")

    if not args.apply_flag:
        out('')
        out('[DRY-RUN] 未写入。加 --apply 执行。')
        return 0

    require_closed(args.force)
    bk = make_backup(db_path, 'move')
    out(f'已备份: {os.path.basename(bk)}')

    et = {'mode': 'local',
          'host': {'id': 'local', 'kind': 'local', 'label': 'Local'},
          'workspace': {'id': et_id, 'path': root}}
    et_json = json.dumps(et, ensure_ascii=False, separators=(',', ':'))
    w = connect(db_path, write=True)
    try:
        with w:
            for r in plan:
                w.execute('update chat_sessions set workspace_id=?, cwd=?, execution_target_json=? '
                          'where session_id=?', (ws['workspace_id'], root, et_json, r['session_id']))
    finally:
        w.close()
    out(f'已迁移 {len(plan)} 条 -> {ws["name"]}')
    return 0


# ---------------------------------------------------------------- workspace

def cmd_workspace(args, con, db_path):
    sub = args.ws_cmd

    if sub == 'list':
        rows = load_workspaces(con, include_deleted=args.include_deleted)
        counts = {}
        for r in con.execute('select workspace_id, count(*) from chat_sessions '
                             'where deleted_at is null group by workspace_id'):
            counts[r[0]] = r[1]
        if args.json:
            print(json.dumps([{'id': w['workspace_id'], 'name': w['name'],
                               'source': w['workspace_source'], 'root': primary_root(w),
                               'sessions': counts.get(w['workspace_id'], 0),
                               'deleted': bool(w['deleted_at'] if 'deleted_at' in w.keys() else 0)}
                              for w in rows], ensure_ascii=False, indent=2))
            return 0
        out(f"{'名称':<24} {'会话':>4} {'来源':<10} 根路径")
        out('-' * 90)
        for w in rows:
            src = 'local' if (w['workspace_source'] or '').startswith('local') else 'peer'
            out(f"{w['name'][:24]:<24} {counts.get(w['workspace_id'], 0):>4} {src:<10} {primary_root(w)}")
        return 0

    if sub == 'new':
        name, path = args.name, args.path
        if not name or not path:
            die('workspace new 需要 --name 与 --path')
        exists = [w for w in load_workspaces(con)
                  if (w['name'] or '') == name and (w['workspace_source'] or '').startswith('local')]
        if exists:
            out(f'同名工作区已存在，不再新建：')
            for w in exists:
                src = 'local' if (w['workspace_source'] or '').startswith('local') else 'peer'
                out(f"  {w['workspace_id']}  {w['name']}  [{src}]  {primary_root(w)}")
            out('')
            out('如需把会话归入其中，直接用 move --to <名称或UUID>。')
            return 0
        norm = os.path.normpath(path)
        if os.path.exists(norm):
            out(f'目录已存在: {norm}（直接复用）')
        else:
            out(f'[NOTE] 目录不存在: {norm}')
            out('       技能不会自动创建目录，请先确认是否要建，或改用已有路径。')
            if not args.allow_missing:
                out('       如确认要在不存在路径上建工作区，加 --allow-missing。')
                return 0
        new_id = str(uuid.uuid4())
        now = now_ms()
        if args.json:
            print(json.dumps({'id': new_id, 'name': name, 'path': norm,
                              'dir_exists': os.path.exists(norm), 'applied': bool(args.apply_flag)},
                             ensure_ascii=False, indent=2))
            if not args.apply_flag:
                return 0
        if not args.apply_flag:
            out('')
            out(f'[DRY-RUN] 将新建工作区 {name} -> {norm}（id {new_id}）')
            return 0
        require_closed(args.force)
        bk = make_backup(db_path, 'wsnew')
        out(f'已备份: {os.path.basename(bk)}')
        w = connect(db_path, write=True)
        try:
            with w:
                w.execute('insert into workspaces(workspace_id,name,workspace_source,root_paths_json,'
                          'product_mode,extra_json,created_at,updated_at,archived,deleted_at) '
                          'values(?,?,?,?,?,?,?,?,0,null)',
                          (new_id, name, 'local', json.dumps([norm], ensure_ascii=False),
                           'coding', json.dumps({'workspaceIcon': 'folder',
                                                 'workspaceColor': 'primary',
                                                 'workspaceIndexEnabled': True}, ensure_ascii=False),
                           now, now))
        finally:
            w.close()
        out(f'已创建工作区 {name} -> {norm}')
        return 0

    # 其余子命令都需要定位工作区
    ws, cands = find_workspace(con, args.name or args.id or '', include_deleted=True, local_only=True)
    if not ws:
        if cands:
            die('工作区名不唯一，请用 --id 指定 UUID：\n' +
                '\n'.join(f"  {w['workspace_id']}  {w['name']}  {primary_root(w)}" for w in cands))
        die('未找到工作区')

    if sub == 'rename':
        if not args.new_name:
            die('workspace rename 需要 --new-name')
        if args.json and not args.apply_flag:
            print(json.dumps({'id': ws['workspace_id'], 'old': ws['name'], 'new': args.new_name,
                              'applied': False}, ensure_ascii=False, indent=2))
            return 0
        out(f"重命名: {ws['name']} -> {args.new_name}")
        if not args.apply_flag:
            out('[DRY-RUN] 未写入')
            return 0
        require_closed(args.force)
        bk = make_backup(db_path, 'wsrename')
        out(f'已备份: {os.path.basename(bk)}')
        w = connect(db_path, write=True)
        try:
            with w:
                w.execute('update workspaces set name=?, updated_at=? where workspace_id=?',
                          (args.new_name, now_ms(), ws['workspace_id']))
        finally:
            w.close()
        out('已重命名')
        return 0

    if sub in ('archive', 'unarchive'):
        val = 1 if sub == 'archive' else 0
        if args.json and not args.apply_flag:
            print(json.dumps({'id': ws['workspace_id'], 'archive': val, 'applied': False},
                             ensure_ascii=False, indent=2))
            return 0
        out(f"{'归档' if val else '取消归档'}工作区: {ws['name']}")
        if not args.apply_flag:
            out('[DRY-RUN] 未写入')
            return 0
        require_closed(args.force)
        make_backup(db_path, 'wsarch')
        w = connect(db_path, write=True)
        try:
            with w:
                w.execute('update workspaces set archived=?, updated_at=? where workspace_id=?',
                          (val, now_ms(), ws['workspace_id']))
        finally:
            w.close()
        out('已完成')
        return 0

    if sub == 'retarget':
        if not args.path:
            die('workspace retarget 需要 --path')
        root_old = primary_root(ws)
        root_new = os.path.normpath(args.path)
        n_sess = con.execute('select count(*) from chat_sessions where workspace_id=? and deleted_at is null',
                             (ws['workspace_id'],)).fetchone()[0]
        et_id, _ = infer_et_id(con, ws['workspace_id'], root_new)
        if not args.json:
            out(f"{ws['name']}: {root_old}  ->  {root_new}")
            out(f'将级联更新 {n_sess} 条会话的 cwd 与执行目标')
        if not args.apply_flag:
            if args.json:
                print(json.dumps({'id': ws['workspace_id'], 'from': root_old, 'to': root_new,
                                  'sessions': n_sess, 'applied': False}, ensure_ascii=False, indent=2))
            else:
                out('[DRY-RUN] 未写入')
            return 0
        require_closed(args.force)
        bk = make_backup(db_path, 'wsretarget')
        out(f'已备份: {os.path.basename(bk)}')
        et = {'mode': 'local', 'host': {'id': 'local', 'kind': 'local', 'label': 'Local'},
              'workspace': {'id': et_id, 'path': root_new}}
        w = connect(db_path, write=True)
        try:
            with w:
                w.execute('update workspaces set root_paths_json=?, updated_at=? where workspace_id=?',
                          (json.dumps([root_new], ensure_ascii=False), now_ms(), ws['workspace_id']))
                for r in w.execute('select session_id, extra_json from chat_sessions where workspace_id=?',
                                   (ws['workspace_id'],)).fetchall():
                    e = load_json(r[1])
                    if is_peer_type({'extra_json': json.dumps(e, ensure_ascii=False),
                                     'execution_target_json': ''}):
                        continue
                    w.execute('update chat_sessions set cwd=?, execution_target_json=? where session_id=?',
                              (root_new, json.dumps(et, ensure_ascii=False, separators=(',', ':')),
                               r[0]))
        finally:
            w.close()
        out('已改路径并级联更新')
        return 0

    if sub == 'delete':
        sess = list(con.execute('select session_id, title, deleted_at from chat_sessions where workspace_id=?',
                                (ws['workspace_id'],)))
        alive = [s for s in sess if not s['deleted_at']]
        if not args.json:
            out(f"删除工作区: {ws['name']}  ({primary_root(ws)})")
            out(f'其下会话 {len(sess)} 条，其中未删除 {len(alive)} 条将被一并软删除（进回收站）')
        if not args.yes:
            die('删除类操作需要 --yes 确认（软删除，可在 Qoder 回收站恢复）')
        if not args.apply_flag:
            if args.json:
                print(json.dumps({'id': ws['workspace_id'], 'name': ws['name'],
                                  'sessions': len(sess), 'applied': False}, ensure_ascii=False, indent=2))
            else:
                out('[DRY-RUN] 未写入')
            return 0
        require_closed(args.force)
        bk = make_backup(db_path, 'wsdel')
        out(f'已备份: {os.path.basename(bk)}')
        ts = now_ms()
        w = connect(db_path, write=True)
        try:
            with w:
                w.execute('update chat_sessions set deleted_at=?, archived=1, archived_at=? '
                          'where workspace_id=? and deleted_at is null',
                          (ts, ts, ws['workspace_id']))
                w.execute('update workspaces set deleted_at=?, archived=1, updated_at=? where workspace_id=?',
                          (ts, ts, ws['workspace_id']))
        finally:
            w.close()
        out(f'已软删除工作区及 {len(alive)} 条会话')
        return 0

    die(f'未知的 workspace 子命令: {sub}')


# ---------------------------------------------------------------- backup / rollback

def cmd_backup(args, con, db_path):
    if args.list:
        files = list_backups(db_path)
        if args.json:
            print(json.dumps([{'path': p, 'size': os.path.getsize(p),
                               'mtime': os.path.getmtime(p)} for p in files], ensure_ascii=False, indent=2))
            return 0
        if not files:
            out('尚无备份')
            return 0
        out(f'共 {len(files)} 份备份（保留最近 {BACKUP_KEEP} 份）')
        for p in files:
            out(f"  {fmt_ms(os.path.getmtime(p)*1000)}  {os.path.getsize(p)/1048576:>7.1f} MB  {os.path.basename(p)}")
        return 0
    require_closed(args.force)
    p = make_backup(db_path, 'manual')
    out(f'已备份: {p}')
    return 0


def cmd_rollback(args, con, db_path):
    src = args.backup
    if not src or not os.path.isfile(src):
        die(f'备份文件不存在: {src}')
    if not args.yes:
        die('回滚会覆盖当前数据库，需要 --yes 确认')
    if not args.apply_flag:
        out(f'[DRY-RUN] 将用 {os.path.basename(src)} 覆盖当前库（当前库会先另存一份）')
        return 0
    require_closed(args.force)
    safety = make_backup(db_path, 'pre-rollback')
    out(f'当前库已另存: {os.path.basename(safety)}')
    con.close()
    shutil.copy2(src, db_path)
    for suffix in ('-wal', '-shm'):
        p = db_path + suffix
        if os.path.exists(p):
            try:
                os.remove(p)
            except OSError:
                pass
    out(f'已从 {os.path.basename(src)} 恢复')
    return 0


# ---------------------------------------------------------------- CLI

def build_parser():
    p = argparse.ArgumentParser(
        prog='qoder_sessions.py',
        description='Qoder 会话管理：列表 / 重命名 / 迁移工作区 / 管理工作区 / 备份回滚 / 体检')
    p.add_argument('--db', help='Qoder main.sqlite 路径（默认自动探测）')
    p.add_argument('--json', action='store_true', help='输出结构化 JSON')
    p.add_argument('--force', action='store_true', help='Qoder 运行时仍强制写入（有风险）')
    p.add_argument('--version', action='version', version=f'qoder-conversation-manager {VERSION}')
    sub = p.add_subparsers(dest='cmd', required=True)

    # 允许把 --db/--json/--force 写在子命令后面；SUPPRESS 避免覆盖主解析器的值
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument('--db', default=argparse.SUPPRESS)
    common.add_argument('--json', action='store_true', default=argparse.SUPPRESS)
    common.add_argument('--force', action='store_true', default=argparse.SUPPRESS)

    sub.add_parser('doctor', parents=[common], help='体检：库/表/进程/路径/影子/备份')

    lp = sub.add_parser('list', parents=[common], help='列出会话')
    lp.add_argument('--workspace', help='按工作区名/路径/UUID 过滤')
    lp.add_argument('--cwd', help='按工作目录包含匹配')
    lp.add_argument('--keyword', help='按标题关键词')
    lp.add_argument('--filter', help='表达式，如 "cwd like %%NAS%% and title contains 工具包"')
    lp.add_argument('--since', help='YYYY-MM-DD 之后更新过')
    lp.add_argument('--include-deleted', action='store_true')
    lp.add_argument('--include-peer', action='store_true')
    lp.add_argument('--limit', type=int)

    rp = sub.add_parser('rename', parents=[common], help='重命名（导出/导入两步）')
    rp.add_argument('--export', action='store_true', help='导出完整历史供 agent 起名')
    rp.add_argument('--import', dest='import_file', metavar='FILE',
                    help='把 titles.json 写回（默认 dry-run，加 --apply 才落盘）')
    rp.add_argument('--apply-flag', '--apply', dest='apply_flag', action='store_true',
                    help='真正落盘')
    rp.add_argument('--out', help='导出目录')
    rp.add_argument('--ids', help='逗号分隔的会话 ID 前缀')
    rp.add_argument('--filter', help='筛选表达式')
    rp.add_argument('--limit', type=int)
    rp.add_argument('--user-cap', type=int, default=4000, help='单条用户消息保留字符数')
    rp.add_argument('--assist-cap', type=int, default=1500, help='单条助手消息保留字符数')

    mp = sub.add_parser('move', parents=[common], help='迁移会话到工作区')
    mp.add_argument('--to', required=True, help='目标工作区：名称 / 根路径 / UUID')
    mp.add_argument('--ids', help='逗号分隔的会话 ID 前缀')
    mp.add_argument('--filter', help='筛选表达式')
    mp.add_argument('--apply-flag', '--apply', dest='apply_flag', action='store_true',
                    help='真正落盘')
    mp.add_argument('--skip-in-target', action='store_true', default=True,
                    help='已在目标工作区的会话自动跳过（默认开启）')

    wp = sub.add_parser('workspace', parents=[common], help='工作区管理')
    wsub = wp.add_subparsers(dest='ws_cmd', required=True)
    wl = wsub.add_parser('list', parents=[common])
    wl.add_argument('--include-deleted', action='store_true')
    wn = wsub.add_parser('new', parents=[common])
    wn.add_argument('--name', required=True)
    wn.add_argument('--path', required=True)
    wn.add_argument('--allow-missing', action='store_true', help='目标目录不存在也允许创建')
    wn.add_argument('--apply-flag', '--apply', dest='apply_flag', action='store_true')
    for name in ('rename', 'archive', 'unarchive', 'delete', 'retarget'):
        sp = wsub.add_parser(name, parents=[common])
        sp.add_argument('--id', help='工作区 UUID')
        sp.add_argument('--name', help='工作区名称')
        sp.add_argument('--apply-flag', '--apply', dest='apply_flag', action='store_true')
        if name == 'rename':
            sp.add_argument('--new-name', required=True)
        if name == 'retarget':
            sp.add_argument('--path', required=True)
        if name == 'delete':
            sp.add_argument('--yes', action='store_true')

    bp = sub.add_parser('backup', parents=[common], help='备份')
    bp.add_argument('--list', action='store_true', help='列出备份')

    rb = sub.add_parser('rollback', parents=[common], help='从备份恢复')
    rb.add_argument('--backup', required=True, help='备份文件路径')
    rb.add_argument('--yes', action='store_true')
    rb.add_argument('--apply-flag', '--apply', dest='apply_flag', action='store_true')

    return p


def main(argv=None):
    global CUSTOM_DB
    parser = build_parser()
    args = parser.parse_args(argv)
    default = None
    for cand in qoder_db_candidates():
        if os.path.isfile(cand):
            default = os.path.abspath(cand)
            break
    db_path = resolve_db(args.db)
    CUSTOM_DB = bool(args.db) and os.path.abspath(args.db) != default
    con = connect(db_path, write=False)
    try:
        if args.cmd == 'doctor':
            return cmd_doctor(args, con, db_path)
        if args.cmd == 'list':
            return cmd_list(args, con, db_path)
        if args.cmd == 'rename':
            return cmd_rename(args, con, db_path)
        if args.cmd == 'move':
            return cmd_move(args, con, db_path)
        if args.cmd == 'workspace':
            return cmd_workspace(args, con, db_path)
        if args.cmd == 'backup':
            return cmd_backup(args, con, db_path)
        if args.cmd == 'rollback':
            return cmd_rollback(args, con, db_path)
        parser.print_help()
        return 2
    finally:
        try:
            con.close()
        except Exception:
            pass


if __name__ == '__main__':
    sys.exit(main())
