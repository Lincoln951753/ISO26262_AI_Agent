FROM docker.io/library/python:3.12-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY agent.py .
COPY tools/ ./tools/
COPY test_data/ ./test_data/
COPY test_tool.py .

CMD ["python", "agent.py"]