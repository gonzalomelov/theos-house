"""Rules the fake brain uses offline: turn a parent's note into a log event, answer from a summary, refuse health questions.

The real brain (Claude now, Muse Spark Open later) does this from the tool descriptions. These rules let
the tests check the whole path to Baby Buddy and back with no network, and give the fake brain the same
behaviour the system prompt asks of the real one.
"""
import datetime
import re

ML = re.compile(r"(\d+(?:\.\d+)?)\s*ml", re.I)
MINUTES = re.compile(r"(\d+)\s*(?:min|minutes)", re.I)
SPAN = re.compile(r"from\s+(\d{1,2})[:.](\d{2})\s+(?:to|until)\s+(\d{1,2})[:.](\d{2})", re.I)
MEDICAL = re.compile(r"\b(fever|temperature|medicine|medication|dose|dosage|paracetamol|ibuprofen|rash|vomit|sick|"
                     r"diagnos|should i give|is it normal|cough|infection|antibiotic|tylenol|acetaminophen|motrin|advil|"
                     r"calpol|nurofen|simethicone|gripe water|teething gel)", re.I)
# Tired parents skip the accents and the question mark: "a q hr le toca", "cuanto durmio", "y cuantos pañales".
QUESTION_START = re.compile(r"^(y |and )?(when|how|what|did|has|have|is|was|why|cu[aá]nd[oa]|cu[aá]nt[oa]s?|qu[eé]|q|a qu[eé]|a q|"
                            r"c[oó]mo|d[oó]nde|por qu[eé]|para cu[aá]ndo|hace cu[aá]nto|desde cu[aá]ndo|le toca|"
                            r"toca\b|cada cu[aá]nto)\b", re.I)
# Health words in Spanish, on top of the English ones in MEDICAL. A bottle the parent gives ("le doy la mamadera") is
# not one of them, only a question about what to give ("le puedo dar").
MEDICAL_ES = re.compile(r"\b(fiebre|temperatura|medicamento|medicina|remedio|dosis|paracetamol|ibuprofeno|sarpullido|"
                        r"erupci|v[oó]mit|enferm|diagn[oó]s|tos\b|infecci|antibi[oó]tic|es normal|le puedo dar|puedo darle|"
                        r"c[oó]lico|gotas para)", re.I)
# Red flags: an answer in no time, with no brain call, that says to call emergency services. Fussing and crying are
# not on the list, they get the likely reason from the log instead.
EMERGENCY = re.compile(
    r"\b(not breathing|stopped breathing|isn'?t breathing|can'?t breathe|cannot breathe|struggling to breathe|"
    r"(blue|purple|gr[ae]y) (lips|face)|lips (are |look |turned |turning )?(blue|purple|gr[ae]y)|turn(ed|ing|s)? (blue|purple)|"
    r"limp|floppy|chok(e|es|ed|ing)|won'?t wake|wont wake|can'?t wake|cannot wake|not waking|unresponsive|"
    r"fell (off|from|down|out of)|had a fall|dropped (him|her|the baby)|hit (his|her|the|its) head|head injury|seizure|convuls\w*|"
    r"no respira|dej[oó] de respirar|le cuesta respirar|no puede respirar|morad[oa]s?|labios azules|se puso azul|"
    r"se (est[aá] )?ahog\w*|atragant\w*|no se despierta|no reacciona|no responde|"
    r"se (me )?cay[oó](?! (el|la) (chupete|mamadera|biber[oó]n|tete|juguete))|"
    r"se golpe[oó]|golpe en la cabeza|convulsi\w*|"
    # Bath, changing table and breathing red flags a safety audit found missing (round 2), English then rioplatense.
    r"gasp\w*|(trouble|difficulty|hard time|problems?) breathing|breath(ing|es) (really |very |so |too )?(fast|hard|rapid\w*|weird\w*|strange\w*)|"
    r"labou?red breathing|went under(?! (the |his |her |a )?(blanket|covers|sheets?|table|bed|crib|cot|sofa|couch|chair))|(head|face) went under|slipped under|under (the )?water|drown\w*|"
    r"(swallowed|ate|ingested|put) (a |an |the |some |one of the |two )?(button |coin )?(battery|batteries|magnets?)\b|"
    r"(swallowed|drank|ate) (some )?(bleach|detergent|a (laundry |detergent )?pod)|poison\w*|"
    r"(bulging|swollen) (soft spot|fontanel\w*)|(soft spot|fontanel\w*) (is |looks |seems )?(bulging|swollen|puffy)|"
    r"(pale|grey|gray) and cold|cold and (pale|grey|gray)|scald\w*|burn(ed|t) (him|her|the baby|his|her)|"
    r"unconscious|passed out|faint(ed|ing)|(he|she|baby)('s| is)? (not|isn'?t) moving|"
    r"boque\w*|le falta (el )?aire|(dificultad|le cuesta) (para )?respirar|"
    r"respira (muy |re |demasiado )?(r[aá]pido|agitad\w*|raro|con dificultad)|"
    r"se (me )?hundi[oó]|(bajo|abajo|debajo) (del|el) agua|ahogad\w*|"
    r"(trag[oó]|se comi[oó]|se trag[oó]) (una |un |la |el |unas |unos )?(pila|pilas|bater[ií]a\w*|im[aá]n|imanes|lavandina|detergente)|"
    r"(pila|pilas|bater[ií]a\w*|im[aá]n|imanes)\b.{0,25}\b(se )?(lo |la |los |las )?trag[oó]|pila de bot[oó]n|envenen\w*|intoxic\w*|"
    r"(fontanela|mollera) (est[aá] |se ve |muy )?(abultad\w*|hinchad\w*|inflad\w*)|"
    r"p[aá]lid[oa] y fr[ií][oa]|fr[ií][oa] y p[aá]lid[oa]|se (me )?quem[oó]|quemadura|"
    r"se desmay[oó]|desmayad[oa]|inconsciente|no se mueve)", re.I)
