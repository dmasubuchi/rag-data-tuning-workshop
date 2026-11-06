# 採用アシスタントのイメージ（自分の PC で動かすなら、使わなくてよい）。Repo 直下を文脈にして作る（Repo 直下の .dockerignore で .env.local などを除く）。
# 接続先とキーはイメージに入れない。メンバー用のファイル（member.local.env）を /secrets/env.local に置いて（マウントして）、WORKSHOP_ENV_FILE で読む。
# 手元だけで開く（127.0.0.1）。人に見せるときは、ASSISTANT_ACCESS_CODE（-e）を決めてから、公開の範囲を広げる。
#   docker build -f applied/assistant/Dockerfile -t hiring-assistant .
#   docker run --rm -p 127.0.0.1:8501:8501 -v "$PWD/member.local.env:/secrets/env.local:ro" hiring-assistant
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    WORKSHOP_ENV_FILE=/secrets/env.local \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    STREAMLIT_CLIENT_TOOLBAR_MODE=minimal \
    STREAMLIT_THEME_PRIMARY_COLOR="#1864ab"

RUN useradd --create-home app
WORKDIR /app
COPY applied/assistant/requirements.txt applied/assistant/requirements.txt
RUN pip install --no-cache-dir -r applied/assistant/requirements.txt
# 手元のファイルは 600 のことがあるので、持ち主をアプリのユーザーにしてコピーする
COPY --chown=app:app applied/lib applied/lib
COPY --chown=app:app applied/assistant applied/assistant
COPY --chown=app:app applied/topics/19-agentic-retrieval/questions.json applied/topics/19-agentic-retrieval/questions.json
USER app
EXPOSE 8501
CMD ["streamlit", "run", "applied/assistant/app.py", "--server.port", "8501", "--server.address", "0.0.0.0"]
