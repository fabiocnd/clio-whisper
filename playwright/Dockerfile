# Dockerfile
FROM mcr.microsoft.com/playwright/python:v1.50.0-noble

WORKDIR /work
COPY pyproject.toml /work/
# or requirements.txt if you prefer

# Example if using requirements.txt:
# COPY requirements.txt /work/
# RUN pip install --no-cache-dir -r requirements.txt

# For pyproject-based installs, you can use uv/poetry/pip depending on your setup.
COPY . /work
CMD ["python", "web_debug_client.py"]