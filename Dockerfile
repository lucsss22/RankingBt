FROM python:3.13-slim

RUN useradd --create-home --uid 10001 atleta

WORKDIR /app

COPY requirements-docker.txt .
RUN pip install --no-cache-dir -r requirements-docker.txt

COPY --chown=atleta:atleta . .

RUN mkdir /dados && chown atleta:atleta /dados

ENV BT_DADOS=/dados
ENV BT_ATUALIZAR_RANKING=0

USER atleta

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "web:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "172.28.0.20"]