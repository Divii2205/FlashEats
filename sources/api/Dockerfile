FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir "flask>=3.0"
COPY mock_dispatch_api.py dispatch_data.json ./
EXPOSE 8000
CMD ["python", "mock_dispatch_api.py"]
