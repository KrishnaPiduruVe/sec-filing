"""Extract readable answer text without changing the model or its factual content."""
import ast
import json
import re


def readable_answer(output: str) -> str:
    """Unwrap serialized provider content blocks; keep ordinary Markdown intact."""
    text = output.strip()
    if text.startswith(('[', '{')):
        value = None
        for decoder in (json.loads, ast.literal_eval):
            try:
                value = decoder(text)
                break
            except (ValueError, SyntaxError, TypeError, RecursionError):
                continue

        def extract(item):
            if isinstance(item, str):
                return item
            if isinstance(item, list):
                return '\n\n'.join(part for child in item if (part := extract(child)))
            if isinstance(item, dict):
                # Ignore signatures, reasoning, IDs, and other provider metadata.
                if item.get('type') in {'thinking', 'reasoning', 'reasoning_content'}:
                    return ''
                if isinstance(item.get('text'), str):
                    return item['text']
                if 'content' in item:
                    return extract(item['content'])
            return ''

        extracted = extract(value)
        if extracted:
            text = extracted
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    text = re.sub(r'\n[ \t]*\n(?:[ \t]*\n)+', '\n\n', text)
    return text.strip()


def answer_markdown(output: str) -> str:
    # Financial amounts should render as literal dollars, not LaTeX delimiters.
    return re.sub(r'(?<!\\)\$', r'\\$', readable_answer(output))
