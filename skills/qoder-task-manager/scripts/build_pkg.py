#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""打包成两个市场上架用的 zip。

- -root：zip 根目录直接是 SKILL.md（部分市场要求此形态）
- -dir：单层目录 qoder-task-manager/，内含 SKILL.md（另一些市场要求此形态）

用法：python scripts/build_pkg.py [--out dist]
"""
import argparse
import os
import re
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # skills/<name>/
REPO = os.path.dirname(os.path.dirname(ROOT))                        # 仓库根
NAME = 'qoder-task-manager'
VERSION_FALLBACK = '1.7.0'
SCRIPT = os.path.join(ROOT, 'scripts', 'qoder_sessions.py')

FILES = ['SKILL.md', 'README.md', 'CHANGELOG.md', 'LICENSE', 'PUBLISHING.md']
DIRS = ['scripts', 'references', 'examples']
SKIP_DIRS = {'__pycache__', '.git', 'dist'}


def read_version():
    """版本号单一来源：主脚本的 VERSION 常量。

    只在读不到时才回退 VERSION_FALLBACK，避免三处版本号各自漂移。
    """
    try:
        with open(SCRIPT, encoding='utf-8') as f:
            text = f.read()
        m = re.search(r"^VERSION\s*=\s*'([^']+)'", text, re.M)
        if m:
            return m.group(1)
    except OSError:
        pass
    return VERSION_FALLBACK


VERSION = read_version()


def collect():
    items = []
    for f in FILES:
        p = os.path.join(ROOT, f)
        if not os.path.isfile(p):          # README/LICENSE 放在仓库根
            p = os.path.join(REPO, f)
        if os.path.isfile(p):
            items.append((p, f))
    for d in DIRS:
        base = os.path.join(ROOT, d)
        for cur, dirs, files in os.walk(base):
            dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
            for fn in files:
                if fn.endswith('.pyc') or fn == 'build_pkg.py':
                    continue
                p = os.path.join(cur, fn)
                items.append((p, os.path.relpath(p, ROOT).replace('\\', '/')))
    return items


def build(out_dir, prefix):
    items = collect()
    path = os.path.join(out_dir, f'{NAME}-{"root" if not prefix else "dir"}-{VERSION}.zip')
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        for p, rel in items:
            z.write(p, f'{prefix}{rel}' if prefix else rel)
    print(f'{os.path.basename(path)}  {os.path.getsize(path)/1024:.1f} KB  {len(items)} files')
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=os.path.join(REPO, 'dist'))
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    build(args.out, '')
    build(args.out, NAME + '/')
    print(f'-> {args.out}')


if __name__ == '__main__':
    main()
