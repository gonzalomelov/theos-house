# Families: invited parents on Telegram

Invited parents log their own baby on Telegram, through a second bot, each family in its own private log. Built during the Meta hackathon. Issue #40. Deployed on the Vostro on Oct 28 2026, invite only.

It is a separate service, walled off like the public demo. Other families never reach Gonza's family agent, his Baby Buddy, his Home Assistant or his LAN.

## For parents: your data in 1 minute

- **What is stored.** Your baby's name or nickname and birth date. What you log: feeds, diapers, sleep, baths and notes. Our conversation of the last 7 days, older lines are deleted. Your Telegram chat id, so the bot can answer you. The only fact the bot keeps is the baby's name: other names, phone numbers, addresses or codes are never saved as facts, but what you type stays in the conversation for 7 days, so please leave them out. To count real use, one row per message with the time and a scrambled id (a hash of your Telegram id), never the text.
- **Where.** One private file for your family on Gonza's home server in Uruguay. No other family can see it, and it is not mixed with Gonza's own family data.
- **Who else sees the text and hears your voice notes.** To write replies, the conversation text and your log lines are sent to Muse Spark Open, Meta's open model, on Baseten. Voice notes you send are heard by Muse on Baseten too: the audio is sent once, never saved by the bot. Baseten's docs say it does not store inputs or outputs of these calls by default: https://docs.baseten.co/observability/security. Only when that call fails, Claude on Anthropic's API answers instead. By default Anthropic does not train on API data and deletes it within 30 days: https://privacy.claude.com/en/articles/7996866. Telegram carries the messages, like any Telegram chat.
- **Medical advice.** It is built to refuse medical advice. Health questions get a kind refusal and a suggestion to call your pediatrician. Red flags (not breathing, gasping, under water, a swallowed battery, a fall) get emergency services (911 in Uruguay) at once. A question on how a baby sleeps safely gets the American Academy of Pediatrics' public safe sleep line with its source, never advice about your baby.
- **How to delete.** Send `/deletemydata`, then `DELETE`. Your family's file, the conversation, the counting rows and both parents' access are removed at once. The other parent gets a message that it happened.

The bot sends the same text when a parent sends `/privacy`.

## Para las familias: tus datos en 1 minuto

- **Qué se guarda.** El nombre o apodo de tu bebé y su fecha de nacimiento. Lo que anotás: tomas, pañales, sueño, baños y notas. Nuestra conversación de los últimos 7 días, lo más viejo se borra. Tu id de chat de Telegram, para que el bot te pueda responder. El único dato que guarda es el nombre de tu bebé: otros nombres, teléfonos, direcciones o códigos nunca se guardan como dato, pero lo que escribís queda en la conversación 7 días, así que mejor no los mandes. Para contar el uso real, una fila por mensaje con la hora y un id mezclado (un hash de tu id de Telegram), nunca el texto.
- **Dónde.** Un archivo privado para tu familia en el servidor de la casa de Gonza, en Uruguay. Ninguna otra familia lo puede ver, y no se mezcla con los datos de la familia de Gonza.
- **Quién más ve el texto y escucha tus audios.** Para escribir las respuestas, el texto de la conversación y lo que anotaste se mandan a Muse Spark Open, el modelo abierto de Meta, en Baseten. Los audios que mandás también los escucha Muse en Baseten: el audio se manda una vez y el bot no lo guarda. Según su documentación, por defecto Baseten no almacena lo que entra ni lo que sale: https://docs.baseten.co/observability/security. Solo si esa llamada falla responde Claude, en la API de Anthropic. Por defecto Anthropic no entrena con los datos de su API y los borra en 30 días: https://privacy.claude.com/en/articles/7996866. Telegram lleva los mensajes, como en cualquier chat de Telegram.
- **Consejos médicos.** Está hecho para no dar consejos médicos. Si preguntás algo de salud, te responde con cariño que no puede y te sugiere llamar a tu pediatra. Las señales de alarma (no respira, boquea, estuvo bajo el agua, tragó una pila, una caída) reciben el 911 enseguida. Si preguntás cómo duerme seguro un bebé, te da la guía pública de sueño seguro de la Academia Estadounidense de Pediatría con su fuente, nunca un consejo sobre tu bebé.
- **Cómo borrar todo.** Mandá `/borrarmisdatos` y después `BORRAR`. Se borran de una el archivo de tu familia, la conversación, las filas de conteo y el acceso de los dos. Al otro papá o mamá le llega un mensaje avisando.