# A question on how a baby sleeps safely gets the AAP's public safe sleep line, the same every time, never the brain's
# words and never a refusal with no fact. Anything that also names a symptom stays refused.
SLEEP_WORD = r"(sleep\w*|slept|asleep|nap\w*|put (him|her|the baby|my baby|them) down|crib|cot|bassinet|dorm\w*|duerm\w*|siesta\w*|cuna|mois[eé]s|acost\w*)"
SLEEP_POSITION = (r"(tumm(y|ies)|stomach|belly|on (his|her|its|their|the) (side|back|front|face)|side[ -]?sleep\w*|face ?down|"
                  r"prone|boca (abajo|arriba)|de (costado|lado|panza|espaldas)|panza (abajo|arriba))")
SAFE_SLEEP = re.compile(
    SLEEP_WORD + r".{0,40}" + SLEEP_POSITION + "|" + SLEEP_POSITION + r".{0,40}" + SLEEP_WORD + "|"
    r"safe(st|ly|r)? (way|position|place) (for (him|her|the baby|a baby|my baby) )?to (sleep|nap)|safe sleep|sleep\w* safely|"
    r"what position .{0,30}" + SLEEP_WORD + "|"
    r"(pillows?|blankets?|bumpers?|stuffed|toys?|quilts?|duvets?|almohad\w*|mantas?|frazadas?|chichoneras?|peluches?|acolchad\w*)"
    r".{0,40}" + SLEEP_WORD + "|" + SLEEP_WORD + r".{0,40}(pillows?|blankets?|bumpers?|stuffed|toys?|quilts?|duvets?|"
    r"almohad\w*|mantas?|frazadas?|chichoneras?|peluches?|acolchad\w*)|"
    r"co-?sleep\w*|bed[ -]?shar\w*|colecho|" + SLEEP_WORD + r".{0,30}(in|on) (our|my|the) (bed|couch|sofa)|"
    + SLEEP_WORD + r".{0,30}(en|con) (nuestra|mi|la) cama|" + SLEEP_WORD + r".{0,30}(sill[oó]n|sof[aá])|"
    + SLEEP_WORD + r".{0,40}(car ?seat|swing|sling|incline\w*|sillita|silla del auto|hamaca|mecedora)|"
    r"(car ?seat|swing|sling|sillita|silla del auto|hamaca).{0,40}" + SLEEP_WORD + "|"
    r"(forma|manera|posici[oó]n) (m[aá]s )?segur\w* (de|para) (dormir|acostar\w*)|sue[ñn]o seguro|dormir segur\w*", re.I)
SAFE_SLEEP_ASK = re.compile(r"\?|\b(can|could|should|is it|is that|ok|okay|safe\w*|how|what|which|where|puedo|debo|"
                            r"deber[ií]a|est[aá] bien|es seguro|segur\w*|c[oó]mo|qu[eé]|cu[aá]l|d[oó]nde|conviene|hay que)\b", re.I)
SAFE_SLEEP_SOURCE = "https://www.healthychildren.org/English/ages-stages/baby/sleep/Pages/a-parents-guide-to-safe-sleep.aspx"
SAFE_SLEEP_FACT = {
    "en": ("This is the public safe sleep guidance of the American Academy of Pediatrics, for every baby, not advice about "
           "yours: on the back for every nap and at night, on a firm, flat surface, with nothing else in the crib (no pillows, "
           "blankets, bumpers or toys). Room sharing yes, bed sharing no. A baby who falls asleep in a car seat, swing or "
           f"sling is moved to a firm, flat surface, on the back. Source: {SAFE_SLEEP_SOURCE} "
           "For anything about your baby's health, ask your pediatrician."),
    "es": ("Esta es la guía pública de sueño seguro de la Academia Estadounidense de Pediatría (AAP), para todos los bebés, "
           "no un consejo sobre el tuyo: boca arriba en todas las siestas y de noche, sobre una superficie firme y plana, sin "
           "nada más en la cuna (ni almohadas, ni mantas, ni chichoneras, ni juguetes). Dormir en el mismo cuarto sí, en la "
           "misma cama no. Si se duerme en la sillita del auto, la hamaca o el fular, se pasa a una superficie firme y plana, "
           f"boca arriba. Fuente: {SAFE_SLEEP_SOURCE} Para cualquier cosa de la salud de tu bebé, consultá a tu pediatra."),
}
# Health and feeding-safety talk. Never a log request, so the not-logged check never answers it with "send it again".
HEALTH = re.compile(r"\b(can i|could i|should i|is it ok|is it safe|safe to|puedo|debo|deber[ií]a|es seguro|"
                    r"cereal|honey|miel|water|agua|not (pooped|peed|eaten)|hasn'?t (pooped|peed|eaten)|"
                    r"no (hizo|ha hecho) (caca|pis)|in \d+ days|\d+ d[ií]as sin|hace \d+ d[ií]as)\b", re.I)
# A message that corrects or removes an entry already in the log.
# Typed at 3 AM: "nono eran 70", "ahh no, 110", "eran 70 nomas", "se mando doble", "me equivoque fueron 80".
EDIT = re.compile(r"\b(perd[oó]n|perdon|correg\w*|corrij\w*|cambi[aá](la|lo)?|borr[aá](la|lo)?|elimin[aá](la|lo)?|sac[aá](la|lo)|"
                  r"quit[aá](la|lo)?|me equivoqu[eé]|me confund\w*|no,? eran?|(no){2,}|no no|no+,? \d+|eran? (de )?\d+(?! *(mamaderas|tomas|pa[ñn]ales))|"
                  r"eran? \d+ no|fue de \d+|fue \d+|fueron \d+(?! *(mamaderas|tomas|pa[ñn]ales))|no,? fue|no,? era|en realidad|o sea|"
                  r"(ese|esa|eso|el|la|lo) .{0,25}\bera (solo|s[oó]lo|nada m[aá]s|de|un|una)\b|era (solo|s[oó]lo)\b|"
                  r"(dos|2) veces|sin querer|duplicad\w*|repetid\w*|doble|se mand\w*|"
                  r"(it|that) was \d+|was \d+ not|not \d+|delete|remove|undo|wrong|mistake|sent (it )?twice|twice by|"
                  r"correct (it|that)|fix (it|that)|change (it|that)|actually)\b", re.I)
