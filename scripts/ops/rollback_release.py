"""검증한 이전 이미지 선언을 새 main 커밋으로 복구합니다."""
import argparse
import json
import re
import subprocess
from pathlib import Path
import sys
import uuid
from check_environment import check
from lab_common import CONFIG, Runner, check_identity

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'ci'))
from release_manifest import pin, validate, MANIFEST, RELEASE, IMAGES


def git(*args):
    return subprocess.check_output(['git', *args], text=True, encoding='utf-8').strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--release-commit', required=True)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    sha = args.release_commit
    if not re.fullmatch(r'[a-f0-9]{40}', sha):
        raise ValueError('Full Git commit SHA required')
    if git('status', '--porcelain'):
        raise ValueError('Commit/stash local changes first')
    check()
    repository = CONFIG['repository']
    urls = {f'https://github.com/{repository}', f'git@github.com:{repository}',
            f'ssh://git@github.com/{repository}'}
    for options in ((), ('--push',)):
        remotes = git('remote', 'get-url', '--all', *options, 'origin').splitlines()
        if len(remotes) != 1 or remotes[0].removesuffix('.git') not in urls:
            raise ValueError('Origin must point only to the configured repository')
    git('fetch', 'origin', 'refs/heads/main')
    head = git('rev-parse', 'FETCH_HEAD')
    git('merge-base', '--is-ancestor', sha, head)
    previous = json.loads(git('show', sha + ':deploy/release.json'))
    images = previous.get('images', {})
    if set(images) != set(IMAGES):
        raise ValueError('Full five-service release is required')
    text = git('show', head + ':' + MANIFEST.as_posix()) + '\n'
    for service, item in images.items():
        if not re.fullmatch(r'[a-f0-9]{40}', item['source']):
            raise ValueError('Invalid image source: ' + service)
        text = pin(text, service, item['source'], item['digest'])
    print(f'Rollback target: {repository} main ({head}) -> images from {sha}')
    for service, item in images.items():
        print(f"  {service}: {item['digest']}")
    if not args.execute:
        print('PREVIEW ONLY. Use --execute to validate ECR and push the rollback commit.')
        return

    runner = Runner()
    check_identity(runner)
    for service, item in images.items():
        result = runner.aws('ecr', 'batch-get-image', '--repository-name', IMAGES[service],
                            '--image-ids', 'imageDigest=' + item['digest'])
        if result.get('failures') or len(result.get('images', [])) != 1:
            raise ValueError('Previous image unavailable: ' + service)
    branch = 'rollback/' + sha[:12] + '-' + uuid.uuid4().hex[:8]
    git('switch', '-c', branch, head)
    MANIFEST.write_text(text, encoding='utf-8')
    previous.update(intent='rollback', rollbackFrom=sha, updatedServices=list(images),
                    buildBaselines=dict.fromkeys(images, head))
    RELEASE.write_text(json.dumps(previous, indent=2) + '\n', encoding='utf-8')
    validate('')
    git('add', MANIFEST.as_posix(), RELEASE.as_posix())
    git('commit', '-m', 'Roll back images to release ' + sha)
    git('push', 'origin', 'HEAD:refs/heads/main')
    print('Rollback pushed: ' + git('rev-parse', 'HEAD'))


if __name__ == '__main__':
    main()
