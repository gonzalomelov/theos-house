"""Red flags and medical questions, in code and outside Muse, so nothing Muse is told can talk its way past them.

A parent's message passes through gate() before Muse sees it. An emergency or a newborn red flag gets the fixed line from
agent/rules.py, to both parents, and Muse is not called. A question asking for advice gets the fixed no-advice line.
Every message Muse writes passes through outbound(): a dose, a drug or a diagnosis is refused, and Muse is told why.
It also passes through unbacked(): how the night went, or an amount in ml, must come from the log or from a parent's words.
"""
import difflib
import re

from ..agent import danger, final_guard, rules
from .settings import BASE_URL, MODEL

# A sentence ends at a stop, never inside 38.6.
SENTENCE = r"(?:(?<!\d)\.|\.(?!\d)|[!?;\n])+"
SCREEN = {"provider": "openai_compatible", "model": MODEL, "base_url": BASE_URL, "key_env": "BASETEN_API_KEY"}
ADVICE_OUT = re.compile(r"\b\d+(?:[.,]\d+)?\s?(?:mg|mcg|ug|gotas|drops)\b|\b(paracetamol|ibuprofen\w*|acetaminophen|tylenol|motrin|advil|"
                        r"calpol|nurofen|simethicone|simeticona|gripe water|antibi[oó]tic\w*|antibiotics?|dosis|dose|dosage|"
                        r"diagn[oó]stic\w*|diagnos\w*)\b", re.I)
# What Muse added on its own in the morning messages (Nov 3): the log holds events, never how the night felt.
HOW_IT_WENT = re.compile(r"\b(durmi[oó]\s+(?:\w+\s+)?(?:bien|tranquil\w*|genial|b[aá]rbaro|de corrido|toda la noche)|durmieron\s+(?:\w+\s+)?bien|descans[oó]\s+bien|"
                         r"noche\s+(?:\w+\s+)?(?:tranquila|buena|linda|b[aá]rbara|bien|sin\s+\w+)|(?:buena|linda|tranquila)\s+noche|"
                         r"sin\s+(?:problemas|sobresaltos|novedad\w*|complicaciones)|todo\s+(?:bien|tranquilo)|"
                         r"slept\s+(?:\w+\s+)?(?:well|through|fine)|(?:quiet|calm|good|easy|peaceful)\s+night|night\s+went\s+\w+)\b", re.I)
MILLILITERS = re.compile(r"\b(\d+)\s?(?:ml|mililitros|milliliters|cc)\b", re.I)
# A danger in a film or a book is not one at home, unless the words are also about this baby.
FICTION = re.compile(r"\b(movie|film|tv show|series|novel|book|story|documentary|episode|in the news|pel[ií]cula|peli|serie|novela|libro|cuento|historia|documental|cap[ií]tulo|noticiero)\b", re.I)
THIS_BABY = re.compile(r"\btheo\b|\b(?:my|our|mi|nuestr[oa])\s+(?:baby|son|boy|kid|child|newborn|beb[eé]|hijo|nene|gur[ií])\b", re.I)
# "He isn't breathing, we were watching a film" is about this baby. "In the film he isn't breathing" is not.
HE_NOW = re.compile(r"\b(?:he|the baby|el beb[eé]|[eé]l)(?:'s|\s+(?:is|isn'?t|won'?t|can'?t|stopped|just|est[aá]|no|se))\b", re.I)
IN_STORY = re.compile(r"\b(?:in|en)\s+(?:the|a|this|that|my|la|el|una|un|esta|este|mi)\s+(?:\w+\s+)?(?:" + FICTION.pattern[3:-3] + r")\b|\b(?:movie|film|novel|book|series|story|pel[ií]cula|peli|serie|novela|libro|cuento)\s+(?:where|about|donde|en la que|sobre)\b", re.I)
# A baby who isn't this one: made up, named something else, or someone else's.
OTHER_BABY = re.compile(r"\b(?:fictional|fictitious|imaginary|made[- ]up|hypothetical(?:ly)?|ficticio\w*|imaginari\w*|inventad\w*|hipot[eé]tic\w*)\b"
                        r"|\b(?:baby|beb[eé]|newborn|reci[eé]n nacido|nene|nena)\s+(?:named|called|llamad[oa]|que se llama)\b"
                        r"|\b(?!ceci|gonza|our\b)\w+'s\s+(?:baby|son|kid|child|newborn)\b|\b(?:another|other|someone else'?s)\s+(?:baby|kid|child|newborn)\b"
                        r"|\b(?:son|daughter|kid|child|baby)\s+of\s+(?:my|our|a|the)\b"
                        r"|\b(?:beb[eé]|hij[oa]|nene|nena)\s+de\s+(?:\d+\s+\w+\s+de\s+)?(?:mi|mis|la|el|una|un|nuestr\w+)\s+\w+|\botr[oa]\s+(?:beb[eé]|nene|nena)\b", re.I)
# A fever in someone else isn't Theo's. "Is my mom's cough a problem" doesn't call a newborn's red flag, and a life in danger still does.
SOMEONE_ELSE = re.compile(r"\b(?:my|our|mi|nuestr[oa]|la|el)\s+(?:mom|mum|mother|dad|father|wife|husband|partner|sister|brother|grandma|grandmother|grandpa|grandfather|friend|neighbou?r|nephew|niece|cousin|coworker|colleague|roommate|dog|cat|boss|aunt|uncle|nanny|mother-in-law|father-in-law|"
                          r"mam[aá]|madre|pap[aá]|padre|esposa|esposo|mujer|marido|herman[oa]|abuel[oa]|amig[oa]|vecin[oa]|perr[oa]|gat[oa]|jefe|jefa|suegr[oa]|t[ií][oa]|ni[ñn]era|sobrin[oa]|prim[oa]|compa[ñn]er[oa])\b|\bgrandma\b|\babuela\b"
                          r"|\b(?:ceci|gonza)\s+(?:has|had|got|is|tiene|ten[ií]a|est[aá])\b"
                          r"|\b(?:i have|i got|i'?ve got|i'?m running|tengo|estoy con)\s+(?:a\s+|mucha\s+|\d\d(?:[.,]\d)?\s+(?:de\s+)?)?(?:fever|fiebre)\b"
                          # An age no newborn has: Theo isn't 3 years old.
                          r"|\b(?:1\s*(?:year|a[nñ]o|a[nñ]ito)|(?:[2-9]|1\d)\s*(?:years?|yrs?|y/?o|a[nñ]os|a[nñ]itos))\b", re.I)
# A child named something else, with the fever said of them. Only a name right before the verb counts, so "Tonight he has a fever" still fires.
NOT_A_NAME = ("Theo Gonza Ceci Today Tonight Now Also Still Yesterday Again Already Apparently Probably Perhaps Maybe Just Really Seems Looks Because Since And But Who Baby Temp Temperature Fever Thermometer Reading Yes Yeah Please Help Hey "
              "Hoy Ahora Anoche Ayer Mañana Tarde Noche Bebe Bebé Nene Nena Sigue Ya Todavía Todavia Recién Recien Creo Parece Capaz Además Ademas También Tambien Igual Aún Aun Justo Otra Esto Esta Este Eso Esa Ese Acá Aca Ahí Ahi Siempre Nunca Quizás Quizas Tal Vez "
              "Temperatura Fiebre Termómetro Termometro Porque Pero Por Para Que Bueno Che Mira Mirá Dale Ojo Hola Ayuda Sí Si No He She It The This That Him El Ella Lo Le").split()
