import os

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv()

MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017")
client = AsyncIOMotorClient(MONGO_URL)
db = client["the_nest"]

# 공용 컬렉션 객체
monitoring_target_collection = db["monitoring_targets"]
strategies_collection = db["strategies"]
portfolio_snapshot_collection = db["portfolio_snapshots"]
