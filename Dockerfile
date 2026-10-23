FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY driver_venus/ driver_venus/
# Beside the module, where driver_info.py looks first (a checkout run uses the repo-root file).
COPY manifest.json driver_venus/manifest.json

# The release workflow passes the git release tag. Unset (a local build) reports "dev".
ARG DRIVER_VERSION
ENV DRIVER_VERSION=${DRIVER_VERSION}

ENTRYPOINT ["python", "-m", "driver_venus.main"]
