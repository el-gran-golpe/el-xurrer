import re


def replace_prompt_placeholders(
    prompt: str, cache: dict[str, str], accept_unfilled: bool = False
) -> str:
    """
    Replace all `{placeholder}` patterns in the prompt string with values from the cache.

    - If `accept_unfilled` is False (default), all placeholders must be present in the cache.
      Raises AssertionError if any are missing.
    - If `accept_unfilled` is True, only replaces placeholders that exist in the cache;
      leaves others unchanged.

    Args:
        prompt: The prompt string with `{placeholder}` patterns.
        cache: Dictionary mapping placeholder names to their replacement values.
        accept_unfilled: If True, allows placeholders to remain if not in cache.

    Returns:
        The prompt string with placeholders replaced as appropriate.
    """
    placeholders = re.findall(r"{(\w+)}", prompt)
    for placeholder in placeholders:
        if placeholder in cache:
            prompt = prompt.replace(f"{{{placeholder}}}", str(cache[placeholder]))
        elif not accept_unfilled:
            raise AssertionError(
                f"Placeholder '{{{placeholder}}}' not found in cache for prompt: {prompt}"
            )
        # else: leave the placeholder as-is if accept_unfilled is True
    return prompt
