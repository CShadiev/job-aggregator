"""OpenSearch client factory from application config."""

from opensearchpy import AsyncOpenSearch

from config import Config, ConfigProvider


def build_opensearch_client(config: Config | None = None) -> AsyncOpenSearch:
    """Create and return an AsyncOpenSearch client instance based on application configuration.

    Args:
        config: Optional Config instance; if omitted, ConfigProvider is used.

    Returns:
        AsyncOpenSearch client configured for the target host and credentials.
    """
    cfg = config or ConfigProvider.get_config()
    http_auth = None
    if cfg.OPENSEARCH_USER and cfg.OPENSEARCH_PASSWORD:
        http_auth = (cfg.OPENSEARCH_USER, cfg.OPENSEARCH_PASSWORD)
    return AsyncOpenSearch(
        hosts=[{"host": cfg.OPENSEARCH_HOST, "port": cfg.OPENSEARCH_PORT}],
        http_compress=True,
        http_auth=http_auth,
        use_ssl=cfg.OPENSEARCH_USE_SSL,
        verify_certs=cfg.OPENSEARCH_VERIFY_CERTS,
        ssl_show_warn=False,
    )
