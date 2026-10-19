const test = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const publishRelease = require('../scripts/publish_release.cjs');
const sha = 'a'.repeat(40);
const payload = Buffer.from(JSON.stringify({version:'1.1.5',tag:'v1.1.5',source_commit:sha})+'\n');
const digest = 'sha256:' + crypto.createHash('sha256').update(payload).digest('hex');
const missing = () => Object.assign(new Error('missing'), {status:404});

function fixture(options={}) {
  const dir=fs.mkdtempSync(path.join(os.tmpdir(),'ssm-release-'));
  const file=path.join(dir,'release.json');fs.writeFileSync(file,payload);
  const events=[];let release=options.release;let assets=options.assets || [];
  const github={rest:{git:{
    async getRef(){if(options.ref) return {data:{object:options.ref}};throw missing();},
    async createRef(args){assert.equal(args.sha,sha);events.push('tag');},
    async getTag(){return {data:{object:{type:'commit',sha}}};}
  },repos:{
    async getReleaseByTag(){if(release)return {data:release};throw missing();},
    async createRelease(args){assert.equal(args.draft,true);assert.equal(args.target_commitish,sha);events.push('draft');release={id:1,draft:true,tag_name:'v1.1.5',html_url:'https://example.invalid/release'};return {data:release};},
    async listReleaseAssets(){return {data:assets};},
    async uploadReleaseAsset(args){assert.equal(release.draft,true);assert.deepEqual(args.data,payload);events.push('upload');if(options.uploadFails)throw new Error('upload failed');assets=[{name:'release.json',digest}];},
    async updateRelease(args){assert.equal(assets[0].digest,digest);assert.equal(args.draft,false);events.push('publish');release.draft=false;return {data:release};}
  }},async paginate(fn,args){return (await fn(args)).data;}};
  return {github,context:{repo:{owner:'owner',repo:'repo'}},tag:'v1.1.5',sourceCommit:sha,manifestPath:file,events,cleanup(){fs.rmSync(dir,{recursive:true,force:true});}};
}

test('publishes only after tested tag and complete manifest upload',async()=>{
  const f=fixture();try {await publishRelease(f);assert.deepEqual(f.events,['tag','draft','upload','publish']);}finally{f.cleanup();}
});
test('conflicting tag never publishes another commit',async()=>{
  const f=fixture({ref:{type:'commit',sha:'b'.repeat(40)}});try {await assert.rejects(publishRelease(f),/commit/);assert.deepEqual(f.events,[]);}finally{f.cleanup();}
});
test('same published manifest is idempotent without replacement',async()=>{
  const f=fixture({ref:{type:'commit',sha},release:{id:1,draft:false,tag_name:'v1.1.5'},assets:[{name:'release.json',digest}]});
  try {await publishRelease(f);assert.deepEqual(f.events,[]);}finally{f.cleanup();}
});
test('conflicting published asset is never overwritten',async()=>{
  const f=fixture({ref:{type:'commit',sha},release:{id:1,draft:false,tag_name:'v1.1.5'},assets:[{name:'release.json',digest:'sha256:wrong'}]});
  try {await assert.rejects(publishRelease(f),/manifest/);assert.deepEqual(f.events,[]);}finally{f.cleanup();}
});
test('upload failure leaves draft unpublished',async()=>{
  const f=fixture({uploadFails:true});try {await assert.rejects(publishRelease(f),/upload failed/);assert.deepEqual(f.events,['tag','draft','upload']);}finally{f.cleanup();}
});
test('annotated tag resolves to its immutable source commit',async()=>{
  const f=fixture({ref:{type:'tag',sha:'c'.repeat(40)}});try {await publishRelease(f);assert.deepEqual(f.events,['draft','upload','publish']);}finally{f.cleanup();}
});
