FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py .

ENV IG_USERNAME=""
ENV IG_PASSWORD=""
ENV PYTHONUNBUFFERED=1

EXPOSE 8500

CMD ["python", "server.py"]
