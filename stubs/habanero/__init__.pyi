from typing import Any

class Crossref:
    def __init__(
        self,
        mailto: str | None = ...,
        ua_string: str | None = ...,
        base_url: str = ...,
        api_key: str | None = ...,
        timeout: int = ...,
    ) -> None: ...

    def works(
        self,
        *,
        filter: dict[str, Any] | None = ...,
        cursor: str | None = ...,
        cursor_max: int = ...,
        select: list[str] | None = ...,
        progress_bar: bool = ...,
        **kwargs: Any,
    ) -> list[dict[str, Any]]: ...
