FROM python:3.11
RUN pip install pipenv

RUN mkdir /app
WORKDIR /app

COPY Pipfile Pipfile.lock ./
RUN pipenv install --dev

COPY . .

EXPOSE 8081
