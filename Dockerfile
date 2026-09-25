# The pipeline ships as a container so `make up && make docker-run` reproduces the same result on
# any machine with Docker — no local Python, no platform-specific wheel issues.
FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir .

COPY sql/ ./sql/
COPY sources/ ./sources/

ENTRYPOINT ["flasheats"]
CMD ["run"]
