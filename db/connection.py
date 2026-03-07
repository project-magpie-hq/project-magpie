"""
MongoDB 공유 연결 관리 모듈.

프로젝트 전체에서 단일 AsyncIOMotorClient 인스턴스를 재사용한다.
모듈 레벨에서 여러 클라이언트를 생성하는 대신 get_client() / get_db() 를 호출하라.

사용 예::

    from db.connection import get_db, close_connection

    db = get_db()
    doc = await db["strategies"].find_one({"_id": some_id})

    # 애플리케이션 종료 시
    await close_connection()
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

load_dotenv()

_MONGO_URL: str = os.getenv("MONGO_URL", "mongodb://localhost:27017")
_DB_NAME: str = "the_nest"

_client: AsyncIOMotorClient | None = None


def get_client() -> AsyncIOMotorClient:
    """프로젝트 공용 AsyncIOMotorClient를 반환한다 (lazy singleton)."""
    global _client
    if _client is None:
        _client = AsyncIOMotorClient(_MONGO_URL)
    return _client


def get_db() -> AsyncIOMotorDatabase:
    """프로젝트 공용 AsyncIOMotorDatabase('the_nest')를 반환한다."""
    return get_client()[_DB_NAME]


async def close_connection() -> None:
    """MongoDB 연결을 안전하게 종료한다. 애플리케이션 종료 시 호출."""
    global _client
    if _client is not None:
        _client.close()
        _client = None
