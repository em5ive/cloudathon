// Optional local Chrome QA. API/config responses are intercepted fictional fixtures.
// This never verifies AWS, Cognito, CORS, database writes, or deployed TLS.
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {existsSync, mkdirSync, mkdtempSync, readFileSync, writeFileSync} from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const origin=process.argv[2] || 'http://127.0.0.1:8765';
assert.equal(new URL(origin).hostname,'127.0.0.1','Only the local preview server is supported');
const chrome=process.env.CHROME_PATH || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
assert.ok(existsSync(chrome),'Set CHROME_PATH to an installed Chrome executable');
mkdirSync(path.join(root,'.build'),{recursive:true});mkdirSync(path.join(root,'reports'),{recursive:true});
const profile=mkdtempSync(path.join(root,'.build','browser-qa-'));
const browser=spawn(chrome,['--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check','--remote-debugging-port=0',`--user-data-dir=${profile}`,'about:blank'],{windowsHide:true,stdio:'ignore'});
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
let socket;
try {
  const activePort=path.join(profile,'DevToolsActivePort');
  for(let count=0;!existsSync(activePort);count++){if(count>100)throw new Error('Chrome did not become ready');await pause(100);}
  const port=readFileSync(activePort,'utf8').split('\n')[0];
  const targets=await(await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  socket=new WebSocket(targets.find(target=>target.type==='page').webSocketDebuggerUrl);
  await new Promise((resolve,reject)=>{socket.addEventListener('open',resolve,{once:true});socket.addEventListener('error',reject,{once:true});});
  let next=0;const pending=new Map(),listeners=[];
  socket.addEventListener('message',event=>{
    const message=JSON.parse(event.data);
    if(message.id){const request=pending.get(message.id);if(!request)return;clearTimeout(request.timer);pending.delete(message.id);message.error?request.reject(new Error(message.error.message)):request.resolve(message.result);}
    else for(const listener of listeners)listener(message);
  });
  const call=(method,params={})=>new Promise((resolve,reject)=>{const id=++next;const timer=setTimeout(()=>{pending.delete(id);reject(new Error(`${method} timed out`));},15000);pending.set(id,{resolve,reject,timer});socket.send(JSON.stringify({id,method,params}));});
  const evaluate=async expression=>{const result=await call('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(result.exceptionDetails)throw new Error(result.exceptionDetails.text);return result.result.value;};
  const products=[...readFileSync(path.join(root,'database/seed.sql'),'utf8').matchAll(/\('([0-9-]+)', '([^']+)', '([^']+)', ([0-9.]+)\)/g)].map(([,id,name,description,price])=>({id,name,description,price,currency:'USD',stock:50}));
  assert.equal(products.length,6);
  const errors=[],supportRequests=[];let failSupportOnce=true;
  listeners.push(message=>{
    if(message.method==='Runtime.exceptionThrown')errors.push(message.params.exceptionDetails.text);
    if(message.method==='Fetch.requestPaused'){
      const {requestId,request}=message.params;
      let data,responseCode=200;
      const route=new URL(request.url).pathname;
      if(request.method==='OPTIONS')responseCode=204;
      else if(route==='/config.json')data={apiBaseUrl:'https://mock.execute-api.us-west-2.amazonaws.com',cognitoDomain:'https://mock.auth.us-west-2.amazoncognito.com',clientId:'offline-fixture',redirectUri:'https://mock.cloudfront.net/'};
      else if(route==='/oauth2/token')data={access_token:'offline-browser-fixture-token',expires_in:900};
      else if(route==='/api/orders')data={orders:[]};
      else if(route==='/api/support/tickets'){responseCode=401;data={error:'Fixture session expired.'};}
      else if(route==='/api/support'){
        const body=JSON.parse(request.postData);supportRequests.push({body,key:request.headers['Idempotency-Key'] || request.headers['idempotency-key']});
        if(!body.escalate && failSupportOnce){failSupportOnce=false;responseCode=503;data={error:'Fixture transient failure.'};}
        else data={answer:body.escalate?'Your support ticket has been created.':'<img src=x onerror=alert(1)> Try checking the charging cable.',order:null,product:products[0],facts_as_of:'2026-11-07T18:00:00Z',ticket:body.escalate?{id:'offline-ticket',status:'open'}:null,ai_available:!body.escalate};
      }else data={products};
      call('Fetch.fulfillRequest',{requestId,responseCode,responseHeaders:[{name:'Content-Type',value:'application/json'},{name:'Access-Control-Allow-Origin',value:origin},{name:'Access-Control-Allow-Headers',value:'authorization,content-type,idempotency-key'},{name:'Access-Control-Allow-Methods',value:'GET,POST,OPTIONS'}],body:data?Buffer.from(JSON.stringify(data)).toString('base64'):''}).catch(error=>errors.push(error.message));
    }
  });
  await call('Page.enable');await call('Runtime.enable');
  await call('Fetch.enable',{patterns:[{urlPattern:'*/config.json'},{urlPattern:'https://mock.execute-api.us-west-2.amazonaws.com/*'},{urlPattern:'https://mock.auth.us-west-2.amazoncognito.com/*'}]});
  await call('Page.addScriptToEvaluateOnNewDocument',{source:"if(location.search.includes('offline-code'))sessionStorage.setItem('anyco.pkce',JSON.stringify({verifier:'offline-fixture-verifier-used-only-for-intercepted-local-qa',state:'offline-state',created:Date.now()}));"});
  const evidence=[];
  for(const [label,width,height] of [['desktop',1440,1100],['mobile',390,900]]){
    await call('Emulation.setDeviceMetricsOverride',{width,height,deviceScaleFactor:1,mobile:label==='mobile'});
    await call('Page.navigate',{url:origin});
    for(let count=0;;count++){if(await evaluate("document.querySelectorAll('.product-card').length===6"))break;if(count>100)throw new Error(`Product fixture did not render: ${await evaluate("document.getElementById('notice')?.textContent")}`);await pause(100);}
    const layout=await evaluate('({viewport:innerWidth,scroll:document.documentElement.scrollWidth})');
    assert.ok(layout.scroll<=layout.viewport,`${label} horizontal overflow: ${JSON.stringify(layout)}`);
    await evaluate("document.querySelector('.add-button').click()");
    assert.equal(await evaluate("document.getElementById('cart-count').textContent"),'1 item');
    await evaluate("document.getElementById('checkout').click()");
    for(let count=0;!(await evaluate("document.getElementById('notice').textContent.includes('sign in')"));count++){if(count>30)throw new Error('Anonymous checkout was not blocked');await pause(50);}
    await evaluate("document.getElementById('search').value='recharge aa';document.getElementById('search').dispatchEvent(new Event('input'))");
    assert.equal(await evaluate("document.querySelectorAll('.product-card').length"),1);
    await evaluate("document.getElementById('search').value='';document.getElementById('search').dispatchEvent(new Event('input'))");
    // The token and all support responses below are intercepted fixtures. This
    // exercises UI behavior without asserting real Cognito/API authorization.
    await call('Page.navigate',{url:`${origin}/?code=offline-code&state=offline-state`});
    for(let count=0;!(await evaluate("document.getElementById('auth-button')?.textContent==='Sign out' && document.querySelectorAll('.product-card').length===6"));count++){if(count>100)throw new Error('Local sign-in fixture did not complete');await pause(100);}
    supportRequests.length=0;failSupportOnce=true;
    await evaluate("document.getElementById('support-message').value='My speaker will not turn on.';document.getElementById('support-product').selectedIndex=1;document.getElementById('support-form').requestSubmit()");
    for(let count=0;!(await evaluate("document.getElementById('notice').textContent==='Fixture transient failure.' && !document.getElementById('send-support').disabled"));count++){if(count>100)throw new Error('Transient fixture failure was not handled');await pause(50);}
    await evaluate("document.getElementById('support-form').requestSubmit()");
    for(let count=0;!(await evaluate("document.getElementById('support-answer').children.length===2 && !document.getElementById('send-support').disabled"));count++){if(count>100)throw new Error('Normal chat response did not render');await pause(50);}
    assert.equal(supportRequests.length,2);assert.equal(supportRequests[0].key,supportRequests[1].key,'UI retry changed idempotency key');assert.equal(supportRequests[1].body.escalate,false);
    assert.equal(await evaluate("document.querySelector('#support-answer img')===null && document.getElementById('support-answer').textContent.includes('<img src=x')"),true,'Model text must never become executable markup');
    assert.equal(await evaluate("document.getElementById('support-facts').textContent.includes('Information checked:') && !document.getElementById('support-facts').textContent.includes('Ticket')"),true,'Chat facts should render without a ticket');
    await evaluate("document.getElementById('escalate-support').click()");
    for(let count=0;!(await evaluate("document.getElementById('support-facts').textContent.includes('Ticket offline-ticket')"));count++){if(count>100)throw new Error('Explicit ticket result did not render');await pause(50);}
    assert.equal(supportRequests.length,3);assert.equal(supportRequests[2].body.escalate,true);assert.notEqual(supportRequests[2].key,supportRequests[1].key);
    assert.equal(await evaluate("document.getElementById('escalate-support').hidden"),true);
    await evaluate("document.getElementById('support').scrollIntoView()");
    const supportLayout=await evaluate('({viewport:innerWidth,scroll:document.documentElement.scrollWidth})');assert.ok(supportLayout.scroll<=supportLayout.viewport,`${label} support overflow`);
    const screenshot=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});
    writeFileSync(path.join(root,'reports',`frontend-${label}-fixtures.png`),Buffer.from(screenshot.data,'base64'));
    await evaluate("document.getElementById('refresh-tickets').click()");
    for(let count=0;!(await evaluate("document.getElementById('auth-button').textContent==='Sign in' && document.getElementById('support-answer').children.length===0"));count++){if(count>100)throw new Error('Expired session did not clear private transcript');await pause(50);}
    assert.equal(await evaluate("document.getElementById('support-facts').hidden && document.getElementById('support-facts').textContent==='' && document.getElementById('escalate-support').hidden && document.getElementById('support-product').value===''"),true);
    evidence.push({viewport:label,width,status:'PASS',checks:['six fictional products','no horizontal overflow','cart add','anonymous checkout blocked','search filter','normal chat without ticket','explicit escalation','stable retry key','generated prose rendered as text','401 clears private conversation and facts'],mocked:true});
  }
  assert.deepEqual(errors,[],'Browser runtime errors');
  writeFileSync(path.join(root,'reports','frontend-browser.json'),JSON.stringify({evidence,limits:'Intercepted local fixture responses only. AWS/Cognito/CORS/TLS/database are not tested.'},null,2)+'\n');
  console.log('PASS: desktop/mobile catalog and support fixtures, safe model text, explicit escalation, stable retries and browser runtime checks.');
} finally {
  if(socket)socket.close();browser.kill();
}
