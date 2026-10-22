const fs=require('fs'),{google}=require('googleapis');
(async()=>{
 const t=JSON.parse(fs.readFileSync(process.env.HOME+'/.clasprc.json')).tokens['ntc-vladimir'];const auth=new google.auth.OAuth2(t.client_id,t.client_secret);auth.setCredentials(t);
 const user=(await google.oauth2({version:'v2',auth}).userinfo.get()).data.email; if(user!=='vladimir.romanovich.grebennikov@gmail.com')throw Error('Wrong owner');
 const created=await google.script({version:'v1',auth}).projects.create({requestBody:{title:'Склад НТЦ · облачная автоматизация',parentId:'1i35SfWZljNR63GEkPuwgU2zVSU_Y2CWoxcRK-LcpjUo'}});
 const p=created.data;fs.writeFileSync('ntc-cloud/.clasp.json',JSON.stringify({scriptId:p.scriptId,rootDir:'.'},null,2));fs.writeFileSync('test/ntc_cloud_project.json',JSON.stringify(p,null,2));console.log({owner:user,scriptId:p.scriptId,parentId:p.parentId});
})().catch(e=>{console.log('create failed',e.code,e.message);process.exitCode=1});
