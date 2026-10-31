"""The simulated full day (issue #17): the plan page day replayed end to end, from 06:10 to 02:30.

    python -m parenting_agent.fullday                 # Muse brain, Baby Buddy on the Vostro, SAM 3.1 on the Mac GPU
    python -m parenting_agent.fullday --wipe-only     # remove every entry an earlier run wrote (tag full-day-sim)

Each step of the day goes through the real agent: voice lines become messages, house sounds become
observations, the changing-table and bath skills watch the generated clips streamed in real time, and the
daily rhythm speaks first. The clock is simulated: the day is compressed into the few minutes the run takes,
and every Baby Buddy entry is timed at the real moment its step ran, so nothing is in the future. Every entry
carries the tag full-day-sim so a run can be wiped.

What is not built yet is shown as dry run, never as success: Home Assistant actions (the token is waiting on
Gonza, issue #9), delivery on Telegram, the ear and the speakers (issues #3 and #8) and the house sound
detector (issue #14). The report says which steps used each.
"""
