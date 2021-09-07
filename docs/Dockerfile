FROM python:3.8-slim

RUN pip install -U pip wheel setuptools

RUN pip install sphinx-serve

ADD . docs

WORKDIR docs

CMD sphinx-serve -p 8080
