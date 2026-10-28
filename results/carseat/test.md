# Car seat coach on rendered clips: test

- Wrong installs flagged: 11 of 12
- False alarms on correct installs: 1 of 12
- Abstained when it could not see: 4 of 4
- Results spoken within 2 s of the step being visible: 100 of 116 (median 1.69 s, max 4.11 s)
- Spoken texts containing 'safe': 0
- Hand checks asked and logged in every clip: True

| Clip | Label | Lap guides | Shoulder guide | No twist | Level line | Handle | Flagged |
|---|---|---|---|---|---|---|---|
| test-01-correct.mp4 | correct | pass | pass | pass | pass | fail | yes |
| test-02-correct.mp4 | correct | pass | pass | pass | pass | pass | no |
| test-03-correct.mp4 | correct | pass | pass | pass | pass | pass | no |
| test-04-correct.mp4 | correct | pass | pass | pass | pass | pass | no |
| test-05-correct.mp4 | correct | pass | pass | pass | pass | pass | no |
| test-06-correct.mp4 | correct | pass | pass | pass | pass | pass | no |
| test-07-correct.mp4 | correct | pass | pass | pass | pass | pass | no |
| test-08-correct.mp4 | correct | pass | pass | pass | pass | pass | no |
| test-09-correct.mp4 | correct | pass | pass | pass | pass | pass | no |
| test-10-correct.mp4 | correct | pass | pass | pass | pass | pass | no |
| test-11-correct.mp4 | correct | pass | pass | pass | pass | pass | no |
| test-12-correct.mp4 | correct | pass | pass | pass | pass | pass | no |
| test-13-outside_guide.mp4 | outside_guide | pass | fail | pass | pass | pass | yes |
| test-14-outside_guide.mp4 | outside_guide | fail | pass | unseen | pass | unseen | yes |
| test-15-outside_guide.mp4 | outside_guide | pass | fail | pass | pass | unseen | yes |
| test-16-twisted.mp4 | twisted | pass | pass | fail | pass | pass | yes |
| test-17-twisted.mp4 | twisted | fail | pass | fail | pass | pass | yes |
| test-18-twisted.mp4 | twisted | pass | pass | fail | pass | pass | yes |
| test-19-recline.mp4 | recline | pass | pass | pass | fail | pass | yes |
| test-20-recline.mp4 | recline | pass | pass | pass | fail | pass | yes |
| test-21-recline.mp4 | recline | pass | pass | pass | fail | pass | yes |
| test-22-handle.mp4 | handle | pass | pass | pass | pass | fail | yes |
| test-23-handle.mp4 | handle | pass | pass | pass | pass | fail | yes |
| test-24-handle.mp4 | handle | pass | pass | pass | pass | unseen | no |
| test-25-unseen.mp4 | unseen | unseen | unseen | unseen | unseen | unseen | no |
| test-26-unseen.mp4 | unseen | unseen | unseen | unseen | unseen | unseen | no |
| test-27-unseen.mp4 | unseen | unseen | unseen | unseen | unseen | unseen | no |
| test-28-unseen.mp4 | unseen | unseen | unseen | unseen | unseen | unseen | no |
