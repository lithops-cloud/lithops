FROM python:3.8-slim

RUN pip install -U pip wheel setuptools

RUN pip install sphinx myst-parser sphinx_copybutton jupyter ipykernel nbsphinx sphinx_book_theme sphinx-serve

ADD . docs

WORKDIR docs

RUN make html

CMD sphinx-serve -p 8080
