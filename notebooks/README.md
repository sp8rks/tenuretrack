# notebooks

`tenuretrack_colab.ipynb` is the no-install path for faculty who want their own
numbers and do not want to clone a repository. It runs in Google Colab, installs
the package from GitHub, and drives exactly the same CLI stages a terminal user
runs. Nothing in it forks the pipeline.

Open it at
[colab.research.google.com/github/sp8rks/tenuretrack](https://colab.research.google.com/github/sp8rks/tenuretrack/blob/main/notebooks/tenuretrack_colab.ipynb).

## Editing it

The logic the notebook needs lives in `tenuretrack/notebook.py`, not in the
cells, so that `make test` covers it. Keep cells to a form, a call, and a print.

To change the notebook: open it in Colab, edit, then **Edit > Clear all
outputs** before **File > Download .ipynb**, and replace the file here.
`tests/test_notebook.py` fails if a committed notebook carries saved output,
because a real run's output contains cohort members' names.

The same test greps the markdown cells for prescriptive wording. This notebook
is the surface most people will actually read, so the descriptive-not-
prescriptive rule (CLAUDE.md rule 3) applies to its prose as strictly as it does
to a generated report.
