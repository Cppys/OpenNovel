import asyncio
from claude_agent_sdk import query, ResultMessage, AssistantMessage, ClaudeAgentOptions


async def main():
    async for message in query(
                prompt="请用中文介绍一下你自己。",
                options=ClaudeAgentOptions(
                    system_prompt="你是一个简洁的助手，只用一句话回答。",
                    model="claude-sonnet-4-6",
                    max_turns=1,
                )):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if hasattr(block, "text"):
                    print(block.text, end="", flush=True)
        elif isinstance(message, ResultMessage):
            print(f"\n\n--- 完成 ---")
            print(f"结果: {message.result}")
            print(f"费用: ${message.total_cost_usd:.4f}")


asyncio.run(main())
