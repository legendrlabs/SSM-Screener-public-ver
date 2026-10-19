"""Resolve tested commits without moving or republishing existing versions."""
import importlib.util
from pathlib import Path
import subprocess

import pytest


def resolve(*args, **kwargs):
    assert importlib.util.find_spec('scripts.release_identity') is not None, 'release identity resolver missing'
    from scripts.release_identity import resolve_release_identity
    return resolve_release_identity(*args, **kwargs)


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], text=True).strip()


@pytest.fixture
def repo(tmp_path):
    root=tmp_path/'repo';root.mkdir()
    git(root,'init','-b','main')
    (root/'pyproject.toml').write_text('[project]\nversion="1.1.5"\n')
    git(root,'add','.')
    git(root,'-c','user.name=Test','-c','user.email=test@example.invalid','commit','-m','initial')
    return root


def identity(root, **overrides):
    kwargs=dict(event_name='push', ref_type='branch', ref_name='main', input_tag='', source_commit=git(root,'rev-parse','HEAD'))
    kwargs.update(overrides)
    return resolve(root, **kwargs)


def test_new_main_version_uses_tested_immutable_commit(repo):
    value=identity(repo)
    assert value=={'tag':'v1.1.5','source_commit':git(repo,'rev-parse','HEAD'),'skip_publish':False}


def test_unchanged_version_does_not_move_old_tag(repo):
    git(repo,'tag','v1.1.5')
    (repo/'new.txt').write_text('later dependencies')
    git(repo,'add','.')
    git(repo,'-c','user.name=Test','-c','user.email=test@example.invalid','commit','-m','later')
    before=git(repo,'rev-parse','v1.1.5')
    assert identity(repo)['skip_publish'] is True
    assert git(repo,'rev-parse','v1.1.5')==before


def test_same_commit_can_retry_interrupted_draft_publication(repo):
    git(repo,'tag','v1.1.5')
    assert identity(repo)['skip_publish'] is False


def test_manual_release_requires_existing_matching_tag(repo):
    with pytest.raises(ValueError,match='existing tag'):
        identity(repo,event_name='workflow_dispatch',input_tag='v1.1.5')
    git(repo,'tag','v1.1.5')
    assert identity(repo,event_name='workflow_dispatch',input_tag='v1.1.5')['skip_publish'] is False


def test_tag_and_project_version_must_agree(repo):
    with pytest.raises(ValueError,match='version'):
        identity(repo,event_name='workflow_dispatch',input_tag='v1.1.6')


def test_feature_branch_cannot_publish(repo):
    with pytest.raises(ValueError,match='main'):
        identity(repo,ref_name='feature')


def test_untrusted_tag_is_not_executed(repo):
    with pytest.raises(ValueError,match='version'):
        identity(repo,event_name='workflow_dispatch',input_tag='v1.1.5; touch NEVER')
    assert not (repo/'NEVER').exists()


def test_module_version_matches_installed_project():
    import ssm
    from ssm.release_policy import project_version
    assert ssm.__version__==project_version(Path(__file__).resolve().parents[1])