# A message that asks for an entry to go, not only to be changed: a delete runs on one of these, or on a "sent twice"
# only when the log really holds the entry twice.
DELETE_SAID = re.compile(r"\b(borr[aá]\w*|elimin[aá]\w*|sac[aá]\w*|quit[aá]\w*|delete|remove|undo|no (le )?(di|dimos|dio|tom[oó])\b|"
                         r"no (fue|hubo|pas[oó]) nada|no pas[oó]|nunca pas[oó]|never happened|didn'?t happen)", re.I)
TWICE_SAID = re.compile(r"(dos|2) veces|sin querer|duplic|repet|doble|se mand|lo mand|la mand|twice|by mistake|double", re.I)
# A reply that says an entry was changed or removed. It goes out only when an edit or delete really ran in that turn.
CLAIMS_CHANGE = re.compile(r"\b(correg[ií](do|da|dos|das)?|corrij[oe]|cambi[eé]|cambiad[oa]s?|actualic[eé]|actualizad[oa]s?|"
                           r"modifiqu[eé]|modificad[oa]s?|borr[eé]|borrad[oa]s?|elimin[eé]|eliminad[oa]s?|saqu[eé]|quit[eé]|"
                           r"quitad[oa]s?|fixed|corrected|deleted|removed|updated|changed)\b", re.I)
NEGATED = re.compile(r"\b(no|not|nothing|never|nunca|nada|sin|n't)\b[^.!?]{0,25}$|n't\s*$", re.I)
# The parent's answer to "did you send it twice or were there two bottles?"
# Strong words for "I sent it twice": checked before the "two" words, so "la mandé otra vez" is one.
DOUBLE_ONCE = re.compile(r"(dos|2) veces|sin querer|repet|duplic|doble|se mand|lo mand|la mand|mand[eé] (dos|2|de nuevo|otra)|"
                         r"la misma|el mismo|me equivoqu|error|twice|by mistake|double|same (one|bottle|feed)", re.I)
DOUBLE_TWO = re.compile(r"(dos|2) (mamaderas|tomas|biberones|veces le di)|fueron (dos|2)|son (dos|2)|\botra\b(?! vez)|"
                        r"una m[aá]s|segunda|tom[oó] (de nuevo|otra)|two (bottles|feeds)|another|second|there were two|"
                        r"were two|both|^\W*(dos|2|two)\W*$", re.I)
# Weak words for one, checked last: "una", "una sola", "solo una", "just one".
DOUBLE_ONE = re.compile(r"\buna sola\b|\bsolo una\b|\bera una\b|\bfue una\b|^\W*(una|uno|1|one|once)\W*$|just one|"
                        r"only one|\bonce\b", re.I)
CRY = re.compile(r"\b(cry|crying|cries|cried|fussy|fussing|screaming|llor\w*|berrinche|molest[oa])\b", re.I)
SIDE_SAID = re.compile(r"izquierd|derech|\bizq|\bder\b|\bdcha\b|ambos|los dos|las dos|left|right|both", re.I)
BOTH_SIDES = re.compile(r"ambos|los dos|las dos|both|(izq\w*|left)\W+(y|e|and|\+|,)\W*(der\w*|right)|"
                        r"(der\w*|right)\W+(y|e|and|\+|,)\W*(izq\w*|left)", re.I)
LEFT_SAID = re.compile(r"izquierd|\bizq\w*|\bleft\b", re.I)
RIGHT_SAID = re.compile(r"derech|\bder\b|\bdcha\b|\bright\b", re.I)
TYPE_SAID = {"formula": re.compile(r"f[oó]rmula|formula|leche de f", re.I),
             "breast milk": re.compile(r"leche materna|materna|extra[ií]da|sacada|breast ?milk|pumped|expressed", re.I)}
TIME_SAID = re.compile(r"\d{1,2}[:.h]\d{2}|\d{1,2}\s*(am|pm|hs?)\b|\ba las?\s+\d|\bat \d|\bhace\b|\bago\b|y media|y cuarto|"
                       r"menos cuarto|anoche|esta ma[ñn]ana|madrugada|this morning|last night|earlier|\bantes\b|from \d|"
                       r"de \d{1,2} a \d{1,2}|\bayer\b|yesterday|\bla de la", re.I)
MINUTES_SAID = re.compile(r"\d+\s*(min|minutos|minutes|mins)\b|\d+\s*m\b|media hora|half an hour", re.I)
COLOR_SAID = re.compile(r"amarill|verde|marr[oó]n|negr|roj|yellow|green|brown|black|red", re.I)

# Spanish note words to the English ones parse_note knows, so "mamadera 120 ml" or "pañal sucio" read as notes too.
NOTE_WORDS_ES = [
    (r"pa[ñn]al(es)?", "diaper"), (r"sucio|caca", "dirty"), (r"mojado|pis|pich[ií]", "wet"),
    (r"se ba[ñn][oó]|ba[ñn]o|ba[ñn]ad[oa]", "bath"), (r"se durmi[oó]|dormid[oa]|se qued[oó] dormid[oa]", "fell asleep"),
    (r"se despert[oó]|despiert[oa]", "woke"), (r"teta|pecho", "breast"), (r"izquierd[oa]", "left"),
    (r"derech[oa]", "right"), (r"mamadera|biber[oó]n", "bottle"), (r"tom[oó]|comi[oó]", "drank"),
    (r"cu[aá]nto", "how much"), (r"cu[aá]ndo", "when"), (r"cu[aá]ntos|cu[aá]ntas", "how many"),
]
SPANISH = re.compile(r"[ñáéíóú¿¡]|\b(se|le|la|el|de|del|un|una|y|con|ya|reci[eé]n|hoy)\b", re.I)
# A reply that says something went into the log. "Noted" and "OK" are not claims, so small talk is never one.
CLAIMS_LOGGED = re.compile(r"\b(logged|recorded|added (it )?to the log|anot[eé]|anotad[oa]s?|registr[eé]|registrad[oa]s?)\b", re.I)
# A reply that says the agent reached someone or did something in the house: sent, called, announced, asked, told.
CLAIMS_ACTED = re.compile(
    r"\b(sent|texted|messaged|notified|pinged|announced|(asked|called|told) (him|her|them|your|ceci|gonza|the)|"
    r"let (him|her|them|your partner) know|(trying|going) to reach|reach(ed|ing)|"
    r"(is|are) on (his|her|their|the) way|request (was |has been )?(sent|made)|"
    r"envi[eé]|enviad[oa]s?|mand[eé]|mandad[oa]s?|avis[eé]|avisad[oa]s?|llam[eé]|le ped[ií]|les ped[ií]|le escrib[ií]|"
    r"anunci[eé]|le dije|les dije|va en camino|est[aá] en camino|pedido enviado|solicitud enviada)\b", re.I)

