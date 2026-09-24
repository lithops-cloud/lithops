# Build Lithops documentation

The [Release workflow](../.github/workflows/release.yml) builds these docs and publishes them to
the website repository on every release. To republish them without a release (e.g. after fixing
them), run the [Publish docs workflow](../.github/workflows/docs.yml) from the *Actions* tab on
`master`. The steps below are for building them locally.

1. Install Lithops with [Sphinx](https://www.sphinx-doc.org/en/master/usage/installation.html) and all plugins, from the repository root:

    ```bash
    python3 -m pip install -e '.[docs]'
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