El bot manda este mismo texto cuando alguien manda `/privacidad`.

## Languages

The bot speaks Rioplatense Spanish with voseo and English. Every fixed message is in `parenting_agent/families/texts.py`, one table per language with the same keys.

- A stranger gets the language of their Telegram app (`language_code`): Spanish when it starts with `es`, English otherwise. Nothing about a stranger is stored.
- A new family starts in the language of the parent who used the invite. It is kept as the fact `_lang` in the family's own file, so both parents, reminders and the evening summary use it. The partner joins in the family's language, whatever their app says.
- `/idioma` switches the family to Spanish and `/language` to English. Both also take a name: `/idioma en`, `/language es`.
- Every command works in both languages: `/resumen` or `/summary`, `/proxima` or `/next`, `/invitar` or `/invite`, `/avisos` or `/reminders`, `/privacidad` or `/privacy`, `/ayuda` or `/help`, `/borrarmisdatos` or `/deletemydata`. The confirmation word follows the family's language: `BORRAR` in Spanish, `DELETE` in English.
- The brain is told the family's language in the system prompt. Over a spend cap the free rule-based brain reads Spanish notes ("mamadera 120 ml", "pañal sucio") through their English words and answers in Spanish.
- Spanish health words (fiebre, dosis, vómito, tos and more) get the Spanish refusal without a brain call, and a reminder or summary with a Spanish advice word is never sent.

## The invite flow

1. Gonza makes a code on the server: `docker exec pa-families python -m parenting_agent.families invite --count 3`. Each code is 8 characters, single use, valid 7 days, and only its hash is stored. With `PA_FAMILIES_BOT_USERNAME` set, each line also has a `https://t.me/<bot>?start=<code>` link that opens the bot with the code filled in.
2. The parent taps the link, or sends `/start K7QM3XPA` to the bot.
3. Three questions: the baby's name or nickname, the birth date (`2026-10-12` or `12/10/2026`, never in the future), and whether the other parent should log too. A yes gives a second code for the other parent, who joins the same log with no questions.
4. The parent is logging. In the tests the whole flow is 4 messages.

Without a valid code the bot replies politely that it is a private beta and stores nothing: no row, no file. After 5 wrong codes in a day from the same Telegram account it stops checking codes for that account until the next day (kept in memory only). Group chats get "please message me directly". The beta holds 20 families at most (`PA_FAMILIES_MAX_FAMILIES`) and 4 people per family.

For Gonza's own test accounts: `invite --internal` makes a code whose parent, and the partner they invite, are marked internal. `PA_FAMILIES_INTERNAL_USERS` (Telegram user ids, comma separated) does the same by account.

## What a family can do