# A medicine the parent gave, a milestone, or an explicit ask to log: a health message with one of these is logged
# first (a medicine or a symptom goes in as a note), and only the advice part is refused.
MEDICINE = re.compile(r"\b(medicine|medication|dose|dosage|paracetamol|acetaminophen|tylenol|ibuprofen|motrin|advil|drops|"
                      r"syrup|antibiotic|vitamin|medicamento|medicina|remedio|dosis|ibuprofeno|gotas|jarabe|antibi[oó]tic\w*|"
                      r"vitamina)\b", re.I)
SYMPTOM = re.compile(r"\b(fever|temperature|rash|vomit\w*|sick|cough\w*|infection|diarrh\w*|fiebre|temperatura|sarpullido|"
                     r"erupci\w*|v[oó]mit\w*|enferm\w*|tos|infecci\w*|diarrea)\b", re.I)
LOG_ASK = re.compile(r"\b(log|logged|note (it|that|down)|write (it|that)? ?down|add (it|that)|record (it|that)|keep a note|"
                     r"save (it|that)|anot[aá]\w*|registr[aá]\w*|apunt[aá]\w*|guard[aá]\w*)\b", re.I)
GAVE = re.compile(r"\b(i gave|we gave|i just gave|gave (him|her|the baby|it)|was given|she had (her|the)|he had (his|the)|"
                  r"le di|le dimos|le dio|le acabo de dar|le administr\w*|tom[oó] (el|la|su|las|los))\b", re.I)
MILESTONE = re.compile(r"\b(rolled over|roll(ed)? over|first time|first smile|smiled|laughed|milestone|sat up|crawl\w*|"
                       r"first tooth|por primera vez|se dio vuelta|se di[oó] vuelta|sonri[oó]|se ri[oó]|primer\w* (sonrisa|diente)|"
                       r"gate[oó]|se sent[oó])\b", re.I)
ADVICE = re.compile(r"\?|\b(should i|should we|can i|can we|could i|is it normal|is that normal|is this normal|is it ok|"
                    r"is it safe|how much (should|do|can)|what (dose|should)|do i need|puedo|debo|deber[ií]a|es normal|"
                    r"le puedo dar|qu[eé] le doy|cu[aá]nto le doy|le doy)\b", re.I)
# What a parent's message may never carry into the transcript: the square brackets the agent uses for its own lines,
# "[observation from ...]" and "[check from the agent ...]". A parent can never pose as a sensor or as the agent.
BRACKETS = str.maketrans({c: "(" for c in "[\uff3b\u27e6\u3010\u3014\u2045\u3016\u301a"} | {c: ")" for c in "]\uff3d\u27e7\u3011\u3015\u2046\u3017\u301b"})
# Secrets and codes: never read aloud on a shared speaker, never sent in a free-text push, never kept as a fact.
SECRET = re.compile(r"\b(code|c[oó]digo|pin|password|passcode|passwd|contrase[ñn]a|clave|alarm|alarma|gate|port[oó]n|"
                    r"wi-?fi|key ?code|keypad|lock|combination|combinaci[oó]n|cvv|card|tarjeta|account|cuenta|token)\b|"
                    r"\d(?:[\s.-]?\d){3,}|@\w+\.\w+", re.I)
CODE_WORD = re.compile(r"\b(code|c[oó]digo|pin|password|passcode|passwd|contrase[ñn]a|clave|alarm|alarma|wi-?fi|key ?code|"
                       r"keypad|combination|combinaci[oó]n|cvv|token)\b", re.I)
CODE_NUMBER = re.compile(r"(?<![\w.])\d(?:[\s.-]?\d){3,}(?![\w])")
CONTACT = re.compile(r"@|\+?\d(?:[\s.-]?\d){5,}|\b(street|st\.|avenue|ave\.|road|calle|avenida|apto|apt|esquina|"
                     r"barrio|zip|postal)\b", re.I)
# The only sentences a house speaker says, in the demo and in the family's kitchen. Free text never reaches a speaker,
# so a gate code or a name typed in a message is never read aloud.
ANNOUNCEMENTS = {
    "come_help": "Can someone come and help with the baby, please?",
    "bring_diaper": "Could someone bring a clean diaper and wipes, please?",
    "bring_bottle": "Could someone bring a bottle, please?",
    "bring_clothes": "Could someone bring clean baby clothes, please?",
    "baby_asleep": "The baby is asleep, please keep it quiet.",
    "feed_soon": "The next feed is coming up soon.",
    "bath_time": "It is bath time.",
    "door": "Someone is at the door, the parent's hands are busy.",
    "dinner_ready": "Dinner is ready.",
    "start_dinner": "Time to start dinner.",
}
# Bounds per event type. A value outside them is asked about, never logged.
BOUNDS = {"amount_ml": (1, 300), "duration_min": (1, 120), "sleep_hours": 14, "future_min": 5}
WORD = re.compile(r"[a-záéíóúñü]{4,}", re.I)
STOP = {"that", "this", "with", "from", "have", "your", "what", "when", "were", "will", "just", "they", "them", "then",
        "there", "about", "baby", "para", "como", "pero", "esta", "este", "todo", "tiene"}

REFUSAL = ("I can't give medical advice. Please call your pediatrician about that. If it is urgent, call emergency "
           "services (911 in Uruguay, or your local emergency number). If you tell me what you saw or gave, I will note it "
           "so you have it ready for the call.")
