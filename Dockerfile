FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV PORT=3000
EXPOSE 3000
# Single worker on purpose: per-call order state in state.py is in-process,
# so a second worker would serve calls that cannot see the order.
CMD ["python", "app.py"]
