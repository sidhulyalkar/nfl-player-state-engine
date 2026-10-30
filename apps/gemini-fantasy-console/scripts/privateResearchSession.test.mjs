import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {mkdtemp,writeFile,rm,symlink} from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {inspectPrivateResearchSession} from './privateResearchSession.mjs';

async function fixture(){
  const dir=await mkdtemp(path.join(os.tmpdir(),'playlab-local-test-'));
  const filename='2017090700-938-research-replay.json';
  const bytes=JSON.stringify({fixture_only:true});
  const sha=createHash('sha256').update(bytes).digest('hex');
  const manifest={
    schema_version:1,data_mode:'HISTORICAL_RESEARCH_BATCH_MANIFEST',
    game_id:'2017090700',source_file_sha256:'a'.repeat(64),
    source_identities:{
      tracking:{file:'tracking_gameId_2017090700.csv',identity_match:true,
        sha256:'a'.repeat(64),git_blob_sha1:'b'.repeat(40),bytes:25},
      games:{file:'games.csv',identity_match:true,
        sha256:'c'.repeat(64),git_blob_sha1:'d'.repeat(40),bytes:20},
      plays:{file:'plays.csv',identity_match:true,
        sha256:'e'.repeat(64),git_blob_sha1:'f'.repeat(40),bytes:30},
    },
    qualification_status:'NONCANONICAL_FIXTURE_ONLY',
    source_video_alignment_verified:false,model_training_authorized:false,
    commercial_reuse_authorized:false,license_declaration:'CI synthetic fixture only',
    play_count:1,plays:[{play_id:'938',file:filename,sha256:sha,
      recorded_frames:2,source_rows:3,missing_source_frames:1,
      omitted_position_rows:0,possession_team:'KC',
      metadata_provenance:'NONCANONICAL_TEST_FIXTURE'}],
  };
  await writeFile(path.join(dir,filename),bytes);
  await writeFile(path.join(dir,'manifest.json'),JSON.stringify(manifest));
  return {dir,filename,manifest};
}

test('local preflight checks exact bytes and produces position-free report',async()=>{
  const {dir}=await fixture();
  try{
    const out=await inspectPrivateResearchSession(dir,{
      expectedPlayCount:1,licenseIdentifier:'CI synthetic fixture only',
    });
    assert.equal(out.play_count,1);
    assert.equal(out.plays[0].recorded_frames,2);
    assert.equal(out.model_training_authorized,false);
    assert.equal(out.original_source_bytes_authenticity_confirmed_by_this_preflight,false);
    assert.equal(out.plays[0].missing_source_frames,1);
    assert.equal(out.source_video_alignment_verified,false);
    assert.equal(JSON.stringify(out).includes('fixture_only'),false);
  }finally{await rm(dir,{recursive:true,force:true});}
});
test('mutated replay bytes cannot pass hash preflight',async()=>{
  const {dir,filename}=await fixture();
  try{
    await writeFile(path.join(dir,filename),'{"fixture_only":false}');
    await assert.rejects(inspectPrivateResearchSession(dir),/SHA-256 mismatch/);
  }finally{await rm(dir,{recursive:true,force:true});}
});
test('reject missing, duplicate, unexpected and traversing replay paths',async()=>{
  const {dir,manifest}=await fixture();
  try{
    const bad={...manifest,plays:[{...manifest.plays[0],file:'../outside.json'}]};
    await writeFile(path.join(dir,'manifest.json'),JSON.stringify(bad));
    await assert.rejects(inspectPrivateResearchSession(dir),/Unsafe/);
    await writeFile(path.join(dir,'manifest.json'),JSON.stringify(manifest));
    await writeFile(path.join(dir,'other.json'),'{}');
    await assert.rejects(inspectPrivateResearchSession(dir),/Unexpected extra/);
  }finally{await rm(dir,{recursive:true,force:true});}
});
test('local preflight rejects forged rights, wrong license acknowledgement and symlinks',async()=>{
  const {dir,filename,manifest}=await fixture();
  try{
    const changed={...manifest,model_training_authorized:true};
    await writeFile(path.join(dir,'manifest.json'),JSON.stringify(changed));
    await assert.rejects(inspectPrivateResearchSession(dir),/Invalid local/);
    await writeFile(path.join(dir,'manifest.json'),JSON.stringify(manifest));
    await assert.rejects(inspectPrivateResearchSession(dir,{licenseIdentifier:'wrong'}),/Invalid local/);
    await rm(path.join(dir,filename));
    await symlink(path.join(dir,'manifest.json'),path.join(dir,filename));
    await assert.rejects(inspectPrivateResearchSession(dir),/symlinked/);
  }finally{await rm(dir,{recursive:true,force:true});}
});
test('preflight enforces expected count',async()=>{
  const {dir}=await fixture();
  try{await assert.rejects(inspectPrivateResearchSession(dir,{expectedPlayCount:12}),/count differs/);}
  finally{await rm(dir,{recursive:true,force:true});}
});

test('reject forged original tracking identity, missing source attestations and false official provenance',async()=>{
  const {dir,manifest}=await fixture();
  try{
    const hashDrift=structuredClone(manifest);
    hashDrift.source_identities.tracking.sha256='9'.repeat(64);
    await writeFile(path.join(dir,'manifest.json'),JSON.stringify(hashDrift));
    await assert.rejects(inspectPrivateResearchSession(dir),/Tracking source SHA-256 differs/);
    const missing=structuredClone(manifest);
    delete missing.source_identities.games;
    await writeFile(path.join(dir,'manifest.json'),JSON.stringify(missing));
    await assert.rejects(inspectPrivateResearchSession(dir),/Missing or malformed source-file identity/);
    const fakeOfficial=structuredClone(manifest);
    fakeOfficial.qualification_status='PINNED_SOURCE_AND_PLAY_METADATA_VIDEO_PENDING';
    await writeFile(path.join(dir,'manifest.json'),JSON.stringify(fakeOfficial));
    await assert.rejects(inspectPrivateResearchSession(dir),/Unsafe, duplicate or malformed replay/);
    const fakePositionQuality=structuredClone(manifest);
    fakePositionQuality.plays[0].omitted_position_rows=-1;
    await writeFile(path.join(dir,'manifest.json'),JSON.stringify(fakePositionQuality));
    await assert.rejects(inspectPrivateResearchSession(dir),/Unsafe, duplicate or malformed replay/);
    const fakeLicense=structuredClone(manifest);
    fakeLicense.license_declaration='x'.repeat(257);
    await writeFile(path.join(dir,'manifest.json'),JSON.stringify(fakeLicense));
    await assert.rejects(inspectPrivateResearchSession(dir),/Invalid local research manifest/);
  }finally{await rm(dir,{recursive:true,force:true});}
});
