import logging
from litellm import completion, ModelResponse

logger = logging.getLogger(__name__)


def call_llm_with_tools(
    model: str,
    messages: list,
    tools: list,
    max_tokens: int = 1024,
    **kwargs,
) -> ModelResponse:
    """
    LiteLLM call with tool use. Returns the full ModelResponse so callers can
    read tool_calls off the assistant message.

    Use this instead of importing litellm directly when tool/function calling
    is needed — keeps all LLM calls routed through this module.
    """
    response = completion(
        model=model,
        messages=messages,
        tools=tools,
        max_tokens=max_tokens,
        **kwargs,
    )
    input_tokens = response.usage.prompt_tokens if response.usage else 0
    output_tokens = response.usage.completion_tokens if response.usage else 0
    logger.debug("call_llm_with_tools model=%s in=%d out=%d", model, input_tokens, output_tokens)
    return response


def call_llm(
    model: str,
    messages: list,
    system: str | None = None,
    max_tokens: int = 4096,
    **kwargs,
) -> tuple[str, int, int]:
    """
    Route an LLM call to any provider via LiteLLM.

    Returns: (content, input_tokens, output_tokens)

    Model string format:
      - OpenRouter:       openrouter/anthropic/claude-sonnet-4-6
      - Anthropic direct: anthropic/claude-sonnet-4-6
      - Moonshot direct:  moonshot/moonshot-v1-8k
      - OpenAI direct:    openai/gpt-4o

    API key env vars (set in .env — only the one matching your provider needed):
      OPENROUTER_API_KEY, ANTHROPIC_API_KEY, MOONSHOT_API_KEY, OPENAI_API_KEY
    """
    if system:
        messages = [{"role": "system", "content": system}] + messages

    response = completion(
        model=model,
        messages=messages,
        max_tokens=max_tokens,
        **kwargs,
    )

    content = response.choices[0].message.content
    input_tokens = response.usage.prompt_tokens if response.usage else 0
    output_tokens = response.usage.completion_tokens if response.usage else 0

    logger.debug("call_llm model=%s in=%d out=%d", model, input_tokens, output_tokens)
    return content, input_tokens, output_tokens
