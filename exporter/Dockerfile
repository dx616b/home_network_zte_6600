FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt zte_exporter.py ./
RUN pip install --no-cache-dir -r requirements.txt
EXPOSE 9105
ENV LISTEN_HOST=0.0.0.0 LISTEN_PORT=9105 SCRAPE_INTERVAL=5
CMD ["python", "zte_exporter.py"]
