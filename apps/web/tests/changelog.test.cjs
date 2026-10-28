const {test,after}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {execFileSync}=require('node:child_process');
const temporary=fs.mkdtempSync(path.join(os.tmpdir(),'pengucoach-changelog-'));
execFileSync(process.execPath,[require.resolve('typescript/bin/tsc'),'lib/changelog.ts','--module','commonjs','--target','ES2022','--skipLibCheck','--outDir',temporary],{cwd:path.resolve(__dirname,'..')});
const {changelogSections,changelogLink}=require(path.join(temporary,'changelog.js'));
after(()=>fs.rmSync(temporary,{recursive:true,force:true}));
test('preserves repository order, release wording and version identifiers',()=>{
 const sections=changelogSections('# Changelog\r\n\r\n## Unreleased\r\n- Coming soon\r\n## [v0.1.0-alpha.72](https://example.com)\r\n- **New** notes\r\n### Details\r\nText\r\n## 0.1.0-alpha.71\r\n- Older');
 assert.equal(sections.length,3);assert.equal(sections[0].version,null);assert.equal(sections[1].version,'0.1.0-alpha.72');
 assert.equal(sections[1].title,'[v0.1.0-alpha.72](https://example.com)');assert.match(sections[1].content,/### Details\nText/);
 assert.deepEqual(sections.map(x=>x.id),['release-0','release-1','release-2']);
});
test('does not turn code samples into extra release sections',()=>{
 assert.equal(changelogSections('# Changelog\n## 1.0.0\n```md\n## example\n```\n## 0.9.0').length,2);
 assert.deepEqual(changelogSections(''),[]);
});
test('resolves repository-relative links and rejects executable protocols',()=>{
 assert.equal(changelogLink('docs/AI_STUDIO.md'),'https://github.com/Borderlane-HA/PenguCoach/blob/main/docs/AI_STUDIO.md');
 assert.equal(changelogLink('https://example.com/notes'),'https://example.com/notes');
 for(const value of ['javascript:alert(1)','data:text/html,test','vbscript:msgbox(1)','file:///etc/passwd','https://user:secret@example.com','java\nscript:alert(1)','https:\\evil.example',''])assert.equal(changelogLink(value),null,value);
});
