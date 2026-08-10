"""Render the package README and refuse channel-relative or unsafe active links."""

from __future__ import annotations

import sys
import warnings
from html.parser import HTMLParser
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_README = _ROOT / "README.md"
_LINK_ATTRIBUTES = frozenset({"href", "src"})


class ReadmeRenderingError(ValueError):
    """The rendered package description violates its public-channel contract."""


class _RenderedLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.targets: list[tuple[str, str]] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        del tag
        self.targets.extend(
            (attribute, value or "") for attribute, value in attrs if attribute in _LINK_ATTRIBUTES
        )

    def handle_startendtag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        self.handle_starttag(tag, attrs)


def _validate_rendered_links(rendered: str) -> None:
    parser = _RenderedLinkParser()
    parser.feed(rendered)
    parser.close()
    unsafe = sorted(
        {
            f"{attribute}={target!r}"
            for attribute, target in parser.targets
            if not (
                target.lower().startswith("https://")
                or (
                    attribute == "href"
                    and (target.startswith("#") or target.lower().startswith("mailto:"))
                )
            )
        }
    )
    if unsafe:
        raise ReadmeRenderingError(
            "rendered README contains channel-relative or unsafe links: " + ", ".join(unsafe)
        )


def verify_readme_rendering() -> None:
    try:
        description = _README.read_text(encoding="utf-8")
    except UnicodeError as exc:
        raise ReadmeRenderingError("README.md is not valid UTF-8") from exc
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="Use `header_id_prefix` instead",
            category=FutureWarning,
            module=r"readme_renderer\.markdown",
        )
        try:
            from readme_renderer import markdown
        except ImportError as exc:
            raise ReadmeRenderingError("locked readme-renderer is not installed") from exc
    rendered = markdown.render(description, variant="GFM")
    if rendered is None:
        raise ReadmeRenderingError("README.md could not be rendered as GFM Markdown")
    _validate_rendered_links(rendered)


def main() -> int:
    try:
        verify_readme_rendering()
    except (OSError, ReadmeRenderingError) as exc:
        print(f"README rendering error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
