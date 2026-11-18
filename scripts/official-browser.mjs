// Ordinary public Chrome navigation for empty HTTP responses. No stealth,
// proxies, credentials, fingerprint overrides or challenge interaction.
import {chromium} from 'playwright';
import readline from 'node:readline';
const hosts=new Set(['rfef.es','resultados.rfef.es','www.ffcm.es','www.rfcylf.es','www.frfutbol.com']);
let browser;const pages=new Map();
async function read(value){
  const u=new URL(value);
  if(u.protocol!=='https:'||!hosts.has(u.hostname)||u.username||u.password||u.port||u.hash||u.href.length>700||!['/es/resultados','/pnfg/NPcd/NFG_VisCalendario_Vis','/pnfg/NPcd/NFG_CmpJornada','/pnfg/NPcd/NFG_CmpPartido','/pnfg/NPcd/NFG_VisEquipos','/pnfg/NPcd/NFG_LstEquipos','/pnfg/NPcd/NFG_VisCompeticiones_Equipo','/pnfg/NPcd/NFG_VisCompeticiones_Grupo'].includes(u.pathname))throw Error('Fuente fuera de la consulta pública permitida');
  browser ||= await chromium.launch({channel:'chrome',headless:true});
  let page=pages.get(u.hostname);
  if(!page){page=await browser.newPage();pages.set(u.hostname,page);}
  const response=await page.goto(u.href,{waitUntil:'domcontentloaded',timeout:40000});
  if(!response||response.status()>=400||new URL(page.url()).hostname!==u.hostname||page.url().includes('/NLogin'))throw Error('La fuente no permite completar la consulta pública');
  if(/challenge|access denied|forbidden/i.test(await page.title()))throw Error('La fuente solicita una verificación');
  const html=await page.content();
  if(Buffer.byteLength(html)>8000000||!/<h[2345]\b/i.test(html))throw Error('La fuente no entrega datos deportivos verificables');
  return html;
}
try{
  for await(const line of readline.createInterface({input:process.stdin,crlfDelay:Infinity})){
    try{const input=JSON.parse(line);process.stdout.write(JSON.stringify({html:await read(input.url)})+'\n');}
    catch{process.stdout.write(JSON.stringify({error:'La fuente no permite completar la consulta pública de navegador'})+'\n');}
  }
}finally{await browser?.close();}