NO_ADVICE = {"en": "I can't give medical advice on it: please ask your pediatrician, or call emergency services (911 in "
                   "Uruguay) if it is urgent.",
             "es": "No puedo darte consejo médico sobre eso: consultá a tu pediatra, o llamá al 911 si es urgente."}
EMERGENCY_REPLY = {
    "en": "This may be an emergency. Call emergency services now: 911 in Uruguay, or your local emergency number.",
    "es": "Puede ser una emergencia. Llamá ya al 911 (emergencias en Uruguay) y contales lo que ves.",
}


def is_medical(text):
    return bool(MEDICAL.search(text))


def is_emergency(text):
    return bool(EMERGENCY.search(text or ""))


def is_safe_sleep_question(text):
    """A question on how a baby sleeps safely, with no symptom, medicine or red flag in it."""
    text = text or ""
    return (bool(SAFE_SLEEP.search(text)) and bool(SAFE_SLEEP_ASK.search(text)) and not is_emergency(text)
            and not is_medical(text) and not is_medical_es(text) and not SYMPTOM.search(text))


def is_medical_es(text):
    return bool(MEDICAL_ES.search(text or ""))


def is_health(text):
    """Any health, safety or emergency talk, in English or Spanish. Never treated as a note to log."""
    return is_medical(text) or is_medical_es(text) or is_emergency(text) or bool(HEALTH.search(text or ""))


def is_edit_request(text):
    return bool(EDIT.search(text or "")) and not is_health(text)


def double_answer(text):
    """"once" when the parent sent the same note twice by mistake, "two" when there were two, None when unclear."""
    text = (text or "").strip()
    if DOUBLE_ONCE.search(text):
        return "once"
    if DOUBLE_TWO.search(text):
        return "two"
    if DOUBLE_ONE.search(text):
        return "once"
    return None


def asks_delete(text):
    """True when the parent asks for an entry to go: "borrá la última", "no le di nada"."""
    return bool(DELETE_SAID.search(text or ""))


WOKE_SAID = re.compile(r"despert|despiert|\bwoke\b|\bwakes?\b|\bawake\b", re.I)
ASLEEP_SAID = re.compile(r"durm|dorm|asleep|\bnap", re.I)


def says_woke_only(text):
    """True when the parent reports a wake-up and no falling asleep: "se desperto a las 5", not "se desperto y se durmio"."""
    text = text or ""
    return bool(WOKE_SAID.search(text)) and not ASLEEP_SAID.search(text)


def says_twice(text):
    return bool(TWICE_SAID.search(text or ""))


def claims_change(text):
    """True when a reply says an entry was corrected or removed, and does not say the opposite ("no cambié nada")."""
    text = text or ""
    return any(not NEGATED.search(text[max(0, m.start() - 40):m.start()]) for m in CLAIMS_CHANGE.finditer(text))


def is_cry_question(text):
    return bool(CRY.search(text or "")) and not is_emergency(text)


WET_SAID = re.compile(r"wet|pee|wee|pis|mojad|orin|me[oó]\b|meado|both|ambos|los dos|y (con )?caca|and dirty|and poo", re.I)
SOLID_SAID = re.compile(r"dirty|poo|solid|caca|sucio|pop[oó]|deposici|cacona|both|ambos|los dos", re.I)


def said_only(request, kind, details, ts=None):
    """The log call's details and time, without anything the parent did not say: no breast side, milk type, duration,
    amount, diaper color or time the brain made up. Returns (details, ts)."""
    details = dict(details or {}) if isinstance(details, dict) else {}
    request = request or ""
    timed = bool(TIME_SAID.search(request))
    if not timed:
        ts = None
        if kind != "sleep":
            for name in ("start", "end", "time"):
                details.pop(name, None)
    if kind == "feeding":
        method = str(details.get("method") or "")
        if "breast" in method.lower():
            # The side the parent said, never one the brain picked: "teta der" is the right breast.
            details["method"] = side_said(request) or "breast"
        milk = details.get("type")
        if milk and not any(pattern.search(request) for pattern in TYPE_SAID.values()):
            details.pop("type", None)
        if details.get("duration_min") is not None and not MINUTES_SAID.search(request):
            details.pop("duration_min", None)
        if details.get("amount_ml") is not None and not re.search(r"\d", request):
            details.pop("amount_ml", None)
        if details.get("amount_ml") is not None and ounces_ml(request):
            # "3 onzas" is 90 ml on the bottle, never the brain's 89.
            details["amount_ml"] = ounces_ml(request)
        elif details.get("amount_ml") is not None and not amount_said(details["amount_ml"], request):
            # An amount the message never names comes from an earlier message: on Oct 29 Muse logged the 00:40 bottle's
            # 120 ml again inside "teta izq 15 min".
            details.pop("amount_ml", None)
        breast_said, bottle_said = BREAST_WORDS.search(request), BOTTLE_WORDS.search(request)
        if breast_said and not bottle_said and "breast" not in str(details.get("method") or ""):
            details["method"] = side_said(request) or "breast"
            if not re.search(r"\d+\s*ml", request, re.I):
                details.pop("amount_ml", None)
        elif bottle_said and not breast_said and "breast" in str(details.get("method") or ""):
            details["method"] = "bottle"
    if kind == "diaper" and details.get("color") and not COLOR_SAID.search(request):
        details.pop("color", None)
    if kind == "diaper" and details.get("wet") and details.get("solid"):
        # Both only when the parent said both: "she pooped, dirty diaper" is not a wet diaper.
        if not WET_SAID.search(request):
            details.pop("wet", None)
        elif not SOLID_SAID.search(request):
            details.pop("solid", None)
    return details, ts


DAY_SAID = re.compile(r"\b(ayer|anoche|anteayer|yesterday|last night|lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|"
                      r"domingo|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b|\d{1,2}/\d{1,2}", re.I)


OUNCES = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:onzas?|oz|ounces?)\b", re.I)
ML_PER_OUNCE = 30


BREAST_WORDS = re.compile(r"\b(teta|tetas|pecho|pechos|breast\w*|nurs\w*|amamant\w*)\b", re.I)
BOTTLE_WORDS = re.compile(r"\b(mamadera|biber[oó]n|bottle|f[oó]rmula|formula)\b|\d\s*ml\b|\bonzas?\b", re.I)


