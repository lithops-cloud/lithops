# Configuration file for the Sphinx documentation builder.
#
# This file only contains a selection of the most common options. For a full
# list see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Path setup --------------------------------------------------------------

# If extensions (or modules to document with autodoc) are in another directory,
# add these directories to sys.path here. If the directory is relative to the
# documentation root, use os.path.abspath to make it absolute, like shown here.

import os
import sys
import lithops
sys.path.insert(0, os.path.abspath('.'))

sys.path.insert(0, os.path.abspath("../"))

from datetime import datetime


# -- Project information -----------------------------------------------------

project = 'Lithops'
copyright = str(datetime.now().year) + ', The Lithops Team'
author = 'The Lithops Team'

# -- General configuration ---------------------------------------------------

# Add any Sphinx extension module names here, as strings. They can be
# extensions coming with Sphinx (named 'sphinx.ext.*') or your custom
# ones.
extensions = [
    'myst_parser',
    'sphinx.ext.autodoc',
    'sphinx.ext.todo',
    'sphinx_copybutton',
    'nbsphinx'
]

todo_include_todos = True
nbsphinx_allow_errors = False

# Add any paths that contain templates here, relative to this directory.
templates_path = ['_templates']

# List of patterns, relative to source directory, that match files and
# directories to ignore when looking for source files.
# This pattern also affects html_static_path and html_extra_path.
exclude_patterns = ['_build', 'Thumbs.db', '.DS_Store', 'README.md', 'Dockerfile']

source_suffix = {
    '.rst': 'restructuredtext',
    '.txt': 'markdown',
    '.md': 'markdown',
}

# -- Autodoc options ---------------------------------------------------------

autodoc_typehints = 'description'

# -- nbsphinx options --------------------------------------------------------

jupyter_execute_notebooks = 'never'

# -- Options for HTML output -------------------------------------------------

# The theme to use for HTML and HTML Help pages.  See the documentation for
# a list of builtin themes.

# html_theme = 'furo'
# html_theme = 'sphinx_material'
# html_theme = 'karma_sphinx_theme'
html_theme = 'sphinx_book_theme'
html_favicon = '_static/favicon.png'

language = 'en'

html_theme_options = {
    'repository_url': 'https://github.com/lithops-cloud/lithops',
    'repository_branch': 'master',
    'use_issues_button': False,
    'use_download_button': True,
    'use_fullscreen_button': False,
    'use_repository_button': True,
    'show_navbar_depth': 1,
    # https://pydata-sphinx-theme.readthedocs.io/en/latest/user_guide/branding.html
    "logo": {
        "text": f"Lithops v{lithops.__version__}",
        "image_light": "_static/lithops_logo_readme.png",
        "image_dark": "_static/lithops_logo_readme.png",
    },
    # https://pydata-sphinx-theme.readthedocs.io/en/latest/user_guide/analytics.html
    "analytics": {
        "google_analytics_id": "G-7YKZHZYDCR",
    }
}


# Add any paths that contain custom static files (such as style sheets) here,
# relative to this directory. They are copied after the builtin static files,
# so a file named "default.css" will overwrite the builtin "default.css".
html_static_path = ['_static']
