"""Facts from existing product API; no new retrieval stack or guessed policies."""
from my_agent.shipping_workflow import latest_text,message
from my_agent.tools import query_product

def answer(state):
    result=state.get('intent_result') or {};product_id=result.get('product_id')
    if not product_id:return message('请提供商品编号（SKU），我会查询现有商品资料。',pending_intent={'intent':'product_qa'})
    outcome=query_product.invoke({'product_id':product_id})
    if not outcome['ok']:return message(outcome['error']['message'])
    data=outcome['data'];text=latest_text(state)
    policy=any(word in text for word in ['七天','无理由','政策','退货','保修','退款多久'])
    known_policy={k:v for k,v in data['attributes'].items() if any(w in k for w in ['售后','退货','保修','政策'])}
    if policy and not known_policy:
        return message('商品资料未提供相关售后政策，无法确认。资料来源：商品接口 '+product_id+'。',pending_intent=None)
    attrs=known_policy if policy else data['attributes']
    lines=[f"{data['title']}（{data['product_id']}）",data['description'],f"价格：{data['price']}；库存：{data['stock_status']}"]
    lines.extend(f'{k}：{v}' for k,v in attrs.items())
    lines.append('资料来源：现有商品详情接口。未列出的属性无法确认。')
    return message('\n'.join(lines),pending_intent=None)
