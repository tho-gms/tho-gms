FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .
# Mount a persistent volume here: it holds the WHOOP tokens and the food/weight database.
ENV WHOOP_MCP_HOME=/data
EXPOSE 8000
CMD ["whoop-mcp", "http"]
