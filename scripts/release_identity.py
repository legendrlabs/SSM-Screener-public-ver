"""Derive a versioned release from a tested main commit or an existing tag."""
from pathlib import Path
import os
import re
import subprocess

from ssm.release_policy import project_version, SOURCE_COMMIT_RE


def _git(root, *args):
    return subprocess.run(['git','-C',str(root),*args],capture_output=True,text=True)


def resolve_release_identity(root, *, event_name, ref_type, ref_name, input_tag, source_commit):
    root=Path(root)
    expected=f'v{project_version(root)}'
    if not re.fullmatch(r'v\d+\.\d+\.\d+',expected):
        raise ValueError('release project version must be a stable semantic version')
    if not SOURCE_COMMIT_RE.fullmatch(source_commit):
        raise ValueError('source commit must be a full commit SHA')
    head=_git(root,'rev-parse','HEAD^{commit}')
    if head.returncode or head.stdout.strip()!=source_commit:
        raise ValueError('source commit differs from tested checkout')
    main_push=event_name=='push' and ref_type=='branch' and ref_name=='main'
    if event_name=='workflow_dispatch':tag=input_tag
    elif main_push:tag=expected
    elif event_name=='push' and ref_type=='tag':tag=ref_name
    else:raise ValueError('only main, tag pushes or manual tag releases may publish')
    if tag!=expected:raise ValueError('release tag and project version differ')
    existing=_git(root,'rev-parse','--verify',f'refs/tags/{tag}^{{commit}}')
    if existing.returncode:
        if not main_push:raise ValueError('manual/tag releases require an existing tag')
        skip=False
    elif existing.stdout.strip()!=source_commit:
        if not main_push:raise ValueError('release tag points to a different source commit')
        skip=True
    else:skip=False
    return {'tag':tag,'source_commit':source_commit,'skip_publish':skip}


def main():
    root=Path(__file__).resolve().parents[1]
    identity=resolve_release_identity(root,event_name=os.environ['GITHUB_EVENT_NAME'],
        ref_type=os.environ['GITHUB_REF_TYPE'],ref_name=os.environ['GITHUB_REF_NAME'],
        input_tag=os.environ.get('INPUT_TAG',''),source_commit=_git(root,'rev-parse','HEAD^{commit}').stdout.strip())
    if identity['skip_publish']:
        print('Version already tagged at another commit; preserving existing release.')
    with open(os.environ['GITHUB_OUTPUT'],'a',encoding='utf-8') as handle:
        for key,value in identity.items():
            handle.write(f'{key}={str(value).lower() if isinstance(value,bool) else value}\n')


if __name__=='__main__':main()
