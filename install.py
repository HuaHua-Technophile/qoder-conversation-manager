#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把仓库里的技能安装/同步到宿主技能目录（扁平布局）。

仓库按 skills/<name>/SKILL.md 组织（便于 skills.sh 等目录索引），
宿主则要求 <技能目录>/SKILL.md，所以安装时把内容摊平复制过去。

开发时建议用 --link：直接建符号链接指向仓库，改代码立即生效，不用反复同步。

用法：
    python install.py                       # 复制安装到 ~/.workbuddy/skills
    python install.py --link                # 符号链接到仓库（开发模式）
    python install.py --to ~/.qoder/skills
    python install.py --targets all         # 三个宿主目录都装
"""
import argparse
import os
import shutil
import sys

NAME = 'qoder-conversation-manager'
REPO = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(REPO, 'skills', NAME)
FILES = ['SKILL.md', 'CHANGELOG.md', 'PUBLISHING.md']
DIRS = ['scripts', 'references', 'examples']
SKIP = {'__pycache__', '.git', 'dist'}

HOMES = {
    'workbuddy': '~/.workbuddy/skills',
    'qoder': '~/.qoder/skills',
    'agents': '~/.agents/skills',
}


def sync(dest_root):
    if not os.path.isdir(SRC):
        raise SystemExit(f'找不到技能目录: {SRC}')
    dest = os.path.join(os.path.expanduser(dest_root), NAME)
    os.makedirs(dest, exist_ok=True)
    n = 0
    for f in FILES:
        p = os.path.join(SRC, f)
        if os.path.isfile(p):
            shutil.copy2(p, os.path.join(dest, f))
            n += 1
    for d in DIRS:
        for cur, dirs, files in os.walk(os.path.join(SRC, d)):
            dirs[:] = [x for x in dirs if x not in SKIP]
            rel = os.path.relpath(cur, SRC)
            os.makedirs(os.path.join(dest, rel), exist_ok=True)
            for fn in files:
                if fn.endswith('.pyc') or fn == 'build_pkg.py':
                    continue
                shutil.copy2(os.path.join(cur, fn), os.path.join(dest, rel, fn))
                n += 1
    return dest, n


def link(dest_root):
    """建符号链接指向仓库里的技能目录，改代码立即生效。"""
    if not os.path.isdir(SRC):
        raise SystemExit(f'找不到技能目录: {SRC}')
    dest = os.path.join(os.path.expanduser(dest_root), NAME)
    if os.path.islink(dest):
        cur = os.path.realpath(dest)
        if os.path.normcase(cur) == os.path.normcase(os.path.realpath(SRC)):
            return dest, -1                     # 已是同一个链接
        raise SystemExit(f'已存在指向别处的链接: {dest} -> {cur}\n如需重建，先删除它')
    if os.path.exists(dest):
        raise SystemExit(
            f'目标已存在且不是链接: {dest}\n'
            f'先移走或删除它（例如市场安装版），再执行 --link'
        )
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    os.symlink(SRC, dest, target_is_directory=True)
    return dest, 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--to', help='目标技能根目录，例如 ~/.qoder/skills')
    ap.add_argument('--targets', choices=['one', 'all'], default='one',
                    help='all = 同时装到 WorkBuddy / Qoder / .agents')
    ap.add_argument('--link', action='store_true',
                    help='建符号链接而不是复制（开发用；Windows 需开发者模式或管理员）')
    args = ap.parse_args()

    targets = list(HOMES.values()) if args.targets == 'all' else [args.to or HOMES['workbuddy']]
    for t in targets:
        if args.link:
            dest, n = link(t)
            print(f'[LINK] {dest}  ->  {SRC}' if n == 0 else f'[SKIP] {dest} 已指向本仓库')
        else:
            dest, n = sync(t)
            print(f'[OK] {n} 个文件 -> {dest}')


if __name__ == '__main__':
    sys.exit(main())
