import asyncio
import os
from weakref import WeakKeyDictionary

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection, AsyncIOMotorDatabase

load_dotenv()

MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017")
_clients: WeakKeyDictionary[asyncio.AbstractEventLoop, AsyncIOMotorClient] = WeakKeyDictionary()


def get_mongo_client() -> AsyncIOMotorClient:
    loop = asyncio.get_running_loop()
    client = _clients.get(loop)
    if client is None:
        client = AsyncIOMotorClient(MONGO_URL, io_loop=loop)
        _clients[loop] = client
    return client


def get_database() -> AsyncIOMotorDatabase:
    return get_mongo_client()["the_nest"]


def get_monitoring_targets_collection() -> AsyncIOMotorCollection:
    return get_database()["monitoring_targets"]


def get_strategies_collection() -> AsyncIOMotorCollection:
    return get_database()["strategies"]


def get_wallets_collection() -> AsyncIOMotorCollection:
    return get_database()["wallets"]
