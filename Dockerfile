# The hosted server for the GitHub Pages dashboard (and a way to run the whole desk anywhere Docker runs).
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV HOST=0.0.0.0 BUDGET_PROFILE=demo PYTHONUNBUFFERED=1
# The host sets PORT; the app reads it. Secrets (API keys, ACCESS_CODE) come from the host's environment, never from the image.
CMD ["python", "-m", "app"]
