FROM python:3.12-bookworm
ENV PYTHONUNBUFFERED=1 PLAYWRIGHT_BROWSERS_PATH=/ms-playwright HOME=/home/lockx
WORKDIR /app
COPY requirements.txt requirements-browser.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-browser.txt \
    && python -m playwright install --with-deps chromium \
    && groupadd --gid 10001 lockx \
    && useradd --uid 10001 --gid 10001 --create-home lockx
COPY . .
CMD ["python", "start_server.py"]
