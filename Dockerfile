FROM python:3.12-slim

WORKDIR /app

# git needed for pip git+ dependencies
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

# Install jaskot-config (copied into _jaskot-config/ by deploy script)
COPY _jaskot-config /opt/jaskot-config
RUN pip install --no-cache-dir /opt/jaskot-config

# Install jaskot-clio (copied into _jaskot-clio/ by deploy script / CI)
COPY _jaskot-clio /opt/jaskot-clio
RUN pip install --no-cache-dir /opt/jaskot-clio
# Install app dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY . .

EXPOSE 5001

CMD ["gunicorn", "--bind", "0.0.0.0:5001", "--workers", "2", "--timeout", "120", "app:create_app()"]
