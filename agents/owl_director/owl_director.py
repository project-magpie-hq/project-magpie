import os

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_google_genai import ChatGoogleGenerativeAI

from tools.db_tools import register_strategy
from tools.market_tools import request_chart_analysis


def load_prompt():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    prompt_path = os.path.join(current_dir, "owl_director_prompt.md")

    with open(prompt_path, encoding="utf-8") as f:
        return f.read()


def get_owl_llm():
    # 1. 사용할 모델
    llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0.2)

    # 2. 도구(Tool) 바인딩
    tools = [register_strategy, request_chart_analysis]
    llm_with_tools = llm.bind_tools(tools)

    # 3. 프롬프트 설정
    prompt_template = ChatPromptTemplate.from_messages(
        [
            ("system", load_prompt()),
            MessagesPlaceholder(variable_name="messages"),
        ]
    )

    return prompt_template | llm_with_tools


def owl_node(state: dict):
    agent = get_owl_llm()
    response = agent.invoke({"messages": state["messages"]})

    return {"messages": [response]}
