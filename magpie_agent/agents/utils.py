import inspect
import logging
import os

from langchain_core.messages import AIMessage

logger = logging.getLogger(__name__)


def normalize_content(response: AIMessage) -> AIMessage:
    """Gemini가 content를 list[dict]로 반환할 경우 text 블록만 추출해 string으로 정규화"""
    if isinstance(response.content, list):
        text_parts = [
            block["text"]
            for block in response.content
            if isinstance(block, dict) and block.get("type") == "text" and block.get("text")
        ]
        return response.model_copy(update={"content": "\n".join(text_parts)})
    return response


def load_prompt(file_name: str = "prompt.md") -> str:
    """에이전트 시스템 프롬프트 로드"""
    # 1. 호출 스택을 가져와서 이 함수를 호출한 이전 프레임([1])을 확인합니다.
    caller_frame = inspect.stack()[1]
    # 2. 호출한 파일의 경로를 추출합니다.
    caller_filepath = caller_frame.filename
    # 3. 만약 파일 경로가 없다면 현재 작업 디렉토리로 대체합니다.
    caller_dir = os.getcwd() if caller_filepath == "<stdin>" else os.path.dirname(os.path.abspath(caller_filepath))

    prompt_path = os.path.join(caller_dir, file_name)
    try:
        with open(prompt_path, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        logger.error("프롬프트 파일을 찾을 수 없습니다: %s", prompt_path)
        raise
    except OSError as e:
        logger.exception("프롬프트 파일 읽기 실패: %s", prompt_path)
        raise RuntimeError(f"프롬프트 파일 읽기 실패: {prompt_path}") from e
