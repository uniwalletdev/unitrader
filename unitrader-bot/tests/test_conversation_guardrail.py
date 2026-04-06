import pytest


class _ClaudeTextBlock:
    def __init__(self, text: str):
        self.text = text


class _ClaudeResp:
    def __init__(self, text: str):
        self.content = [_ClaudeTextBlock(text)]


@pytest.mark.asyncio
async def test_conversation_guardrail_retries_on_access_limitation_copy():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from src.agents.core.conversation_agent import ConversationAgent
    from src.agents.shared_memory import SharedContext
    from config import settings

    settings.anthropic_api_key = "test"

    # Prevent DB access for User lookup
    class _FakeSession:
        async def execute(self, *_args, **_kwargs):
            return type(
                "_Res",
                (),
                {
                    "scalar_one_or_none": lambda _self: SimpleNamespace(
                        id="user-001",
                        email="u@example.com",
                        ai_name="Zeus",
                    )
                },
            )()

    class _FakeAsyncSessionLocal:
        def __call__(self):
            return self

        async def __aenter__(self):
            return _FakeSession()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    import src.agents.core.conversation_agent as ca
    ca.AsyncSessionLocal = _FakeAsyncSessionLocal()

    agent = ConversationAgent("user-001")

    # 1st call violates prompt; 2nd call should be used.
    agent._claude = type(
        "_Claude",
        (),
        {
            "messages": type(
                "_Msgs",
                (),
                {
                    "create": AsyncMock(
                        side_effect=[
                            _ClaudeResp(
                                "As an AI assistant, I do not have access to your balance."
                            ),
                            _ClaudeResp("Your balance is $123.45 across connected exchanges."),
                        ]
                    )
                },
            )()
        },
    )()

    # Avoid DB writes/reads (conversation_agent imports these symbols directly)
    ca.get_recent_messages_for_claude = AsyncMock(return_value=[])
    ca.save_conversation = AsyncMock(return_value=type("_Conv", (), {"id": "c1"})())

    ctx = SharedContext.default("user-001")
    ctx.ai_name = "Zeus"
    ctx.trading_accounts = [{"exchange": "binance", "is_paper": True, "balance_usd": 123.45}]

    out = await agent.respond(
        "what's my balance",
        shared_context=ctx,
        channel="web_app",
    )

    assert "do not have access" not in out["response"].lower()
    assert "123.45" in out["response"]

