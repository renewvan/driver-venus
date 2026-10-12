FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY node_venus/ node_venus/

ENTRYPOINT ["python", "-m", "node_venus.main"]
