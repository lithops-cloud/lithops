# Build Lithops documentation

1. Install [Sphinx](https://www.sphinx-doc.org/en/master/usage/installation.html) and all plugins:

    ```bash
    python3 -m pip install sphinx myst-parser sphinx_copybutton jupyter ipykernel nbsphinx sphinx_book_theme 
    ```

2. Install [Pandoc](https://pandoc.org/installing.html). For debian/ubuntu:

    ```bash
    sudo apt install pandoc
    ```

3. Build the static HTML files:

    ```bash
    make html
    ```

4. The documentation HTML files are located in the `_build` folder. Copy them to the website repo under `docs` folder:

    ```bash
    rm -R ../../lithops-cloud.github.io/docs/*
    cp -R _build/html/* ../../lithops-cloud.github.io/docs/
    ```

5. To clean build files run:

    ```bash
    make clean
    ```

You can also use [this](Dockerfile) Dockerfile to build the documentation using a Docker container.
