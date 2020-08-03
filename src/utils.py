from typing import List, Optional


def pagify(
    text: str,
    *,
    page_size: int = 1800,
    delims: Optional[List[str]] = None,
    strip_before_yield=True,
):

    delims = delims or ["\n"]

    while len(text) > page_size:
        closest_delims = (text.rfind(d, 1, page_size) for d in delims)
        closest_delim = max(closest_delims)
        closest_delim = closest_delim if closest_delim != -1 else page_size

        chunk = text[:closest_delim]
        if len(chunk.strip() if strip_before_yield else chunk) > 0:
            yield chunk
        text = text[closest_delim:]

    if len(text.strip() if strip_before_yield else text) > 0:
        yield text


def only_once(f):
    has_called = False

    def wrapped(*args, **kwargs):
        nonlocal has_called

        if not has_called:
            try:
                f(*args, **kwargs)
            finally:
                has_called = True

    return wrapped
