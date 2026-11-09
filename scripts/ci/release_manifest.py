"""검사한 이미지를 게시하고 배포 선언을 main에 기록합니다."""
import argparse
import gzip
import json
import os
from pathlib import Path
import re
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).parent))
from changed_services import select, SERVICES, diff_paths
from update_image_tags import update, ENVIRONMENT, IMAGES, REGISTRY
MANIFEST=Path('app/msa/kustomization.yaml')
RELEASE=Path('deploy/release.json')
def run(*args):
    return subprocess.check_output(args,text=True,encoding="utf-8").strip()
def pin(text, service, sha, digest):
    if not re.fullmatch(r'sha256:[a-f0-9]{64}',digest): raise ValueError('Invalid digest')
    text=update(text,[service],sha)
    pattern=r'(^  - name: '+re.escape(REGISTRY+'/'+IMAGES[service])+r'\n    newTag: [^\n]+)(?:\n    digest: [^\n]+)?'
    text,count=re.subn(pattern,lambda m:m[1]+'\n    digest: '+digest,text,flags=re.M)
    if count!=1: raise ValueError('Missing image')
    return text
def validate(base):
    if not RELEASE.exists(): return
    data=json.loads(RELEASE.read_text(encoding='utf-8'))
    if data.get('intent') not in ('release','rollback'): raise ValueError('Invalid release intent')
    text=MANIFEST.read_text(encoding='utf-8')
    for service,item in data['images'].items():
        if service not in SERVICES or not re.fullmatch(r'[a-f0-9]{40}',item['source']): raise ValueError('Invalid source')
        if not re.fullmatch(r'sha256:[a-f0-9]{64}',item['digest']): raise ValueError('Invalid image digest')
        if pin(text,service,item['source'],item['digest'])!=text: raise ValueError('Release/image mismatch')
    # 배포 선언만 바뀌면 해당 소스가 빌드 이후 바뀌었는지 검사합니다.
    if not base or set(base)=={'0'}: return
    paths=diff_paths(base,'HEAD')
    if 'deploy/release.json' in paths and not select(paths) and data['intent']=='release':
        for service in data.get('updatedServices',[]):
            if service in select(diff_paths(data['images'][service]['source'],base)):
                raise ValueError('Source changed after build; rebuild release')
def publish():
    services=json.loads(os.environ['SERVICES_JSON']);sha=os.environ['GITHUB_SHA']
    data=json.loads(RELEASE.read_text(encoding='utf-8')) if RELEASE.exists() else {'images':{}}
    text=MANIFEST.read_text(encoding='utf-8')
    for service in services:
        if service not in SERVICES: raise ValueError('Invalid service')
        # Actions artifact는 지정한 서비스 디렉터리만 읽고, 검사한 docker save 산출물을 그대로 게시한다.
        with gzip.open(Path('images')/('image-'+service)/'image.tar.gz','rb') as source, open('image.tar','wb') as target:
            import shutil;shutil.copyfileobj(source,target)
        subprocess.run(['docker','load','-i','image.tar'],check=True)
        repo=IMAGES[service];image=f'{REGISTRY}/{repo}:{sha}'
        subprocess.run(['docker','tag','local-check:'+service,image],check=True)
        subprocess.run(['docker','push',image],check=True)
        raw=run('aws','ecr','batch-get-image','--region',ENVIRONMENT['region'],'--repository-name',repo,'--image-ids','imageTag='+sha,'--output','json')
        result=json.loads(raw)
        if result.get('failures') or len(result['images'])!=1: raise ValueError('ECR image lookup failed')
        digest=result['images'][0]['imageId']['imageDigest']
        text=pin(text,service,sha,digest);data['images'][service]={'source':sha,'digest':digest}
    baselines = data.pop('buildBaselines', {})
    remaining = {service: base for service, base in baselines.items() if service not in services}
    if remaining:
        data['buildBaselines'] = remaining
    data.pop('rollbackFrom', None)
    data.update(intent='release',updatedServices=services,runId=os.environ['GITHUB_RUN_ID'])
    RELEASE.parent.mkdir(exist_ok=True);RELEASE.write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')
    MANIFEST.write_text(text,encoding='utf-8')
def deploy():
    source = os.environ['GITHUB_SHA']
    remote = run('git', 'ls-remote', 'origin', 'refs/heads/main').split()
    if not remote or remote[0] != source or run('git', 'rev-parse', 'HEAD') != source:
        raise ValueError('Main changed since the build; rerun from current main')
    validate('')
    run('git', 'config', 'user.name', 'github-actions[bot]')
    run('git', 'config', 'user.email', '41898282+github-actions[bot]@users.noreply.github.com')
    run('git', 'add', str(MANIFEST), str(RELEASE))
    run('git', 'commit', '-m', 'Deploy tested images from ' + source, '--', str(MANIFEST), str(RELEASE))
    # A competing main update rejects this ordinary fast-forward push.
    run('git', 'push', 'origin', 'HEAD:refs/heads/main')
    with Path(os.environ['GITHUB_OUTPUT']).open('a', encoding='utf-8') as output:
        output.write('revision=' + run('git', 'rev-parse', 'HEAD') + '\n')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=['publish','deploy','validate']);parser.add_argument('--base',default='');args=parser.parse_args()
    {'publish':publish,'deploy':deploy,'validate':lambda:validate(args.base)}[args.command]()