NAMED_OTHER = re.compile(r"\b(?!(?:" + "|".join(NOT_A_NAME) + r")\b)[A-ZÁÉÍÓÚÑ][a-záéíóúñ]{2,}(?:,[^,.!?]{0,40},)?\s+(?i:has|had|is running|got|tiene|ten[ií]a|est[aá] con)\s+(?i:a\s+|an?\s+|una?\s+|mucha\s+|high\s+)?(?i:fever|fiebre|temp\w*|calentura|\d\d)")
# A question about the room, with nothing said about him: Muse reads the sensor and answers.
ROOM_WORD = re.compile(r"\b(?:room|nursery|in there|in here|cuarto|habitaci[oó]n|pieza|ac[aá] adentro|ah[ií] adentro)\b", re.I)
ROOM_ASK = re.compile(r"\b(?:temp\w*|hot|warm|cold|humid\w*|calor|fr[ií]o|caliente|humedad)\b", re.I)
SAID_OF_HIM = re.compile(r"\b(?:theo|he|he'?s|him|his|baby|beb[eé]|él|fiebre|fever|tiene|lo siento)\b", re.I)
# "Unrelated to Theo" says it isn't him, so his name there doesn't make it about him.
UNRELATED = re.compile(r"\b(?:unrelated to|nothing to do with|not about|has nothing to do with|not related to)\s+(?:theo|our (?:baby|son)|my (?:baby|son))\b|\b(?:not|isn'?t)\s+theo\b(?!')|\b(?:no (?:tiene )?)?(?:nada )?(?:que ver|relacionado) con (?:theo|nuestro (?:beb[eé]|hijo)|mi (?:beb[eé]|hijo))\b|\bno es (?:sobre |por )?theo\b", re.I)
SAYS_ABOUT_HIM = re.compile(r"\b(?:says|said|thinks|told me|dice|dijo|cree)\s+(?:that\s+|que\s+)?(?:he|[eé]l|le|tiene)\b", re.I)
THEO_NAMED = re.compile(r"\btheo\b|\bbaby\b|\bbeb[eé]\b|\bson\b|\bhijo\b|\bnewborn\b|\breci[eé]n nacido\b", re.I)
# Words trying to change the rules aren't a danger, and Muse refuses them. They never land in the log or in memory.
INJECTION = re.compile(r"\b(?:ignore|disregard|forget|override|bypass)\b[^.!?]{0,30}\b(?:rules?|instructions?|prompt|guidelines?|safety)\b|\b(?:ignor[aá]|olvid[aá]|salte[aá])\w*\b[^.!?]{0,30}\b(?:reglas?|instrucciones|prompt)\b|\bsystem prompt\b|\byou are now\b|\bact as\b|\bdeveloper mode\b|\bmaintenance mode\b|\bnew (?:rules|instructions)\b|\bnuevas (?:reglas|instrucciones)\b|\bfrom now on you\b", re.I)
AM_PM = re.compile(r"\b(1[0-2]|0?[1-9])(?::([0-5]\d))?\s?([ap])\.?\s?m\b\.?", re.I)
# Claims that only hold for a while. The warmer turns itself off, and a long gap between feeds is never fine.
WARM_CLAIM = re.compile(r"\b(bottle|mamadera|biber[oó]n)\b[^.!?]{0,40}\b(warm|ready|caliente|tibia|lista|pronta)\b|\b(warm|caliente|tibia|lista|pronta)\b[^.!?]{0,40}\b(bottle|mamadera|biber[oó]n)\b", re.I)
REASSURE = re.compile(r"sleep when you can|get some rest|rest up|beside you|all good|no worries|due soon|al lado tuyo|dorm[ií] tranquil\w*|descans[aá]\b|tranquil[oa]\b|todo bien|sin problema|le toca pronto", re.I)
# Calm in the agent's own voice, which nobody can say while an alarm has no answer. Narrower than REASSURE: "his feed is due soon" is only a fact.
CALM = re.compile(r"sleep when you can|rest when you can|get some rest|rest up|rest well|sleep well|sleep tight|sleep easy|all good|all fine|no worries|don'?t worry|nothing to worry|every(?:thing|one)(?:'s| is) (?:fine|ok|okay|good)|"
                  r"dorm[ií] tranquil\w*|descans[aáeé]\w*|tranquil[oa]s?\b|todo (?:bien|en orden)|sin problema|no te preocupes|que duermas bien", re.I)
# Words that say an alarm is still open. Asking how he is does too (ASKS_HOW).
SAYS_OPEN = re.compile(r"sigue abiert\w*|sigue sin respuesta|sin respuesta|todav[ií]a nadie|nadie (?:dijo|cont[oó]|respondi[oó]|avis[oó]|me dijo)|no (?:tengo|hay) respuesta|no s[eé] c[oó]mo (?:est[aá]|sigue)|"
                       r"still open|still no answer|no answer|nobody has (?:said|answered|told)|no one has (?:said|answered|told)|nobody (?:said|answered|told)|hasn'?t been answered|don'?t know how (?:he|theo)", re.I)
ABOUT_THE_AIR = re.compile(r"dehumid|deshumid|humid", re.I)
ABOUT_THE_ROOM = re.compile(r"\broom\b|temperatur|\bcuarto\b", re.I)
GETS_READY = re.compile(r"warmer|prewarm|pre-warm|warm the|bottle|mamadera|calentador|calentar", re.I)
HOT_ROOM, COLD_ROOM = 28.0, 14.0
FEED_GAP_H, STALE_LOG_H = 8, 48
# A fever a parent names as over. Only these exact shapes, closed off by a stop or an "and": "the fever is over 39" and "la fiebre pasó a 39" aren't one.
FEVER_OVER = re.compile(r"\b(?:(?:yesterday'?s |last night'?s )?(?:the |his |that )?fever(?:(?:'s|\s+is|\s+has)(?:\s+(?:already|finally|now|completely))?\s+(?:gone(?:\s+away)?|over|passed|broken)|\s+gone|\s+(?:already\s+)?(?:broke|passed|went away))"
                        r"|no more fever|no longer has (?:a )?fever|no (?:longer a )?fever (?:anymore|any more)|(?:doesn'?t|does not) have (?:a )?fever (?:anymore|any more)"
                        r"|(?:(?:la|su|esa) )?fiebre(?: de (?:ayer|anoche))?(?: ya)?(?: se)?(?: le)?(?: ya)? (?:pas[oó]|fue|termin[oó]|cort[oó]|cedi[oó])|(?:(?:la|su|esa) )?fiebre(?: de (?:ayer|anoche))? ya(?: le)? baj[oó]"
                        r"|(?:ya )?(?:se )?(?:le )?(?:pas[oó]|fue|termin[oó]|cort[oó]) (?:la|su|esa) fiebre|ya(?: le)? baj[oó] (?:la|su) fiebre"
                        r"|ya no (?:tiene|hay|tuvo)(?: m[aá]s)? fiebre|no (?:tiene|hay) m[aá]s fiebre)"
                        r"(?:\s+(?:ya|hoy|anoche|ahora|now|today|already|yesterday|last night|this morning|this afternoon|esta ma[ñn]ana|esta tarde|a la tarde|a la ma[ñn]ana|ayer))*(?=\s*(?:$|[,.;:!\n]|(?:y|and)\b))", re.I)
# Words that put it in doubt, anywhere in the message: then the fever line fires as ever.
FEVER_DOUBT = re.compile(r"\b(?:pero|but|though|although|aunque|however|sin embargo|volvi\w*|vuelve|vuelta|de nuevo|otra vez|again|came back|comes? back|coming back|back up|returned|sub\w+|going up|gone up|rising"
                         r"|creo|parece|capaz|quiz[aá]s?|tal vez|supongo|ojal[aá]|espero|i think|i guess|i hope|i wish|seems?|maybe|probably|hopefully|looks like|no s[eé]|not sure|dunno"
                         r"|should|can (?:i|we|he)|is it (?:ok|okay|safe|normal)|puedo|podemos|debo|debemos|es normal|hay que|tengo que|qu[eé] (?:hago|le doy)|what (?:do|should) (?:i|we))\b"
                         r"|\b(?:sigue|still|todav[ií]a|a[uú]n)\b[^.!?\n]{0,30}\b(?:caliente|hot|warm|calor|ardiendo|burning|mal|raro|weird|off)\b", re.I)