def amount_said(amount, text):
    """True when the message names this amount: "le di 90" for 90 ml."""
    try:
        wanted = float(amount)
    except (TypeError, ValueError):
        return False
    return any(abs(float(n.replace(",", ".")) - wanted) < 0.5 for n in re.findall(r"-?\d+(?:[.,]\d+)?", text or ""))


def ounces_ml(text):
    """The ml of "tomo 3 onzas", at 30 ml an ounce as the bottle marks read, or None. One amount only."""
    found = OUNCES.findall(text or "")
    if len(found) != 1:
        return None
    return round(float(found[0].replace(",", ".")) * ML_PER_OUNCE)


def side_said(text):
    """The breast side a message names, as a log method, or None."""
    text = text or ""
    if BOTH_SIDES.search(text) or (LEFT_SAID.search(text) and RIGHT_SAID.search(text)):
        return "both breasts"
    if LEFT_SAID.search(text):
        return "left breast"
    if RIGHT_SAID.search(text):
        return "right breast"
    return None


def latest_time(ts, now, request=""):
    """A clock time the parent named, "a las 4 y media", is the latest such time not after now. The brain sometimes
    puts it on the wrong day, so its date is kept only when the parent named a day."""
    if not ts or DAY_SAID.search(request or ""):
        return ts
    try:
        moment = datetime.datetime.fromisoformat(str(ts))
    except ValueError:
        return ts
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=now.tzinfo)
    moment = moment.astimezone(now.tzinfo)
    latest = now.replace(hour=moment.hour, minute=moment.minute, second=moment.second, microsecond=0)
    if latest > now:
        latest -= datetime.timedelta(days=1)
    return latest.isoformat(timespec="seconds")


MANY_DIAPERS = re.compile(r"\b(dos|tres|2|3|two|three|otro|another|second|segundo)\b.{0,20}(pa[nñ]al|diaper)|"
                          r"(pa[nñ]al|diaper)es.{0,10}\b(dos|tres|2|3)|\bdiapers\b|pa[nñ]ales", re.I)


def one_diaper(calls, request):
    """One diaper the parent reported is one entry. A brain can split "she pooped, dirty diaper" into a wet call and a
    dirty call, so the diaper calls of one reply become one call with both, unless the parent named more diapers."""
    diapers = [c for c in calls if c.get("name") == "log_baby_event" and (c.get("arguments") or {}).get("kind") == "diaper"]
    if len(diapers) < 2 or MANY_DIAPERS.search(request or ""):
        return calls
    merged = {}
    for call in diapers:
        for key, value in ((call["arguments"] or {}).get("details") or {}).items():
            merged[key] = merged.get(key) or value
    first = {**diapers[0], "arguments": {**diapers[0]["arguments"], "details": merged}}
    return [first if c is diapers[0] else c for c in calls if c is diapers[0] or c not in diapers]


KIND_WORDS = {
    "feeding": re.compile(r"\b(bottle|breast|feed|fed|nursed|formula|milk|ml|mamadera|biber[oó]n|teta|pecho|toma|tom[oó]|leche|"
                          r"f[oó]rmula|mililitros|milliliters?)\b|\d+\s*ml\b|breastfed", re.I),
    "diaper": re.compile(r"diaper|pa[nñ]al|\bwet\b|dirty|poo|\bpee\b|caca|\bpis\b|mojad|sucio|pop[oó]", re.I),
    "sleep": re.compile(r"sleep|slept|asleep|\bnap|woke|wake|awake|dorm|durm|siest|despert|sue[nñ]o", re.I),
    "bath": re.compile(r"\bbath|ba[nñ][oóé]|ba[nñ]amos|ba[nñ]ar", re.I),
}


def kinds_said(text):
    """The log kinds a message talks about. A brain can log earlier messages again inside a new one: a sleep note
    that also logs the 02:00 bottle. Only the kinds in the newest message are logged for it."""
    return {kind for kind, words in KIND_WORDS.items() if words.search(text or "")}


CLOCK_ES = re.compile(r"\ba las? (\d{1,2})(?:[:.](\d{2})| y (media|cuarto|diez|veinte|cinco|\d{1,2}\b(?!\s*(?:min|ml))))?"
                      r"(?!\s*(?:min|ml|hs?\b))", re.I)
MINUTE_WORDS = {"media": 30, "cuarto": 15, "diez": 10, "veinte": 20, "cinco": 5}
RANGE_SAID = re.compile(r"\bde (las? )?\d{1,2}.{0,12}\ba (las? )?\d|\bfrom \d{1,2}.{0,12}\b(to|until|till) \d|\bdesde\b|\bhasta\b", re.I)
CLOCK_EN = re.compile(r"\bat (\d{1,2})(?:[:.](\d{2}))?\s*(am|pm)?\b(?!\s*(?:min|ml))", re.I)


def named_time(request, now):
    """The clock time a note names, "a las 3", "a las 4 y media", "at 3:15", as the latest such moment not after now,
    or None when it names none or more than one. "a las 3" at 15:20 is 15:00, at 03:20 it is 03:00."""
    found = [(m.group(1), m.group(2), m.group(3)) for m in CLOCK_ES.finditer(request or "")] + \
            [(m.group(1), m.group(2), m.group(3)) for m in CLOCK_EN.finditer(request or "")]
    if len(found) != 1 or DAY_SAID.search(request or "") or RANGE_SAID.search(request or ""):
        return None
    hour, minute, extra = found[0]
    extra_low = (extra or "").lower()
    hour = int(hour)
    minute = int(minute) if minute else (int(extra_low) if extra_low.isdigit() else MINUTE_WORDS.get(extra_low, 0))
    if hour > 23 or minute > 59:
        return None
    if (extra or "").lower() in ("am", "pm"):
        hours = [hour % 12 + (12 if extra.lower() == "pm" else 0)]
    else:
        hours = [hour] if hour >= 12 or hour == 0 else [hour, hour + 12]
    moments = []
    for h in hours:
        moment = now.replace(hour=h, minute=minute, second=0, microsecond=0)
        moments.append(moment if moment <= now else moment - datetime.timedelta(days=1))
    return max(moments).isoformat(timespec="seconds")


