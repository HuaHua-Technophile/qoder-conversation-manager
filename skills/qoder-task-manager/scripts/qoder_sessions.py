#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Qoder 任务管理：列出 / 重命名 / 迁移工作区 / 管理工作区 / 备份回滚 / 体检。

只依赖 Python 3.9+ 标准库。只操作 Qoder 本地数据（Windows）。
所有写操作默认 dry-run，必须显式 --apply 才落盘；落盘前自动整库备份。
"""
import argparse
import glob
import filecmp
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import unicodedata
import uuid
from datetime import datetime, timedelta

VERSION = '1.7.1'
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


JSON_MODE = False   # --json：人类可读输出全部静音，整条命令只在最后打一份 JSON
WARNINGS = []       # JSON_MODE 下的 [WARN]/[NOTE] 收集到这里，随结果一起输出


def out(msg=''):
    """人类可读输出。JSON_MODE 下静音，保证 stdout 只有一个 JSON 文档。"""
    if JSON_MODE:
        return
    print(msg)


def warn(msg, tag='WARN'):
    """告警。人类可读时直出；JSON_MODE 下只收集，避免污染 stdout。"""
    WARNINGS.append(msg)
    if not JSON_MODE:
        print(f'[{tag}] {msg}')


def emit_json(payload):
    """JSON 模式的唯一出口：整份结果只打一次。

    字典结果自行带 warnings 字段；数组结果（如 list）把告警打到 stderr，
    以保持「数组」这个形状不变。
    """
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if not isinstance(payload, dict):
        for w in WARNINGS:
            print(f'[WARN] {w}', file=sys.stderr)


def die(msg, code=2):
    """致命错误。JSON_MODE 下 stdout 也给一份合法 JSON，自动化不会拿到半截输出。"""
    print(f'[ERROR] {msg}', file=sys.stderr)
    if JSON_MODE:
        print(json.dumps({'error': msg, 'exit': code}, ensure_ascii=False))
    sys.exit(code)


def connect(db_path, write=False):
    if write:
        con = sqlite3.connect(db_path, timeout=8)
    else:
        con = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True, timeout=8)
    con.row_factory = sqlite3.Row
    return con


def is_custom_db(db_arg, default_path):
    """--db 是否指向非默认库（副本）。

    `CUSTOM_DB` 在 v1.7.0 起是安全闸门（整库覆盖硬拦 / gate_running / post_write_hint
    三处都看它），所以不能简单比字符串：
    - 先 `realpath` 解开 junction / 符号链接 / `\\\\?\\` 前缀，否则 `--db` 走 junction
      指向同一个库也能绕过硬拦；
    - 再 `normcase` 抹平大小写与分隔符（Windows 路径大小写不敏感）。
    不存在的路径 realpath 原样返回，不影响「副本」判定。
    """
    if not db_arg or not default_path:
        return bool(db_arg) and not default_path
    return (os.path.normcase(os.path.realpath(db_arg))
            != os.path.normcase(os.path.realpath(default_path)))


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


CUSTOM_DB = False   # --db 指向非默认库（副本）时为 True


def gate_running(require_closed_flag=False):
    """写前闸门。

    默认允许热写：Qoder 运行时不阻断，写完提示重启让侧栏按数据库重建。
    传 --require-closed 时恢复硬性拦截（退出码 3）。
    """
    if CUSTOM_DB:
        return
    n = qoder_running()
    if not n:
        return
    if require_closed_flag:
        die(f'检测到 {n} 个 Qoder 进程在运行，且指定了 --require-closed。'
            f'请完全退出 Qoder 后重试。', 3)
    warn(f'Qoder 正在运行（{n} 个进程）。按热写继续；完成后请重启 Qoder 验证。')


def post_write_hint(what='写入'):
    if CUSTOM_DB:
        return
    out('')
    out(f'提示：{what}已落盘。请重启 Qoder 让侧栏按数据库重建，'
        f'然后核对标题/归属是否保持；若回退，用 rollback 恢复。')


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


def is_peer_type(row, d=None):
    """影子任务判断。可传 (row, dict)，也可只传一个含字段的 dict。"""
    if d is None:
        d = row if isinstance(row, dict) else {}
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


def message_last(con):
    """每个任务最后一条消息的时间（ms），用于增量判断「最近有没有新对话」。"""
    try:
        return {r[0]: int(r[1] or 0) for r in con.execute(
            'select session_id, max(created_at) from chat_session_messages group by session_id')}
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
    """解析形如 `cwd like %NAS% and title contains 工具包` 的安全子集。

    只支持 `and` 连接 + contains/like/startswith/endswith/=/!=。
    其它语法（or / 括号 / not / 比较运算）一律显式报错——
    静默当字面值处理会让用户以为「真的没有匹配的任务」。
    """
    if not expr:
        return []
    bad = []
    if re.search(r'\s+or\s+', expr, flags=re.I):
        bad.append('or')
    if '(' in expr or ')' in expr:
        bad.append('括号')
    if re.search(r'\bnot\b', expr, flags=re.I):
        bad.append('not')
    if re.search(r'[<>]=?', expr):
        bad.append('比较运算')
    if bad:
        raise FilterError(
            f'不支持的语法: {"、".join(bad)}。'
            f'只支持 and 连接与 contains/like/startswith/endswith/=/!=，'
            f'不支持 or、括号、not 与比较运算（不是 SQL）。')
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

BACKUP_ROOT = None   # 由 --backup-dir / 环境变量 / 工作目录 决定


def work_root():
    """备份与临时产物的根目录：默认放在当前工作目录下。"""
    if BACKUP_ROOT:
        return BACKUP_ROOT
    env = os.environ.get('QODER_CM_BACKUP_DIR')
    if env:
        return os.path.abspath(env)
    return os.path.join(os.getcwd(), 'qoder-cm-backups')


def ensure_root():
    root = work_root()
    os.makedirs(root, exist_ok=True)
    gi = os.path.join(root, '.gitignore')
    if not os.path.exists(gi):
        try:
            with open(gi, 'w', encoding='utf-8') as f:
                f.write('*' + chr(10))
        except OSError:
            pass
    return root


def db_backup_dir():
    return os.path.join(work_root(), 'db')


def list_backups(db_path):
    items = []
    d = db_backup_dir()
    if os.path.isdir(d):
        for p in glob.glob(os.path.join(d, '*')):
            if p.endswith('-wal') or p.endswith('-shm'):
                continue
            items.append(p)
    items.sort(key=os.path.getmtime, reverse=True)
    return items


def make_backup(db_path, tag='manual'):
    ensure_root()
    d = db_backup_dir()
    os.makedirs(d, exist_ok=True)
    ts = time.strftime('%Y%m%d-%H%M%S')
    dst = os.path.join(d, f'main.sqlite.bak-{tag}-{ts}')
    n = 1
    while os.path.exists(dst):
        dst = os.path.join(d, f'main.sqlite.bak-{tag}-{ts}-{n}')
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


# ------------------------------------------------ 按对象备份（manifest 可单条回滚）

def backup_sets(db_path):
    root = work_root()
    if not os.path.isdir(root):
        return []
    out = []
    for d in os.listdir(root):
        p = os.path.join(root, d)
        if not os.path.isdir(p) or d == 'db':
            continue
        if os.path.isdir(os.path.join(p, 'items')) or os.path.isfile(os.path.join(p, 'batch.json')):
            out.append(p)
    out.sort(key=os.path.getmtime, reverse=True)
    return out


def new_backup_set(db_path, tag):
    root = ensure_root()
    base = os.path.join(root, f'{tag}-{time.strftime("%Y%m%d-%H%M%S")}')
    n = 1
    while os.path.exists(base):
        base = os.path.join(root, f'{tag}-{time.strftime("%Y%m%d-%H%M%S")}-{n}')
        n += 1
    os.makedirs(os.path.join(base, 'items'), exist_ok=True)
    return base


def backup_row(con, table, key_col, key_value, base):
    """把一行完整存成 JSON；返回 manifest 路径。"""
    try:
        row = con.execute(f'select * from {table} where {key_col}=?', (key_value,)).fetchone()
    except sqlite3.Error:
        return None
    if not row:
        return None
    payload = {
        'version': 1,
        'table': table,
        'key_column': key_col,
        'key_value': key_value,
        'saved_at': int(time.time() * 1000),
        'row': {k: row[k] for k in row.keys()},
    }
    path = os.path.join(base, 'items', f'{table}-{key_value}.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return path


def write_batch_manifest(base, items, note='', extra=None):
    payload = {
        'version': 1,
        'created_at': datetime.now().isoformat(timespec='seconds'),
        'note': note,
        'items': items,
    }
    if extra:
        payload.update(extra)
    path = os.path.join(base, 'batch.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return path


# 回滚清单只允许这两张表，且主键列必须与表匹配。
# restore_row() 要把表名/主键名拼进 SQL（标识符无法用占位符），
# 不校验就等于让清单文件直接执行任意 SQL。
KEY_COLUMNS = {'chat_sessions': 'session_id', 'workspaces': 'workspace_id'}


def restore_row(w, payload):
    """按 manifest 里的一行恢复；只写回存在的列。

    `op == "insert"` 表示这行是本次操作**新建**的（如 move --create 建的工作区），
    回滚时反向删除，否则会残留成孤儿行。
    表名与主键列先过白名单：清单是外部文件，不能信。
    """
    table = payload.get('table')
    key_col = payload.get('key_column')
    expected = KEY_COLUMNS.get(table)
    if not expected or key_col != expected:
        die(f'备份清单不合法：table={table!r} key_column={key_col!r}', 2)
    if payload.get('op') == 'insert':
        try:
            cur = w.execute(f'delete from {table} where {key_col}=?', (payload['key_value'],))
        except sqlite3.Error:
            return 0
        return cur.rowcount
    row = payload['row']
    have = set(table_columns(w, table))
    cols = [c for c in row if c != key_col and c in have]
    if not cols:
        return 0
    sql = f'update {table} set ' + ', '.join(f'{c}=?' for c in cols) + f' where {key_col}=?'
    cur = w.execute(sql, [row[c] for c in cols] + [payload['key_value']])
    return cur.rowcount


# ---------------------------------------------------------------- doctor

CHECK_NAMES = ['数据库', 'WAL 状态', '表结构', 'Qoder 进程', '工作区路径', '影子任务', '备份']


def cmd_doctor(args, con, db_path):
    results = []

    def add(name, ok, detail):
        results.append({'check': name, 'ok': ok, 'detail': detail})

    # 1 数据库
    try:
        n_sess = con.execute('select count(*) from chat_sessions').fetchone()[0]
        add('数据库', True, f'可读，任务 {n_sess} 条')
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

    # 4 进程（热写允许，仅作提示，不计为异常）
    n = qoder_running()
    add('Qoder 进程', True,
        '未运行' if n == 0 else f'{n} 个进程（允许热写；写完请重启 Qoder 验证）')

    # 5 工作区路径
    ws = load_workspaces(con)
    local = [w for w in ws if (w['workspace_source'] or '').startswith('local')]
    bad = [w['name'] for w in local if primary_root(w) and not os.path.exists(primary_root(w))]
    add('工作区路径', not bad,
        f'本地工作区 {len(local)} 个，路径均可达' if not bad else f'不可达: {", ".join(bad[:4])}')

    # 6 影子任务
    try:
        rows = list(con.execute('select session_id, extra_json, execution_target_json from chat_sessions'))
        peers = sum(1 for r in rows if is_peer_type(r, {'extra_json': r['extra_json'],
                                                        'execution_target_json': r['execution_target_json']}))
        ratio = (peers / len(rows) * 100) if rows else 0
        add('影子任务', True, f'{peers}/{len(rows)} 条（{ratio:.0f}%），迁移与改名会自动跳过')
    except sqlite3.Error as ex:
        add('影子任务', False, str(ex))

    # 7 备份（超过 14 天，或库里有数据却从未备份，都要标 !!）
    bks = list_backups(db_path)
    try:
        has_data = con.execute('select count(*) from chat_sessions').fetchone()[0] > 0
    except sqlite3.Error:
        has_data = False
    if bks:
        age_h = (time.time() - os.path.getmtime(bks[0])) / 3600
        stale = age_h > 14 * 24
        add('备份', not stale,
            f'{work_root()}｜{len(bks)} 份，最近 {os.path.basename(bks[0])}（{age_h:.1f} 小时前）'
            + ('；已超 14 天，建议跑一次 backup' if stale else ''))
    elif has_data:
        add('备份', True, f'{work_root()}｜尚无备份，首次写入会自动创建；建议先跑一次 backup')
    else:
        add('备份', True, f'{work_root()}｜尚无备份，首次写入会自动创建')

    if getattr(args, 'deep', False):
        try:
            drows = session_rows(con, include_deleted=False, include_peer=False)
            missing = mismatch = 0
            for r in drows:
                cur = find_project_dir(r['session_id'])
                if not cur:
                    missing += 1
                    continue
                want_dir = os.path.join(projects_root(), encode_cwd(r['cwd']))
                if os.path.normcase(cur) != os.path.normcase(want_dir):
                    mismatch += 1
            add('任务文件', missing == 0,
                f'{len(drows)} 条任务均有正文文件' if missing == 0
                else f'{missing}/{len(drows)} 条缺正文文件')
            add('目录一致性', mismatch == 0,
                '项目目录与 cwd 全部一致' if mismatch == 0
                else f'{mismatch} 条目录与 cwd 不一致，可用 repair 修复')
            mem_dirs = []
            proot = projects_root()
            if os.path.isdir(proot):
                for name in os.listdir(proot):
                    mp = os.path.join(proot, name, 'memory')
                    if os.path.isdir(mp):
                        n_mem = len([f for f in os.listdir(mp) if os.path.isfile(os.path.join(mp, f))])
                        if n_mem:
                            mem_dirs.append((name, n_mem))
            add('项目记忆', True,
                f'{len(mem_dirs)} 个项目共 {sum(n for _, n in mem_dirs)} 个记忆文件'
                if mem_dirs else '尚无项目记忆')
            n_out = con.execute('select count(distinct session_id) from turn_file_change_sets').fetchone()[0]
            add('产出索引', True, f'{n_out} 条任务有产出记录')
            orphans = []
            if os.path.isdir(proot):
                for name in sorted(os.listdir(proot)):
                    d = os.path.join(proot, name)
                    if os.path.isdir(d) and project_sessions(d) == 0:
                        orphans.append(name)
            add('孤立项目目录', not orphans,
                '无空项目目录' if not orphans
                else f'{len(orphans)} 个空项目目录（无 jsonl，可手工删除）：'
                     + ', '.join(orphans[:3]) + ('…' if len(orphans) > 3 else ''))
        except Exception as ex:
            add('深度检查', False, str(ex))

    if args.json:
        emit_json({'db': db_path, 'version': VERSION, 'checks': results})
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

    def scope(rows):
        """六道筛子（不含 `--limit`），显示路与影子计数路共用同一份逻辑。

        顺序不能改：`_ws_name` 在 workspace 段之后赋值，`--filter` 里的
        `workspace contains …` 依赖这个隐式前提。
        """
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
        return rows

    rows = scope(session_rows(con, include_deleted=args.include_deleted,
                              include_peer=args.include_peer))

    # 影子任务默认隐藏，但必须告诉用户「同一筛选范围内有多少条没显示」。
    # 口径 = 若再加 --include-peer 会多出来的行数；必须在 --limit 之前算，
    # 且不能用「全库总数 − 当前结果数」（那会把被关键词/limit 筛掉的本地任务也算成影子）。
    peer_hidden = 0
    if not args.include_peer:
        peer_hidden = sum(1 for r in scope(session_rows(con, include_deleted=args.include_deleted,
                                                       include_peer=True)) if r['_peer'])
    hint = f'另有 {peer_hidden} 条影子任务未显示，加 --include-peer 查看' if peer_hidden else ''

    if args.limit:
        rows = rows[:args.limit]

    if args.json:
        payload = [{'sid': r['session_id'], 'title': r['title'], 'cwd': r['cwd'],
                    'workspace': r['_ws_name'], 'workspace_id': r['workspace_id'],
                    'archived': bool(r['archived']), 'deleted': bool(r['deleted_at']),
                    'peer': r['_peer'], 'updated_at': r['updated_at'],
                    'messages': stats.get(r['session_id'], (0, 0))[0]}
                   for r in rows]
        emit_json(payload)
        if hint:
            print(f'[NOTE] {hint}', file=sys.stderr)
        return 0

    if not rows:
        out('没有匹配的任务')
        if hint:
            out(f'（{hint}）')
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
    if hint:
        out('')
        out(f'（{hint}）')
    return 0


# ---------------------------------------------------------------- rename

FORBIDDEN = set('"“”\'‘’《》<>。？?！!\n\r\t/\\|')


def validate_title(t, min_len=12, max_len=30, require_prefix=False):
    """标题校验。默认 12–30 字符（含 `[分类] ` 前缀与空格）。

    文档规则是「正文 8–22 个汉字 + `[分类] ` 前缀」，合计约 12–30 字符，
    默认值必须与文档对齐，否则自带示例都会被拒。
    """
    t = (t or '').strip()
    errs = []
    if not t:
        errs.append('空标题')
    if any(c in FORBIDDEN for c in t):
        errs.append('含非法字符（引号/书名号/句号/问号/换行/路径分隔符）')
    if any(ord(c) < 32 for c in t):
        errs.append('含控制字符')
    if len(t) > max_len:
        errs.append(f'过长（{len(t)} > {max_len} 字符）')
    if len(t) < min_len:
        errs.append(f'过短（{len(t)} < {min_len} 字符）')
    if require_prefix and not re.match(r'^\[[^\[\]\r\n]{1,8}\]\s+\S', t):
        errs.append('缺少 [短分类] 前缀')
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


def write_shards(outdir, index, n):
    """LPT（最长处理时间优先）按字数把任务均衡分到 n 片，供子智能体并行。"""
    items = sorted(index, key=lambda x: -int(x.get('chars') or 0))
    bins = [[] for _ in range(n)]
    tot = [0] * n
    for it in items:
        j = min(range(n), key=lambda k: tot[k])
        bins[j].append(it)
        tot[j] += int(it.get('chars') or 0)

    sdir = os.path.join(outdir, 'shards')
    os.makedirs(sdir, exist_ok=True)
    info = []
    for i, bucket in enumerate(bins, 1):
        if not bucket:
            continue
        name = f'group{i}'
        payload = {
            'group': name,
            'count': len(bucket),
            'chars': tot[i - 1],
            'items': [{'sid': x['sid'], 'short': x['short'], 'title': x['title'],
                       'chars': x.get('chars'), 'file': x.get('file')} for x in bucket],
        }
        path = os.path.join(sdir, name + '.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        info.append({'group': name, 'count': len(bucket), 'chars': tot[i - 1], 'path': path})
    return info


def parse_since(expr):
    """today / yesterday / YYYY-MM-DD → 当天本地零点（ms）。"""
    e = (expr or 'today').strip().lower()
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    if e in ('today', '今日'):
        d = today
    elif e in ('yesterday', '昨日'):
        d = today - timedelta(days=1)
    else:
        try:
            d = datetime.strptime((expr or '').strip(), '%Y-%m-%d')
        except ValueError:
            die('--pending-since 需要 today / yesterday / YYYY-MM-DD')
    return int(d.timestamp() * 1000)


def pending_rows(con, rows, since_ms, respect_manual=False):
    """增量候选：上次判断之后又产生过新对话的 + 标题未定稿的。

    判定基准是「上次判断时间」而不是「今天零点」——
    只要该任务在上一轮判断之后又被对话过，就重新判断一次，
    哪怕它早就被改过名。基准取 extra_json.qoderCm.renamedAt；
    老版本改过、没有留痕的任务退回 --pending-since。

    只有 --respect-manual 时，才跳过「标题被手工改过」的任务
    （titleSource 仍为 custom 且与记录不一致，说明不是 Qoder 自动重生成的）。
    """
    last = message_last(con)
    stats = message_stats(con)
    picked, skip = [], {'已定稿且无新对话': 0, '空任务': 0, '人工标题': 0}
    for r in rows:
        e = load_json(r['extra_json'])
        cm = e.get('qoderCm') or {}
        src = e.get('titleSource') or ''
        cur = (r['title'] or '').strip()
        last_ms = last.get(r['session_id']) or (r['updated_at'] or 0)
        base = int(cm.get('renamedAt') or 0) or since_ms

        if respect_manual and cm.get('title') and src == 'custom' and cm['title'] != cur:
            skip['人工标题'] += 1
            continue
        if stats.get(r['session_id'], (0, 0))[1] == 0:
            skip['空任务'] += 1
            continue
        if src != 'custom':
            picked.append((r, '标题未定稿', last_ms))
        elif last_ms > base:
            why = '上次判断后又有新对话' if cm.get('renamedAt') else '近期有新对话（无改名留痕）'
            picked.append((r, why, last_ms))
        else:
            skip['已定稿且无新对话'] += 1
    return picked, skip


def cmd_rename(args, con, db_path):
    if args.export:
        return rename_export(args, con, db_path)
    if args.import_file:
        return rename_apply(args, con, db_path)
    die('请指定 rename --export 或 rename --import <titles.json>')


def rename_export(args, con, db_path):
    ws_map = {w['workspace_id']: w for w in load_workspaces(con, include_deleted=True)}
    stats = message_stats(con)
    lasts = message_last(con)
    rows = session_rows(con, include_deleted=False, include_peer=False)

    if args.ids:
        want = {s.strip() for s in args.ids.split(',') if s.strip()}
        missing = [w for w in want if not any(r['session_id'].startswith(w) for r in rows)]
        if missing:
            warn(f"这些 ID 未匹配到任务：{', '.join(missing)}")
        rows = [r for r in rows if any(r['session_id'].startswith(w) for w in want)]
    for r in rows:
        w = ws_map.get(r['workspace_id'])
        r['_ws_name'] = w['name'] if w else ''
    if args.filter:
        try:
            rows = apply_filter(rows, parse_filter(args.filter))
        except FilterError as ex:
            die(str(ex))

    reasons, skip = {}, {}
    since_ms = 0
    if getattr(args, 'pending', False):
        since_ms = parse_since(getattr(args, 'pending_since', None))
        picked, skip = pending_rows(con, rows, since_ms,
                                    respect_manual=getattr(args, 'respect_manual', False))
        reasons = {r['session_id']: why for r, why, _ in picked}
        rows = [r for r, _, _ in picked]

    if args.limit:
        rows = rows[:args.limit]

    if not rows:
        if args.json:
            emit_json({'out_dir': None, 'count': 0, 'items': [], 'shards': [],
                       'skipped': skip, 'warnings': list(WARNINGS)})
            return 0
        out('没有匹配的任务')
        if skip and any(skip.values()):
            out('增量筛选：' + '，'.join(f'{k} {v} 条' for k, v in skip.items() if v))
        return 0

    outdir = args.out or os.path.join(os.getcwd(), 'qoder-extract')
    os.makedirs(outdir, exist_ok=True)
    index = []
    for r in rows:
        e = load_json(r['extra_json'])
        msgs, users = stats.get(r['session_id'], (0, 0))
        last_ms = lasts.get(r['session_id']) or 0
        body = [
            f"SESSION_ID: {r['session_id']}",
            f"CURRENT_TITLE: {(r['title'] or '').strip()}",
            f"TITLE_SOURCE: {e.get('titleSource', '')}",
            f"PICK_REASON: {reasons.get(r['session_id'], '-')}",
            f"WORKSPACE: {r['_ws_name'] or '(无工作区)'}",
            f"CWD: {r['cwd']}",
            f"CREATED_AT: {fmt_ms(r['created_at'])}",
            f"UPDATED_AT: {fmt_ms(r['updated_at'])}",
            f"LAST_MESSAGE_AT: {fmt_ms(last_ms)}",
            f"MSG_COUNT: {msgs}",
            f"USER_TURNS: {users}",
            '===== 完整任务历史（时间顺序）=====',
            render_transcript(con, r['session_id'], args.user_cap, args.assist_cap),
        ]
        path = os.path.join(outdir, r['session_id'][:8] + '.txt')
        text = '\n'.join(body)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(text)
        index.append({'sid': r['session_id'], 'short': r['session_id'][:8],
                      'title': (r['title'] or '').strip(), 'title_source': e.get('titleSource'),
                      'reason': reasons.get(r['session_id']), 'workspace': r['_ws_name'],
                      'last_message_at': last_ms,
                      'messages': msgs, 'user_turns': users,
                      'bytes': os.path.getsize(path), 'chars': len(text),
                      'file': os.path.basename(path)})

    with open(os.path.join(outdir, 'index.json'), 'w', encoding='utf-8') as f:
        json.dump(index, f, ensure_ascii=False, indent=2)

    shard_info = []
    if getattr(args, 'shards', 0) and len(index) > 1:
        shard_info = write_shards(outdir, index, max(1, args.shards))

    if args.json:
        emit_json({'out_dir': outdir, 'count': len(index), 'items': index,
                   'shards': shard_info, 'skipped': skip,
                   'warnings': list(WARNINGS)})
        return 0
    out(f'已导出 {len(index)} 个任务的完整历史 -> {outdir}')
    out(f'索引文件: {os.path.join(outdir, "index.json")}')
    if reasons:
        out('')
        out('增量筛选命中：')
        for it in index:
            out(f"  {it['short']}  {it['reason']}  {it['title'][:34]}")
    if skip and any(skip.values()):
        out('')
        out('增量筛选跳过：' + '，'.join(f'{k} {v} 条' for k, v in skip.items() if v))
    if shard_info:
        out('')
        out(f'已按字数均衡切成 {len(shard_info)} 片（LPT）：')
        for s in shard_info:
            out(f"  {s['group']:<18} {s['count']:>3} 条  {s['chars']:>9,} 字  {s['path']}")
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
    by_full = {r['session_id']: r for r in all_rows}

    plan, touched, skipped = [], [], []
    for it in data:
        sid = str(it.get('sid') or '').strip()
        if not sid:
            skipped.append(('-', '缺少 sid', ''))
            continue
        if len(sid) >= 36:
            # 完整 ID 直查 by_full：按前 8 位反查会在前缀撞车时改错任务
            row = by_full.get(sid)
            if not row:
                skipped.append((sid[:8], '库中不存在', ''))
                continue
        else:
            cand = [r for r in all_rows if r['session_id'].startswith(sid)]
            if not cand:
                skipped.append((sid[:8], '库中不存在', ''))
                continue
            if len(cand) > 1:
                skipped.append((sid[:8], f'ID 前缀不唯一（{len(cand)} 条命中），请给完整 ID', ''))
                continue
            row = cand[0]
        if row['_peer']:
            skipped.append((sid[:8], '影子任务（正文在另一台设备），已拒绝', ''))
            continue
        if row['deleted_at']:
            skipped.append((sid[:8], '任务已删除，已跳过', ''))
            continue
        raw_title = it.get('new_title')
        cat = str(it.get('category') or '').strip()
        composed = (raw_title or '').strip()
        if cat and not re.match(r'^\[[^\[\]]{1,8}\]', composed):
            composed = f'[{cat}] {composed}'
        title, errs = validate_title(
            composed,
            min_len=getattr(args, 'min_title_len', 12),
            max_len=getattr(args, 'max_title_len', 30),
            require_prefix=getattr(args, 'require_prefix', False),
        )
        if errs:
            skipped.append((sid[:8], '；'.join(errs), title))
            continue
        cur_title = (row['title'] or '').strip()
        meta_row = load_json(row['extra_json']) or {}
        cm = meta_row.get('qoderCm') or {}
        if getattr(args, 'respect_manual', False) and cm.get('title') \
                and (meta_row.get('titleSource') or '') == 'custom' and cm['title'] != cur_title:
            skipped.append((sid[:8], '标题已被手工修改（--respect-manual 生效），已跳过', title))
            continue
        if title == cur_title:
            # 标题没变但这条任务刚被重新判断过：刷新「上次判断时间」并认领，
            # 否则下一轮还会因为「比 renamedAt 新」被反复导出。
            touched.append((row['session_id'], cur_title))
            skipped.append((sid[:8], '与现标题相同（仅刷新判断时间）', title))
            continue
        plan.append((row['session_id'], row['title'], title))

    # 允许不同任务重名，不做去重告警

    plan_json = [{'sid': s, 'old': o, 'new': n} for s, o, n in plan]
    touched_json = [{'sid': s, 'title': t} for s, t in touched]
    skipped_json = [{'sid': s, 'reason': r} for s, r, _ in skipped]

    if not args.json:
        out(f'待写入 {len(plan)} 条，标题不变仅刷新判断时间 {len(touched)} 条，跳过 {len(skipped)} 条')
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
        if args.json:
            emit_json({'applied': False, 'plan': plan_json, 'touched': touched_json,
                       'skipped': skipped_json, 'results': [], 'backup': None,
                       'warnings': list(WARNINGS)})
            return 0
        out('')
        out('[DRY-RUN] 未写入。确认后加 --apply 落盘。')
        return 0

    gate_running(getattr(args, 'require_closed', False))

    base = new_backup_set(db_path, 'rename')
    manifests = {}
    for sid, _, _ in plan:
        mp = backup_row(con, 'chat_sessions', 'session_id', sid, base)
        if mp:
            manifests[sid] = os.path.basename(mp)
    for sid, _t in touched:
        mp = backup_row(con, 'chat_sessions', 'session_id', sid, base)
        if mp:
            manifests.setdefault(sid, os.path.basename(mp))

    w = connect(db_path, write=True)
    results = []
    ts = now_ms()
    try:
        for sid, old, new in plan:
            try:
                with w:   # 每条独立事务
                    row = w.execute('select extra_json from chat_sessions where session_id=?', (sid,)).fetchone()
                    e = load_json(row['extra_json'] if row else '{}')
                    e['titleResolved'] = True
                    e['titleSource'] = 'custom'
                    e['titleRevision'] = int(e.get('titleRevision') or 0) + 1
                    # 留痕：记录本技能写入的标题与时间，供增量识别「已定稿 / 人工改过」
                    e['qoderCm'] = {'title': new, 'renamedAt': ts, 'by': f'qoder-task-manager {VERSION}'}
                    w.execute('update chat_sessions set title=?, extra_json=? where session_id=?',
                              (new, json.dumps(e, ensure_ascii=False, separators=(',', ':')), sid))
                chk = w.execute('select title, extra_json from chat_sessions where session_id=?',
                                (sid,)).fetchone()
                meta = load_json(chk['extra_json']) if chk else {}
                ok = bool(chk) and chk['title'] == new and \
                    meta.get('titleSource') == 'custom' and meta.get('titleResolved') is True
                results.append({'session_id': sid, 'old_title': old, 'title': new,
                                'status': 'ok' if ok else 'verify_failed',
                                'manifest': manifests.get(sid)})
                out(f"[{'OK' if ok else 'WARN'}] {sid[:8]}  {new}")
            except Exception as ex:
                results.append({'session_id': sid, 'old_title': old, 'title': new,
                                'status': 'failed', 'error': str(ex),
                                'manifest': manifests.get(sid)})
                out(f'[FAIL] {sid[:8]}  {ex}')
        # 标题未变、但已重新判断过的任务：只刷新判断时间并认领标题来源
        for sid, t in touched:
            try:
                with w:
                    row = w.execute('select extra_json from chat_sessions where session_id=?', (sid,)).fetchone()
                    e = load_json(row['extra_json'] if row else '{}')
                    e['titleResolved'] = True
                    e['titleSource'] = 'custom'
                    e['qoderCm'] = {'title': t, 'renamedAt': ts, 'by': f'qoder-task-manager {VERSION}'}
                    w.execute('update chat_sessions set extra_json=? where session_id=?',
                              (json.dumps(e, ensure_ascii=False, separators=(',', ':')), sid))
                results.append({'session_id': sid, 'title': t, 'status': 'unchanged',
                                'manifest': manifests.get(sid)})
                out(f'[SAME] {sid[:8]}  {t}')
            except Exception as ex:
                results.append({'session_id': sid, 'title': t, 'status': 'failed', 'error': str(ex),
                                'manifest': manifests.get(sid)})
                out(f'[FAIL] {sid[:8]}  {ex}')
    finally:
        w.close()

    batch = write_batch_manifest(base, results, note='rename')
    ok_n = sum(1 for x in results if x['status'] == 'ok')
    same_n = sum(1 for x in results if x['status'] == 'unchanged')
    bad_n = len(results) - ok_n - same_n
    out('')
    out(f'完成：改名 {ok_n}，标题不变 {same_n}，失败/异常 {bad_n}，共 {len(results)} 条')
    out(f'备份与清单: {base}')
    out(f'单条回滚: rollback --manifest "{os.path.join(base, "items", "chat_sessions-<sid>.json")}"')
    out(f'整批回滚: rollback --batch "{batch}"')
    post_write_hint('标题')
    if args.json:
        emit_json({'applied': True, 'plan': plan_json, 'touched': touched_json,
                   'skipped': skipped_json, 'results': results, 'backup': base,
                   'warnings': list(WARNINGS)})
    return 0 if bad_n == 0 else 1


# ---------------------------------------------------------------- move

def infer_et_id(con, target_ws_id, target_root):
    """优先复用目标工作区已有任务的 execution_target_json.workspace.id。"""
    ids = {}
    for r in con.execute('select execution_target_json from chat_sessions where workspace_id=?', (target_ws_id,)):
        et = load_json(r[0])
        wid = (et.get('workspace') or {}).get('id')
        if wid:
            ids[wid] = ids.get(wid, 0) + 1
    if ids:
        return max(ids.items(), key=lambda x: x[1])[0], True
    return target_ws_id, False


# ------------------------------------------------ Qoder 项目目录与文件迁移

QODER_HOME_OVERRIDE = None


def qoder_home():
    if QODER_HOME_OVERRIDE:
        return QODER_HOME_OVERRIDE
    return os.path.join(os.path.expanduser('~'), '.qoder')


def projects_root():
    return os.path.join(qoder_home(), 'projects')


def encode_cwd(cwd):
    """Qoder 的 project 目录名：cwd 里的非字母数字一律换成 -。"""
    return re.sub(r'[^A-Za-z0-9._-]', '-', cwd or '')


def find_project_dirs(sid):
    """返回所有含该任务正文的项目目录（按名字排序，顺序稳定）。"""
    root = projects_root()
    if not os.path.isdir(root) or not sid:
        return []
    hits = []
    for name in sorted(os.listdir(root)):
        d = os.path.join(root, name)
        if os.path.isfile(os.path.join(d, f'{sid}.jsonl')) or os.path.isdir(os.path.join(d, sid)):
            hits.append(d)
    return hits


def find_project_dir(sid):
    """命中多个副本时取排序后的第一个（原来取 listdir 里碰巧第一个，顺序不定）。"""
    hits = find_project_dirs(sid)
    if not hits:
        return None
    if len(hits) > 1:
        warn(f'{sid[:8]} 有 {len(hits)} 份正文副本，取 {os.path.basename(hits[0])}', 'NOTE')
    return hits[0]


def project_sessions(proj_dir):
    if not proj_dir or not os.path.isdir(proj_dir):
        return 0
    return len([f for f in os.listdir(proj_dir) if f.endswith('.jsonl')])


def clean_orphan_dirs(candidates, keep=()):
    """删除已经没有任何任务的项目目录；keep 里的目标目录永不删。"""
    removed = []
    seen = set()
    keep_norm = {os.path.normcase(k) for k in keep if k}
    for d in candidates:
        if not d or not os.path.isdir(d):
            continue
        key = os.path.normcase(d)
        if key in seen or key in keep_norm:
            continue
        seen.add(key)
        if project_sessions(d) > 0:
            continue
        try:
            shutil.rmtree(d)
            removed.append(d)
        except Exception:
            pass
    return removed


def unique_path(p):
    if not os.path.exists(p):
        return p
    stem, ext = os.path.splitext(p)
    return f'{stem}-{time.strftime("%Y%m%d-%H%M%S")}{ext}'


def backup_path(src, base, sid, bucket, rel=None):
    """把 src 备份到 `files/<sid8>/<bucket>/`，文件优先保留相对路径。

    只按 basename 落盘时，`out/x/log.txt` 与 `out/y/log.txt` 会撞成同一个
    `output/log.txt`，后者覆盖前者——原始内容就丢了。所以文件按 rel 建中间
    目录；拿不到合法 rel 时退回 `basename-<绝对路径 sha1 前 8 位>`。
    目录（sidecar / memory）仍按 basename 整棵复制。
    """
    dst_dir = os.path.join(base, 'files', sid[:8], bucket)
    src_clean = (src or '').rstrip('\\/')
    if os.path.isdir(src):
        dst = os.path.join(dst_dir, os.path.basename(src_clean))
        os.makedirs(dst_dir, exist_ok=True)
        shutil.copytree(src, dst, dirs_exist_ok=True)
        return dst

    parts = []
    rel = (rel or '').strip()
    # 绝对路径与盘相对路径（D:x.txt）都不能进备份目录——join 会把它们变成本身
    if rel and not os.path.isabs(rel) and not os.path.splitdrive(rel)[0]:
        parts = [p for p in re.split(r'[\\/]+', rel) if p not in ('', '.', '..')]
    if not parts:
        digest = hashlib.sha1(os.path.abspath(src_clean).encode('utf-8', 'ignore')).hexdigest()[:8]
        stem, ext = os.path.splitext(os.path.basename(src_clean))
        parts = [f'{stem}-{digest}{ext}']
    dst = os.path.join(dst_dir, *parts)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)
    return dst


def move_entry(src, dst, base, sid, bucket, kind, rel=None):
    """搬一个文件或目录，返回记录（含备份路径）。"""
    rec = {'kind': kind, 'src': src, 'dst': dst, 'status': 'pending'}
    if not os.path.exists(src):
        rec['status'] = 'missing'
        return rec
    try:
        rec['backup'] = backup_path(src, base, sid, bucket, rel)
    except Exception as ex:
        rec['backup_error'] = str(ex)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    dst2 = unique_path(dst)
    rec['dst'] = dst2
    if os.path.isdir(src):
        shutil.copytree(src, dst2, dirs_exist_ok=True)
        shutil.rmtree(src)
    else:
        shutil.move(src, dst2)
    rec['status'] = 'moved'
    return rec


def merge_memory(src_dir, dst_dir):
    """总是合并：MEMORY.md 逐行去重追加；同名不同内容另存为带时间戳文件。"""
    rep = {'copied': [], 'merged': [], 'skipped': []}
    if not os.path.isdir(src_dir):
        return rep
    os.makedirs(dst_dir, exist_ok=True)
    for name in sorted(os.listdir(src_dir)):
        src = os.path.join(src_dir, name)
        if not os.path.isfile(src):
            continue
        dst = os.path.join(dst_dir, name)
        if not os.path.exists(dst):
            shutil.copy2(src, dst)
            rep['copied'].append(name)
            continue
        if name.lower() == 'memory.md':
            try:
                old_lines = open(src, encoding='utf-8', errors='ignore').read().splitlines()
                cur = open(dst, encoding='utf-8', errors='ignore').read()
                have = {l.strip() for l in cur.splitlines()}
                add = [l for l in old_lines if l.strip() and l.strip() not in have]
                if add:
                    with open(dst, 'a', encoding='utf-8') as f:
                        f.write(chr(10) + chr(10).join(add) + chr(10))
                    rep['merged'].append(f'{name}(+{len(add)})')
                else:
                    rep['skipped'].append(name)
            except Exception:
                rep['skipped'].append(name)
            continue
        try:
            if filecmp.cmp(src, dst, shallow=False):
                rep['skipped'].append(name)
                continue
        except Exception:
            pass
        alt = unique_path(dst)
        shutil.copy2(src, alt)
        rep['merged'].append(os.path.basename(alt))
    return rep


def is_dedicated_cwd(cwd, sid):
    """末段等于任务 ID 前 8 位时，视为该任务独占的临时工作目录。"""
    if not cwd or not sid:
        return False
    return os.path.basename(os.path.normpath(cwd)).lower() == sid[:8].lower()


def cwd_entries(cwd, sid):
    """专属 cwd 下的全部顶层条目（文件与目录）。"""
    if not is_dedicated_cwd(cwd, sid) or not os.path.isdir(cwd):
        return []
    out = []
    for name in os.listdir(cwd):
        out.append(os.path.join(cwd, name))
    return out


def path_under(p, root):
    if not p or not root:
        return False
    try:
        pn = os.path.normcase(os.path.abspath(p))
        rn = os.path.normcase(os.path.abspath(root))
    except Exception:
        return False
    return pn == rn or pn.startswith(rn + os.sep)


WRITE_TOOLS = ('Write', 'Edit', 'MultiEdit', 'NotebookEdit')


def tool_output_paths(jsonl_path, root):
    """从任务正文里抽 Write/Edit 类工具写过的、位于 root 下的绝对路径。"""
    out = set()
    if not jsonl_path or not os.path.isfile(jsonl_path):
        return out
    try:
        fh = open(jsonl_path, encoding='utf-8', errors='ignore')
    except Exception:
        return out
    with fh:
        for line in fh:
            if 'tool_use' not in line:
                continue
            try:
                o = json.loads(line)
            except Exception:
                continue
            msg = o.get('message') or {}
            cont = msg.get('content')
            if not isinstance(cont, list):
                continue
            for c in cont:
                if not isinstance(c, dict) or c.get('type') != 'tool_use':
                    continue
                if c.get('name') not in WRITE_TOOLS:
                    continue
                inp = c.get('input') or {}
                for k in ('file_path', 'notebook_path', 'path'):
                    v = inp.get(k)
                    if isinstance(v, str) and v and path_under(v, root):
                        out.add(os.path.abspath(v))
    return out


def session_outputs(con, sid, extra=None, old_cwd=None):
    """该任务涉及的文件（绝对源路径）。DB 索引 + 调用方给的正文路径两路合并。"""
    found = {}
    try:
        rows = con.execute(
            'select f.path as path, f.operation as op, s.roots_json as roots '
            'from turn_file_change_files f '
            'join turn_file_change_sets s on f.change_set_id = s.change_set_id '
            'where s.session_id = ?', (sid,)).fetchall()
    except sqlite3.Error:
        rows = []
    for r in rows:
        roots = load_json(r['roots'], [])
        root = ''
        if isinstance(roots, list):
            for x in roots:
                if isinstance(x, dict) and x.get('id') == 'primary':
                    root = x.get('path') or ''
                    break
            if not root and roots and isinstance(roots[0], dict):
                root = roots[0].get('path') or ''
        rel = (r['path'] or '').replace('/', os.sep)
        if not root or not rel:
            continue
        found[os.path.normcase(os.path.join(root, rel))] = os.path.join(root, rel)

    for p in (extra or ()):
        if p:
            found.setdefault(os.path.normcase(p), p)

    for p in cwd_entries(old_cwd, sid):
        found.setdefault(os.path.normcase(p), p)

    return list(found.values())


def move_files_for_session(con, sid, old_cwd, new_root, base, metadata_only=False,
                           memory_mode='always'):
    """搬任务文件、项目记忆与产出；返回记录列表。

    memory_mode: always=总是合并；auto=仅当旧项目再无其他任务时合并。
    """
    recs = []
    if metadata_only:
        return recs
    old_proj = find_project_dir(sid)
    new_proj = os.path.join(projects_root(), encode_cwd(new_root))
    os.makedirs(new_proj, exist_ok=True)
    # 正文里的工具路径必须在搬走 jsonl 之前抽出来
    proto_jsonl = os.path.join(old_proj, f'{sid}.jsonl') if old_proj else None
    extra_paths = tool_output_paths(proto_jsonl, old_cwd) if proto_jsonl else set()

    if old_proj and os.path.normcase(old_proj) != os.path.normcase(new_proj):
        recs.append(move_entry(os.path.join(old_proj, f'{sid}.jsonl'),
                               os.path.join(new_proj, f'{sid}.jsonl'),
                               base, sid, 'session', 'jsonl'))
        recs.append(move_entry(os.path.join(old_proj, sid),
                               os.path.join(new_proj, sid),
                               base, sid, 'session', 'sidecar'))
        mem_old = os.path.join(old_proj, 'memory')
        if os.path.isdir(mem_old):
            shared = project_sessions(old_proj) > 1
            do_merge = memory_mode == 'always' or (memory_mode == 'auto' and not shared)
            if do_merge:
                try:
                    backup_path(mem_old, base, sid, 'memory')
                except Exception:
                    pass
                rep = merge_memory(mem_old, os.path.join(new_proj, 'memory'))
                recs.append({'kind': 'memory', 'src': mem_old,
                             'dst': os.path.join(new_proj, 'memory'),
                             'status': 'merged', 'report': rep})
            else:
                recs.append({'kind': 'memory', 'src': mem_old,
                             'dst': os.path.join(new_proj, 'memory'),
                             'status': 'skipped-shared',
                             'reason': f'旧项目仍有 {project_sessions(old_proj) - 1} 条其他任务'})

    for src in session_outputs(con, sid, extra_paths, old_cwd):
        try:
            rel = os.path.relpath(src, old_cwd)
        except Exception:
            continue
        if rel.startswith('..'):
            continue
        dst = os.path.join(new_root, rel)
        if os.path.normcase(src) == os.path.normcase(dst):
            continue
        rec = move_entry(src, dst, base, sid, 'output', 'output', rel)
        if rec['status'] == 'moved':          # 旧路径留链接，历史引用仍可用
            try:
                os.link(rec['dst'], rec['src'])
                rec['link'] = True
            except Exception:
                try:
                    shutil.copy2(rec['dst'], rec['src'])
                    rec['link'] = 'copy'
                except Exception:
                    rec['link'] = False
        recs.append(rec)
    return recs


def undo_files(recs):
    """把已搬走的文件放回原位；记忆合并不可逆，只报告。"""
    notes = []
    for r in reversed(recs or []):
        kind = r.get('kind')
        if kind == 'memory':
            notes.append('memory:merged(需手工核对)')
            continue
        if r.get('status') != 'moved':
            continue
        src, dst = r.get('src'), r.get('dst')
        try:
            if r.get('link') in (True, 'copy') and os.path.exists(src):
                if r.get('link') is True:
                    os.unlink(src)
                else:
                    os.remove(src)
            if os.path.exists(dst):
                os.makedirs(os.path.dirname(src), exist_ok=True)
                if os.path.isdir(dst):
                    shutil.copytree(dst, src, dirs_exist_ok=True)
                    shutil.rmtree(dst)
                else:
                    shutil.move(dst, src if not os.path.exists(src) else unique_path(src))
                notes.append('restored')
        except Exception as ex:
            notes.append(f'fail:{ex}')
    return notes


def cmd_move(args, con, db_path):
    pending = None
    ws, cands = find_workspace(con, args.to, include_deleted=False, local_only=True)
    if not ws:
        if cands:
            die('目标工作区名不唯一，请改用 UUID：\n' +
                '\n'.join(f"  {w['workspace_id']}  {w['name']}  {primary_root(w)}" for w in cands))
        if not getattr(args, 'create', False):
            die(f'未找到目标工作区: {args.to}（加 --create 自动创建，或用 workspace new）')
        path = os.path.abspath(os.path.normpath(args.to))
        name = getattr(args, 'name', None) or os.path.basename(path) or path
        if not os.path.isdir(path) and not getattr(args, 'allow_missing', False):
            die(f'目录不存在: {path}。确认要在该路径上建工作区就加 --allow-missing')
        pending = {'id': str(uuid.uuid4()), 'name': name, 'path': path}
        ws = {'workspace_id': pending['id'], 'name': name, 'workspace_source': 'local',
              'root_paths_json': json.dumps([path], ensure_ascii=False),
              'product_mode': 'coding'}
        warn(f'目标工作区不存在，将新建：{name} -> {path}', 'NOTE')
    if not (ws['workspace_source'] or '').startswith('local'):
        die(f'目标工作区是另一台设备的投影（{ws["workspace_source"]}），本机不能作为迁移目标')
    root = primary_root(ws)
    if not root:
        die('目标工作区没有根路径')

    et_id, reused = infer_et_id(con, ws['workspace_id'], root)
    stats = message_stats(con)
    all_rows = session_rows(con, include_deleted=False, include_peer=False)
    rows = all_rows
    if args.skip_in_target:
        rows = [r for r in rows if r['workspace_id'] != ws['workspace_id']]

    if args.ids:
        want = [s.strip() for s in args.ids.split(',') if s.strip()]
        # 「库里根本没有这个 ID」与「已在目标工作区、按默认策略跳过」是两件事，分开报
        missing = [w for w in want if not any(r['session_id'].startswith(w) for r in all_rows)]
        if missing:
            warn(f"这些 ID 未匹配到任务：{', '.join(missing)}")
        if args.skip_in_target:
            in_target = [w for w in want if w not in missing
                         and not any(r['session_id'].startswith(w) for r in rows)]
            if in_target:
                warn(f"已在目标工作区，跳过：{', '.join(in_target)}"
                     f"（要重跑加 --no-skip-in-target）", 'NOTE')
        rows = [r for r in rows if any(r['session_id'].startswith(w) for w in want)]
    if args.filter:
        try:
            rows = apply_filter(rows, parse_filter(args.filter))
        except FilterError as ex:
            die(str(ex))

    # 默认跳过已在目标工作区的任务；--no-skip-in-target 时连它们一起重跑（例如只补搬文件）
    if args.skip_in_target:
        plan = [r for r in rows if r['workspace_id'] != ws['workspace_id']]
    else:
        plan = list(rows)

    def move_payload(applied, results, backup, removed_dirs):
        """move 的 JSON 契约：单文档，空结果也合法。"""
        return {'target': {'id': ws['workspace_id'], 'name': ws['name'], 'root': root,
                           'et_id': et_id, 'et_id_reused': reused},
                'plan': [{'sid': r['session_id'], 'title': r['title'], 'from': r['cwd']}
                         for r in plan],
                'applied': applied, 'results': results, 'backup': backup,
                'removed_dirs': removed_dirs, 'warnings': list(WARNINGS)}

    if not plan:
        if args.json:
            emit_json(move_payload(False, [], None, []))
            return 0
        out('没有需要迁移的任务')
        return 0

    if not args.json:
        out(f"目标: {ws['name']}  ({root})")
        out(f"执行标识: {et_id}" + ('（复用该工作区已有值）' if reused else '（新工作区，使用 UUID）'))
        out('')
        out(f'待迁移 {len(plan)} 条：')
        for r in plan:
            out(f"  {r['session_id'][:8]}  {(r['title'] or '')[:38]}")
            out(f"      {r['cwd']}  ->  {root}")

    if not args.apply_flag:
        if args.json:
            emit_json(move_payload(False, [], None, []))
            return 0
        out('')
        out('[DRY-RUN] 未写入。加 --apply 执行。')
        return 0

    gate_running(getattr(args, 'require_closed', False))

    # 按对象备份：每条任务存一份完整行，可单条回滚。
    # 先建备份组，`--create` 新建的工作区也能落进 items/，回滚时反向删除。
    base = new_backup_set(db_path, 'move')
    metadata_only = getattr(args, 'metadata_only', False)
    ws_item = None

    if pending:
        now = now_ms()
        ws_extra = json.dumps({'workspaceIcon': 'folder', 'workspaceColor': 'primary',
                               'workspaceIndexEnabled': True}, ensure_ascii=False)
        w0 = connect(db_path, write=True)
        try:
            with w0:
                w0.execute('insert into workspaces(workspace_id,name,workspace_source,root_paths_json,'
                           'product_mode,extra_json,created_at,updated_at,archived,deleted_at) '
                           'values(?,?,?,?,?,?,?,?,0,null)',
                           (pending['id'], pending['name'], 'local',
                            json.dumps([pending['path']], ensure_ascii=False), 'coding',
                            ws_extra, now, now))
        finally:
            w0.close()
        # 这行是本次操作插入的，回滚必须删掉，否则 rollback --batch 后留孤儿工作区
        mp_ws = os.path.join(base, 'items', f"workspaces-{pending['id']}.json")
        ws_row = {'workspace_id': pending['id'], 'name': pending['name'],
                  'workspace_source': 'local',
                  'root_paths_json': json.dumps([pending['path']], ensure_ascii=False),
                  'product_mode': 'coding', 'extra_json': ws_extra,
                  'created_at': now, 'updated_at': now, 'archived': 0, 'deleted_at': None}
        with open(mp_ws, 'w', encoding='utf-8') as f:
            json.dump({'version': 1, 'table': 'workspaces', 'key_column': 'workspace_id',
                       'key_value': pending['id'], 'op': 'insert',
                       'saved_at': int(time.time() * 1000), 'row': ws_row,
                       'meta': {'reason': 'move --create'}}, f, ensure_ascii=False, indent=2)
        ws_item = {'manifest': os.path.basename(mp_ws), 'table': 'workspaces',
                   'title': pending['name'], 'status': 'inserted', 'op': 'insert'}
        out(f"已创建工作区: {pending['name']} -> {pending['path']}")

    et = {'mode': 'local',
          'host': {'id': 'local', 'kind': 'local', 'label': 'Local'},
          'workspace': {'id': et_id, 'path': root}}
    et_json = json.dumps(et, ensure_ascii=False, separators=(',', ':'))

    # 搬之前的项目目录快照：搬完之后 find_project_dir 只会命中新目录，
    # 用它清空目录才有效（原来在搬完后求值，removed 永远为空）。
    pre_dirs = {r['session_id']: find_project_dir(r['session_id']) for r in plan}

    w = connect(db_path, write=True)
    results = []
    try:
        for r in plan:
            sid = r['session_id']
            files = []
            try:
                # 先搬文件（任务正文/子目录/项目记忆/产出），再改库
                files = move_files_for_session(con, sid, r['cwd'], root, base, metadata_only)
                row = con.execute('select * from chat_sessions where session_id=?', (sid,)).fetchone()
                payload = {'version': 1, 'table': 'chat_sessions', 'key_column': 'session_id',
                           'key_value': sid, 'saved_at': int(time.time() * 1000),
                           'row': {k: row[k] for k in row.keys()}, 'files': files,
                           'meta': {'from_cwd': r['cwd'], 'to_root': root,
                                    'metadata_only': metadata_only}}
                mp = os.path.join(base, 'items', f'chat_sessions-{sid}.json')
                with open(mp, 'w', encoding='utf-8') as f:
                    json.dump(payload, f, ensure_ascii=False, indent=2)

                with w:   # 每条独立事务：失败只影响自己
                    w.execute('update chat_sessions set workspace_id=?, cwd=?, execution_target_json=? '
                              'where session_id=?', (ws['workspace_id'], root, et_json, sid))
                chk = w.execute('select workspace_id, cwd, execution_target_json '
                                'from chat_sessions where session_id=?', (sid,)).fetchone()
                ok = (chk and chk['workspace_id'] == ws['workspace_id'] and chk['cwd'] == root
                      and load_json(chk['execution_target_json']).get('workspace', {}).get('path') == root)
                moved_files = sum(1 for f in files if f.get('status') == 'moved')
                mem = next((f for f in files if f.get('kind') == 'memory'), None)
                rep = (mem or {}).get('report', {}) if mem else {}
                mem_n = len(rep.get('copied', [])) + len(rep.get('merged', []))
                results.append({'session_id': sid, 'title': r['title'],
                                'status': 'ok' if ok else 'verify_failed',
                                'manifest': os.path.basename(mp),
                                'files_moved': moved_files, 'memory_merged': mem_n,
                                'memory_report': rep})
                extra = ''
                if files:
                    extra = f'  文件 {moved_files}'
                    if mem and mem.get('status') == 'merged':
                        extra += (f"｜记忆 新增{len(rep.get('copied', []))}"
                                  f"/合并{len(rep.get('merged', []))}"
                                  f"/跳过{len(rep.get('skipped', []))}")
                out(f"[{'OK' if ok else 'WARN'}] {sid[:8]}  {(r['title'] or '')[:30]}{extra}")
            except Exception as ex:
                if files:
                    undo_files(files)
                results.append({'session_id': sid, 'title': r['title'],
                                'status': 'failed', 'error': str(ex),
                                'manifest': None, 'files_moved': 0, 'memory_merged': 0})
                out(f'[FAIL] {sid[:8]}  {ex}')
    finally:
        w.close()

    removed = []
    if not getattr(args, 'keep_orphans', False):
        removed = clean_orphan_dirs([pre_dirs.get(x['session_id']) for x in plan],
                                    keep=[os.path.join(projects_root(), encode_cwd(root))])
    batch_items = results + ([ws_item] if ws_item else [])
    batch = write_batch_manifest(base, batch_items, note=f'move -> {ws["name"]} ({root})',
                                 extra={'removed_dirs': removed})
    ok_n = sum(1 for x in results if x['status'] == 'ok')
    bad_n = len(results) - ok_n
    out('')
    out(f'完成：成功 {ok_n}，失败/异常 {bad_n}，共 {len(results)} 条')
    out(f'备份与清单: {base}')
    if not metadata_only:
        out('已按默认策略搬运：任务文件 → 项目目录；项目记忆 → 合并到目标项目；产出 → 新工作区（旧路径留链接）')
        if removed:
            out(f'已清理 {len(removed)} 个空项目目录')
    out(f'单条回滚: rollback --manifest "{os.path.join(base, "items", "chat_sessions-<sid>.json")}"')
    out(f'整批回滚: rollback --batch "{batch}"')
    post_write_hint('迁移')
    if args.json:
        emit_json(move_payload(True, results, base, removed))
    return 0 if bad_n == 0 else 1


# ---------------------------------------------------------------- workspace

def cmd_repair(args, con, db_path):
    """补齐历史上「只改库没搬文件」的任务：按当前 cwd 把任务文件、记忆、产出归位。"""
    rows = session_rows(con, include_deleted=False, include_peer=False)
    if getattr(args, 'ids', None):
        want = [x.strip() for x in args.ids.split(',') if x.strip()]
        rows = [r for r in rows if any(r['session_id'].startswith(w) for w in want)]
    plan = []
    for r in rows:
        cur = find_project_dir(r['session_id'])
        want_dir = os.path.join(projects_root(), encode_cwd(r['cwd']))
        if cur and os.path.normcase(cur) == os.path.normcase(want_dir):
            continue
        plan.append((r, cur, want_dir))

    plan_json = [{'sid': r['session_id'], 'title': r['title'], 'from': cur, 'to': want_dir}
                 for r, cur, want_dir in plan]

    def repair_payload(applied, results, backup, removed_dirs):
        return {'applied': applied, 'plan': plan_json, 'results': results,
                'backup': backup, 'removed_dirs': removed_dirs,
                'warnings': list(WARNINGS)}

    if not plan:
        if args.json:
            emit_json(repair_payload(False, [], None, []))
            return 0
        out('没有需要修复的任务：所有项目目录都与当前 cwd 一致')
        return 0

    if not args.json:
        out(f'待修复 {len(plan)} 条（数据库不动，只搬文件）')
        out('')
        for r, cur, want_dir in plan:
            out(f"  {r['session_id'][:8]}  {(r['title'] or '')[:32]}")
            out(f"      归属 {r['cwd']}")
            out(f"      目录 {os.path.basename(cur) if cur else '(无)'}  ->  {os.path.basename(want_dir)}")
        out('')
        out('记忆策略：源目录只有这一条任务时合并其项目记忆；共用目录的记忆留在原项目，避免复制污染。')

    # 按源目录统计：只有「该目录仅此一条任务」时才算独享，才搬记忆
    dir_counts = {}
    for r, cur, _want in plan:
        if cur:
            dir_counts[cur] = project_sessions(cur)
    explicit = getattr(args, 'memory_mode', None)

    if not args.apply_flag:
        if args.json:
            emit_json(repair_payload(False, [], None, []))
            return 0
        ded = sum(1 for _r, cur, _w in plan if cur and dir_counts.get(cur) == 1)
        out('')
        out(f'其中 {ded} 条来自独享目录（记忆会合并），{len(plan) - ded} 条来自共用目录（记忆留在原项目）')
        out('[DRY-RUN] 未写入。加 --apply 执行。')
        return 0

    gate_running(getattr(args, 'require_closed', False))
    base = new_backup_set(db_path, 'repair')
    results = []
    for r, cur, want_dir in plan:
        sid = r['session_id']
        recs = []
        try:
            mode = explicit or ('always' if cur and dir_counts.get(cur) == 1 else 'never')
            recs = move_files_for_session(con, sid, r['cwd'], r['cwd'], base, False,
                                          memory_mode=mode)
            moved = sum(1 for x in recs if x.get('status') == 'moved')
            mem = next((x for x in recs if x.get('kind') == 'memory'), None)
            rep = (mem or {}).get('report', {}) if mem else {}
            mem_state = '-'
            if mem:
                if mem['status'] == 'merged':
                    mem_state = (f"新增{len(rep.get('copied', []))}"
                                 f"/合并{len(rep.get('merged', []))}"
                                 f"/跳过{len(rep.get('skipped', []))}")
                else:
                    mem_state = '共用目录，未搬'
            results.append({'session_id': sid, 'title': r['title'], 'from': cur,
                            'to': want_dir, 'status': 'ok', 'files_moved': moved,
                            'memory': mem_state, 'memory_report': rep})
            out(f"[OK] {sid[:8]}  文件 {moved}｜记忆 {mem_state}")
        except Exception as ex:
            if recs:
                undo_files(recs)
            results.append({'session_id': sid, 'status': 'failed', 'error': str(ex)})
            out(f'[FAIL] {sid[:8]}  {ex}')

    removed = []
    if not getattr(args, 'keep_orphans', False):
        removed = clean_orphan_dirs([cur for _r, cur, _w in plan],
                                    keep=[w for _r, _c, w in plan])
    batch = write_batch_manifest(base, results, note='repair',
                                 extra={'removed_dirs': removed})
    ok_n = sum(1 for x in results if x['status'] == 'ok')
    out('')
    out(f'完成：修复 {ok_n}，失败 {len(results) - ok_n}')
    if removed:
        out(f'已清理 {len(removed)} 个空项目目录：')
        for d in removed:
            out(f'  - {os.path.basename(d)}')
    out(f'备份与清单: {base}')
    if args.json:
        emit_json(repair_payload(True, results, base, removed))
    return 0 if ok_n == len(results) else 1


def _pad(s, width):
    """按终端显示宽度左对齐补空格（CJK 记 2 列）。

    `f'{name:<24}'` 按字符数补位，中文名会把后面几列整体右移。
    """
    w = sum(2 if unicodedata.east_asian_width(c) in 'WF' else 1 for c in s)
    return s + ' ' * max(0, width - w)


def workspace_device(w):
    """工作区所属设备：本地 → 本机；对端 → workspace_source 第二段前 8 位。"""
    src = (w['workspace_source'] or '')
    if src.startswith('local'):
        return '本机'
    parts = src.split(':')
    return (parts[1][:8] if len(parts) > 1 and parts[1] else '对端')


def cmd_workspace(args, con, db_path):
    sub = args.ws_cmd

    if sub == 'list':
        rows = load_workspaces(con, include_deleted=args.include_deleted)
        counts = {}
        for r in con.execute('select workspace_id, count(*) from chat_sessions '
                             'where deleted_at is null group by workspace_id'):
            counts[r[0]] = r[1]
        if args.json:
            emit_json([{'id': w['workspace_id'], 'name': w['name'],
                        'source': w['workspace_source'], 'device': workspace_device(w),
                        'root': primary_root(w),
                        'sessions': counts.get(w['workspace_id'], 0),
                        'deleted': bool(w['deleted_at'] if 'deleted_at' in w.keys() else 0)}
                       for w in rows])
            return 0
        out(f"{_pad('名称', 24)} {'任务':>4} {'来源':<6} {_pad('设备', 10)} 根路径")
        out('-' * 100)
        for w in rows:
            src = 'local' if (w['workspace_source'] or '').startswith('local') else 'peer'
            out(f"{_pad(w['name'][:24], 24)} {counts.get(w['workspace_id'], 0):>4} {src:<6} "
                f"{_pad(workspace_device(w), 10)} {primary_root(w)}")
        return 0

    if sub == 'new':
        name, path = args.name, args.path
        if not name or not path:
            die('workspace new 需要 --name 与 --path')
        exists = [w for w in load_workspaces(con)
                  if (w['name'] or '') == name and (w['workspace_source'] or '').startswith('local')]
        if exists:
            if args.json:
                emit_json({'created': False, 'reason': '同名工作区已存在',
                           'items': [{'id': w['workspace_id'], 'name': w['name'],
                                      'root': primary_root(w)} for w in exists],
                           'applied': False, 'warnings': list(WARNINGS)})
                return 0
            out(f'同名工作区已存在，不再新建：')
            for w in exists:
                src = 'local' if (w['workspace_source'] or '').startswith('local') else 'peer'
                out(f"  {w['workspace_id']}  {w['name']}  [{src}]  {primary_root(w)}")
            out('')
            out('如需把任务归入其中，直接用 move --to <名称或UUID>。')
            return 0
        norm = os.path.normpath(path)
        dir_exists = os.path.exists(norm)
        if dir_exists:
            out(f'目录已存在: {norm}（直接复用）')
        else:
            warn(f'目录不存在: {norm}', 'NOTE')
            out('       技能不会自动创建目录，请先确认是否要建，或改用已有路径。')
            if not args.allow_missing:
                if args.json:
                    emit_json({'created': False, 'reason': '目录不存在，需 --allow-missing',
                               'name': name, 'path': norm, 'dir_exists': False,
                               'applied': False, 'warnings': list(WARNINGS)})
                    return 0
                out('       如确认要在不存在路径上建工作区，加 --allow-missing。')
                return 0
        new_id = str(uuid.uuid4())
        now = now_ms()
        if not args.apply_flag:
            if args.json:
                emit_json({'created': False, 'id': new_id, 'name': name, 'path': norm,
                           'dir_exists': dir_exists, 'applied': False,
                           'warnings': list(WARNINGS)})
                return 0
            out('')
            out(f'[DRY-RUN] 将新建工作区 {name} -> {norm}（id {new_id}）')
            return 0
        gate_running(getattr(args, 'require_closed', False))
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
        if args.json:
            emit_json({'created': True, 'id': new_id, 'name': name, 'path': norm,
                       'dir_exists': dir_exists, 'applied': True,
                       'backup': os.path.basename(bk), 'warnings': list(WARNINGS)})
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
        out(f"重命名: {ws['name']} -> {args.new_name}")
        if not args.apply_flag:
            if args.json:
                emit_json({'id': ws['workspace_id'], 'old': ws['name'], 'new': args.new_name,
                           'applied': False, 'warnings': list(WARNINGS)})
                return 0
            out('[DRY-RUN] 未写入')
            return 0
        gate_running(getattr(args, 'require_closed', False))
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
        if args.json:
            emit_json({'id': ws['workspace_id'], 'old': ws['name'], 'new': args.new_name,
                       'applied': True, 'backup': os.path.basename(bk),
                       'warnings': list(WARNINGS)})
        return 0

    if sub in ('archive', 'unarchive'):
        val = 1 if sub == 'archive' else 0
        out(f"{'归档' if val else '取消归档'}工作区: {ws['name']}")
        if not args.apply_flag:
            if args.json:
                emit_json({'id': ws['workspace_id'], 'archive': val, 'applied': False,
                           'warnings': list(WARNINGS)})
                return 0
            out('[DRY-RUN] 未写入')
            return 0
        gate_running(getattr(args, 'require_closed', False))
        bk = make_backup(db_path, 'wsarch')
        w = connect(db_path, write=True)
        try:
            with w:
                w.execute('update workspaces set archived=?, updated_at=? where workspace_id=?',
                          (val, now_ms(), ws['workspace_id']))
        finally:
            w.close()
        out('已完成')
        if args.json:
            emit_json({'id': ws['workspace_id'], 'archive': val, 'applied': True,
                       'backup': os.path.basename(bk), 'warnings': list(WARNINGS)})
        return 0

    if sub == 'retarget':
        if not args.path:
            die('workspace retarget 需要 --path')
        root_old = primary_root(ws)
        root_new = os.path.normpath(args.path)
        n_all = con.execute('select count(*) from chat_sessions where workspace_id=?',
                            (ws['workspace_id'],)).fetchone()[0]
        n_sess = con.execute('select count(*) from chat_sessions where workspace_id=? and deleted_at is null',
                             (ws['workspace_id'],)).fetchone()[0]
        et_id, _ = infer_et_id(con, ws['workspace_id'], root_new)
        if not args.json:
            out(f"{ws['name']}: {root_old}  ->  {root_new}")
            extra = f'（含已删除 {n_all - n_sess} 条）' if n_all > n_sess else ''
            out(f'将级联更新 {n_all} 条任务的 cwd 与执行目标{extra}')
        if not args.apply_flag:
            if args.json:
                emit_json({'id': ws['workspace_id'], 'from': root_old, 'to': root_new,
                           'sessions': n_sess, 'sessions_all': n_all, 'applied': False,
                           'warnings': list(WARNINGS)})
                return 0
            out('[DRY-RUN] 未写入')
            return 0
        gate_running(getattr(args, 'require_closed', False))
        bk = make_backup(db_path, 'wsretarget')
        out(f'已备份: {os.path.basename(bk)}')
        et = {'mode': 'local', 'host': {'id': 'local', 'kind': 'local', 'label': 'Local'},
              'workspace': {'id': et_id, 'path': root_new}}
        skipped = 0
        w = connect(db_path, write=True)
        try:
            with w:
                w.execute('update workspaces set root_paths_json=?, updated_at=? where workspace_id=?',
                          (json.dumps([root_new], ensure_ascii=False), now_ms(), ws['workspace_id']))
                for r in w.execute('select session_id, extra_json, execution_target_json '
                                   'from chat_sessions where workspace_id=?',
                                   (ws['workspace_id'],)).fetchall():
                    if is_peer_type(None, {'extra_json': r['extra_json'],
                                           'execution_target_json': r['execution_target_json'] or ''}):
                        skipped += 1
                        continue
                    w.execute('update chat_sessions set cwd=?, execution_target_json=? where session_id=?',
                              (root_new, json.dumps(et, ensure_ascii=False, separators=(',', ':')),
                               r['session_id']))
        finally:
            w.close()
        out('已改路径并级联更新' + (f'（跳过影子任务 {skipped} 条）' if skipped else ''))
        note = 'cwd 已改，项目目录未搬；如需恢复项目记忆请运行 repair（先干跑看清单）'
        out('')
        out(f'注意：{note}')
        if args.json:
            emit_json({'id': ws['workspace_id'], 'from': root_old, 'to': root_new,
                       'sessions': n_sess, 'sessions_all': n_all, 'applied': True,
                       'skipped_peer': skipped, 'backup': os.path.basename(bk),
                       'note': note, 'warnings': list(WARNINGS)})
        return 0

    if sub == 'delete':
        sess = list(con.execute('select session_id, title, deleted_at from chat_sessions where workspace_id=?',
                                (ws['workspace_id'],)))
        alive = [s for s in sess if not s['deleted_at']]
        if not args.json:
            out(f"删除工作区: {ws['name']}  ({primary_root(ws)})")
            out(f'其下任务 {len(sess)} 条，其中未删除 {len(alive)} 条将被一并软删除（进回收站）')
        if not args.yes:
            die('删除类操作需要 --yes 确认（软删除，可在 Qoder 回收站恢复）')
        if not args.apply_flag:
            if args.json:
                emit_json({'id': ws['workspace_id'], 'name': ws['name'],
                           'sessions': len(sess), 'alive': len(alive), 'applied': False,
                           'warnings': list(WARNINGS)})
                return 0
            out('[DRY-RUN] 未写入')
            return 0
        gate_running(getattr(args, 'require_closed', False))
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
        out(f'已软删除工作区及 {len(alive)} 条任务')
        if args.json:
            emit_json({'id': ws['workspace_id'], 'name': ws['name'],
                       'sessions': len(sess), 'alive': len(alive), 'applied': True,
                       'backup': os.path.basename(bk), 'warnings': list(WARNINGS)})
        return 0

    die(f'未知的 workspace 子命令: {sub}')


# ---------------------------------------------------------------- backup / rollback

def cmd_backup(args, con, db_path):
    if args.list:
        files = list_backups(db_path)
        sets = backup_sets(db_path)
        if args.json:
            emit_json({'root': work_root(),
                       'snapshots': [{'path': p, 'size': os.path.getsize(p),
                                      'mtime': os.path.getmtime(p)} for p in files],
                       'sets': [{'path': p, 'mtime': os.path.getmtime(p),
                                 'batch': os.path.isfile(os.path.join(p, 'batch.json'))}
                                for p in sets],
                       'warnings': list(WARNINGS)})
            return 0
        out(f'备份根目录: {work_root()}')
        if not files and not sets:
            out('尚无备份')
            return 0
        if files:
            out('')
            out(f'整库快照 {len(files)} 份（保留最近 {BACKUP_KEEP} 份）')
            for p in files:
                out(f"  {fmt_ms(os.path.getmtime(p)*1000)}  {os.path.getsize(p)/1048576:>7.1f} MB  {os.path.basename(p)}")
        if sets:
            out('')
            out(f'按对象清单 {len(sets)} 组（可单条/整批回滚）')
            for p in sets:
                n_items = len(glob.glob(os.path.join(p, 'items', '*.json')))
                out(f"  {fmt_ms(os.path.getmtime(p)*1000)}  {n_items:>3} 条  {os.path.basename(p)}")
        return 0
    gate_running(getattr(args, 'require_closed', False))
    p = make_backup(db_path, 'manual')
    out(f'已备份: {p}')
    if args.json:
        emit_json({'path': p, 'root': work_root(), 'ok': True, 'warnings': list(WARNINGS)})
    return 0


def cmd_rollback(args, con, db_path):
    if args.manifest or args.batch:
        return rollback_items(args, con, db_path)

    src = args.backup
    if not src:
        die('请指定 --backup（整库快照）、--manifest（单条）或 --batch（整批）')
    if not os.path.isfile(src):
        die(f'备份文件不存在: {src}')
    if not args.yes:
        die('回滚会覆盖当前数据库，需要 --yes 确认')
    if not args.apply_flag:
        if args.json:
            emit_json({'restored': 0, 'failed': 0, 'items': [], 'applied': False,
                       'backup': src, 'warnings': list(WARNINGS)})
            return 0
        out(f'[DRY-RUN] 将用 {os.path.basename(src)} 覆盖当前库（当前库会先另存一份）')
        return 0
    # 整库覆盖是 copy2 + 删 -wal/-shm，不是 WAL 事务：应用在跑时会把库写坏。
    # 其它写操作有事务保护，这一条没有，所以这里必须硬拦（--force-hot 才放行）。
    if not CUSTOM_DB:
        n = qoder_running()
        if n and not getattr(args, 'force_hot', False):
            die(f'检测到 {n} 个 Qoder 进程在运行。整库覆盖无法热写'
                f'（直接复制文件 + 删 -wal/-shm，会把库写坏）。'
                f'请完全退出 Qoder 后重试；确要在运行中执行，加 --force-hot。', 3)
        if n:
            warn(f'--force-hot：{n} 个 Qoder 进程在运行，整库覆盖有损坏风险', 'WARN')
    gate_running(getattr(args, 'require_closed', False))
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
    if args.json:
        emit_json({'restored': 1, 'failed': 0,
                   'items': [{'backup': src, 'safety': safety, 'status': 'ok'}],
                   'applied': True, 'warnings': list(WARNINGS)})
    return 0


def rollback_items(args, con, db_path):
    """按 manifest / batch 逐行恢复，只影响清单里列出的行。"""
    paths = []
    if args.manifest:
        paths.append(args.manifest)
    if args.batch:
        if not os.path.isfile(args.batch):
            die(f'批次清单不存在: {args.batch}')
        with open(args.batch, encoding='utf-8') as f:
            batch = json.load(f)
        base = os.path.dirname(os.path.abspath(args.batch))
        for it in batch.get('items', []):
            name = it.get('manifest')
            if not name:
                continue
            p = os.path.join(base, 'items', name)
            if os.path.isfile(p):
                paths.append(p)

    if not paths:
        die('清单里没有可恢复的条目')

    out(f'待恢复 {len(paths)} 条')
    if not args.yes:
        die('按清单回滚会覆盖对应任务的当前值，需要 --yes 确认')
    if not args.apply_flag:
        if args.json:
            emit_json({'restored': 0, 'failed': 0, 'items': [], 'applied': False,
                       'warnings': list(WARNINGS)})
            return 0
        out('[DRY-RUN] 未写入')
        return 0

    gate_running(getattr(args, 'require_closed', False))
    w = connect(db_path, write=True)
    ok = fail = 0
    items = []
    try:
        for p in paths:
            entry = {'path': p}
            try:
                with open(p, encoding='utf-8') as f:
                    payload = json.load(f)
                entry.update({'table': payload.get('table'),
                              'key': str(payload.get('key_value'))[:8],
                              'op': payload.get('op') or 'restore'})
                with w:
                    n = restore_row(w, payload)
                notes = undo_files(payload.get('files'))
                entry['files'] = sorted(set(notes))
                if n:
                    ok += 1
                    entry['status'] = 'ok'
                    out(f"[OK] {payload['table']}  {str(payload['key_value'])[:8]}"
                        + (f"  文件: {'/'.join(sorted(set(notes)))}" if notes else ''))
                else:
                    fail += 1
                    entry['status'] = 'miss'
                    out(f"[MISS] {payload['table']}  {str(payload['key_value'])[:8]}（未命中）")
            except Exception as ex:
                fail += 1
                entry.update({'status': 'failed', 'error': str(ex)})
                out(f'[FAIL] {os.path.basename(p)}  {ex}')
            items.append(entry)
    finally:
        w.close()
    out('')
    out(f'完成：恢复 {ok}，失败 {fail}')
    post_write_hint('回滚')
    if args.json:
        emit_json({'restored': ok, 'failed': fail, 'items': items, 'applied': True,
                   'warnings': list(WARNINGS)})
    return 0 if fail == 0 else 1


# ---------------------------------------------------------------- CLI

def build_parser():
    p = argparse.ArgumentParser(
        prog='qoder_sessions.py',
        description='Qoder 任务管理：列表 / 重命名 / 迁移工作区 / 管理工作区 / 备份回滚 / 体检')
    p.add_argument('--db', help='Qoder main.sqlite 路径（默认自动探测）')
    p.add_argument('--json', action='store_true', help='输出结构化 JSON')
    p.add_argument('--require-closed', action='store_true',
                   help='Qoder 运行时拒绝写入（默认允许热写，写完重启验证）')
    p.add_argument('--backup-dir',
                   help='备份与临时产物根目录（默认 <当前工作目录>/qoder-cm-backups）')
    p.add_argument('--qoder-home',
                   help='Qoder 数据根目录（默认 ~/.qoder），用于指向沙箱副本')
    p.add_argument('--version', action='version', version=f'qoder-task-manager {VERSION}')
    sub = p.add_subparsers(dest='cmd', required=True)

    # 允许把 --db/--json/--require-closed 写在子命令后面；SUPPRESS 避免覆盖主解析器的值
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument('--db', default=argparse.SUPPRESS)
    common.add_argument('--json', action='store_true', default=argparse.SUPPRESS)
    common.add_argument('--require-closed', action='store_true', default=argparse.SUPPRESS)
    common.add_argument('--backup-dir', default=argparse.SUPPRESS,
                        help='备份与临时产物根目录（默认 ./qoder-cm-backups）')
    common.add_argument('--qoder-home', default=argparse.SUPPRESS,
                        help='Qoder 数据根目录（默认 ~/.qoder）')

    dp = sub.add_parser('doctor', parents=[common], help='体检：库/表/进程/路径/影子/备份')
    dp.add_argument('--deep', action='store_true',
                    help='加查任务文件、目录一致性、项目记忆、产出索引')

    lp = sub.add_parser('list', parents=[common], help='列出任务')
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
    rp.add_argument('--ids', help='逗号分隔的任务 ID 前缀')
    rp.add_argument('--filter', help='筛选表达式')
    rp.add_argument('--pending', action='store_true',
                    help='增量模式：只导出「标题未定稿」或「指定时间后新增过对话」的本地任务')
    rp.add_argument('--pending-since', dest='pending_since', default='yesterday',
                    help='仅对没有改名留痕的老任务生效的兜底窗口：today / yesterday / YYYY-MM-DD'
                         '（默认 yesterday，避免 23:00 之后到零点的对话被漏掉）')
    rp.add_argument('--respect-manual', dest='respect_manual', action='store_true',
                    help='跳过「标题被手工改过」的任务（默认不跳：只要又有新对话就重新判断）')
    rp.add_argument('--limit', type=int)
    rp.add_argument('--user-cap', type=int, default=4000, help='单条用户消息保留字符数')
    rp.add_argument('--assist-cap', type=int, default=1500, help='单条助手消息保留字符数')
    rp.add_argument('--shards', type=int, default=0,
                    help='导出时按字数做 LPT 均衡分组，生成 shards/groupN.json')
    rp.add_argument('--min-title-len', type=int, default=12, dest='min_title_len',
                    help='标题最小长度（字符，含 [分类] 前缀，默认 12）')
    rp.add_argument('--max-title-len', type=int, default=30, dest='max_title_len',
                    help='标题最大长度（字符，含 [分类] 前缀，默认 30）')
    rp.add_argument('--require-prefix', action='store_true', dest='require_prefix',
                    help='要求标题带 [短分类] 前缀')

    mp = sub.add_parser('move', parents=[common], help='迁移任务到工作区')
    mp.add_argument('--to', required=True, help='目标工作区：名称 / 根路径 / UUID')
    mp.add_argument('--ids', help='逗号分隔的任务 ID 前缀')
    mp.add_argument('--filter', help='筛选表达式')
    mp.add_argument('--apply-flag', '--apply', dest='apply_flag', action='store_true',
                    help='真正落盘')
    mp.add_argument('--skip-in-target', action=argparse.BooleanOptionalAction, default=True,
                    help='已在目标工作区的任务自动跳过（默认开启；--no-skip-in-target 关闭）')
    mp.add_argument('--metadata-only', action='store_true', dest='metadata_only',
                    help='只改数据库归属，不搬任务文件/记忆/产出')
    mp.add_argument('--keep-orphans', action='store_true', dest='keep_orphans',
                    help='保留搬空的源项目目录（默认自动删除）')
    mp.add_argument('--create', action='store_true',
                    help='目标工作区不存在时，按 --to 的路径新建')
    mp.add_argument('--name', help='配合 --create 指定工作区名（默认取路径末段）')
    mp.add_argument('--allow-missing', action='store_true', dest='allow_missing',
                    help='配合 --create，允许目录尚不存在')

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

    rpp = sub.add_parser('repair', parents=[common],
                         help='补齐历史只改库未搬文件的任务（按当前 cwd 归位文件/记忆/产出）')
    rpp.add_argument('--ids', help='逗号分隔的任务 ID 前缀')
    rpp.add_argument('--apply-flag', '--apply', dest='apply_flag', action='store_true')
    rpp.add_argument('--memory-mode', choices=['auto', 'always'], default=None,
                     dest='memory_mode',
                     help='默认按源目录判断；always=总是合并，auto=共用目录不搬')
    rpp.add_argument('--keep-orphans', action='store_true', dest='keep_orphans',
                     help='保留搬空的源项目目录（默认自动删除）')

    rb = sub.add_parser('rollback', parents=[common], help='从备份恢复（整库 / 单条 / 整批）')
    rb.add_argument('--backup', help='整库快照文件（main.sqlite.bak-*）')
    rb.add_argument('--manifest', help='单条清单（qoder-cm-backups/**/items/*.json）')
    rb.add_argument('--batch', help='整批清单（qoder-cm-backups/**/batch.json）')
    rb.add_argument('--yes', action='store_true')
    rb.add_argument('--force-hot', action='store_true', dest='force_hot',
                    help='整库覆盖时允许 Qoder 运行中执行（默认硬拦，容易写坏库）')
    rb.add_argument('--apply-flag', '--apply', dest='apply_flag', action='store_true')

    return p


def _force_utf8(stream):
    """把输出流切到 UTF-8。

    Windows 控制台/管道按 locale（GBK）编码，标题里一个 emoji 就 UnicodeEncodeError
    崩掉整条命令。reconfigure 在 3.7+ 的 TextIOWrapper 上可用，其它情况静默跳过。
    """
    try:
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass


def main(argv=None):
    global CUSTOM_DB, BACKUP_ROOT, QODER_HOME_OVERRIDE, JSON_MODE
    _force_utf8(sys.stdout)
    _force_utf8(sys.stderr)
    parser = build_parser()
    args = parser.parse_args(argv)
    JSON_MODE = bool(getattr(args, 'json', False))
    if getattr(args, 'backup_dir', None):
        BACKUP_ROOT = os.path.abspath(args.backup_dir)
    if getattr(args, 'qoder_home', None):
        QODER_HOME_OVERRIDE = os.path.abspath(args.qoder_home)
    default = None
    for cand in qoder_db_candidates():
        if os.path.isfile(cand):
            default = os.path.abspath(cand)
            break
    db_path = resolve_db(args.db)
    CUSTOM_DB = is_custom_db(args.db, default)
    con = connect(db_path, write=False)
    try:
        if args.cmd == 'doctor':
            return cmd_doctor(args, con, db_path)
        if args.cmd == 'list':
            return cmd_list(args, con, db_path)
        if args.cmd == 'rename':
            return cmd_rename(args, con, db_path)
        if args.cmd == 'repair':
            return cmd_repair(args, con, db_path)
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
