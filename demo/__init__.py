"""Self-contained demo data for the extraction platform (no model calls, no network).

`python -m demo.make [ROOT]` lays out a one-page synthetic paper, its SI, and the work directory
the pipeline would leave behind: five entries with their recorded labels, yields, conditions and
product names, and structures redrawn from the product names with RDKit. Nothing is copied from a
published PDF. The result imports into the curator as it is.
"""
