FROM python:3.12-slim
WORKDIR /app
COPY backends.py llm_server.py ./
COPY config/ ./config/
EXPOSE 8815
CMD ["python", "llm_server.py", "--host", "0.0.0.0", "--port", "8815"]
