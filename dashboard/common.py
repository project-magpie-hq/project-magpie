import json
from typing import Any


def pretty_json(data: Any) -> str:
    """값을 보기 좋은 JSON 문자열로 변환"""
    try:
        if isinstance(data, str):
            return json.dumps(json.loads(data), ensure_ascii=False, indent=2)
        return json.dumps(data, ensure_ascii=False, indent=2, default=str)
    except Exception:
        return str(data)