# In its clause, before the words: "no se le fue la fiebre", "if the fever is gone", "is the fever gone".
FEVER_NOT_OVER_YET = re.compile(r"\b(?:no|not|never|nunca|ni|si|if|when|cuando|once|until|hasta|whether|antes|before|after|despu[eé]s|apenas|is|did|has|was)\b", re.I)
# The ladder: each step is said once, from code, and from BOTH_FROM up it reaches both parents, day or night.
GAP_STEPS, BOTH_FROM = (8, 12, 18, 24, 36), 18
GAP_LINES = {"en": ("The log shows no feed for {h} hours. Did feeds go unlogged? If he truly hasn't eaten, call your pediatrician.",
                    "The log shows no feed for {h} hours, which is long for a newborn. If feeds didn't go unlogged, call your pediatrician now.",
                    "No feed in the log for {h} hours. If he truly hasn't eaten, call your pediatrician or emergency services now. Please check on him and log what he had."),
             "es": ("El registro no tiene tomas hace {h} horas. ¿Quedaron tomas sin registrar? Si de verdad no comió, llamá a su pediatra.",
                    "El registro no tiene tomas hace {h} horas, y es mucho para un recién nacido. Si no quedaron tomas sin registrar, llamá a su pediatra ahora.",
                    "No hay tomas en el registro hace {h} horas. Si de verdad no comió, llamá ahora a su pediatra o a emergencias. Fijate cómo está y anotá lo que tomó.")}
# "Not an emergency" counts, unless the words name a sign nobody can wave away.
# A false alarm says the same, and closes the alarm it is about.
FALSE_ALARM = re.compile(r"\bfalse alarm\b|\bfalsa alarma\b|\b(?:it'?s|it was|was) nothing\b|\b(?:says|said) it'?s nothing\b|\bno (?:es|fue|era) nada\b|\bdice que no es nada\b", re.I)
DENIED = re.compile(r"\b(not an emergency|no emergency|nothing urgent|not urgent|no es (?:una )?(?:emergencia|urgencia)|no es urgente|nada urgente)\b|" + FALSE_ALARM.pattern, re.I)
VITAL = re.compile(r"not breathing|n'?t breathing|stop\w* breathing|can'?t breathe|no respira|dej[oó] de respirar|\bblu(?:e|ish)\b|\bazul|\bmorad|\blimp\b|won'?t wake|not waking|no (?:se )?despierta|unresponsive|no reacciona|no responde|seizure|convuls|hard to wake|dif[ií]cil de despertar|cuesta despertar", re.I)
# "Lips not blue" is reassurance, so it is no sign.
NOT_A_SIGN = re.compile(r"\b(?:not|aren'?t|isn'?t|no|sin|ni)\s+(?:\w+\s+)?(?:blu(?:e|ish)|azul\w*|morad\w*|limp|gr[ae]y|gris\w*|hard to wake)\b", re.I)
# Signs the word list misses, and how they come out typed fast at night. Everything else goes to the danger screen.
BUMPED = re.compile(r"\b(?:bump|bang|knock|smack)\w*\s+(?:his|her|the|its)\s+head\b|\bhead\s+(?:bump|knock)\b|\bse\s+(?:dio|peg[oó])\s+(?:\w+\s+)?(?:en\s+)?la\s+cabeza\b", re.I)
HARD_TO_WAKE = re.compile(r"\b(?:hard|difficult|tough) to wake\b|\b(?:es|est[aá]|muy|re)?\s*dif[ií]cil (?:de )?despertarl[oa]\b|\b(?:cuesta|costó|cost[oó]) (?:mucho )?despertarl[oa]\b", re.I)
TYPED_FAST = re.compile(r"\b(?:lips?|labios?)\b[^.!?]{0,12}\b(?:blu\b|bleu\b|azul\w*|gr[ae]y\b|gris\w*)|\bbre?a?th?i?n?g?\w{0,3}\s+(?:funny|weird|strange|raro)\b|\bbreathng\b|\bw(?:no|on)t\s+wake\b|\bno\s+respir\b|\bno\s+resira\b", re.I)
# Which language the danger is written in, when a short message has no other word to go by.
DANGER_ES = re.compile(r"\b(?:respir\w*|despiert\w*|azul\w*|morad\w*|fiebre|labios?|convuls\w*|trag[oó]|golpe\w*|cabeza|pila|reacciona|ahog\w*|miel|leche)\b", re.I)
DANGER_EN = re.compile(r"\b(?:breath\w*|won'?t|wake|lips?|seizure|swallow\w*|battery|bump\w*|head|fever|stopped|limp|choking|fell|honey|milk)\b", re.I)
# Words on a label or a shelf, not about a baby now (Nov 3, a toy label and a thermometer on sale both called 911).
ERRANDS = re.compile(r"\bchoking hazards?\b|\bpeligro de asfixia\b|\bfever (?:thermometers?|reducers?)\b|\bterm[oó]metros? para (?:la )?fiebre\b", re.I)
STOPPED = re.compile(r"\bstops? breathing\b|\bdeja de respirar\b", re.I)
CLAUSE = re.compile(SENTENCE + r"|\b(?:also|adem[aá]s|tambi[eé]n)\b|,\s*y\s+|,?\s+y\s+(?=agreg|anot|compr|pon|prend|apag)|,?\s+and\s+(?=add|log|buy|turn|put|remind|tell)", re.I)
# A parent who is scared or worn out, with no danger sign named, needs the log and a human line, not the 911 line.
SCARED = re.compile(r"\b(?:i'?m|i am|im)\s+(?:so |really |very )?(?:scared|worried|frightened|anxious|nervous|panicking)\b|\btengo miedo\b|\bestoy\s+(?:muy |re )?(?:asustad[ao]|preocupad[ao]|nervios[ao])\b|\bme (?:asust\w+|preocupa)\b", re.I)
WORN_OUT = re.compile(r"\b(?:i'?m|i am|im)\s+(?:so |really |very )?(?:exhausted|tired|wrecked|done)\b|\bdoing (?:this|it) (?:all )?wrong\b|\bcan'?t do this\b|\bagotad[ao]\b|\bno doy m[aá]s\b|\bestoy muert[ao]\b|\blo estoy haciendo mal\b", re.I)
LOG_QUESTION = re.compile(r"\b(?:did|really|when|how long|how many|has he)\b[^.!?]{0,50}\b(?:eat|ate|eaten|fed|feed|feeds|bottle)\b[^.!]{0,40}\?|\b(?:de verdad|realmente|cu[aá]ndo|hace cu[aá]nto|cu[aá]ntas?)\b[^.!?]{0,50}\b(?:comi[oó]|tom[oó]|tomas?|mamadera)\b[^.!]{0,40}\?", re.I)
DANGER_SIGN = re.compile(r"breath|respir|\bblue\b|azul|morad|\blimp\b|floppy|blando|won'?t wake|not waking|wake up|no (?:se )?despierta|unrespons|no reacciona|no responde|seizure|convuls|vomit|sangr|blood|fever|fiebre|\bhot\b|caliente|\bpale\b|p[aá]lid|rash|chok|ahog|won'?t eat|refus|no quiere|rechaz|weird|strange|not right|\boff\b|raro|\bmal\b(?! hecho)|sleepy|letarg|callad|\bquiet\b|\bfell\b|se cay|golpe|\bhit\b|inconsolable|no para de llorar|dolor|\bpain\b", re.I)
# How far a room can't move in a few minutes.
SENSOR_JUMP = {"humidity": 30.0, "temperature": 10.0}
JUMP_MINUTES = 10
# What a message can't promise or say. The end time of the warmer is when it switches off, not when a bottle is ready.
PROMISE = re.compile(r"\bi'?ll (?:remind|ping|wake|message|text|check in|let you know|tell you)\b|\b(?:te|les) (?:aviso|avisar[eé]|recuerdo|escribo|despierto)\b|\bvoy a (?:avisar|recordar|escribir)\w*", re.I)
READY_AT = re.compile(r"\b(?:ready|warm)\s+(?:by|at|around)\s+\d|\b(?:lista|pronta|tibia|caliente)\s+(?:a las|para las|a eso de)\s+\d", re.I)
# A parent saying they fed him: the feed goes in the log first, so the gap it closes is never raised.
FEED_REPORT = re.compile(r"\b(?:gave|fed|just fed|nursed|drank|ate)\b|\bbottle (?:at|of)\b|\ble di\b|\btom[oó]\b|\bcomi[oó]\b|\bmamadera (?:a las|de)\b|\b\d+\s?ml\b", re.I)
# What the agent can't keep: the home decides these, not a promise in a chat.
# The agent can't see him. Only a person can go and look.
CANT_SEE = re.compile(r"\b(?:checking|i'?ll check|i will check|going to check|let me check|looking in) (?:on|in on) (?:him|theo)\b|\bvoy a (?:ver|revisar|chequear)(?:lo)?\s+(?:a theo|c[oó]mo est[aá])\b|\b(?:lo )?(?:estoy|sigo) (?:mirando|chequeando|revisando)\b", re.I)
CANT_KEEP = re.compile(r"\bi (?:won'?t|will not) (?:message|text|wake|bother|tell|write)\b|\bno (?:te|le|les) (?:escribo|aviso|molesto|despierto|voy a (?:escribir|avisar|molestar|despertar))\b|\bi'?ll (?:alert|tell|wake|message|text) (?:you )?both\b|\b(?:les )?aviso a (?:los |ustedes )?dos\b|\bdespierto a los dos\b", re.I)
WRONG_NUMBER = re.compile(r"\b(?:112|999|000)\b")
PET = re.compile(r"\b(?:dogs?|puppy|cats?|kitten|perr[oa]s?|cachorr[oa]s?|gat[oa]s?|gatit[oa]s?)\b", re.I)
ABOUT_HIM = re.compile(r"\b(?:theo|baby|newborn|he|him|his|son|beb[eé]|nene|hijo|[eé]l|lo|le)\b", re.I)
# A parent's words that can justify waking the other one. A thing too hot isn't a sign in him ("this bottle feels hot"), so it is taken out first.
HOT_THING = re.compile(r"\b(?:bottle|milk|formula|water|bath|mamadera|biber[oó]n|leche|f[oó]rmula|agua|ba[ñn]o)\b[^.!?]{0,30}\b(?:hot|warm|caliente|calent\w*|tibi\w*)\b|\b(?:hot|warm|caliente|calent\w*|tibi\w*)\b[^.!?]{0,30}\b(?:bottle|milk|formula|water|bath|mamadera|biber[oó]n|leche|f[oó]rmula|agua|ba[ñn]o)\b", re.I)
WORTH_WAKING = re.compile(DANGER_SIGN.pattern + r"|" + SCARED.pattern + r"|\b(?:alarm\w*|smoke|humo|fire|fuego|incendi\w*|gas|emergenc\w*|urgent\w*|urgenc\w*|help|ayuda|hurt\w*|lastim\w*|burn\w*|quem\w*|scald\w*|injur\w*|accident\w*|bleed\w*|hospital|ambulanc\w*|ambulancia|911|wrong|pasa algo|algo le pasa|not moving|no se mueve|won'?t feed|won'?t drink|no toma|no come|can'?t cope|no puedo m[aá]s|swallow\w*|trag\w*|battery|pila|im[aá]n|magnet|pressed|still)\b", re.I)
# A tip nobody asked for that reads as care advice. Other tips are left to the prompt's line.
UNASKED_TIP = re.compile(r"\b(?:wrist|mu[ñn]eca)\b", re.I)
# What the rest of a message has to ask for, once the gate answered the worrying part. "He's 3 weeks old" isn't an errand.
ERRAND = re.compile(r"\b(?:add|log|buy|turn|put|remind|tell|write|note|shopping)\b|\bagreg|\banot|\bcompr|\bpon[eé]\b|\bprend|\bapag|\brecord|\bavis|\bdecile\b|\blista\b", re.I)
ALARM_TOLD = re.compile(r"emergenc|\b911\b|alarm|fever|fiebre|urgent|pediatr|call|llam|wrote|escribi|respir|breath|anoche|last night|esta madrugada", re.I)
# A feed no newborn can drink is a typo, not a danger. The real danger screen once read "5000 ml" as one.
MAX_FEED_ML = 500
IMPOSSIBLE_ML = re.compile(r"\b(?:[5-9]\d\d|[1-9]\d{3,})\s?(?:ml|mililitros|milliliters|cc)\b", re.I)
# Firm, public rules for every baby, in code: honey and cow's milk as a drink before 12 months. A fixed line, and nothing beyond it.
UNSAFE_FOODS = ((re.compile(r"\bhoney\b|\bmiel\b", re.I), {"en": "Honey is not for babies under 12 months. Please ask your pediatrician.", "es": "La miel no es para bebés menores de 12 meses. Consultá a su pediatra."}),
                (re.compile(r"\bcow'?s?\s+milk\b|\bwhole milk\b|\bleche de vaca\b|\bleche entera\b", re.I), {"en": "Cow's milk as a drink is not for babies under 12 months. Please ask your pediatrician.", "es": "La leche de vaca como bebida no es para bebés menores de 12 meses. Consultá a su pediatra."}))
