FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Default brand profile. Override at deploy time with:
#   -e MCP_PROFILE_PATH=/app/profiles/your.yaml
# or by mounting a private profile into the container:
#   -v /path/to/onramp.yaml:/app/profiles/active.yaml
ENV MCP_PROFILE_PATH=/app/profiles/example.yaml

EXPOSE 8000

CMD ["python", "server_remote.py"]
