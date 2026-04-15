import os

API_BASE_URL = os.getenv(
    "CLARITY_API_BASE_URL",
    "https://cl-1446b1cdb7464773a91ee73e5b8cc20d.ecs.us-east-1.on.aws/"
)

CONFIG_SYNC_ENABLED = os.getenv("CONFIG_SYNC_ENABLED", "true").lower() == "true"
CONFIG_SYNC_INTERVAL_SECONDS = int(os.getenv("CONFIG_SYNC_INTERVAL_SECONDS", "900"))
