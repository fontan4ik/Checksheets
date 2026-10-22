const fs=require('fs'),vm=require('vm'),axios=require('axios');
const c=vm.createContext({});vm.runInContext(fs.readFileSync('Shared_Настройки.js','utf8')+';this.creds={OZON_CLIENT_ID:OZON_CLIENT_ID(),OZON_API_KEY:OZON_API_KEY(),WB_TOKEN:WB_API_TOKEN()};',c);
const telegram=fs.readFileSync('Shared_Telegram.js','utf8');const token=telegram.match(/: '([^']+)'/)[1];const chat=telegram.match(/: '(-\d+)'/)[1];
fs.writeFileSync('ntc-cloud/Shared_Credentials.js','/* Bootstrap into Script Properties; excluded from Git. */\nconst NTC_BOOTSTRAP = '+JSON.stringify({...c.creds,TELEGRAM_TOKEN:token,TELEGRAM_CHAT:chat})+';\n',{mode:0o600});
(async()=>{
 const results=await Promise.allSettled([
 axios.post('https://api-seller.ozon.ru/v2/warehouse/list',{limit:200,offset:0},{headers:{'Client-Id':c.creds.OZON_CLIENT_ID,'Api-Key':c.creds.OZON_API_KEY},timeout:20000}),
 axios.get('https://marketplace-api.wildberries.ru/api/v3/warehouses',{headers:{Authorization:c.creds.WB_TOKEN},timeout:20000})]);
 results.forEach((r,i)=>{if(r.status==='rejected')console.log(['Ozon','WB'][i],'HTTP',r.reason.response?.status||r.reason.code);else{const d=r.value.data;const list=Array.isArray(d)?d:d.warehouses||d.result;console.log(['Ozon','WB'][i],list.map(w=>({id:w.id||w.warehouse_id,name:w.name})));}});
})().catch(e=>console.log(e.code));
