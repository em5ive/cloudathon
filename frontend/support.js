// Support request state stays in memory. Authentication is still enforced by
// API Gateway and the backend; browser history is only untrusted chat context.
export function boundedHistory(messages) {
  const result = messages.filter(item => ['user', 'assistant'].includes(item.role) && typeof item.content === 'string' && item.content.trim())
    .map(item => ({role:item.role,content:item.content.slice(0,2000)})).slice(-6);
  // A byte bound also keeps multi-byte text below the API's overall body limit.
  while (result.reduce((length,item)=>length+new TextEncoder().encode(item.content).byteLength,0)>6000) result.shift();
  return result;
}

function contextKey(body) { return JSON.stringify([body.order_id || '',body.product_id || '']); }
const copy = value => JSON.parse(JSON.stringify(value));

export class SupportConversation {
  constructor(randomKey = () => crypto.randomUUID()) {
    this.randomKey=randomKey;this.history=[];this.context='';this.unresolved=new Map();this.lastExchange=null;
  }
  attempt(body) {
    const payload=JSON.stringify(body);
    // Keep every uncertain request, even if another question is attempted
    // before its outcome is known. Losing an escalation key can duplicate it.
    if(!this.unresolved.has(payload))this.unresolved.set(payload,{payload,key:this.randomKey(),body:copy(body)});
    return copy(this.unresolved.get(payload));
  }
  prepareMessage({message,orderId='',productId=''}) {
    const body={message:message.trim(),escalate:false};
    if(!body.message)throw new Error('Please enter a support message.');
    if(orderId.trim())body.order_id=orderId.trim();
    if(productId)body.product_id=productId;
    body.history=contextKey(body)===this.context?boundedHistory(this.history):[];
    return this.attempt(body);
  }
  acceptMessage(request,response) {
    this.history=boundedHistory([...request.body.history,{role:'user',content:request.body.message},{role:'assistant',content:response.answer}]);
    this.context=contextKey(request.body);this.lastExchange={body:copy(request.body),response:copy(response)};this.unresolved.delete(request.payload);
  }
  prepareEscalation() {
    if(!this.lastExchange)throw new Error('Send a support message before requesting a ticket.');
    if(this.lastExchange.response.ticket)throw new Error('A support ticket already exists for this request.');
    // An escalation is a distinct, explicit request. Never reuse the chat key.
    return this.attempt({...copy(this.lastExchange.body),escalate:true});
  }
  acceptEscalation(request,response) {
    if(this.lastExchange)this.lastExchange.response=copy(response);
    this.unresolved.delete(request.payload);
  }
  reset() { this.history=[];this.context='';this.unresolved.clear();this.lastExchange=null; }
}

export function supportDetails(response) {
  // Keep database facts separate from generated prose. Render these strings
  // with textContent so product names and model output cannot become markup.
  const lines=[];
  if(response.order)lines.push(`Order ${response.order.id} · Status: ${response.order.status} · Total: ${response.order.total} ${response.order.currency}`);
  if(response.product)lines.push(`${response.product.name} · Price: ${response.product.price} ${response.product.currency} · Available: ${response.product.stock}`);
  if(lines.length && response.facts_as_of)lines.push(`Information checked: ${response.facts_as_of}`);
  if(response.ticket)lines.push(`Ticket ${response.ticket.id} · ${response.ticket.status}`);
  return lines;
}
