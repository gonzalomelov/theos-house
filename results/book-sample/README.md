# First-month book, sample

A sample, labelled as such: 30 simulated days of simulated Theo in a local log, with the text written by Muse Spark Open and every number checked by code against that day's log (`parenting_agent/core/book.py`). Rebuild with `python scripts/first_month_book.py`.

The illustrations in `parenting_agent/simulator/static/book/` were made by hand on Nov 3, 2026 in Meta's Muse app, which said it used Muse Image. No API for that model is open to this project: Baseten serves only Muse Spark Open, and the Meta Model API isn't set up here. So the agent doesn't generate images.

Grandma's recipe: `preview_family_recipe` checks a recipe and sends nothing, simulated by default and through Recipe Sender's public connector with `PA_RECIPE=real`. Recipe Sender (Oct 2026, repo chatgpt-plugins) is prior work, not built for this hackathon, and no sending code lives here. A real send happens only from Meta's Muse app after the person says yes.
