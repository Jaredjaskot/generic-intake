FROM python:3.12-slim

WORKDIR /app

# Install jaskot-config first (separate layer for caching)
COPY jaskot-config /opt/jaskot-config
RUN pip install --no-cache-dir /opt/jaskot-config

# Install app dependencies
COPY generic-intake/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY generic-intake/ .

EXPOSE 5001

CMD ["gunicorn", "--bind", "0.0.0.0:5001", "--workers", "2", "--timeout", "120", "app:create_app()"]