FOR_BABY = re.compile(r"\btheo\b|\b(?:baby|newborn|infant|him|his|beb[eé]|reci[eé]n nacido)\b|\ble\s+(?:di|doy|damos|dimos|puedo|podemos|pongo|ponemos|paso|untamos)\b|\bpara [eé]l\b|\bdarle\b|\bponerle\b", re.I)
FOR_BABY_ASKED = re.compile(r"\b(?:for|to|give|feed)\s+(?:theo|him|the baby)\b|\bpara (?:theo|[eé]l|el beb[eé])\b|\ba theo\b", re.I)
SHOPPING = re.compile(r"\b(?:shopping|list|buy|store|lista|compr\w+|s[uú]per)\b", re.I)
RECIPE_WORDS = re.compile(r"\b(?:recipes?|recetas?|pur[eé]e?|pur[eé]|thermomix|cookidoo)\b", re.I)
SUITS = re.compile(r"\b(?:suitable|perfect|great|ideal|good|safe|appropriate|fine|ok|okay|right)\s+(?:for|to give(?: to)?)\s+(?:theo|him|the baby|babies|a baby|a newborn|newborns|your baby|his age|little)\b|\bbaby[- ]friendly\b"
                   r"|\b(?:ideal|perfect[oa]|apt[oa]|adecuad[oa]|segur[oa]|buen[oa]|recomendad[oa])\s+para\s+(?:theo|[eé]l|el beb[eé]|beb[eé]s|un beb[eé]|su edad|reci[eé]n nacidos)\b|\b(?:suits|apt) (?:theo|him|a baby)\b", re.I)
