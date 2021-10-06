# Build Lithops documentation

1. Install [Sphinx](https://www.sphinx-doc.org/en/master/usage/installation.html) and all plugins:
    ```
    python3 -m pip install sphinx myst-parser sphinx_copybutton jupyter ipykernel nbsphinx sphinx_book_theme 
    ```
2. Install [Pandoc](https://pandoc.org/installing.html). For debian/ubuntu:
3. ```
   sudo apt install pandoc
   ```
4. Build the static HTML files:
   ```
   make html
   ```
5. The documentation HTML files are located in the _build folder.
6. To clean build files run:
   ```
   make clean
   ```

You can also use [this](Dockerfile) Dockerfile to build the documentation using a Docker container.