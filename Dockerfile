FROM python:3.11-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y git tree

RUN pip install pytest
RUN pip install testscript-eval