| Message | What happens |
|---|---|
| `bottle 120 ml`, `left breast 15 min`, `wet and dirty diaper`, `she fell asleep`, `she woke up`, `bath done` | A log entry in the family's own file, never timed in the future |
| `when did she last eat?`, `how much did she drink today?` | Answered from the family's log through `baby_summary` and `read_baby_log` |
| `perdón eran 100 no 120`, `la de la 1 y media fue 80, corregila`, `la mandé 2 veces sin querer`, `borrá la última` | The entry is changed or removed, and the reply says exactly what changed: "Corregí la mamadera de las 01:30: 120 ml → 100 ml." |
| `¿a qué hora le toca?`, `when is the next feed?` | The brain calls `next_feed`, the same rhythm answer as `/next`, given as a time from the family's own log |
| `no para de llorar, ¿por qué?` | The likely reason from the log (the cry reason from #32), a guess and never a diagnosis, without a brain call |
| Red flags: not breathing, blue lips, limp, choking, won't wake, a fall, a hit to the head, a seizure, and the Spanish forms | "Call emergency services now" with 911 for Uruguay, at once, without a brain call |
| Health questions | The kind refusal, with "if it is urgent, call emergency services", without a brain call |
| `vomito un poquito dsp de la toma`, `tiene tos` | What the parent saw, with no question: noted in their words and the advice refused, in one turn, without a brain call (issue #77) |
| `le di 5 ml de ibuprofeno a las 14, anotalo`, `se dio vuelta por primera vez, ¿es normal?` | Logged as a note in the parent's words, never as a feed, and only the advice part is refused. The reply comes from the log, not the brain (issue #60) |
| `mamadera 9000 ml` | Asked about, never logged: a feed is 1 to 300 ml and 1 to 120 min, a sleep at most 14 hours, nothing in the future (issue #60) |
| `/summary` | Today so far, computed from the log, no brain call |
| `/next` | The next feed from the rhythm engine (`patterns.next_feed`) |
| `/invite` | A code for the other parent |
| `/reminders off`, `/reminders on` | Next feed reminders |
| `/privacy` | The privacy note above |
| `/deletemydata` then `DELETE` | Wipes the family. Anything else cancels, and the confirmation expires after 10 minutes |
| `/borrarmisdatos` then `BORRAR` | The same in Spanish |
| `/idioma`, `/language` | Spanish or English for the whole family |

The bot speaks first twice: a next feed reminder about 10 minutes before the feed the rhythm engine expects ("Según tu registro, la próxima toma sería cerca de las 15:55"), sent once per feed to every parent, only when the last feed is less than 8 hours old. And a daily summary at 20:00 local time, once a day, only when something was logged that day. Both pass the rhythm engine's `no_advice` check.

## One message, one entry

On Oct 28 an internal round trip logged "mamadera 120 ml" as 2 feeds of 120 ml. The brain failed after the log tool had run, the parent got "please try again", and the conversation kept the message with no answer, so the next turn logged it a second time. Now:

- If the brain fails after something was logged, the parent gets what was kept ("I could not finish my answer, but I logged a feed of 120 ml. No need to send it again.") and that answer stays in the conversation. A failure before anything was logged is kept as answered too.
- Within one message, the same entry (kind, amount or diaper contents, method and the time named) is logged once, however often the brain repeats the call. Two feeds at different times in one message are both logged.
- The same Telegram update id is handled once.
- The brain is told to log only what the newest message says, and that a new message is a new event even when it repeats an earlier one. With the real brain a second "mamadera 120 ml" or "bottle 120 ml" 1 to 20 minutes later was logged in 17 of 18 runs, against 6 of 12 with the old prompt.

The fix is in the shared decide loop, so the demo and the family agent get it too. Tests: `tests/test_one_message_one_entry.py`.

## Never "logged" when nothing was saved

With the real brain, a burst of notes such as "mamadera 120 ml", "pañal sucio", "se durmió" often got "Anotado" or "Logged" with no log tool call. The conversation keeps only the answers' text, so the brain copied its earlier "Anotado". On Oct 28 that was 71 of 150 notes (47 of 90 in Spanish, 24 of 60 in English). The fix is in the shared decide loop, so the demo and the family agent get it too:

- When the parent's message reports something to log (the rule parser in `parenting_agent/agent/rules.py`, Spanish words included) and no log call ran, the brain's answer is never sent. The same holds when its answer says it logged, or when a log call failed.
- The brain is asked once more, with the parent's message quoted, to call `log_baby_event` for that one message. After that ask only one entry of the kind the message reports can run, so earlier messages are not logged again.
- If it still does not log, the parent gets "No pude anotarlo, ¿me lo repetís?" or "I could not log that. Could you send it again?", and that answer stays in the conversation.
- Questions, small talk, a plug-in phrase such as "bath time" and a call waiting for the parent's yes are left alone.

On the same 150 notes after the fix: 0 false "logged" and every note logged once. The brain needed the second ask on 65 of them. Tests: `tests/test_no_false_logged.py`.

## Corrections, double sends and nothing made up

The real-new-parent judge ran 3 Spanish days with the real brain on Oct 28 and found that the log could not be corrected: "perdón eran 100 no 120" kept the 120 and the bot said "Listo", a bottle sent twice by mistake stayed twice, and the totals were wrong from then on. Now:

- `edit_baby_event` and `delete_baby_event` change or remove an entry, named by id, by kind and local time ("01:30") or as the last one. They are in the shared tools for any baby log that can change entries (the family log). Totals, `/resumen` and the evening summary read the log, so they follow.
- The reply for a change is built from the log, not from the brain: "Corregí la mamadera de las 01:30: 120 ml → 100 ml." or "Borré el pañal de las 03:30."
- The no-false-logged guard covers corrections. Until an edit or delete ran, no new entry is logged for a correction and no "Listo" is sent. The brain is asked once more, and if it still did not change anything the parent hears "No pude cambiar el registro". A log that cannot change entries (the demo) says so and adds nothing.
- The same feed (same amount and method) from a new message within 3 minutes is not logged. The bot asks "¿La mandaste dos veces o fueron dos mamaderas?", or "dos tomas de pecho" for a breast feed. "la mandé 2 veces sin querer" or "se mando doble" keeps one, "fueron dos" logs the second at its own time. An unclear answer keeps one and is asked once more, and only a new note, a question or a correction goes to the brain (issue #77).
- A log call keeps only what the parent said: the side the parent named and no other ("teta der" is the right breast, "teta 10 min" is a breast feed with the side unknown), no milk type (a bottle with no type is logged with the type unknown, never breast milk), no duration, amount, diaper color or time the parent did not say. A feed is logged at the message time, and starts earlier only when the parent said how long it lasted.
- The brain is told never to talk about its own bookkeeping ("no reporta nada nuevo", "ahora sí quedó registrada", apologies for answers the parent never saw), and the guard's own check message says the same.
- The next feed is a time from the family's log, never advice. A feed due in the last 30 minutes is "más o menos ahora". When none was logged for longer, the bot says "Ya pasaron 3 h 50 min desde la última toma anotada, a las 12:10. ¿Comió Tomi?", and only when the last feed is less than 8 hours old. Older than that it only says when the last feed was and how long ago, and the evening summary leaves it out.
- A health message is never answered with "No pude anotarlo, ¿me lo repetís?". "le doy la mamadera, 120 ml" is a bottle, not a health question.

Measured on Oct 28 with `scripts/families_3day_run.py`: 34 Spanish messages over 3 simulated days, two parents, Claude Haiku 5.5 (before Muse became the brain, the Muse run is `results/families/three-day-muse.md`). Before the fix 10 of 29 checks passed, with 10 replies of bookkeeping talk and 8 "se esperaba" texts. After, three runs passed 29, 28 and 27 of 29 with none of either. Each miss was the brain not calling a tool ("teta 10 min" once, "borrá la última" once), and the parent got the honest "No pude anotarlo" or "No pude cambiar el registro", never a false "Listo". Transcripts in `results/families/three-day-before.md` and `results/families/three-day-after.md` (plus `-2` and `-3`). Tests: `tests/test_log_edit.py`.

## The log is never wrong (round 2)

The round 2 real-new-parent judge saw "nono eran 70" log a second bottle with the reply "corregido", and "se mando doble perdon" delete the only breast feed. The fix does not depend on clean words (issue #77):

- A reply that claims a change ("corregido", "borré", "fixed", "deleted") goes out only when an edit or delete really ran in that turn. Otherwise what the turn logged is taken back, the brain is asked once to edit, and if it still does not, the parent gets the honest "No pude cambiar el registro".
- A delete runs when the parent asks for one ("borrá", "no le di nada"), or for "sent twice" only when the log really holds the entry twice. "se mando doble" with one entry gets "No borré nada: en el registro la toma de pecho de las 05:20 está una sola vez."
- An edit or delete on a message that corrects nothing never touches an earlier entry, and an amount the message never names is dropped, so an earlier bottle never rides along into "teta izq 15 min".
- Every log confirmation is built from the stored entry: "Anoté la toma de pecho derecho de 12 min de las 05:20." The side is the one the parent said ("teta der" is the right breast). An ounce is 30 ml.
- The next feed is always a time or how long since the last feed. Feeds less than 30 minutes apart are one feed for the rhythm, the interval is said only from at least 4 feeds in the last day, and with fewer feeds more than 6 hours apart the bot names the last feed and how long ago. A question is never answered with "No pude anotarlo".
- Spanish replies use Uruguayan words: mamadera, cédula, mutualista.

## Every confirmation from the log diff (round 3)

The round 3 real-new-parent judge ran 37 phrasings the team had never seen. The log ended wrong in 7 of 9 nights, and 3 of those replies said "Anoté", "Corregí" or "ya anoté el sueño, no hace falta que lo mandes de nuevo" over a lost or corrupted entry. Phrase lists do not fix that, so the structure changed (issue #77):

- The agent takes a snapshot of the log before the turn and one after it. Every confirmation and every "already saved" line is built from that diff, never from the tool calls that ran. A reply that says "anoté", "corregí", "borré", "moví" or "logged" with an empty diff is replaced with "No cambió nada en el registro, así que no quedó anotado. ¿Me lo decís de nuevo?". When the brain fails after a log call, the parent hears exactly what the diff holds, or that nothing was kept. This is shared agent code, so the demo and the family agent have it too.
- A sleep is "anotado" only when a finished sleep with a start and an end is in the log. A wake-up ("ya se levanto", "recién se despertó", "woke") closes the open sleep. A sleep with its length ("durmio 2 horas recien se desperto", "hizo una siestita de 40 min") is one finished sleep ending now, never a new start and never a negative length.
- An edit only touches an entry from the last 4 hours unless the parent names a day or a time ("la de la 1 y 20 fue 80"). When the log call before it failed, a correction asks instead of editing an older entry. A correction right after an ounce message is in ounces, and amounts are whole ml, never 88.72.
- Short follow-ups are corrections: "de mamadera digo", "no espera, fue a las 12", a bare time after "no". "tomo la mitad de la mamadera de 120" is 60 ml. "pecho izquierdo 15" keeps the 15 minutes.
- "q comio ayer en total" is yesterday only: the summary gets an end time.
- A reply that claims an action needs the tool for that action to have run in the turn: "le avisé" or "told" needs call_partner, "announced" needs announce, "saved" needs remember or a log call, "added" needs prep_add, "ticked" needs prep_check. Another acting tool does not cover it. A brain-written "Espero tu sí" line is removed, a sentence with a code word and digits never goes out, and a brain answer in the wrong language is asked for once more in the right one. A turn that only added entries is never undone because Muse said "actualicé el registro".

Measured with `scripts/families_never_wrong_run.py`, which now runs the 70 team messages and the judge's 37 each in a new family. The numbers are in `results/families-never-wrong/README.md`. Tests: `tests/test_log_diff_r3.py`.

Round 2 measurement, before the judge's set: `scripts/families_never_wrong_run.py`, 70 new messages over 3 simulated nights on Muse Spark Open: 0 wrong log states in each of 3 runs. The misses of the earlier rounds and their diffs are in `results/families-never-wrong/README.md`. Tests: `tests/test_never_wrong_log.py`.

## Muse decides the log (log ops, issue #77)

The guards above decided what the parent said from rules, and four blind sets still scored 8, 8, 5 and 11 wrong log states of 45. An ablation (`results/families-log-ablation/README.md`) compared architectures on all 180 messages and then on a fifth blind set. The winner is now the default:

- Each message gets one Muse call that sees what a careful parent sees: the log of the last 30 hours with ids, the open sleep, today's and yesterday's totals, the rhythm line for the next feed and the last 12 messages with their times. Muse returns the log operations as data (add, edit or delete by id, sleep start, sleep end) and a short reply.
- Code only does what code is sure about: ounces to ml at 30 ml an ounce, a clock time on the latest such moment not in the future, the bounds on amounts, lengths and times, and the confirmation built from the log diff. A reply with no operations never says something was logged.
- A Muse answer with no `log_ops` call is asked for once more. If it still has none, as with the free rule brain after the spend cap, the message goes through the guarded loop above.
- Fifth blind set, scored once each: log ops 1 of 45 wrong, the guarded loop 13 of 45, at half the cost and latency.

Round 4 fixes (issue #126, `results/babylog-r4/README.md`):

- A symptom told with a feed ("tomo 70 y vomito un poco") logs the feed and a note with the parent's words in the same turn, whatever Muse proposed. The feed is added by code only when Muse proposed none and the log has no such feed in the last 30 minutes. Without log ops, and on the red flag line ("tomo 40 y vomito todo"), plain code reads the amount or the minutes.
- A symptom reported with no question gets no "No puedo darte consejo médico" tail. A question, a fever and every red flag line keep their fixed lines.
- The reply language is the family's. A Spanish family's "sorry" or "ok" never turns the reply English, only a message clearly in English does. A log ops reply in the wrong language is asked for once more and never sent as it was.
- A bare clock hour ("a las 2", "a las 5 menos cuarto") with no half of the day named lands on the latest of its two readings in code, so "a las 2" said at 15:00 is 14:00. A correction keeps Muse's own reading, since it can mean an earlier entry.
- Yesterday's totals name yesterday's own last entries, and the totals Muse reads carry their dates.

`PA_FAMILIES_LOG_MODE` is `ops` by default, `ops-verify` adds a second checking call (no better on the 180, twice the cost) and `guards` is the old loop. The emergency, red flag, safe sleep and health gates run before any mode. Code: `parenting_agent/agent/log_ops.py`. Tests: `tests/test_log_ops.py`.

## How it is built

| Part | Code |
|---|---|
| Settings, the environment scrub, reading only the brain key and the bot token | `parenting_agent/families/settings.py` |
| Registry, session rows, spend | `parenting_agent/families/store.py` |
| One SQLite file per family: log, conversation, facts | `parenting_agent/families/babylog.py` |
| Invite gate, onboarding, commands, caps, reminders, summaries | `parenting_agent/families/service.py` |
| Telegram long polling and the reminder clock | `parenting_agent/families/bot.py` |
| `run`, `invite`, `check` | `parenting_agent/families/__main__.py` |
| Session export for the scorer | `parenting_agent/families/export_sessions.py` |
| Docker files and the wall check | `deploy/families/` |
| Deploy, check, rollback, backups | `deploy/public.sh`, `deploy/backup.sh` |

Each family gets its own agent with its own bus and its own file, `family-<id>.sqlite` in the data folder, opened by nothing else. The tools are only `log_baby_event`, `edit_baby_event`, `delete_baby_event`, `read_baby_log`, `baby_summary`, `next_feed`, `remember` and `current_time`. There is no Baby Buddy client, no Home Assistant client, no house tool, no channel router and no sitter role in the service. The Telegram adapter is the one from `parenting_agent/channels/telegram.py`, standard library only, so no new package was added.

## Walled off

- The service never loads the family env file. `--keys-env FILE` reads only `ANTHROPIC_API_KEY`, `BASETEN_API_KEY` and `TELEGRAM_FAMILIES_BOT_TOKEN`.
- At start, every variable that could reach the house or holds another secret is removed from the environment, including Gonza's own `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`. Only their names are printed.
- It refuses to start when the families token equals the family bot's token, or when `getMe` says the token belongs to `@home_agent_example_bot`.
- In Docker (`deploy/families/compose.yml`) the container sits only on an internal network with no gateway and no host address. Its one way out is a proxy that allows HTTPS to `api.anthropic.com`, `inference.baseten.co` and `api.telegram.org`. Nothing is published and nothing is on the Cloudflare tunnel, the bot long-polls. It never joins `babybuddy-net`, `home-assistant_default` or `parenting-agent-internal`. No host networking.
- `deploy/families/check-wall.sh` proves it from inside after a deploy.

## Caps

| Cap | Default | Setting |
|---|---|---|
| Messages per family per UTC day, then "back tomorrow" | 150 | `PA_FAMILIES_MAX_MESSAGES` |
| Brain spend per family per UTC day | $0.50 | `PA_FAMILIES_FAMILY_USD` |
| Brain spend for the whole service per UTC day | $3.00 | `PA_FAMILIES_DAILY_USD` |
| Message length | 500 characters | `PA_FAMILIES_MAX_INPUT` |
| Families | 20 | `PA_FAMILIES_MAX_FAMILIES` |
| Wrong invite codes per account per day | 5 | `PA_FAMILIES_MAX_BAD_CODES` |

Over a spend cap the service does not go silent: the free rule-based brain takes over, so "bottle 120 ml" and "when did she last eat?" keep working until the next day. Spend is priced like the demo, at the price of the brain that answered (Muse Spark Open $1.25 and $4.25 per million tokens, Claude Haiku 5.5 $0.10 and $0.50 when it answers as the fallback). A local run of onboarding, 4 messages through Claude, a refusal and a summary cost $0.002.

## Session records for the real-user scorer

`families.sqlite` in the data folder, table `sessions(ts TEXT ISO8601 UTC, visitor_id TEXT, channel TEXT, kind TEXT, internal INTEGER, family_id TEXT)`.

- One row per message a joined parent sends, including the onboarding answers. Strangers, too long messages and messages over the family cap write no row.
- `visitor_id` is the sha256 of the Telegram user id. `channel` is `telegram`, `kind` is `family`, `family_id` is a random 16 hex id.
- `internal` is 1 for Gonza's test accounts (see the invite flow).
- No message text is stored in this file.

```bash
python -m parenting_agent.families.export_sessions                 # JSON lines, oldest first, with family_id
python -m parenting_agent.families.export_sessions --db other/families.sqlite
```

The demo export prints the same columns without `family_id`, and also prints `family_id` if a table has it. `measure-kr222.sh` reads one stream, so on the Vostro both exports are chained:

```bash
KR222_EXPORT_CMD='ssh vostro "docker exec pa-demo python -m parenting_agent.demo.export_sessions; docker exec pa-families python -m parenting_agent.families.export_sessions"' \
  your-scorer.sh
```

Checked on Oct 28 with a simulated export: 3 parents on 3 days, 1 parent on 2 days and 1 internal parent scored "parents 2/3", the internal rows were not counted, and the chained demo and families exports scored together. The scorer's default command now chains both exports like this.

## On the Vostro

Deployed on Oct 28 2026 with `deploy/public.sh`, from the Mac in a clean checkout. Two containers in the compose project `pa-families`: `pa-families` (only on `pa-families-internal`, isolated gateway, nothing published) and `pa-families-egress` (HTTPS to the brain and api.telegram.org only).

- Env file `~/apps/pa-families.env`, mode 600, written by `push-env` with only `BASETEN_API_KEY`, `ANTHROPIC_API_KEY` (the fallback), `TELEGRAM_FAMILIES_BOT_TOKEN`, `PA_FAMILIES_BOT_USERNAME` and `PA_FAMILIES_INTERNAL_USERS` (Gonza's Telegram user id, taken from `TELEGRAM_CHAT_ID`).
- Data `~/apps/pa-families-data`, owned by the container user (uid 10002), mode 700. Backed up daily with the demo (see `docs/demo-app.md`).
- Health: the container runs with no restarts and its log says `families: polling started`, then `families check` inside.

```bash
sh deploy/public.sh families push-env
WALL_EXTRA_TARGETS="192.0.2.10:80 192.0.2.10:22" sh deploy/public.sh families deploy
sh deploy/public.sh families check | status | logs 200 | stop | start
docker exec pa-families python -m parenting_agent.families invite --count 3    # on the Vostro
```

On Oct 28 the wall check passed with 110 probes blocked or refused, and the proxy allowed only the brain and Telegram.

Still open: send `/setjoingroups` to @BotFather and pick Disable, so the bot cannot be added to groups (it already answers groups with "please message me directly").