# "I can't say if it's right for him" is what the home asks Muse to say, so it isn't the claim. Nor is "ask his pediatrician when it's ok for him".
HEDGED = re.compile(r"\w+n'?t\b|\b(?:not|never|cannot|whether|if|when|ask|no|ni|nunca|si|cu[aá]ndo|todav[ií]a|pregunt\w*|consult\w*|depends?|depende)\b", re.I)
SENT_THERE = re.compile(r"\b(?:sent|saved|published|added|uploaded)\b[^.!?]{0,25}\b(?:cookidoo|thermomix)\b|\b(?:envi[eé]|mand[eé]|guard[eé]|publiqu[eé]|sub[ií])\b[^.!?]{0,25}\b(?:cookidoo|thermomix)\b", re.I)
CANT_SEND = re.compile(r"\b(?:can'?t|cannot|can not|won'?t|not able to|unable to)\s+(?:\w+\s+)?(?:send|save|publish|upload)|\bnot sent\b|\bno\s+(?:\w+\s+)?(?:puedo|pude|podemos)\s+(?:\w+\s+)?(?:enviar|mandar|guardar|publicar|subir)|\bno se (?:puede|envi[oó]|mand[oó])", re.I)
# Words that say a parent is answering how Theo is, against an errand that only happens to come after an alarm.
HOW_HE_IS = re.compile(r"\btheo\b|\b(?:he|he's|him|his|beb[eé]|[eé]l)\b|\b(?:fine|better|okay|ok|calm|doctor|pediatr\w*|mejor|bien|tranquil\w*|doctora|m[eé]dic\w*)\b", re.I)
# A plan a parent reports from a doctor: it reaches the morning report in their words, whatever Muse chose to remember.
PLAN = re.compile(r"\b(?:pediatrician|pediatra|doctor\w*|doc|dr|m[eé]dic[oa]|nurse|enfermer[oa]|guardia)\b[^.!?]{0,40}\b(?:says?|said|told|wants?|asked|dijo|dice|quiere|pidi[oó]|indic\w+)\b"
                  r"|\b(?:bring(?:ing)?|tak(?:e|ing)) (?:him|theo)\b[^.!?]{0,40}\b(?:morning|tomorrow|doctor|pediatrician|clinic|hospital)\b"
                  r"|\b(?:llev\w+|lo llev\w+)\b[^.!?]{0,40}\b(?:ma[nñ]ana|pediatra|doctor\w*|m[eé]dic\w*|emergencia|guardia)\b", re.I)
PLAN_TOLD = re.compile(r"pediatr|doctor|m[eé]dic|bring|take him|llev|appointment|consulta|clinic|hospital|nurse|enfermer|guardia", re.I)
SAME_PLAN = re.compile(r"\bsame plan\b|\bmismo plan\b|\btake it back\b|\bla retoma\b|\bthe rota stands?\b|\bsigue en pie\b|\bstill stands?\b", re.I)
ASKS_HOW = re.compile(r"c[oó]mo\s+(?:est[aá]|sigue|anda|amaneci[oó]|pas[oó])|how(?:'s| is| was| did)\s+(?:theo|he)|how (?:theo|he) is", re.I)
BLUE_OR_BREATH = re.compile(VITAL.pattern + r"|breath|respir|\bblu\b|\bgr[ae]y\b|gris", re.I)
# Only what is known can be said about a night: "yesterday you were on", with the home started after it, was made up.
SAID_DUTY = re.compile(r"\b(?:yesterday|last night|ayer|anoche)\b[^.!?]{0,40}\b(?:on duty|de turno|was on|were on|you covered|covered|took|took over|estuvo|estuviste|cubri\w+|te toc[oó]|le toc[oó]|tuvo|tuviste)\b"
                      r"|\b(?:you were on|was on|on duty|de turno|te toc[oó]|le toc[oó]|estuviste|estuvo)\b[^.!?]{0,30}\b(?:yesterday|last night|ayer|anoche)\b", re.I)
WAITS_FOR_YES = re.compile(r"\b(?:when|once|if|until|as soon as|after)\s+(?:he|she|gonza|ceci)\s+(?:confirms?|says yes|agrees?|accepts?)\b|\b(?:cuando|si|hasta que|una vez que|apenas)\s+(?:\w+\s+)?(?:confirme|confirma|acepte|acepta|diga que s[ií])\b|\bpending (?:his|her) (?:ok|confirmation|yes)\b", re.I)
DAY_WORDS = re.compile(r"\bdaytime\b|\bdurante el d[ií]a\b|\bit'?s (?:the )?day\b|\bes de d[ií]a\b|\bby day\b", re.I)
NIGHT_WORDS = re.compile(r"\bnighttime\b|\bit'?s (?:the )?night\b|\bes de noche\b|\bat this hour of the night\b", re.I)
GLITCH = re.compile(r"\bglitch\w*|\b(?:is|it's|its|just|only|probably|likely|surely)\s+(?:a |an |the )?(?:sensor\s+)(?:fault|error|problem|failure)\b|\b(?:es|ser[aá]|solo|seguro|probablemente)\s+(?:un |una |el |la )?(?:error|falla|problema)\s+del\s+sensor\b", re.I)
CRY_SAID = re.compile(r"\bcry\w*|\bllor\w*|\bawake\b|\bup\b|despiert\w*|despert\w*", re.I)
# An appointment gets a reminder ahead of it. The rule against early wakes is for "remind me at 3".
APPOINTMENT = re.compile(r"\b(?:appointment|checkup|check-up|vaccin\w*|visit|consulta|cita|vacuna\w*|flight|vuelo|ecograf\w*)\b|\b(?:turno|control) (?:con|del?|en)\b|\b(?:at|to see|to the) (?:the )?(?:doctor|pediatrician|dentist)\b", re.I)
# Who is on duty has one record, the home's. A fact of Muse's own about it is how two versions came to exist.
DUTY_CLAIM = re.compile(r"\bon[ _]duty\b|\bde[ _]turno\b|\brota\b|\bnight[ _]shift\b|\btakes?[ _]the[ _]night\b|\bse queda con la noche\b|\b(?:te|le) toca la noche\b|\bwhose night\b", re.I)
# Muse saying it missed what a parent wrote, which it says when the home asks again without their words.
DIDNT_CATCH = re.compile(r"\b(?:didn'?t|did not|couldn'?t|could not)\s+(?:catch|get|see|read)\s+(?:your|that)\b|\bmissed your\b|\bno\s+(?:vi|le[ií]|entend[ií]|recib[ií]|capt[eé]|me lleg[oó])\s+tu\b|\bno te entend[ií]\b", re.I)
REMIND_ASK = re.compile(r"\bremind\w*|\brecord[aá]\w*|\bacord[aá]\w*|\bavis[aá]me\b|\bav[ií]same\b", re.I)
ABOUT_HOW_HE_IS = re.compile(ASKS_HOW.pattern + r"|\bcheck (?:on|how) (?:theo|him)\b|\bfollow[- ]?up\b|reached (?:his|the|a) (?:doctor|pediatrician)", re.I)
# A morning message isn't a ledger, and nobody owes anybody a night.
SCOREKEEP = re.compile(r"\bcovered for\b|\bte cubri\w*\b|\bcubri\w* a\b|\btakes? it back\b|\bla retoma\b|\bretom[aá]\w*\b|\byou owe\b|\bowes you\b|\bte debe\b|\ble deb[eé]s\b|\bpay(?:s|ing)? (?:you |him |her )?back\b", re.I)
# How a log reads, not how a person writes. A parent asking for the numbers gets them.
QUESTION = re.compile(r"¿[^?\n]*\??|[^.!?¿\n]*\?")
# A question that is really a request, or a tag on what they just said: "Can you turn it off?" and "Ceci has tonight, right?" are answered by "Dale".
ASKS_TO_DO = re.compile(ERRAND.pattern + r"|\b(?:can|could|would|will) you\b|\bpod[eé]s\b|\bpodr[ií]as\b|\b(?:right|ok|okay|dale|s[ií]|no|vale)\W*$", re.I)
WANTS_A_FACT = re.compile(r"\b(?:how|when|what|who|where|why|cu[aá]nd\w*|cu[aá]nt\w*|qué|qui[eé]n|d[oó]nde|c[oó]mo)\b", re.I)
BARE_ACK = re.compile(r"^\W*(?:(?:ya lo tengo|lo tengo|ya est[aá]|got it|got that|i have it|i'?ve got it|i got it|noted|anotad[oa]|listo|lista|dale|ok|okay|okey|perfecto|entendido|recibido|de acuerdo|all set|done|hecho|claro|sure|thanks|thank you|gracias|gonza|ceci)\W*)+$", re.I)
ACK_WORDS = 5
# Nov 4: "Gonza's on duty and checking on it", when nobody had said so. Who is on duty is known, what they are doing now isn't. Asking it, or saying they aren't, is fine.
OTHER_ON_IT = re.compile(r"\b(?:gonza|ceci)\b[^.!?\n]{0,40}?(?<![a-z]n't )(?<!\bno )\b(?:checking on (?:it|him|theo)|checking it|is checking|'s checking|looking (?:at it|into it|in on (?:him|theo))|is on it|going to check|"
                         r"est[aá] (?:revisando|chequeando|viendo|mirando)|(?:lo|la) est[aá] (?:viendo|revisando|chequeando|mirando)|va a (?:chequear|revisar|ver|mirar)|lo va a (?:ver|revisar|chequear))\b(?![^.!\n]*\?)", re.I)
