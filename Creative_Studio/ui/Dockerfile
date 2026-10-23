# Written by Anju for the Multi-Agent Creative Studio capstone (new file).
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONUTF8=1
WORKDIR /app
COPY requirements-ui.txt .
RUN pip install --no-cache-dir -r requirements-ui.txt
COPY app.py .
# Cloud Run sends traffic to $PORT (8080 by default)
CMD streamlit run app.py --server.port=${PORT:-8080} --server.address=0.0.0.0 --server.headless=true --browser.gatherUsageStats=false
