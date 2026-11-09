import {makeLogin, redeemCode} from './auth.js';
import {SupportConversation, supportDetails} from './support.js';

const el = id => document.getElementById(id);
let config, session, products = [], cart = new Map(), orderAttempt;
const supportConversation=new SupportConversation();
const money = value => new Intl.NumberFormat('en-US', {style:'currency',currency:'USD'}).format(Number(value));
const cents = value => Math.round(Number(value) * 100);
function node(tag, text, className) {
  const item = document.createElement(tag);
  if (text !== undefined) item.textContent = text;
  if (className) item.className = className;
  return item;
}
function notice(message, error = false) {
  el('notice').textContent = message; el('notice').classList.toggle('error', error); el('notice').hidden = false;
}
function authenticated() { return session && session.expires > Date.now() + 5000; }
function clearPrivateState() {
  session=null;el('auth-button').textContent='Sign in';orderAttempt=undefined;supportConversation.reset();
  el('support-answer').replaceChildren();el('support-facts').replaceChildren();el('support-facts').hidden=true;
  el('escalate-support').hidden=true;el('order-id').value='';el('support-message').value='';el('support-product').value='';
  el('support-mode').textContent='Sign in to chat. A support ticket is created only when you request one.';
  el('tickets').replaceChildren();el('orders').replaceChildren(node('p','Sign in to see your orders and their latest status.','muted'));
  el('notice').textContent='';el('notice').hidden=true;
}
async function api(path, {method='GET', body, privateRequest=false, headers={}} = {}) {
  if (!config) throw new Error('The store is not connected yet. Please try again later.');
  if (privateRequest && !authenticated()) { clearPrivateState(); throw new Error('Please sign in to continue.'); }
  const requestSession=privateRequest?session:null;
  const requestHeaders = {'Accept':'application/json', ...headers};
  if (body) requestHeaders['Content-Type'] = 'application/json';
  if (privateRequest) requestHeaders.Authorization = `Bearer ${session.accessToken}`;
  const response = await fetch(`${config.apiBaseUrl}${path}`, {method, headers:requestHeaders, body:body ? JSON.stringify(body) : undefined, cache:'no-store', credentials:'omit'});
  const data = await response.json().catch(() => ({}));
  if (privateRequest && response.status===401) { clearPrivateState();throw new Error('Please sign in to continue.'); }
  // A request started before sign-out/another 401 must not restore old account
  // data after the private view and conversation have been cleared.
  if(privateRequest && session!==requestSession)throw new Error('Your sign-in session changed. Please try again.');
  if (!response.ok) throw new Error(data.error || `The request could not be completed (${response.status}).`);
  return data;
}
function renderProducts() {
  const term = el('search').value.trim().toLowerCase();
  const visible = products.filter(p => `${p.name} ${p.description}`.toLowerCase().includes(term));
  el('products').replaceChildren();
  if (!visible.length) { el('products').append(node('p', 'No essentials found. Try another search.', 'muted')); return; }
  for (const product of visible) {
    const card = node('article', undefined, 'product-card');
    const art = node('div', product.name.toLowerCase().includes('battery') ? '▰' : product.name.toLowerCase().includes('phone') ? '▯' : '⌘', 'product-art');
    art.setAttribute('aria-hidden', 'true');
    card.append(art, node('p','EVERYDAY ESSENTIALS','product-category'), node('h3',product.name), node('p',product.description,'product-description'));
    const bottom = node('div', undefined, 'product-bottom');
    const price = node('span',money(product.price),'product-price');
    price.append(node('span',product.stock > 0 ? `${product.stock} available` : 'Out of stock','stock'));
    const add = node('button','Add to bag +','add-button'); add.type = 'button'; add.disabled = product.stock < 1;
    add.addEventListener('click', () => {
      const quantity = (cart.get(product.id) || 0) + 1;
      if (quantity > Math.min(product.stock, 20)) return notice('You have reached the available quantity for this product.');
      cart.set(product.id,quantity); orderAttempt = undefined; renderCart();
    });
    bottom.append(price,add); card.append(bottom); el('products').append(card);
  }
}
function renderCart() {
  const list = el('cart-items'); list.replaceChildren(); let total = 0, count = 0;
  for (const [id, quantity] of cart) {
    const product = products.find(p => p.id === id); if (!product) continue;
    count += quantity; total += cents(product.price) * quantity;
    const row = node('div',undefined,'cart-item'), info = node('div');
    info.append(node('span',`${product.name} × ${quantity}`),node('strong',money(cents(product.price)*quantity/100)));
    const remove = node('button','Remove','text-button'); remove.type='button'; remove.addEventListener('click',()=>{cart.delete(id);orderAttempt=undefined;renderCart();});
    row.append(info,remove);list.append(row);
  }
  if (!count) list.append(node('p','Good things start here. Add an essential to your bag.','muted'));
  el('cart-count').textContent = `${count} ${count === 1 ? 'item' : 'items'}`;
  el('cart-total').textContent = money(total/100); el('checkout').disabled = !count;
}
async function loadProducts() {
  products = (await api('/api/products')).products; renderProducts();
  const selected=el('support-product').value;
  el('support-product').replaceChildren(node('option','Choose a product (optional)'));
  el('support-product').firstElementChild.value='';
  for(const product of products){const option=node('option',product.name);option.value=product.id;el('support-product').append(option);}
  el('support-product').value=selected;
}
async function loadOrders() {
  const data = await api('/api/orders',{privateRequest:true}); el('orders').replaceChildren();
  if (!data.orders.length) el('orders').append(node('p','Your next great find is waiting. No orders yet.','muted'));
  for (const order of data.orders) {
    const row=node('div',undefined,'order-row'), info=node('div');
    info.append(node('strong',order.id),node('br'),node('small',new Date(order.created_at).toLocaleString()));
    const help=node('button','Ask about this order','text-button');help.type='button';help.addEventListener('click',()=>{el('order-id').value=order.id;el('support').scrollIntoView({behavior:'smooth'});el('support-message').focus();});
    row.append(info,node('span',order.status,'status'),node('strong',money(order.total)),help);el('orders').append(row);
  }
}
el('search').addEventListener('input',renderProducts);
el('auth-button').addEventListener('click',async()=>{
  try {
    if (!config) throw new Error('Sign-in is not connected yet.');
    if (authenticated()) {
      clearPrivateState();cart.clear();renderCart();
      const url=new URL('/logout',config.cognitoDomain);url.search=new URLSearchParams({client_id:config.clientId,logout_uri:config.redirectUri});location.assign(url.href);
    } else location.assign(await makeLogin(config));
  } catch(error) {notice(error.message,true);}
});
el('checkout').addEventListener('click',async()=>{
  const button=el('checkout');button.disabled=true;
  try {
    const items=[...cart].map(([product_id,quantity])=>({product_id,quantity}));
    orderAttempt ||= crypto.randomUUID(); // Retain on ambiguous network failures; customer retry is idempotent.
    const data=await api('/api/orders',{method:'POST',privateRequest:true,headers:{'Idempotency-Key':orderAttempt},body:{items}});
    cart.clear();orderAttempt=undefined;renderCart();notice(`Order ${data.order.id} received. Your total is ${money(data.order.total)}. No payment was collected.`);
    await Promise.all([loadProducts(),loadOrders()]);
  } catch(error) {notice(error.message,true);} finally {button.disabled=cart.size===0;}
});
el('refresh-orders').addEventListener('click',()=>loadOrders().catch(error=>notice(error.message,true)));
function appendSupportMessage(role,text) {
  const message=node('div',undefined,`support-message ${role==='user'?'support-user':'support-assistant'}`);
  message.append(node('strong',role==='user'?'You':'AnyCo support'),node('p',text));
  el('support-answer').append(message);
  while(el('support-answer').children.length>12)el('support-answer').firstElementChild.remove();
}
function showSupportDetails(data) {
  const details=el('support-facts');details.replaceChildren();
  for(const line of supportDetails(data))details.append(node('p',line));
  details.hidden=!details.children.length;
  el('escalate-support').hidden=Boolean(data.ticket);
  el('support-mode').textContent=data.ticket?'Your ticket has been saved for the support team.':data.ai_available?'You are speaking with our AI assistant. You can request a support ticket at any time.':'AI assistance is unavailable. You can still request a support ticket.';
}
function supportBusy(busy) { el('send-support').disabled=busy;el('escalate-support').disabled=busy; }
el('support-form').addEventListener('submit',async event=>{
  event.preventDefault();supportBusy(true);
  try {
    const request=supportConversation.prepareMessage({message:el('support-message').value,orderId:el('order-id').value,productId:el('support-product').value});
    const data=await api('/api/support',{method:'POST',privateRequest:true,body:request.body,headers:{'Idempotency-Key':request.key}});
    supportConversation.acceptMessage(request,data);
    appendSupportMessage('user',request.body.message);appendSupportMessage('assistant',data.answer);showSupportDetails(data);
    el('support-message').value='';
  } catch(error) {notice(error.message,true);} finally {supportBusy(false);}
});
el('escalate-support').addEventListener('click',async()=>{
  supportBusy(true);
  try {
    const request=supportConversation.prepareEscalation();
    const data=await api('/api/support',{method:'POST',privateRequest:true,body:request.body,headers:{'Idempotency-Key':request.key}});
    supportConversation.acceptEscalation(request,data);appendSupportMessage('assistant',data.answer);showSupportDetails(data);
  } catch(error) {notice(error.message,true);} finally {supportBusy(false);}
});
el('refresh-tickets').addEventListener('click',async()=>{
  try {
    const data=await api('/api/support/tickets',{privateRequest:true});el('tickets').replaceChildren();
    if(!data.tickets.length)el('tickets').append(node('p','No support tickets yet.','muted'));
    for(const ticket of data.tickets){const row=node('div',undefined,'ticket-row');row.append(node('span',`${ticket.id}\n${ticket.message}`),node('span',ticket.status,'status'));el('tickets').append(row);}
  } catch(error) {notice(error.message,true);}
});
async function start() {
  try {
    const response=await fetch('./config.json',{cache:'no-store'});if(!response.ok)throw new Error('This store is awaiting its deployment configuration. Shopping will be available after setup.');
    config=await response.json();
    for(const key of ['apiBaseUrl','cognitoDomain','redirectUri'])if(new URL(config[key]).protocol!=='https:')throw new Error('The store requires a secure HTTPS configuration.');
    config.apiBaseUrl=config.apiBaseUrl.replace(/\/$/,'');
    const params=new URLSearchParams(location.search);
    // Remove the authorization code from history before network calls or UI rendering.
    if(params.has('code')||params.has('error'))history.replaceState(null,'',location.pathname+location.hash);
    if(params.has('error'))throw new Error('Sign-in was canceled or unavailable. Please try again.');
    if(params.has('code')){session=await redeemCode(config,params.get('code'),params.get('state'));el('auth-button').textContent='Sign out';notice('You are signed in. Welcome to AnyCo.');}
    await loadProducts();if(authenticated())await loadOrders();
  } catch(error) {el('products').replaceChildren(node('p','Our essentials will be here soon.','muted'));notice(error.message,true);}
}
start();
