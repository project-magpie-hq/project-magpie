from langchain_core.messages import AIMessage


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
