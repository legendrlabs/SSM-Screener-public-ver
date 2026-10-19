// Publish a tested immutable commit. Draft releases hide incomplete manifests.
const fs = require('node:fs');
const crypto = require('node:crypto');

module.exports = async function publishRelease({github,context,tag,sourceCommit,manifestPath}) {
  const {owner,repo}=context.repo;
  const data=fs.readFileSync(manifestPath);
  const manifest=JSON.parse(data.toString('utf8'));
  if (manifest.tag!==tag || manifest.source_commit!==sourceCommit || tag!==`v${manifest.version}`) {
    throw new Error('manifest identity differs from tested release');
  }
  const digest='sha256:'+crypto.createHash('sha256').update(data).digest('hex');
  let ref;
  try {ref=(await github.rest.git.getRef({owner,repo,ref:`tags/${tag}`})).data.object;}
  catch(error) {
    if(error.status!==404)throw error;
    await github.rest.git.createRef({owner,repo,ref:`refs/tags/${tag}`,sha:sourceCommit});
    ref={type:'commit',sha:sourceCommit};
  }
  for(let depth=0;ref.type==='tag' && depth<5;depth++) {
    ref=(await github.rest.git.getTag({owner,repo,tag_sha:ref.sha})).data.object;
  }
  if(ref.type!=='commit' || ref.sha!==sourceCommit)throw new Error('release tag commit differs from tested commit');

  let release;
  try {release=(await github.rest.repos.getReleaseByTag({owner,repo,tag})).data;}
  catch(error) {
    if(error.status!==404)throw error;
    release=(await github.rest.repos.createRelease({owner,repo,tag_name:tag,target_commitish:sourceCommit,
      name:`SSM ${tag}`,draft:true,generate_release_notes:true})).data;
  }
  if(release.tag_name!==tag)throw new Error('existing release tag differs');
  const assets=await github.paginate(github.rest.repos.listReleaseAssets,{owner,repo,release_id:release.id,per_page:100});
  const asset=assets.find(item=>item.name==='release.json');
  if(asset) {
    if(asset.digest!==digest)throw new Error('existing release manifest differs or has no verifiable digest; refusing replacement');
  } else {
    if(!release.draft)throw new Error('published release has no manifest; refusing to mutate it');
    await github.rest.repos.uploadReleaseAsset({owner,repo,release_id:release.id,name:'release.json',
      headers:{'content-type':'application/json','content-length':data.length},data});
  }
  if(release.draft) {
    release=(await github.rest.repos.updateRelease({owner,repo,release_id:release.id,draft:false,make_latest:'true'})).data;
  }
  return release.html_url;
};
