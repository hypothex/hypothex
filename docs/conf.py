"""Sphinx configuration."""

project = "Hypothex"
author = "Shreyas Vinaya Sathyanarayana"
extensions = ["sphinx.ext.autodoc", "sphinx.ext.viewcode", "numpydoc"]
html_theme = "sphinx_rtd_theme"
numpydoc_show_class_members = False
exclude_patterns = ["_build", "superpowers"]
