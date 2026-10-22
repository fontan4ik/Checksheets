const fs=require('fs'),vm=require('vm'),assert=require('assert');
const dir='ntc-cloud';const files=fs.readdirSync(dir).filter(n=>n.endsWith('.js')&&n!=='Shared_Credentials.js');const names=new Map();
for(const name of files){const code=fs.readFileSync(dir+'/'+name,'utf8');for(const m of code.matchAll(/^function\s+(\w+)\s*\(/gm)){assert(!names.has(m[1]),`Duplicate global function ${m[1]}: ${names.get(m[1])} and ${name}`);names.set(m[1],name);}}
const bundle=files.map(n=>fs.readFileSync(dir+'/'+n,'utf8')).join('\n');const context=vm.createContext({});vm.runInContext(bundle,context);
assert.equal(context.ntcCatalogPhotoUrl_('=IMAGE("https://example.com/photo.jpg")',{}),'https://example.com/photo.jpg');
assert.equal(context.ntcCatalogPhotoUrl_('',{}),'');
assert.equal(context.ntcPhotoUrl_('https://example.com/photo.jpg'),'https://example.com/photo.jpg');
console.log('NTC combined GAS bundle: unique globals, catalog images, API photo validator pass');
