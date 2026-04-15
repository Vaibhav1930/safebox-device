# scripts/config_sync_once.py
from core.config_sync import ConfigSyncManager

if __name__ == "__main__":
    mgr = ConfigSyncManager()
    print(mgr.sync_once())
