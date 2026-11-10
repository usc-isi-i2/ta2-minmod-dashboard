# Use an official Python runtime as a parent image
FROM python:3.9-slim

# Set the working directory in the container
WORKDIR /usr/src/app

# Copy only the necessary files to install dependencies first
COPY pyproject.toml poetry.lock ./

# Install Poetry (pinned -- the installer defaults to the latest release,
# which requires Python >=3.10 and fails to install under this image's 3.9)
RUN apt-get update && \
    apt-get install -y curl && \
    curl -sSL https://install.python-poetry.org | POETRY_VERSION=1.8.3 python3 - && \
    # Make poetry available in the PATH
    ln -s /root/.local/bin/poetry /usr/local/bin/poetry && \
    # Install project dependencies
    poetry config virtualenvs.create true && \
    poetry config virtualenvs.in-project true && \
    poetry install --no-root && \
    # Cleanup to reduce image size
    apt-get remove -y curl && \
    apt-get autoremove -y && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Copy the rest of the application code
COPY . .

# Make port 8050 available to the world outside this container
EXPOSE 8050

# Run app.py when the container launches
# dev
CMD ["poetry", "run", "python", "app.py"]

# prod
# CMD ["poetry", "run", "gunicorn", "index:server", "--workers", "3", "-b", "0.0.0.0:8050"]
