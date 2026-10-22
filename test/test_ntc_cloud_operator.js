'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const context = vm.createContext({});
vm.runInContext(fs.readFileSync('ntc-cloud/Shared_Operator.js', 'utf8'), context);
const headers = ['МОДЕЛЬ','КОЛИЧЕСТВО, ШТ','','МОДЕЛЬ','ПОСТАВКА, ШТ','','МОДЕЛЬ','СПИСАНИЕ, ШТ'];
const legacy = ['МОДЕЛЬ','КОЛИЧЕСТВО, ШТ','ПОСТАВКА, ШТ','СПИСАНИЕ, ШТ','','','',''];
function sheet(rows, h = headers) {
  const data = Array.from({length: 6}, () => Array(8).fill('')); data[5] = h; data.push(...rows);
  return {getLastRow: () => data.length, getRange: (row, col, height, width) => ({getValues: () => data.slice(row - 1, row - 1 + height).map(r => Array.from({length: width}, (_, i) => r[col - 1 + i] ?? '')), getDisplayValues: () => data.slice(row - 1, row - 1 + height).map(r => Array.from({length: width}, (_, i) => String(r[col - 1 + i] ?? '')))})};
}
const read = s => JSON.parse(JSON.stringify(context.ntcReadOperatorMovements_(s)));
let actual = read(sheet([['A',10,'','B',3,'','A',2],['B',4,'','A',1,'','B','']]));
assert.deepEqual(actual.supplies, [{model:'B', quantity:3,type:'supply'},{model:'A',quantity:1,type:'supply'}]);
assert.deepEqual(actual.writeoffs, [{model:'A',quantity:2,type:'writeoff'}]);
assert.deepEqual(actual.extras, [{row:7,col:5,modelCol:4,model:'B',quantity:3},{row:8,col:5,modelCol:4,model:'A',quantity:1},{row:7,col:8,modelCol:7,model:'A',quantity:2}]);
actual = read(sheet([[123,10,4,2]], legacy));
assert.equal(actual.supplies[0].model,'123'); assert.equal(actual.writeoffs[0].quantity,2); assert.equal(actual.extras[0].modelCol,1);
assert.throws(() => read(sheet([['A',1,'','A',2,'','A',''],['B',2,'','A','','','B','']])), /повторяется/);
assert.throws(() => read(sheet([['A',1,'','',2]])), /Не указана модель/);
[true,0,-1,1.5,'x',Number.MAX_SAFE_INTEGER+1].forEach(q => assert.throws(() => read(sheet([['A',1,'','A',q]])), /целое количество/));
assert.throws(() => read(sheet([], ['МОДЕЛЬ','broken'])), /заголовки/);
assert.deepEqual(read(sheet([])), {supplies:[],writeoffs:[],extras:[]});
const drafts = (s,l,m,t) => JSON.parse(JSON.stringify(context.ntcOperatorDrafts_(s,l,m,t)));
assert.deepEqual(drafts(sheet([['A',10,4,2],['NEW',20,9,'']],legacy),'legacy',['A','B'],'supply'),[['A',4],['NEW',9],['B','']]);
assert.deepEqual(drafts(sheet([['A',10,'','B',7,'','A',4],['B',20,'','A',9,'','B',2]]),'three',['A','B','C'],'supply'),[['B',7],['A',9],['C','']]);
assert.deepEqual(drafts(sheet([['A',10,'','',8]]),'three',['A'],'supply'),[['',8],['A','']]);
assert.deepEqual(drafts(sheet([]),'empty',['A'],'writeoff'),[['A','']]);
console.log('NTC operator: independent tables, legacy migration, drafts and input validation passed');
// Formatting must move existing drafts safely and be repeatable after independent reordering.
class OperatorSheet {
  constructor() { this.data = Array.from({length: 16}, () => Array(11).fill('')); this.data[5] = legacy.slice(); this.data[6] = ['A',10,4,2]; this.data[7] = ['B',20,9,'']; this.images = []; }
  getLastRow() { let n = this.data.length; while (n && this.data[n-1].every(v => v === '' || v == null)) n--; return n; }
  getRange(row,col,height,width) {
    if (typeof row === 'string') { const m = /^([A-Z]+)(\d+):([A-Z]+)(\d+)$/.exec(row); assert(m,row); col = m[1].charCodeAt(0)-64; width = m[3].charCodeAt(0)-63-col; row = Number(m[2]); height = Number(m[4])-row+1; }
    height ??= 1; width ??= 1;
    while(this.data.length < row+height-1) this.data.push(Array(11).fill(''));
    const range = {getValues:()=>this.data.slice(row-1,row+height-1).map(r=>Array.from({length:width},(_,i)=>r[col-1+i]??'')), getDisplayValues:()=>range.getValues().map(r=>r.map(String)),setValues:v=>{v.forEach((r,i)=>r.forEach((x,j)=>{this.data[row-1+i][col-1+j]=x;}));return range;}, setValue:v=>{this.data[row-1][col-1]=v;return range;}, clearContent:()=>{for(let i=0;i<height;i++)for(let j=0;j<width;j++)this.data[row-1+i][col-1+j]='';return range;}};
    ['clearDataValidations','setFontFamily','merge','breakApart','setFontSize','setFontWeight','setBackground','setFontColor','setWrap','setNumberFormat','setDataValidation','setBorder'].forEach(name=>range[name]=()=>range);
    return range;
  }
  getImages() { return this.images; }
  insertImage() { const image={getAltTextTitle:()=>image.title||''}; ['setAnchorCell','setAnchorCellXOffset','setAnchorCellYOffset','setAltTextDescription','assignScript','setWidth','setHeight'].forEach(n=>image[n]=()=>image); image.setAltTextTitle=v=>{image.title=v;return image;};this.images.push(image);return image; }
}
['setFrozenRows','setHiddenGridlines','setRowHeight','setColumnWidth'].forEach(n=>OperatorSheet.prototype[n]=()=>{});
const validation={requireFormulaSatisfied:()=>validation,setAllowInvalid:()=>validation,build:()=>({})};
context.SpreadsheetApp={newDataValidation:()=>validation,BorderStyle:{SOLID:'solid'}};
context.Utilities={newBlob:()=>({}),base64Decode:()=>[]}; context.NTC_BUTTONS=[{handler:'ntcSupply',label:'Supply',png:''}];
vm.runInContext(fs.readFileSync('ntc-cloud/Flow_НТЦ__Установка.js','utf8'),context);
const operator = new OperatorSheet();
context.ntcFormatOperator_(operator,{stock_by_model:{A:10,B:20}});
assert.deepEqual(operator.data[6].slice(0,8),['A',10,'','A',4,'','A',2]);
assert.deepEqual(operator.data[7].slice(0,8),['B',20,'','B',9,'','B','']);
operator.data[6][3]='B'; operator.data[7][3]='A';
context.ntcFormatOperator_(operator,{stock_by_model:{A:11,B:20,C:0}});
assert.deepEqual(operator.data[6].slice(3,5),['B',4]);
assert.deepEqual(operator.data[7].slice(3,5),['A',9]);
assert.deepEqual(operator.data[8].slice(3,5),['C','']);
assert.equal(operator.images.length,1);
console.log('NTC operator formatting: legacy drafts preserved, independent order retained, controls reused');