def is_question(text):
    return "?" in text or bool(QUESTION_START.search(text.strip()))


def latest_span(h1, m1, h2, m2, now=None):
    """A "from 23:00 to 00:00" span as the latest one already over: it ends at the latest such time not after now and
    starts before its end, so a span across midnight keeps its start on the day before."""
    now = now or datetime.datetime.now().astimezone()
    end = now.replace(hour=h2, minute=m2, second=0, microsecond=0)
    if end > now:
        end -= datetime.timedelta(days=1)
    start = end.replace(hour=h1, minute=m1)
    if start >= end:
        start -= datetime.timedelta(days=1)
    return start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds")


def parse_note(text):
    """(kind, details) for a parent's note, or None when it is not about the baby's day."""
    low = text.lower()
    if medicine_only(text) or (MILESTONE.search(text) and not ML.search(text)):
        return "note", {"text": text}  # a medicine given or a milestone is a note in the parent's words, never a feed
    if "diaper" in low or "nappy" in low or "poop" in low or "pee" in low:
        solid = any(w in low for w in ("dirty", "poop", "solid", "messy"))
        wet = "wet" in low or "pee" in low or not solid
        return "diaper", {"wet": wet, "solid": solid}
    if "bath" in low:
        return "bath", {"text": text}
    if "asleep" in low or "fell asleep" in low or "went down" in low:
        return "sleep", {"action": "start"}
    if "woke" in low or "awake" in low:
        return "sleep", {"action": "end"}
    span = SPAN.search(text)
    if span and ("nap" in low or "slept" in low or "sleep" in low):
        h1, m1, h2, m2 = (int(g) for g in span.groups())
        start, end = latest_span(h1, m1, h2, m2)
        return "sleep", {"start": start, "end": end}
    amount, minutes = ML.search(text), MINUTES.search(text)
    if "breast" in low or amount or "bottle" in low or "fed" in low or "drank" in low:
        details = {}
        if amount:
            details["amount_ml"] = float(amount.group(1))
        if "both breast" in low:
            details["method"] = "both breasts"
        elif "left" in low:
            details["method"] = "left breast"
        elif "right" in low:
            details["method"] = "right breast"
        else:
            details["method"] = "bottle"
        details["type"] = "breast milk" if ("breast" in low) else "formula"
        if minutes:
            details["duration_min"] = int(minutes.group(1))
        return "feeding", details
    if any(w in low for w in ("smiled", "rolled", "laughed", "first time", "milestone")):
        return "note", {"text": text}
    return None


def note_to_english(text):
    out = text
    for pattern, word in NOTE_WORDS_ES:
        out = re.sub(rf"\b(?:{pattern})\b", word, out, flags=re.I)
    return out


def log_kind(text):
    """The kind of log entry a parent's message reports (feeding, diaper, sleep, bath, note), in English or Spanish.
    None for questions, health questions and anything that is not a note about the baby."""
    english = note_to_english(text)
    if is_question(text) or is_question(english) or is_health(text):
        return None
    parsed = parse_note(text) or parse_note(english)
    return parsed[0] if parsed else None


def is_log_request(text):
    return log_kind(text) is not None


def describes_house(text, observed=False):
    """True when a reply speaks of an action in the house: "I'll announce one moment please", "Said one moment please
    at the door", "dimmed the light". On an observation turn (the doorbell rang) the words the agent would say at the
    door, "one moment please", count too. "Someone is at the door" only reports, it is no action."""
    text = text or ""
    return bool(HOUSE_ACTION.search(text) or (observed and ONE_MOMENT.search(text)))


def claims_acted(text):
    """True when a reply says the agent already sent, called, announced, asked or told someone."""
    return bool(CLAIMS_ACTED.search(text or ""))


def claims_logged(text):
    return bool(CLAIMS_LOGGED.search(text or ""))


def looks_spanish(text):
    return note_to_english(text) != text or bool(SPANISH.search(text))


ENGLISH = re.compile(r"\b(the|she|he|his|her|him|is|was|did|gave|had|just|when|how|what|why|it|that|bottle|diaper|"
                     r"nappy|feed|fed|nursed|breast|woke|asleep|slept|nap|crying|poop|pee|wet|dirty|bath|left|right|"
                     r"at|ago|hello|hi|thanks|please|delete|fix|sorry)\b", re.I)


def message_lang(text):
    """The language of one parent message, "es" or "en", or None when its words say neither ("120", "ok")."""
    if looks_spanish(text):
        return "es"
    return "en" if ENGLISH.search(text or "") else None


def answer(question, summary):
    """A short answer to a parent's question from baby_summary, or None when the rules do not know the question."""
    q = question.lower()
    feeds, diapers, sleep, baths = summary["feedings"], summary["diapers"], summary["sleep"], summary["baths"]
    if "dirty" in q or "poop" in q:
        if "how many" in q:
            return f"{diapers['dirty']} dirty diapers today."
        return f"The last dirty diaper was at {diapers['last_dirty_at']}." if diapers["last_dirty_at"] else "No dirty diaper in the log yet."
    if "wet" in q:
        return f"{diapers['wet']} wet diapers today."
    if "diaper" in q:
        return f"{diapers['count']} diapers today, {diapers['wet']} wet and {diapers['dirty']} dirty."
    if "bath" in q:
        return f"The last bath was at {baths['last_at']} on {baths['last_date']}." if baths["last_at"] else "No bath in the log yet."
    if "sleep" in q or "nap" in q or "slept" in q:
        if "how long" in q or "how much" in q:
            return f"{sleep['total_min']} minutes of sleep today."
        return f"The last sleep ended at {sleep['last_end_at']}." if sleep["last_end_at"] else "No sleep in the log yet."
    if "last bottle" in q or "last feed" in q and "how much" in q:
        return f"The last feed was {feeds['last_amount_ml']:g} ml at {feeds['last_at']}." if feeds["last_amount_ml"] else "No feed amount in the log."
    if "how many" in q and ("feed" in q or "bottle" in q):
        return f"{feeds['count']} feeds today."
    if "how much" in q or "drank" in q or "drunk" in q or "drink" in q:
        return f"{feeds['total_ml']} ml today over {feeds['count']} feeds."
    if "eat" in q or "fed" in q or "feed" in q:
        return f"The last feed was at {feeds['last_at']}." if feeds["last_at"] else "No feed in the log yet."
    return None