SAID_ON_IT = re.compile(r"\bcheck\w*|\bchequ\w*|\brevis\w*|\bviendo\b|\bmirando\b|\bvoy\b|\blook\w*|\bon it\b|\bva a\b|\bgoing\b", re.I)
# How an alarm ended, as a parent says it. A parent asking it, or saying he isn't, isn't an ending.
SETTLED = re.compile(FALSE_ALARM.pattern + r"|\ball (?:is )?(?:fine|good|ok|okay|well)\b|\b(?:he|theo)(?:'s| is| was)(?: \w+)? (?:fine|ok|okay|better|calm|calmer|asleep|sleeping|good)\b|\btodo (?:est[aá] |anda |sigue )?(?:bien|tranquilo)\b|"
                     r"(?:^\W*|\b(?:theo|[eé]l|ya|beb[eé]|nene)\s+)(?:est[aá]|qued[oó]|sigue|anda)(?: \w+)? (?:bien|mejor|tranquilo|dormido)\b(?!\s*,)|\bya (?:pas[oó]|est[aá] bien)\b|\bse (?:calm[oó]|durmi[oó])\b", re.I)
NOT_SETTLED = re.compile(r"\b(?:not|isn'?t|wasn'?t|no)\s+(?:\w+\s+)?(?:fine|ok|okay|better|good|calm|asleep|sleeping|est[aá]|anda|sigue|qued[oó]|bien|mejor|tranquilo|dormido)\b", re.I)
LOG_LIKE = re.compile(r"\b\d+\s?(?:ml|cc)\s+(?:total|in all|in total|overall|en total|en todo)\b|\b(?:total|en total)\s*[:(]?\s*\d+\s?(?:ml|cc)\b|\b\d+\s+(?:feeds?|tomas?|comidas?)\s*\(|"
                      r"\b\d+\s+(?:wet|dirty|pis|caca)\b|\bwet only\b|\bsolo pis\b|\b\d+\s+(?:diapers?|pa[ñn]ales?)\b", re.I)
ASKS_NUMBERS = re.compile(r"\bhow (?:many|much)\b|\btotals?\b|\bsummary\b|\bcu[aá]nt[oa]s?\b|\bresumen\b|\bbaby_summary\b", re.I)
# A camera that speaks like a friend's nudge, never like someone watching them.
WATCHING = re.compile(r"\bi(?:'m| am) (?:watching|monitoring|keeping an eye)\b|\bi (?:saw|see|caught) you\b|\byou (?:left|took|let go|removed|forgot)\b|\bmonitor\w*|\bsurveil\w*|\bcaught\b|\bwarning\b"
                      r"|\bte (?:vi|veo|estoy (?:viendo|mirando))\b|\bsacaste\b|\bdejaste\b|\bte olvidaste\b|\bvigil\w*|\bmonitore\w*", re.I)
