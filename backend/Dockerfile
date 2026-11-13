FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

ENV PORT=8000
EXPOSE 8000
# Load the reviewed CSVs on start so a fresh database always has the IPO list.
CMD ["sh", "-c", "python -m pipeline load && uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
