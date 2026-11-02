from langchain_core.messages import HumanMessage, ToolMessage

from my_agent.llm import llm
from my_agent.tools import query_user_orders


llm_with_tools = llm.bind_tools([query_user_orders])


def run_agent(question: str):
    # 1. 用户消息
    messages = [HumanMessage(content=question)]

    # 2. 第一次调用：让 LLM 决定是否使用工具
    response = llm_with_tools.invoke(messages)
    messages.append(response)

    # 3. 执行模型请求的工具
    for tool_call in response.tool_calls:
        if tool_call["name"] != query_user_orders.name:
            raise ValueError("不支持的工具")

        result = query_user_orders.invoke(tool_call["args"])

        # 4. 将工具执行结果交还给 LLM
        messages.append(
            ToolMessage(
                content=str(result),
                tool_call_id=tool_call["id"],
            )
        )

    # 5. 第二次调用：让 LLM 根据工具结果回答
    if response.tool_calls:
        final_response = llm_with_tools.invoke(messages)
    else:
        final_response = response

    return final_response.content


if __name__ == "__main__":
    answer = run_agent("帮我查询用户 u1001 最近有哪些订单")
    print("Agent 回复：", answer)