ENDS_ALONE = re.compile(r"\bby itself\b|\bon its own\b|\bitself\b|\bautomatically\b|\bsolo\b|\bsola\b|\bsolito\b|\bautom[aá]tic\w*", re.I)
# What a recipe is for, with a newborn in the house. Theo's age is a fact. It says nothing of what any food does.
LATER_ON = re.compile(r"\blater\b|\bfor you\b|\bfor now\b|\bnot yet\b|\bgrown[- ]?ups?\b|\bpara ustedes\b|\bpor ahora\b|\bm[aá]s adelante\b|\btodav[ií]a no\b|\bm[aá]s grande\b|\blos grandes\b", re.I)
DOCTOR_STEP = re.compile(r"\bpediatr\w*|\bdoctor\w*|\bm[eé]dic\w*|\b911\b", re.I)
# "Evening check, ..." is the home talking to itself.
NAMES_CHECK = re.compile(r"\b(?:evening|morning|nightly|daily) check\b|\brevisi[oó]n de la (?:noche|ma[ñn]ana)\b|\bchequeo de la (?:noche|ma[ñn]ana)\b", re.I)
SHORT_DATE = re.compile(r"\s*\(\s*(?:\d{1,2}\s+(?:de\s+)?(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|ene|abr|ago|set|dic)[a-z]*\.?|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2})\s*\)", re.I)
ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}:\d{2})(?::\d{2})?(?:[+-]\d{2}:?\d{2}|Z)?)?\b")
MONTHS = {"en": "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(), "es": "ene feb mar abr may jun jul ago set oct nov dic".split()}
JARGON = re.compile(r"\brota\b|\bper the\b|\bas per\b|\bper (?:ceci|gonza)\b|\bdoes that (?:still )?stand\b|\bsince 22:00\b|\bdesde las 22\b", re.I)


def amounts(entries):
    """Every ml amount in the log, and the running totals from the newest feed back, so "180 ml in all" can be true."""
    feeds = [e["details"]["amount_ml"] for e in entries if isinstance((e.get("details") or {}).get("amount_ml"), (int, float))]
    known, total = set(), 0
    for amount in reversed(feeds):
        total += amount
        known |= {int(amount), int(total)}
    return known


def unbacked(text, entries, heard=""):
    """Why a message can't go out because it says what nobody knows, or None. entries is a callable, so the log is read only
    when a message makes such a claim. heard is the parent's own words: repeating them is fine."""
    text, heard = text or "", heard or ""
    claim = HOW_IT_WENT.search(text)
    if claim and claim.group(0).lower() not in heard.lower():
        return f'Refused, nothing was sent: the log does not say "{claim.group(0)}". Say only what the log shows.'
    said = {int(n) for n in MILLILITERS.findall(text)} - {int(n) for n in re.findall(r"\d+", heard)}
    if said:
        missing = said - amounts(entries())
        if missing:
            return f"Refused, nothing was sent: the log has no {min(missing)} ml. Say only what the log shows."
    return None


def lang_of(text, default="es"):
    text = text or ""
    if rules.looks_spanish(text) or DANGER_ES.search(text):
        return "es"
    return "en" if rules.ENGLISH.search(text) or DANGER_EN.search(text) else default


def about_a_story(text):
    """A film, a book, a made-up baby or someone else's: not an alarm in this home. Muse answers, and anything about Theo in the same words still fires."""
    text = text or ""
    if THIS_BABY.search(text):
        return False
    if OTHER_BABY.search(text):
        return True
    return bool(FICTION.search(text)) and (bool(IN_STORY.search(text)) or not HE_NOW.search(text))


def about_someone_else(text):
    text = text or ""
    return bool(SOMEONE_ELSE.search(text) or NAMED_OTHER.search(text)) and not THEO_NAMED.search(text) and not SAYS_ABOUT_HIM.search(text)


def about_the_room(text):
    """A question about the room's heat or air, and nothing about him. Muse reads the sensor."""
    text = text or ""
    return bool(ROOM_WORD.search(text) and ROOM_ASK.search(text)) and not SAID_OF_HIM.search(text)


def injected(text):
    return bool(INJECTION.search(text or ""))


SIGN_MAX = 160
SIGN_WORDS = re.compile(DANGER_SIGN.pattern + r"|fever|fiebre|\b3[89](?:[.,]\d)?\b|\b40(?:[.,]\d)?\b|gasping|choking|ahog", re.I)


def sign_of(text):
    """The words that raised the alarm, kept whole: the sentence with the danger in it, without the rest of the message. It is what the other parent,
    the log and the morning check quote, so an instruction in the same message goes no further."""
    parts = [p.strip(" ,\n") for p in re.split(SENTENCE, text or "") if p.strip() and not INJECTION.search(p)]
    worst = [p for p in parts if VITAL.search(p) or rules.EMERGENCY.search(p)] or [p for p in parts if SIGN_WORDS.search(p)]
    words = ". ".join(worst or parts[:1])
    if len(words) <= SIGN_MAX:
        return words
    found = VITAL.search(words) or rules.EMERGENCY.search(words) or SIGN_WORDS.search(words)  # a long run-on keeps the part with the danger, not its start
    start = max(0, found.start() - SIGN_MAX // 2) if found else 0
    start = words.find(" ", start) + 1 if start else 0
    return words[start:start + SIGN_MAX].strip(" ,")


def unsafe_room(payload):
    """The reading when a temperature event says Theo's room is far out of range, or None."""
    if "temperature" not in str(payload.get("entity_id", "")):
        return None
    try:
        value = float(payload.get("state"))
    except (TypeError, ValueError):
        return None
    return value if value >= HOT_ROOM or value <= COLD_ROOM else None


def because(sender, text, line, lang):
    """The fixed line for the other parent says who wrote and why, or it reads as an alarm from nowhere."""
    words = {"es": 'escribió', "en": "wrote"}[lang]
    return f'{str(sender).capitalize()} {words}: "{sign_of(text)}"\n{line}'


def just_worry(text):
    """Fear, tiredness or a question the log can answer, with no danger sign named. Muse reads the log and answers."""
    text = text or ""
    return bool(SCARED.search(text) or WORN_OUT.search(text) or LOG_QUESTION.search(text)) and not DANGER_SIGN.search(text)


def without_fever_over(text):
    """A message with the words naming a fever as over taken out, so whatever else it says is read as ever. Any number that could be a fever, a question about it, a doubt, or a sign of it coming back leaves it whole, and it fires."""
    text = text or ""
    if not FEVER_OVER.search(text) or FEVER_DOUBT.search(text) or rules.TEMP_NUMBER.search(text):
        return text
    for found in FEVER_OVER.finditer(text):
        clause = re.split(r"[,;:.!?\n]", text[:found.start()])[-1]
        sentence_end = re.search(r"[.!?\n]", text[found.end():])
        sentence = re.split(r"[.!?\n]", text[:found.start()])[-1] + text[found.start():found.end() + (sentence_end.end() if sentence_end else len(text))]
        if FEVER_NOT_OVER_YET.search(clause) or "?" in sentence or "¿" in sentence:
            return text
    return FEVER_OVER.sub(" ", text)


def worth_waking(text):
    """Whether a parent's words name anything that could justify waking the other at night: a sign, a fear, a danger in the house. Muse setting emergency isn't enough."""
    text = without_fever_over(HOT_THING.sub(" ", text or ""))
    return bool(WORTH_WAKING.search(text) or rules.is_emergency(text) or rules.spoken_emergency(text) or BUMPED.search(text) or HARD_TO_WAKE.search(text) or TYPED_FAST.search(text))


def unasked_tip(text, heard):
    """A care step nobody asked about, like testing drops on the wrist."""
    return bool(UNASKED_TIP.search(text or "")) and not UNASKED_TIP.search(heard or "")


def needs_answer(heard):
    """Whether a parent's words ask something that "got it" doesn't answer."""
    return any(WANTS_A_FACT.search(q) or not ASKS_TO_DO.search(q) for q in QUESTION.findall(heard or ""))


def only_acknowledges(text, heard):
    """A bare "Ya lo tengo." back to a parent who asked something: Ceci asked how much he took, and that is all she got."""
    return len((text or "").split()) <= ACK_WORDS and bool(BARE_ACK.match(text or "")) and needs_answer(heard)


def says_other_on_it(text, heard):
    """A parent named as doing something right now, and nobody said so. A question in their words ("can you check?") isn't them saying it."""
    return bool(OTHER_ON_IT.search(text or "")) and not SAID_ON_IT.search(QUESTION.sub(" ", heard or ""))


def reassures(text):
    """Calm said in the agent's own voice. A parent's quoted words and a question ("¿todo bien?") aren't."""
    unquoted = re.sub(r'"[^"]*"|“[^”]*”', " ", text or "")
    return any(CALM.search(sentence) and "?" not in sentence and "¿" not in sentence for sentence in re.split(r"(?<=[.!?\n])\s*", unquoted))


def only_asks(text):
    """All a parent wrote is a question. "¿Cuánto tomó?" says nothing of how he is, so it can't answer an alarm."""
    return "?" in (text or "") and not re.sub(r"\W+", "", QUESTION.sub(" ", text))


def settled_line(text):
    """The sentence where a parent says an alarm ended well, in their own words, or None."""
    for sentence in re.split(r"(?<=[.!?\n])\s*", text or ""):
        if SETTLED.search(sentence) and "?" not in sentence and "¿" not in sentence and not NOT_SETTLED.search(sentence) and not VITAL.search(sentence) and not INJECTION.search(sentence):
            return sentence.strip(" ,.\n")[:SIGN_MAX]
    return None


def writes_as_someone_else(parent, text):
    """Why a message reads wrong to the one getting it: "does Ceci take it back?", written to Ceci. Their name opening the line is fine."""
    found = re.search(rf"\b{re.escape(str(parent))}\b", text or "", re.I)
    if found and found.start() > 3:
        return f"Refused, nothing was sent: this goes to {parent}, so write to them as you, not about {str(parent).capitalize()}. Say what you need from them."
    return None


def frightened(text):
    """A parent afraid about a sign in Theo right now, which the gate didn't call a danger. The other parent should know, and the first words are who to call."""
    text = text or ""
    return bool(SCARED.search(text) and DANGER_SIGN.search(text)) and not about_a_story(text) and not about_someone_else(text) and not injected(text)


def plain_dates(text, lang="es"):
    """Nobody writes (2026-12-15) to a person, in a message or in the book. Dropped when it only repeats tonight, and said as a date when it is the only date there."""
    text = SHORT_DATE.sub("", re.sub(r"\s*\(\s*\d{4}-\d{2}-\d{2}\s*\)", "", text or ""))

    def said(found):
        month, day = MONTHS["en" if lang == "en" else "es"][int(found.group(2)) - 1], int(found.group(3))
        date = f"{month} {day}" if lang == "en" else f"{day} de {month}"
        return f"{date} {found.group(4)}" if found.group(4) else date
    return ISO_DATE.sub(said, text)


def reports_feed(text):
    return bool(FEED_REPORT.search(text or "")) and "?" not in (text or "")


def worn_out(text):
    return bool(WORN_OUT.search(text or "")) and not DANGER_SIGN.search(text or "")


def brief(line):
    """The fixed urgent line, short, with its source last and on its own line, so it stays one tap and not a wall of text."""
    found = re.search(r"https?://\S+", line)
    if not found:
        return line
    words = re.sub(r"\s*(?:This is the public guidance|Es la gu[ií]a p[uú]blica)[^:]*:?\s*$", "", line[:found.start()]).rstrip()
    return f"{words}\n{found.group(0)}"


def without_pets(text):
    """A sentence about an animal, with no word for him in it, isn't a sign in Theo. "The dog bit him" keeps its sentence."""
    return " ".join(p for p in re.split(r"(?<=[.!?;\n])\s+", text or "") if not PET.search(p) or ABOUT_HIM.search(p)) if PET.search(text or "") else (text or "")


def gate(text, screen=None, lang=None):
    """(kind, line) for a message that must not reach Muse, or None. kind is emergency, urgent or medical."""
    lang = lang_of(text, lang or "es")
    text = without_fever_over(without_pets(UNRELATED.sub(" ", text or "")))
    if about_a_story(text):  # a dose Muse might write is still refused on the way out
        return None
    signs = NOT_A_SIGN.sub(" ", text or "")
    if DENIED.search(text or ""):
        if not VITAL.search(signs):
            return None
        return "emergency", rules.EMERGENCY_REPLY[lang]  # a sign named outranks the words around it, with or without the model
    text = ERRANDS.sub(" ", text or "")
    signs = NOT_A_SIGN.sub(" ", text)
    if rules.is_emergency(text) or rules.spoken_emergency(text) or BUMPED.search(text) or TYPED_FAST.search(signs) or HARD_TO_WAKE.search(signs) or (STOPPED.search(text) and not FICTION.search(text)):
        return "emergency", rules.EMERGENCY_REPLY[lang]
    if about_the_room(text):
        return None
    if just_worry(text):
        return None
    if about_someone_else(text):  # not about Theo: Muse answers, and a dose is still refused
        return ("medical", rules.NO_ADVICE[lang]) if rules.asks_dose(text) else None
    if injected(text):  # the screen reads only what isn't an order to it, and only if it says something about him
        text = ". ".join(p for p in re.split(SENTENCE, text) if not INJECTION.search(p) and (DANGER_SIGN.search(p) or THEO_NAMED.search(p)))
        if not text:
            return None
    food = unsafe_food(text, lang)
    if food:
        return "medical", food
    urgent = rules.newborn_red_flag(text)
    if urgent:
        return "urgent", brief(rules.URGENT_REPLY[urgent][lang])
    if rules.asks_dose(text) or (rules.asks_advice(text) and (rules.is_medical(text) or rules.is_medical_es(text))):
        return "medical", rules.NO_ADVICE[lang]
    if (screen or danger.build(SCREEN)).screen(IMPOSSIBLE_ML.sub("a bottle", text))[0]:
        return "emergency", rules.EMERGENCY_REPLY[lang]
    return None


def unsafe_food(text, lang="es"):
    """The fixed line for a food no baby under 12 months has, if these words are about giving it to Theo. A cake for the grown-ups, or honey on the shopping list, is nothing."""
    for clause in re.split(SENTENCE, text or ""):
        for food, line in UNSAFE_FOODS:
            if food.search(clause) and FOR_BABY.search(clause) and (not SHOPPING.search(clause) or FOR_BABY_ASKED.search(clause)):
                return line["en" if lang == "en" else "es"]
    return None


def water_only(item):
    """Water, alone or among the words of one list item. It comes from the tap, so it isn't shopping (Nov 3, "100 g de agua" on the list)."""
    return any(re.fullmatch(r"(?:\d+[.,]?\d*\s*(?:g|gr|grams?|gramos?|ml|l|cc|liters?|litros?|cups?|tazas?)?\s*)?(?:(?:of|de)\s+)?(?:tap\s+|filtered\s+)?(?:water|agua)(?:\s+de\s+la\s+canilla)?", part.strip(), re.I)
               for part in re.split(r"[,;]|\by\b|\band\b", str(item or "")))


def near_same(one, other):
    """Nearly the same message: the same numbers, and most of the same words."""
    if set(re.findall(r"\d+(?:[.,:]\d+)?", one)) != set(re.findall(r"\d+(?:[.,:]\d+)?", other)):
        return False
    return difflib.SequenceMatcher(None, one.lower(), other.lower()).ratio() >= 0.75


def says_cant_send(text):
    return bool(CANT_SEND.search(text or "") and re.search(r"cookidoo|thermomix", text or "", re.I))


def says_suits(text):
    """A recipe called good for a baby, said as a fact. The same words after a no, an if or a when say the opposite."""
    for sentence in re.split(SENTENCE, text or ""):
        for found in SUITS.finditer(sentence):
            if not HEDGED.search(sentence[:found.start()]):
                return True
    return False


def plan_of(text):
    """The sentences of a parent's message that hold a doctor's plan, or an empty string. Not an order to the agent and nobody else's child."""
    if injected(text) or about_a_story(text) or about_someone_else(text):
        return ""
    return ". ".join(p.strip(" ,\n") for p in re.split(SENTENCE, text or "") if PLAN.search(p))[:SIGN_MAX]


def rest_of(text):
    """The parts of a message the gate has no business with, for Muse. An alarm in one sentence never eats the errand in the next."""
    parts = [p.strip(" ,") for p in CLAUSE.split(text or "") if p and len(p.split()) >= 3]
    return " ".join(p + "." for p in parts if len(parts) > 1 and ERRAND.search(p) and not gate(p, _NO_SCREEN))


class _NoScreen:
    def screen(self, text):
        return False, "words"


_NO_SCREEN = _NoScreen()


def gap_step(hours):
    """The highest step of the ladder this gap has reached, or None."""
    return max((s for s in GAP_STEPS if hours >= s), default=None)


def gap_line(hours, step, lang="es"):
    lines = GAP_LINES["en" if lang == "en" else "es"]
    return lines[0 if step < BOTH_FROM else 1 if step < 24 else 2].format(h=int(hours))


def sensor_jump(entity, value, before, minutes):
    """Why a reading can't be the room, or None: a room doesn't move this far this fast."""
    kind = next((k for k in SENSOR_JUMP if k in str(entity)), None)
    if kind and minutes <= JUMP_MINUTES and abs(value - before) >= SENSOR_JUMP[kind]:
        if unsafe_room({"entity_id": entity, "state": value}) is not None:  # "31.5 is a sensor glitch" hid a hot room: until a second reading, it is real
            return (f"This reading went from {before:g} to {value:g} in {minutes:.0f} minutes. It may be the sensor, and nobody can know yet, so treat it as real: tell the parent on duty the reading now, "
                    "and to go and check the room. Never say it is a glitch or nothing. You are woken in a few minutes to read it again. Don't move a device on it until another reading agrees.")
        return f"This reading went from {before:g} to {value:g} in {minutes:.0f} minutes, which a room can't do. Suspect the sensor: say so to the parent on duty and don't move a device on it until another reading agrees."
    return None


def topic_of(why):
    """What a wake is about, so two chains about one thing become one. None when it is about anything else."""
    why = str(why or "")
    return "air" if ABOUT_THE_AIR.search(why) else "warmer" if GETS_READY.search(why) else "room" if ABOUT_THE_ROOM.search(why) else None


def wake_about_him(why):
    """A wake that would ask how Theo is after an alarm. "Follow up on the humidity" is about the air, and only "follow up" named it (Nov 4)."""
    why = str(why or "")
    return bool(ABOUT_HOW_HE_IS.search(re.sub(r"\bfollow[- ]?up\b", " ", why, flags=re.I) if topic_of(why) else why))


def clock24(found):
    hour = int(found.group(1)) % 12 + (12 if found.group(3).lower() == "p" else 0)
    return f"{hour:02d}:{found.group(2) or '00'}"


def plain(text):
    """Muse writes long dashes, and nobody in this house texts with them. Times read one way, on the 24 hour clock."""
    return AM_PM.sub(clock24, re.sub(r"\s*[\u2014\u2013]\s*", ", ", (text or "").replace("**", "")))


def outbound(text, lang="es"):
    """(text to send, why it was refused). The final guard drops machinery, a dose or a drug refuses the whole message."""
    if ADVICE_OUT.search(text or ""):
        return None, "Refused, nothing was sent: never a dose, a drug or a diagnosis. Say what you saw or did instead."
    out = final_guard.apply(plain(plain_dates(text, lang)), lang=lang)
    if out in final_guard.FALLBACK.values():  # "that answer did not come out right" isn't a message to a parent (Nov 3, the recipe's line about Cookidoo)
        return None, "Refused, nothing was sent: that couldn't go out as written. Write it again in plain words, in the language the event names, with no names of models or tools."
    return out, None
