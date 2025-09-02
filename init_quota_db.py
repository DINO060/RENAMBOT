#!/usr/bin/env python3
import asyncio
import os
from utils.quota import init_quota_db

async def main():
    db_path = os.getenv("QUOTA_DB_PATH", "data/quotas.db")
    await init_quota_db(db_path)
    print(f"✅ Base de données des quotas initialisée : {db_path}")

if __name__ == "__main__":
    asyncio.run(main())
