import logging
import os

from dotenv import load_dotenv
from langchain_core.runnables import RunnableConfig
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters

from magpie_agent.graph import build_graph

# 로깅 설정
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

# 전역 변수로 그래프 앱 초기화
app = build_graph()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/start 명령 처리"""
    if not update.message:
        return

    welcome_text = (
        "👋 안녕하세요! Project Magpie의 Owl Director입니다.\n\n"
        "저는 당신의 투자 전략을 수립하고, 미어캣(Meerkat) 스캐너를 통해 "
        "시장을 감시하여 최적의 타점을 찾아내는 인공지능 에이전트입니다.\n\n"
        "대화를 시작하려면 메시지를 입력해주세요."
    )
    await update.message.reply_text(welcome_text)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """사용자 메시지 처리 및 그래프 실행"""
    if not update.message or not update.message.text or not update.effective_user or not update.effective_chat:
        return

    telegram_input = update.message.text.strip()
    # 텔레그램 정보를 기반으로 user_id와 thread_id 설정
    user_id = str(update.effective_user.id)
    thread_id = str(update.effective_chat.id)

    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
    user_input = {
        "user_id": user_id,
        "messages": [("user", telegram_input)],
        "from_daemon": False,
    }

    try:
        # 그래프 실행 (업데이트 스트림 모드)
        async for event in app.astream(user_input, config=config, stream_mode="updates"):
            # Owl의 최종 응답 출력
            if "owl_director" in event:
                node_output = event["owl_director"]
                if "messages" in node_output:
                    ai_msg = node_output["messages"][0]
                    # 도구 호출이 아닌 일반 메시지인 경우에만 출력
                    if not getattr(ai_msg, "tool_calls", None) and ai_msg.content:
                        await update.message.reply_text(f"🦉 [Owl]: {ai_msg.content}")

            # 미어캣의 활동 표시 (모드별 메시지 차별화)
            if "meerkat_scanner" in event:
                node_output = event["meerkat_scanner"]
                if "messages" in node_output:
                    ai_msg = node_output["messages"][0]
                    # 차트 분석 전용 모드: content만 있고 tool_calls 없음
                    if ai_msg.content and not getattr(ai_msg, "tool_calls", None):
                        await update.message.reply_text("🦦 [Meerkat]: 차트 분석 리포트를 생성했습니다.")
                    elif "chart_context" in node_output:
                        await update.message.reply_text("🦦 [Meerkat]: 차트 분석 완료, Calculate Team에 전달했습니다.")
                    else:
                        await update.message.reply_text("🦦 [Meerkat]: 타점 분석을 마치고 결과를 기록했습니다.")

            # Calculate Team (Bull/Bear/Dolphin) 활동 표시
            if "calculate_team" in event:
                await update.message.reply_text("🐂🐻🐬 [Calculate Team]: Bull/Bear 토론 및 Dolphin 최종 타점 계산을 완료했습니다.")

    except Exception as e:
        logger.exception("메시지 처리 중 오류 발생")
        await update.message.reply_text(f"❌ [Error]: {e}")


def main():
    """텔레그램 봇 실행"""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN이 .env 파일에 설정되어 있지 않습니다.")
        return

    application = ApplicationBuilder().token(token).build()

    # 핸들러 등록
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))

    print("\n" + "=" * 55)
    print("📱 [Project Magpie] - Telegram Bot 서비스 시작")
    print("=" * 55 + "\n")

    application.run_polling()


if __name__ == "__main__":
    main()
