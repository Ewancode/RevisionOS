# samples/ (git-ignored)

Put a few of your own lecture PDFs (and any other formats you use) here for
local checks. Everything in this folder except this README is git-ignored:
the files are University of Liverpool copyright and the repository is public.

`cd backend && uv run pytest -m samples -s` runs text extraction on each file
(no AI calls, no cost) and prints which pages would be sent to Claude vision.
CI never runs these tests.
