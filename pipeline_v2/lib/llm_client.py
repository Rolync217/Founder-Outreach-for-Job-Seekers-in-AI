import logging
from litellm import completion

logger = logging.getLogger(__name__)


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
