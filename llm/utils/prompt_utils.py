import re


def replace_prompt_placeholders(
    prompt: str, cache: dict[str, str], accept_unfilled: bool = False
) -> str:
    placeholders = re.findall(r"{(\w+)}", prompt)
    for placeholder in placeholders:
        if placeholder in cache:
            prompt = prompt.replace(f"{{{placeholder}}}", str(cache[placeholder]))
        elif not accept_unfilled:
            raise AssertionError(
                f"Placeholder '{{{placeholder}}}' not found in cache for prompt: {prompt}"
            )
    return prompt
