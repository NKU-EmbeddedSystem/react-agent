"""Reaction dataset manager: python -m curator import|serve|export|check.

The pipeline's results are imported once into a SQLite file of the curator's own (reactions, the
blocks they come from, and the PDFs themselves); from then on everything is read from and written to
that file. Every change to a reaction is a new revision; nothing is overwritten or deleted.
`pipeline` is not imported here: the contract with the pipeline is the files under work/<id>/,
read by `import` only.
"""
