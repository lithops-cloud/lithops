# Build Lithops documentation

1. Install [Sphinx](https://www.sphinx-doc.org/en/master/usage/installation.html) and all plugins:
    ```
    python3 -m pip install sphinx myst-parser sphinx_copybutton jupyter ipykernel nbsphinx sphinx_book_theme 
    ```
2. Build the static HTML files:
   ```
   make html
   ```
3. The documentation HTML files are located in the _build folder.
4. To clean build files run:
   ```
   make clean
   ```