def parent_text(text):
    """A parent's message as the transcript may carry it: no square brackets, so it can never pose as an observation
    from a skill or a check from the agent."""
    return str(text or "").translate(BRACKETS)


_HOUSE = (r"announc\w*|one moment|un momento|speaker|parlante|altavoz|door|doorbell|puerta|timbre|lights?|luz|luces|"
          r"dim\w*|lamp|vacuum|aspiradora|tv|tele")
ONE_MOMENT = re.compile(r"\b(one moment|un momento|just a moment|ya va(mos)?|we'?ll be right (there|with you))\b", re.I)
HOUSE_ACTION = re.compile(rf"\b(i'?ll|i will|i am|i'm|i've|i have|let me|voy a|le digo|les digo|said|told|dije|avis[eé])\b"
                          rf"[^.?!]{{0,60}}\b({_HOUSE})\b|"
                          r"\b(announced|anunci[eé]|dimmed|turned (on|off|down) the)\b", re.I)


def has_secret(text):
    """True when the text names a code, a password, a PIN or a card, or holds a run of four or more digits. The plain
    word "key" is no secret: "bring the spare key" is an errand, "the key code is 4471" is caught by its code."""
    return bool(SECRET.search(str(text or "")))


def holds_code(text, numbers=True):
    """True when a prep item or an appointment holds a code: a word that names one (code, PIN, password, wifi, alarm)
    or, with numbers, a run of four or more digits that stands alone. Narrower than has_secret, because "the health
    provider card" and "a MAX98357A amplifier" are items on the plan, while "gate code 4471" and "wifi password
    babytheo2026" are not."""
    text = str(text or "")
    return bool(CODE_WORD.search(text) or (numbers and CODE_NUMBER.search(text)))


def personal_detail(text):
    """True for a secret or a contact detail: an email, a phone number, an address."""
    return has_secret(text) or bool(CONTACT.search(str(text or "")))


def health_route(text):
    """None for a message with no health talk. "refuse" for health advice with nothing to log: the kind refusal, no
    brain call. "note" for a symptom the parent reports with no question: noted in their words, no brain call. "log" for a health message that also reports something the parent wants kept, a medicine given, a
    milestone or an explicit ask to log: it is logged as a note and only the advice part is refused."""
    if not text or is_emergency(text) or not (is_medical(text) or is_medical_es(text)):
        return None
    if LOG_ASK.search(text) or GAVE.search(text) or MILESTONE.search(text):
        return "log"
    if SYMPTOM.search(text) and not is_question(text) and not ADVICE.search(text):
        # "vomito un poquito dsp de la toma" reports what the parent saw: it is kept as a note in their words, for the
        # pediatrician, and only the advice part is refused, in one turn.
        return "note"
    return "refuse"


def asks_advice(text):
    return bool(ADVICE.search(text or "")) or bool(SYMPTOM.search(text or ""))


FEED_WORDS = re.compile(r"\b(bottle|breast|feed|fed|nursed|formula|milk|mamadera|biber[oó]n|teta|pecho|toma|tom[oó] \d|"
                        r"leche|f[oó]rmula)\b", re.I)
NAME = re.compile(r"^[^\W\d_](?:[^\W\d_]|[' .-]){0,39}$")


def mentions_medicine(text):
    return bool(MEDICINE.search(text or ""))


def medicine_only(text):
    """A medicine with no feed in the same message: "I gave her 2.5 ml of paracetamol" is a note, never a 2.5 ml feed,
    while "bottle 120 ml, then vitamin D drops" still logs the bottle."""
    return mentions_medicine(text) and not FEED_WORDS.search(text or "")


def plain_name(value):
    """A baby's name or nickname: letters, at most 6 words, no digits, no codes. Anything else would ride along in
    every prompt as a "fact"."""
    value = str(value or "").strip()
    return bool(NAME.match(value)) and len(value.split()) <= 6 and not personal_detail(value)


def _number_or_none(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def out_of_bounds(kind, details, ts=None, now=None, parse=None, future=True):
    """(field, value) when a log call holds a value no real entry can have, else None: a feed outside 1 to 300 ml or
    1 to 120 min, a sleep longer than 14 hours or ending before it starts, or, with future, a time in the future."""
    details = details if isinstance(details, dict) else {}
    if kind == "feeding":
        for name in ("amount_ml", "duration_min"):
            if details.get(name) is None:
                continue
            value = _number_or_none(details[name])
            low, high = BOUNDS[name]
            if value is None or not low <= value <= high:
                return name, details[name]
    if parse is not None and now is not None:
        moments = {}
        for name, value in (("ts", ts), ("start", details.get("start")), ("end", details.get("end"))):
            if value:
                try:
                    moments[name] = parse(value)
                except (TypeError, ValueError):
                    return name, value
        for name, moment in moments.items():
            if future and moment > now + datetime.timedelta(minutes=BOUNDS["future_min"]):
                return "future", value_hhmm(moment)
        if kind == "sleep" and "start" in moments and "end" in moments:
            hours = (moments["end"] - moments["start"]).total_seconds() / 3600
            if not 0 < hours <= BOUNDS["sleep_hours"]:
                return "sleep_hours", round(hours, 1)
    return None


def value_hhmm(moment):
    return moment.strftime("%Y-%m-%d %H:%M")


def content_words(text):
    return {w.lower() for w in WORD.findall(str(text or ""))} - STOP


def from_earlier(note, request, earlier):
    """True when a note the brain wants to log repeats an earlier message and shares nothing with the newest one, which
    asks for nothing to be logged: the "log only what the newest message says" rule, kept by the harness."""
    words = content_words(note)
    if not words or LOG_ASK.search(request or "") or words & content_words(request):
        return False
    need = max(2, (len(words) + 1) // 2)
    return any(len(words & content_words(text)) >= need for text in earlier)
