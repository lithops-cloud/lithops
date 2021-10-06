FROM python:3.8-buster

RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        pandoc \
    && rm -rf /var/lib/apt/lists/*

RUN pip install -U --no-cache-dir pip wheel setuptools

RUN pip install --no-cache-dir sphinx myst-parser sphinx_copybutton jupyter ipykernel nbsphinx sphinx_book_theme sphinx-serve lithops

ADD lithops lithops

COPY setup.py ./

RUN python setup.py install

ADD docs docs

WORKDIR docs

RUN make html

# Uncomment to serve files
#CMD sphinx-serve -p 8080
