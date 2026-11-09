"""Prepare local release-demo sources. Never builds, pushes, deploys or calls AWS.

The intentionally faulty stage is opt-in and must never be the final release.
Use a clean Git worktree, review the diff, then use the normal reviewed CI path.
"""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = Path('app/msa/frontend/src')
REGRESSION = Path('app/msa/frontend/tests/product-navigation.test.cjs')
FILES = [p.relative_to(ROOT) for p in sorted((ROOT / SRC).glob('*.html'))] + [SRC / 'assets/app.js', SRC / 'assets/style.css', REGRESSION]
GOOD = 'return `/product-detail.html?id=${encodeURIComponent(productId)}`;'
BAD = 'return `/product-detail.html?productId=${encodeURIComponent(productId)}`;'


def prepare(stage, root=ROOT):
    backup = root / '.lab/release-demo/source'
    manifest = backup / 'manifest.json'
    if not manifest.exists():
        app = (root / SRC / 'assets/app.js').read_text(encoding='utf-8')
        if GOOD not in app or BAD in app:
            raise ValueError('Expected healthy test2 navigation; refuse to capture a faulty baseline')
        exists = {}
        for relative in FILES:
            source = root / relative
            exists[str(relative)] = source.exists()
            if source.exists():
                target = backup / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(source.read_bytes())
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(json.dumps(exists), encoding='utf-8')
    exists = json.loads(manifest.read_text(encoding='utf-8'))
    # Refuse edits made after staging, rather than silently discarding user work.
    state_path = backup.parent / 'stage.json'
    if state_path.exists():
        previous = json.loads(state_path.read_text(encoding='utf-8'))
        for relative, expected in previous['hashes'].items():
            p = root / relative
            actual = hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None
            if actual != expected:
                raise ValueError('Frontend changed since staging; preserve/review your edits before switching: ' + relative)
    for relative in FILES:
        target = root / relative
        if exists[str(relative)]:
            target.write_bytes((backup / relative).read_bytes())
        elif target.exists():
            target.unlink()
    app_path = root / SRC / 'assets/app.js'
    if stage == 'baseline':
        (root / SRC / 'index.html').write_text(
            (ROOT / 'scripts/demo/templates/baseline.html').read_text(encoding='utf-8'), encoding='utf-8')
    elif stage == 'fault':
        app = app_path.read_text(encoding='utf-8')
        if app.count(GOOD) != 1:
            raise ValueError('Navigation source no longer matches demo patch')
        app_path.write_text(app.replace(GOOD, BAD), encoding='utf-8')
    elif stage == 'final':
        (root / REGRESSION).parent.mkdir(parents=True, exist_ok=True)
        (root / REGRESSION).write_text(
            (ROOT / 'scripts/demo/templates/product-navigation.test.cjs').read_text(encoding='utf-8'), encoding='utf-8')
    else:
        raise ValueError('Unknown stage')
    if stage in ('baseline', 'fault'):
        # Distinct URLs prevent a cached app.js masking the deployed version.
        for relative in FILES:
            if relative.suffix == '.html':
                page = root / relative
                page.write_text(page.read_text(encoding='utf-8').replace('/assets/app.js?v=5', '/assets/app.js?v=demo-' + stage), encoding='utf-8')
    hashes = {str(p): hashlib.sha256((root / p).read_bytes()).hexdigest() if (root / p).exists() else None for p in FILES}
    state_path.write_text(json.dumps({'stage': stage, 'hashes': hashes}, indent=2), encoding='utf-8')
    print('LOCAL SOURCE ONLY:', stage)
    print('No AWS / Docker / Git mutation. Review git diff; publish only through approved CI.')
    if stage == 'fault':
        print('INTENTIONAL FAULT: product detail query mismatch. Isolated demonstration only; never final.')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('stage', choices=['baseline', 'fault', 'final'])
    p.add_argument('--write', action='store_true', help='Explicitly allow local frontend file changes')
    args = p.parse_args()
    if not args.write:
        p.error('No changes made. Add --write when ready to prepare this local stage.')
    prepare(args.stage)


if __name__ == '__main__':
    main()
