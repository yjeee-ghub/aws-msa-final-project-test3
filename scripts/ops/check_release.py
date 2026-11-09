"""배포 버전과 실제 읽기 API를 검사합니다. 배포/롤백/주문 데이터 생성은 하지 않습니다."""
import argparse
import json
from pathlib import Path
import subprocess
import io
import tarfile
import tempfile
import time
import urllib.request
from urllib.parse import urlparse

def read(*command):
    return json.loads(subprocess.check_output(command,text=True,encoding="utf-8",timeout=30))
def deployed(declarations,actual):
    for expected in declarations:
        item=next((d for d in actual['items'] if d['metadata']['name']==expected['metadata']['name']),None)
        if item is None:return False
        expected_images=[c['image'] for c in expected['spec']['template']['spec']['containers']]
        actual_images=[c['image'] for c in item['spec']['template']['spec']['containers']]
        status=item.get('status',{});replicas=item['spec'].get('replicas',1)
        if expected_images!=actual_images or status.get('observedGeneration',0)<item['metadata']['generation']:return False
        if status.get('updatedReplicas',0)!=replicas or status.get('availableReplicas',0)<replicas or status.get('replicas',0)!=replicas:return False
    return True
def http_checks(base):
    parsed=urlparse(base)
    if parsed.scheme!='https' or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('','/'):
        raise ValueError('HTTPS origin required')
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,*args,**kwargs):return None
    opener=urllib.request.build_opener(NoRedirect)
    for path in ('/','/product-service/product/list'):
        with opener.open(base.rstrip('/')+path,timeout=10) as result:
            body=result.read(2_000_001)
            if result.status!=200 or len(body)>2_000_000:raise ValueError('Invalid HTTP response')
            if path=='/' and b'<html' not in body.lower():raise ValueError('Missing HTML')
            if path!='/':
                if 'application/json' not in result.headers.get('Content-Type',''):raise ValueError('Missing JSON')
                data=json.loads(body)
                if not isinstance(data,list) or any(not isinstance(p,dict) or not all(k in p for k in ('id','name','price','stockQuantity')) for p in data):raise ValueError('Invalid product API contract')
def main():
    import yaml
    p=argparse.ArgumentParser();p.add_argument('--revision',required=True);p.add_argument('--url',default='https://server.aws-yjeee.com');p.add_argument('--timeout',type=int,default=600)
    p.add_argument('--manifest-ref',help='검증할 선언의 immutable Git SHA. 로컬 checkout을 수정하지 않습니다.')
    args=p.parse_args()
    if args.manifest_ref:
        import re
        if not re.fullmatch(r'[a-f0-9]{40}',args.manifest_ref):raise ValueError('Manifest ref must be an immutable commit')
        archive=subprocess.check_output(['git','archive',args.manifest_ref,'app/msa'],timeout=30)
        with tempfile.TemporaryDirectory(prefix='final-release-check-') as temporary:
            with tarfile.open(fileobj=io.BytesIO(archive)) as source:
                source.extractall(temporary,filter='data')
            rendered=subprocess.check_output(['kubectl','kustomize',str(Path(temporary)/'app/msa')],text=True,encoding='utf-8',timeout=30)
    else:
        rendered=subprocess.check_output(['kubectl','kustomize','app/msa'],text=True,encoding='utf-8',timeout=30)
    expected=[d for d in yaml.safe_load_all(rendered) if d and d.get('kind')=='Deployment']
    if len(expected)!=5:raise ValueError('Expected five application deployments')
    deadline=time.monotonic()+args.timeout
    while True:
        try:
            app=read('kubectl','get','application','final-apps','-n','argocd','-o','json')
            status=app.get('status',{});sync=status.get('sync',{})
            if sync.get('revision')!=args.revision or sync.get('status')!='Synced' or status.get('health',{}).get('status')!='Healthy':raise ValueError('Argo revision/health pending')
            if not deployed(expected,read('kubectl','get','deployments','-n','soldesk','-o','json')):raise ValueError('Deployment version/availability pending')
            http_checks(args.url);print('PASS: revision, images, availability, TLS, HTML, product API');return
        except Exception as error:
            # 임의 응답 본문/인증정보 대신 오류 종류만 출력한다.
            print('Waiting:',type(error).__name__)
            if time.monotonic()>=deadline:raise SystemExit('FAIL: deployment/function check timed out')
            time.sleep(10)
if __name__=='__main__':main()
