from headroom_agent_mcp.config import HeadroomAgentConfig, LLMProfile
from headroom_agent_mcp.llm import OpenAICompatibleLLMClient


def test_llm_client_prefers_headroom_proxy_when_enabled() -> None:
    config = HeadroomAgentConfig(
        headroom_proxy_url="http://127.0.0.1:8788",
        llm_profiles={
            "openrouter": LLMProfile(
                model="openrouter/deepseek/deepseek-chat",
                base_url="https://openrouter.ai/api/v1",
                api_key_env="OPENROUTER_API_KEY",
                use_headroom_proxy=True,
            )
        },
    )

    client = OpenAICompatibleLLMClient(config=config)
    resolved = client.resolve_endpoint("openrouter")

    assert resolved == "http://127.0.0.1:8788/v1"
