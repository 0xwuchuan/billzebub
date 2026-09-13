"""Run the Billzebub HTTP process."""

from __future__ import annotations

import uvicorn

from billzebub.api import create_app
from billzebub.config import Settings


def main() -> None:
    settings = Settings()
    # NAS mode publishes the container only through host-local Tailscale Serve.
    # The proxy is therefore the sole source of forwarded browser scheme headers.
    uvicorn.run(
        create_app(settings),
        host=settings.api_host,
        port=settings.api_port,
        proxy_headers=settings.trust_tailscale_headers,
        forwarded_allow_ips="*" if settings.trust_tailscale_headers else "127.0.0.1",
    )


if __name__ == "__main__":
    main()
