"""Rules the fake brain uses offline: turn a parent's note into a log event, answer from a summary, refuse health questions.

The real brain (Muse Spark Open) does this from the tool descriptions. These rules let
the tests check the whole path to Baby Buddy and back with no network, and give the fake brain the same
behaviour the system prompt asks of the real one.
"""
import datetime
import re
import unicodedata

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
                        r"c[oó]lico|gotas para|larg[oó] (un poc|leche|algo|todo|bastante|mucho|un chorr|lechita)|regurgit|bocanada)", re.I)
# Red flags: an answer in no time, with no brain call, that says to call emergency services. Fussing and crying are
# not on the list, they get the likely reason from the log instead.
EMERGENCY = re.compile(
    r"\b(not breathing|stopped breathing|isn'?t breathing|can'?t breathe|cannot breathe|struggling to breathe|"
    r"(blue|purple|gr[ae]y) (lips|face)|lips (are |look |turned |turning )?(blue|purple|gr[ae]y)|turn(ed|ing|s)? (blue|purple)|"
    r"limp\b|limply|floppy|chok(e|es|ed|ing)|won'?t wake|wont wake|can'?t wake|cannot wake|not waking|unresponsive|"
    r"fell (off|from|down|out of)|had a fall|dropped (him|her|the baby)|hit (his|her|the|its) head|head injury|seizure|convuls\w*|"
    r"no respira|dej[oó] de respirar|le cuesta (mucho |bastante |un mont[oó]n |re |muy )?respirar|no puede respirar|"
    r"no (lo |la )?(puedo|podemos|logro|logramos|consigo) despertar|can'?t be woken|cannot be woken|(won'?t|doesn'?t|isn'?t) waking( up)?|"
    r"(est[aá]|se puso|se pone|se ve|se le puso|qued[oó]|labios|cara|boca) (muy |re |medio |todo |toda |bien |un poco )?(morad|violet|gris)\w*|"
    r"dusky|mottled|ashen|(turn\w*|going|gone|went|go(es)?|got|look\w*|is|was|seems?) (a bit |kind of |very |really |so )?gr[ae]y\b|"
    r"labios azules|se puso azul|"
    # A baby, lips or face that are blue, said with no other sign (the glasses speech run, Oct 30). A blue onesie, a
    # blue eyed baby or a blue sky is not one: the colour has to be what the baby, the lips or the face are.
    r"(beb[eé]|beba|nene|nena|labios|cara|boca|piel|cuerpo) (est[aá]n?|se (le )?(puso|pusieron|pone|ve|ven)|qued[oó]) "
    r"(muy |re |medio |todo |toda |bien |un poco )?azul\w*|se (le |me )?pus(o|ieron) (la cara|la boca|los labios|la piel) "
    r"(muy |re |medio |toda |bien )?(azul|morad|violet)\w*|"
    r"(baby|he|she|lips|face|skin)('s| is| are| looks?| went| turned| seems?) (all |really |very |kind of |a bit |so )?"
    r"blue\b(?![- ]?(eyed|eyes|onesie|outfit|shirt|hat|blanket))|"
    r"se (est[aá] )?ahog\w*|atragant\w*|no se despierta|no reacciona|no responde|"
    r"se (me )?cay[oó](?! (el|la) (chupete|mamadera|biber[oó]n|tete|juguete))(?! (dormid\w*|rendid\w*|frit\w*|redond\w*))|"
    # Falls the round 3 audit found missing: the baby fell, rolled off the bed or the couch.
    r"(the baby|baby|he|she|my baby|my son|my daughter) fell(?! (back )?asleep)(?! into)\b|rol+ed (off|out of)|rol+s (off|out of)|"
    r"(slid|slipped|slides|tumbled|tumbles|toppled|took a tumble|took a fall|had a tumble) (right |straight )?(off|out of|from|down (from|off))\b|"
    r"se (me |le )?(resbal[oó]|desliz[oó]) (del?|de la|de los|de mis|de sus)\b|"
    r"se golpe[oó]|golpe en la cabeza|convulsi\w*|"
    r"(had|has|having|is having|went into) (a |another )?(fit|fits)\b|"
    r"(whole|entire) body (is |was |keeps |kept |started |starts )?(shak|trembl|jerk|twitch|stiffen)\w*|shaking all over|"
    r"(shak|trembl|jerk|twitch)\w* (and|but) (he |she )?(won'?t|doesn'?t|does not|isn'?t|is not|can'?t) (respond|answer|look|react|wake)\w*|"
    r"(eyes|arms|legs|arms and legs) (are |were |keep |kept |won'?t stop )?(twitch|jerk)\w*|won'?t stop (jerking|twitching)|"
    r"tembl\w* (todo el cuerpo|el cuerpo entero|entero|entera|enter[oa]s?)|(le )?tiembla todo el cuerpo|tiembla enter[oa]|"
    r"(todo el cuerpo|el cuerpo entero) (le )?(tembl|sacud)\w*|temblor\w* (en|de) todo el cuerpo|"
    r"(tembl|sacud)\w* (y|pero) no (responde|reacciona|me mira|mira)|"
    # Bath, changing table and breathing red flags a safety audit found missing (round 2), English then rioplatense.
    r"gasp\w*|(trouble|difficulty|hard time|problems?) breathing|breath(ing|es) (really |very |so |too )?(fast|hard|rapid\w*|weird\w*|strange\w*)|"
    r"labou?red breathing|went under(?! (the |his |her |a )?(blanket|covers|sheets?|table|bed|crib|cot|sofa|couch|chair))|(head|face) went under|slipped under|(went|was|stayed|slipped|got|been|is|fell|sank|sunk) (all the way |completely )?under (the )?water|drown\w*|"
    r"(swallowed|ate|ingested|put) (a |an |the |some |one of the |two )?(button |coin )?(battery|batteries|magnets?)\b|"
    r"(swallowed|drank|ate) (some )?(bleach|detergent|a (laundry |detergent )?pod)|poison\w*|"
    r"(dog|puppy|pup|cat|kitten|pet)'?s? (\w+ )?(bit|bites|bitten|nipped|mauled|attacked|scratched|grabbed|clawed)\b|"
    r"(bit|bitten|nipped|mauled|attacked|scratched) by (the |a |our |my )?(dog|puppy|cat|pet)|"
    r"(perr[oa]|cachorr[oa]|gat[oa]|mascota)s? (\w+ )?(lo |la |le )?(mordi[oó]|muerde|ara[ñn][oó]|atac[oó]|agarr[oó])|"
    r"(mordi[oó]|ara[ñn][oó]|atac[oó]) (el|la) (perr[oa]|gat[oa])|mordid[oa] por|"
    r"(got into|licked|bit|bitten|chewed|sucked|mouthed|ate|swallowed|drank|had) (on |at |from )?(a |an |the |some |one of the |my |our )?"
    r"(dishwasher|laundry|detergent|washing) (tablets?|pods?|capsules?|liquid|detergent|soap|powder)|"
    r"(tom[oó]|bebi[oó]|chup[oó]|mordi[oó]|lami[oó]|se meti[oó] en la boca) (\w+ )?(lavandina|detergente|c[aá]psulas? de (detergente|lavarropas|lavavajillas)|pastillas? del lavavajillas)|"
    r"(bulging|swollen|sunken|sunk|caved) (in )?(soft spot|fontanel\w*)|(soft spot|fontanel\w*) (is |looks |seems )?(bulging|swollen|puffy|sunken|sunk|caved)|"
    r"(fontanela|mollera) (est[aá] |se ve |se le ve |muy |re )?hundid\w*|(fontanela|mollera) (se )?(le )?hund(i[oó]|e)|cuello (duro|r[ií]gido|tieso)|"
    r"rash (that )?(doesn'?t|does not|won'?t|didn'?t|isn'?t going to) (fade|go away|blanch)|non[- ]?blanching|"
    r"(spots|dots|rash) (that )?(don'?t|do not|won'?t) fade|(manchitas?|puntitos?|manchas?) (\w+ )?que no se (van|borran|desaparecen)|"
    r"(pale|grey|gray) and cold|cold and (pale|grey|gray)|scald\w*|burn(ed|t) (him|her|the baby|his|her)|"
    r"unconscious|passed out|faint(ed|ing)|(he|she|baby)('s| is)? (not|isn'?t) moving|"
    r"boque\w*|le falta (el )?aire|(dificultad|le cuesta) (para )?respirar|"
    r"respira (muy |re |demasiado )?(r[aá]pido|agitad\w*|raro|con dificultad)|"
    r"se (me )?hundi[oó]|(bajo|abajo|debajo) (del|el) agua|ahogad\w*|"
    r"(trag[oó]|se comi[oó]|se trag[oó]) (una |un |la |el |unas |unos )?(pila|pilas|bater[ií]a\w*|im[aá]n|imanes|lavandina|detergente)|"
    r"(pila|pilas|bater[ií]a\w*|im[aá]n|imanes)\b.{0,25}\b(se )?(lo |la |los |las )?trag[oó]|pila de bot[oó]n|envenen\w*|intoxic\w*|"
    r"(fontanela|mollera) (est[aá] |se ve |muy )?(abultad\w*|hinchad\w*|inflad\w*)|"
    r"p[aá]lid[oa] y fr[ií][oa]|fr[ií][oa] y p[aá]lid[oa]|se (me )?quem[oó]|quemadura|"
    r"se desmay[oó]|desmayad[oa]|inconsciente|(?<!cuna )(?<!silla )(?<!hamaca )(?<!mesa )(?<!cama )(?<!puerta )(?<!rueda )(?<!auto )(?<!mecedora )no se mueve(?! de)(?! (la|el) (hamaca|cuna|mecedora|silla|sillita|puerta|auto|coche|cochecito|carrito|mois[eé]s|juguete|m[oó]vil|ventilador|rueda))|"
    # Pills, medicine and coins, eyes rolling back and a chest that caves in, from the round 3 audit.
    r"(swallowed|ate|got into|chewed) (a |an |some |one of |my |the |his |her |two |few |a few )*(pills?|tablets?|coins?|medicines?|medication|meds)\b|"
    r"drank (some of |some )?(my|mom'?s|dad'?s|grandma'?s|the|a bottle of|his brother'?s|her sister'?s) (medicine|medication|meds|cough syrup|syrup)|"
    r"(se )?(trag[oó]|comi[oó]) (una |un |unas |unos |mi |mis |la |el |las |los |dos )*(monedas?|pastillas?|pastillitas?|comprimidos?|remedios?|medicamentos?)\b|"
    r"se tom[oó] (mi|mis|el de|un frasco de) (remedio|pastillas?|jarabe|medicamento)|"
    r"eyes (are |were |keep |kept )?(rolling|rolled|roll) back|eyes rolling|ojos (para|hacia) atr[aá]s|ojos en blanco|pone los ojos en blanco|"
    r"chest (caves?|caving|caved|sinks?|sinking|sucks?|sucking|pulls?|pulling) in|ribs (show|showing|pull\w*) (in )?when|retraction\w*|"
    r"se le hunde el pecho|se le marcan las costillas|tiraje|"
    # Grunting or moaning with every breath is a 911 sign on the healthychildren.org newborn illness list.
    # Round 5 auditor misses: colour around the mouth, purple and blotchy skin, a dog that snapped or broke the skin,
    # a baby dropped out of the arms, a tumble down stairs, and a bottle hot enough to make him scream.
    r"(blue|purple|gr[ae]y|bluish|dark) (all )?(a?round|near) (the |his |her )?(mouth|lips)|"
    r"(purple|blue|gr[ae]y) and blotchy|blotchy (and )?(purple|blue|gr[ae]y)|blotchy (purple|blue) (skin|patches)|"
    r"(dog|puppy|pup|cat|pet)'?s? (\w+ )?snapped at (the baby|him|her|my (baby|son|daughter))|"
    r"(dog|puppy|pup|cat|pet|bite|bit|scratch\w*|claw\w*)\b[^.!?]{0,40}\bbroke (the |his |her )?skin|"
    r"taras(c|qu)[oó]n|"
    r"(dropped|slipped|fell|slid|tumbled|wriggled) (right |straight )?(out of|from) (my|his|her|our|their|dad'?s|mom'?s) (arms|hands|grip)|"
    r"se (me |le )?cay[oó] de (los|mis|sus) brazos|"
    r"(tumbled|tumbles|rolled|rolls|slid|slipped|bounced) down (the |two |three |a few |some |a couple of |\d+ )?(stairs|steps|staircase)|"
    r"(bottle|milk|formula|water|bath|tea|coffee)\b[^.!?]{0,25}\btoo hot\b[^.!?]{0,40}\b(scream\w*|shriek\w*|howl\w*|burn\w*|blister\w*)|"
    r"(mamadera|leche|agua|ba[ñn]era|t[eé]|caf[eé])\b[^.!?]{0,25}\b(muy|demasiado|re) caliente\b[^.!?]{0,40}\b(grit[oó]|chill[oó]|alarid\w*|ampolla\w*)|"
    r"(grunt|moan)\w* (with|on|at) (each|every) breath|(quej\w*|hace ruido) (en|con) cada respiraci[oó]n|"
    # Signs the round 3 red teamer sent next to a cry: bluish, barely breathing, stiff, a high pitched scream, wheezing,
    # anything swallowed.
    r"bluish|azulad\w*|barely breathing|hardly breathing|apenas respira|casi no respira|stiff\b(?!( neck)? from )|rigid\b|r[ií]gid[oa]|ties[oa]\b|"
    r"high[- ]?pitched(?![^.!?]{0,25}\b(happy|excited|playing|laugh\w*|giggl\w*|squeal\w*))|shrill (cry|scream)|grito agudo|llanto (muy )?agudo|grita agudo|wheez\w*|silbido|le silba el pecho|"
    r"swallowed (something|a |an |some |one |the |his |her |my )(?!(lot of |bit of |little )?(air|milk|formula|leche|aire))"
    r"(?!(whole |entire |full |all (of )?(the |his |her )?)?(bottle|feed|meal|food|milk|formula|breast|boob|puree|banana))|"
    r"se (me )?trag[oó] (algo|un |una |unas |unos )(?!(poco de )?(aire|leche))|"
    # Pregnancy red flags for prep mode: bleeding, the baby stopped moving, a severe headache, blurred vision.
    r"(i'?m|i am|she'?s|she is|estoy|est[aá]) (bleeding|sangrando)(?! (a bit |a little |un poco )?(from (the |my |her )?nipples?|del? (los )?pez[oó]n\w*))|bleeding (a lot|heavily)|heavy bleeding|"
    r"sangr\w* (mucho|abundante)|tengo (un )?sangrado|"
    r"(baby|he|she) (has )?(stopped|isn'?t|is not) moving|(not|no longer|can'?t|cannot) feel (the baby|him|her|it) mov\w*|"
    r"no siento que se mueva|ya no (lo |la )?siento(?! (llor|re[ií]r|quej)\w*)|no (lo |la )?siento mover\w*|dej[oó] de moverse|"
    r"(severe|terrible|worst|really bad|very bad|strong) headache|dolor de cabeza (muy )?(fuerte|intenso|terrible|horrible)|"
    r"blurr\w* vision|vision (is )?blurr\w*|visi[oó]n borrosa|"
    # The nine held-out misses, closed after the one scored run (results/safety-gate-r4/README.md).
    r"(lips|face|mouth) (went|turned|turning|going|gone|are|is|look\w*|seem\w*) (dark|black|dusky)\b(?! (red|pink))(?![^.!?]{0,20}\bfrom\b)|"
    r"(got hold of|got into|grabbed|found|chew\w*|lick\w*|mouth\w*|bit|biting|suck\w*)( on| at)? (a |an |the |some |one of the )?"
    r"(lithium |button |coin |watch )(cell|battery|batteries)|"
    r"(baby|he|she|it) (hasn'?t|has not|didn'?t|did not) (kicked|moved)( much| at all| once)? (all day|today|since|in \d+|for (hours|a day))|"
    r"no (lo |la )?siento (al beb[eé] |a la beba |a mi beb[eé] )?(patear|mover\w*)|no (patea|se mueve) (desde|hace)|"
    r"(the )?(umbilical )?cord (is )?(coming out(?! of the (wall|socket|plug))|prolaps\w*|out first)|(feel|see|saw|felt|can see) the (umbilical )?cord|"
    r"cord[oó]n (umbilical )?(est[aá] )?(saliendo|afuera|colgando)|"
    r"seeing (spots|flashing lights|flashes)|veo (puntitos|manchitas|lucecitas|luces)|splitting headache|"
    r"(burn|scald|hot|boiling|caliente|hirviendo|quem)\w*.{0,40}\b(blister\w*|ampolla\w*)|"
    r"(spilled|spilt|poured|knocked over) (hot|boiling) (tea|coffee|water|soup|milk) (on|over) (him|her|his|the baby|my baby)|"
    r"face (down|first) in (the )?(bath|water|tub)|(bath|tub) water.{0,25}face down|boca abajo en (el agua|la ba[ñn]era)|"
    r"(est[aá]|se puso|lo siento|la siento) (todo |toda )(flojit|blandit)\w*|"
    r"((water|waters)\b.{0,15}\b(broke|broken|burst|went|leak\w*)|fluid|l[ií]quido|bolsa).{0,40}\b(green\w*|brown\w*|verde\w*|"
    r"marr[oó]n\w*|bloody|con sangre|meconi\w*)|(green|brown|verde|marr[oó]n|bloody) (fluid|water|l[ií]quido)|meconi\w*|"
    r"contractions?.{0,25}\b(every|each) ([1-5]|one|two|three|four|five|few|couple( of)?)( to [1-5])? ?(min|minutes|mins)?\b|"
    r"contractions?.{0,15}\b([1-5]|two|three|four|five|few)( to [1-5])? ?(min|minutes|mins) apart|"
    r"contracci\w*.{0,25}\bcada ([1-5]|uno|dos|tres|cuatro|cinco|poc[oa]s)( a [1-5])? ?(min|minutos)?\b)", re.I)
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
    r"(forma|manera|posici[oó]n) (m[aá]s )?segur\w* (de|para) (dormir|acostar\w*)|sue[ñn]o seguro|dormir segur\w*|"
    # The round 3 audit misses: a mantita, sleeping in arms, weighted sleep sacks, inclined sleepers, swaddling.
    r"mantitas?|in (my|our|your|his|her|mom'?s|dad'?s) arms|(en|a) (mis|sus|tus|los) brazos|en brazos|weighted|con peso|"
    r"pesad[oa]s? para dormir|inclin\w* sleep\w*|incline\w*|inclinad\w*|rock ?(n|and|'?n'?) ?play|reclin\w*|swaddl\w*|"
    r"envolv\w*|envuelt\w*|faj\w*|arrull\w*|saco de dormir|sleep ?(sack|bag)", re.I)
SAFE_SLEEP_ASK = re.compile(r"\?|\b(can|could|should|is it|is that|ok|okay|safe\w*|how|what|which|where|puedo|debo|"
                            r"deber[ií]a|est[aá] bien|es seguro|segur\w*|c[oó]mo|qu[eé]|cu[aá]l|d[oó]nde|conviene|hay que)\b", re.I)
SAFE_SLEEP_SOURCE = "https://www.healthychildren.org/English/ages-stages/baby/sleep/Pages/a-parents-guide-to-safe-sleep.aspx"
SAFE_SLEEP_FACT = {
    "en": ("This is the public safe sleep guidance of the American Academy of Pediatrics, for every baby, not advice about "
           "yours: on the back for every nap and at night, on a firm, flat surface, with nothing else in the crib (no pillows, "
           "blankets, bumpers or toys). Room sharing yes, bed sharing no. A baby who falls asleep in a car seat, swing or "
           "sling is moved to a firm, flat surface, on the back, and so is one who falls asleep in your arms. No inclined "
           "sleepers and no weighted sleep sacks, swaddles or blankets. A swaddled baby always sleeps on the back, and "
           f"swaddling stops when the baby starts trying to roll over. Source: {SAFE_SLEEP_SOURCE} "
           "For anything about your baby's health, ask your pediatrician."),
    "es": ("Esta es la guía pública de sueño seguro de la Academia Estadounidense de Pediatría (AAP), para todos los bebés, "
           "no un consejo sobre el tuyo: boca arriba en todas las siestas y de noche, sobre una superficie firme y plana, sin "
           "nada más en la cuna (ni almohadas, ni mantas, ni chichoneras, ni juguetes). Dormir en el mismo cuarto sí, en la "
           "misma cama no. Si se duerme en la sillita del auto, la hamaca o el fular, se pasa a una superficie firme y plana, "
           "boca arriba, y también si se duerme en tus brazos. Nada inclinado y nada con peso (ni saco de dormir, ni manta, "
           "ni envoltura con peso). Un bebé envuelto siempre duerme boca arriba, y se deja de envolver cuando empieza a "
           f"querer darse vuelta. Fuente: {SAFE_SLEEP_SOURCE} Para cualquier cosa de la salud de tu bebé, consultá a tu pediatra."),
}
# Health and feeding-safety talk. Never a log request, so the not-logged check never answers it with "send it again".
HEALTH = re.compile(r"\b(fell(?! (back )?asleep)|fall(s|en)?(?! asleep)|rol+ed off|tumbled|se (me )?cay[oó](?! (dormid|rendid|el chupete|la mamadera|el biber|el tete|el juguete))|ca[ií]da|"
                    r"can i|could i|should i|is it ok|is it safe|safe to|puedo|debo|deber[ií]a|es seguro|"
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
                  r"correct (it|that)|fix (it|that)|change (it|that)|actually|no,? esper[aá]|esper[aá],? (fue|era)|digo|"
                  r"(fue|era) a las? \d|^\W*no\W+(a las? )?\d{1,2}([:.]\d{2}| y \w+)?\W*$)\b", re.I)
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
TIME_SAID = re.compile(r"\d{1,2}[:.h]\d{2}|\d{1,2}\s*(am|pm|hs?)\b|\b(a|desde) las?\s+\d|\b(at|since) \d|\bhace\b|\bago\b|y media|y cuarto|"
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
    # The agent never calls anyone, so "I called 911 for you" is always a claim of an action that never ran.
    r"(called|phoned|dialed|dialled|contacted) (911|emergency|emergencies|an ambulance|the ambulance)|"
    r"let (him|her|them|your partner) know|(trying|going) to reach|reach(ed|ing)|"
    r"(is|are) on (his|her|their|the) way|request (was |has been )?(sent|made)|"
    r"envi[eé]|enviad[oa]s?|mand[eé]|mandad[oa]s?|avis[eé]|avisad[oa]s?|llam[eé]|le ped[ií]|les ped[ií]|le escrib[ií]|"
    r"anunci[eé]|le dije|les dije|va en camino|est[aá] en camino|pedido enviado|solicitud enviada)\b", re.I)

# A medicine the parent gave, a milestone, or an explicit ask to log: a health message with one of these is logged
# first (a medicine or a symptom goes in as a note), and only the advice part is refused.
MEDICINE = re.compile(r"\b(medicine|medication|dose|dosage|paracetamol|acetaminophen|tylenol|ibuprofen|motrin|advil|drops|"
                      r"syrup|antibiotic|vitamin|medicamento|medicina|remedio|dosis|ibuprofeno|gotas|jarabe|antibi[oó]tic\w*|"
                      r"vitamina)\b", re.I)
# "largó un poco" is the Rioplatense spit-up: round 5 found "tomo 60 y largo un poco" stored as two bottles on the demo
# because it went to the brain path. "largo" alone is "long" ("un rato largo"), so only the spit-up phrasings count.
SPIT_UP_ES = r"larg[oó] (un poc\w*|leche|algo|todo|bastante|mucho|un chorr\w*|lechita)|regurgit\w*|bocanada"
SYMPTOM = re.compile(r"\b(fever|temperature|rash|vomit\w*|sick|cough\w*|infection|diarrh\w*|fiebre|temperatura|sarpullido|"
                     r"erupci\w*|v[oó]mit\w*|enferm\w*|tos|infecci\w*|diarrea|" + SPIT_UP_ES + r")\b", re.I)
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

# Newborn red flags from the healthychildren.org "when to call" lists: a fever under 3 months, and the signs that mean
# call the pediatrician now or go to the emergency room. The answer is a fixed line with its public source, never a
# dose, a home remedy or a guess, and what the parent said is kept as a note for the call.
FEVER_SOURCE = "https://www.healthychildren.org/English/health-issues/conditions/fever/Pages/When-to-Call-the-Pediatrician.aspx"
NEWBORN_SOURCE = ("https://www.healthychildren.org/English/tips-tools/symptom-checker/Pages/symptomviewer.aspx"
                  "?symptom=Newborn+Illness+-+How+to+Recognize")
FEVER_WORD = re.compile(r"\b(fever\w*|febrile|high temp\w*|fiebre|febril|calentura|afiebrad\w*|(temperatura|temp) (alta|elevada))\b",
                        re.I)
# Hot to the touch, with no number: a fever word for a newborn, unless the message is about the water or the room.
HOT_WORD = re.compile(r"\b(burning up|feels? (so |very |really |too )?hot|is (so |very |really )?hot|(he|she)'?s (so |very |really )?hot|"
                      r"hirviendo|ardiendo|est[aá] (muy |re |bien )?caliente|lo siento caliente|la siento caliente|"
                      r"volando)\b", re.I)
NO_FEVER = re.compile(r"\b(no|not|without|sin|ni|never|nunca|doesn'?t have( a)?|does not have( a)?)\s+(\w+\s+){0,2}"
                      r"(fever\w*|fiebre|febril|calentura|high temp\w*)", re.I)
# A body temperature: 38 to 42 °C, or 100.4 to 107 °F, and never a millilitre, an ounce, a minute or a weight.
TEMP_NUMBER = re.compile(r"(?<![\d.,])(3[89]|4[0-2]|100[.,][4-9]|10[1-7])([.,]\d)?(?![\d.,]*\d)"
                         r"(?!\s*(ml|cc|oz|onzas?|min\w*|h\b|hs|horas?|hours?|g\b|gr\b|gramos|kg|kilos?|cm|semanas|weeks|"
                         r"d[ií]as|days|%|mamaderas?|bottles?|pa[ñn]ales|diapers))", re.I)
LOW_TEMP_NUMBER = re.compile(r"(?<![\d.,])3[45]([.,]\d)?(?![\d.,]*\d)(?!\s*(ml|cc|oz|min\w*|g\b|gr\b|gramos|kg|cm|semanas|weeks))",
                             re.I)
BODY_HEAT = re.compile(r"\b(hot|warm|burning( up)?|temp\w*|thermometer|degrees|caliente|calient\w*|calor|ardiendo|hirviendo|"
                       r"term[oó]metro|grados)\b|°|º", re.I)
BODY_TEMP = re.compile(r"\b(temp\w*|thermometer|term[oó]metro)\b", re.I)
# What a 38 in a message is about when it is not the baby: the bath water, the room, the bottle, the weather.
NOT_BODY = re.compile(r"\b(water|bath\w*|tub|room|nursery|bottle|milk|formula|outside|weather|heater|oven|agua|ba[ñn]o|"
                      r"ba[ñn]era|tina|cuarto|habitaci[oó]n|ambiente|mamadera|biber[oó]n|leche|f[oó]rmula|afuera|calefa\w*|"
                      r"estufa|horno|d[ií]a|clima)\b", re.I)
RED_FLAG = re.compile(
    r"\b((vomit\w*|throw\w* up|threw up|spit\w* up)( is| was| looks?)? (dark |bright )?green|green (vomit|throw[- ]?up|spit[- ]?up)|"
    r"vomit\w* bile|\bbile\b|"
    # Vomiting that goes on: on the healthychildren.org newborn list as repeated vomiting.
    r"(vomit|throw)\w* (up )?(for|all) (hours|day|night|the whole \w+)|(won'?t|can'?t|cannot|isn'?t|is not|not) (keep|keeping) anything down|"
    r"(vomit\w*|throw\w* up|threw up) everything|vomit\w* todo|no retiene nada|vomit\w* (hace|desde hace) horas|"
    r"weak suck\w*|(can'?t|cannot|won'?t|isn'?t able to) suck|weak cry\w*|"
    r"(won'?t|will not|isn'?t|is not|not|refus\w*( to)?) (feed|feeding|eat|eating)\b|refus\w* (every|all|each|the) (feeds?|bottles?|breast)|"
    r"can'?t finish (a |his |her |any |the )?feeds?|(won'?t|doesn'?t) wake (up )?(for|to) (feeds?|eat)|"
    r"blood (in|on) (his |her |the )?(stool|poop|poo|diaper|nappy|vomit|spit[- ]?up)|bloody (stool|poop|diaper|nappy|vomit)|"
    r"sangre en (la |el |las )?(caca|pa[ñn]al|heces|v[oó]mito|deposici\w*)|caca con sangre|v[oó]mito con sangre|deca[ií]d[oa]|"
    r"hard to wake|difficult to wake|(very|really|so|unusually|too|extremely) (sleepy|drowsy|lethargic)|letharg\w*|"
    r"sleep\w* (much |way |a lot )?more than (normal|usual)|barely moving|moving (much )?less|very weak|"
    r"no wet (diapers|nappies)|no wet (diaper|nappy) (in|since|all|today|for)|fewer wet (diapers|nappies)|dry (diapers|nappies)|"
    r"(hasn'?t|has not) (peed|had a wet (diaper|nappy))|(not|no) (peed|pee) (in|since|all|today|for)|"
    r"jaundic\w*|(skin|eyes?|face|body|chest|whites of (his|her|the) eyes)( is| are| looks?| turned| turning| seems?| got)?"
    r"( a bit| very| really| so| kind of| a little)? yellow\w*|yellow\w* (skin|eyes?|face|tint)|"
    r"v[oó]mit\w* verde|vomit[oó] verde|devolvi[oó] (algo )?verde|vomita (algo )?verde|bilis|"
    r"succi[oó]n d[eé]bil|succiona (muy )?d[eé]bil|no (puede )?(succiona|succionar)\b|llanto d[eé]bil|llora (muy )?d[eé]bil\w*|"
    r"no quiere (comer|tomar|mamar)|no (come|toma|mama) nada|rechaza (todas las tomas|todas las mamaderas|el pecho|la teta|"
    r"la mamadera)|no termina (ninguna|las) tomas?|no se despierta para (comer|tomar|mamar)|"
    r"(es |est[aá] )?(dif[ií]cil|cuesta( mucho)?) (de )?despertarl[oa]|le cuesta despertar\w*|"
    r"muy (dormid[oa]|somnolient[oa]|dormil[oó]n[a]?|d[eé]bil)|let[aá]rgic[oa]|duerme (mucho )?m[aá]s de lo (normal|habitual)|"
    r"no hay (forma|manera) de despertarl[oa]|casi no se mueve|se mueve (mucho )?menos|"
    r"no (hizo|ha hecho|hace) pis (en|hace|desde|todo|en todo)|no moj[oó] (ning[uú]n|ningun) pa[ñn]al|"
    r"pa[ñn]ales secos|menos pa[ñn]ales mojados|ning[uú]n pa[ñn]al mojado|no moja (los )?pa[ñn]ales|"
    r"ictericia|(piel|ojos|cara|cuerpo|pecho|blanco de los ojos)( est[aá]n?| se ve\w*| se puso| se pusieron)?"
    r"( medio| muy| re| un poco| algo)? amarill\w*|amarill\w* (la piel|los ojos|la cara))", re.I)
URGENT_REPLY = {
    "fever": {
        "en": ("A baby under 3 months with a temperature of 38 °C (100.4 °F) or more needs a doctor right away. Call your "
               "pediatrician now, or go to the emergency room. If you cannot reach them, call 911 (Uruguay) or your local "
               "emergency number. This is the public guidance of the American Academy of Pediatrics, not advice about your "
               f"baby: {FEVER_SOURCE}"),
        "es": ("Un bebé de menos de 3 meses con 38 °C (100,4 °F) o más de temperatura tiene que verlo un médico ya. Llamá "
               "ahora a tu pediatra o andá a emergencia. Si no los ubicás, llamá al 911. Es la guía pública de la Academia "
               f"Estadounidense de Pediatría (AAP), no un consejo sobre tu bebé: {FEVER_SOURCE}"),
    },
    "red_flag": {
        "en": ("That is on the list of newborn signs to act on right away. Call your pediatrician now, or go to the emergency "
               "room. If you cannot reach them, call 911 (Uruguay) or your local emergency number. This is the public "
               f"guidance of the American Academy of Pediatrics, not advice about your baby: {NEWBORN_SOURCE}"),
        "es": ("Eso está en la lista de señales en un recién nacido para actuar ya. Llamá ahora a tu pediatra o andá a "
               "emergencia. Si no los ubicás, llamá al 911. Es la guía pública de la Academia Estadounidense de Pediatría "
               f"(AAP), no un consejo sobre tu bebé: {NEWBORN_SOURCE}"),
    },
}


def names_fever(text):
    """True when a message says the baby has a fever: a fever word, or a body temperature of 38 °C (100.4 °F) or more
    with a word for heat. "His bath water was 38 degrees", "le di 38 ml" and "no fever" are not one."""
    text = text or ""
    if FEVER_WORD.search(text) and not NO_FEVER.search(text):
        return True
    if HOT_WORD.search(text) and not NOT_BODY.search(text):
        return True
    return bool(TEMP_NUMBER.search(text) and BODY_HEAT.search(text) and not NOT_BODY.search(text))


def names_low_temperature(text):
    """A thermometer reading of 34 to 35.9 °C, on the newborn list next to fever."""
    text = text or ""
    return bool(LOW_TEMP_NUMBER.search(text) and BODY_TEMP.search(text) and not NOT_BODY.search(text))


def newborn_red_flag(text, under_3_months=True):
    """"fever" for a fever in a baby under 3 months (or of unknown age), "red_flag" for another call-now sign, else None.
    Emergencies come first and keep the 911 line."""
    text = text or ""
    if not text or is_emergency(text):
        return None
    if under_3_months and names_fever(text):
        return "fever"
    if RED_FLAG.search(text) or (under_3_months and names_low_temperature(text)):
        return "red_flag"
    return None


def under_3_months(born, today):
    """True when the baby is under 3 months, or the birth date is unknown (before birth, the demo baby)."""
    return born is None or (today - born).days < 91


def is_medical(text):
    return bool(MEDICAL.search(text))


# Everyday lines the gate read as red flags in round 5 ("he chokes on laughter", "the dog bit his toy"). These words are
# taken out before the gate reads the message, so anything else in it is still read.
EVERYDAY = re.compile(r"\bchok\w* (on|with|from) (laughter|laughing|giggl\w*)|\bse (me |le )?ahog\w* de (la )?risa|"
                      r"\blimp with (sleep|tiredness)|\bseizures? of (giggl\w*|laughter)|"
                      r"\b(dog|puppy|cat|perr[oa]|gat[oa])\b[^.!?]{0,15}\b(bit|bites|chewed|mordi[oó]|muerde)\s+"
                      r"(his|her|the|a|el|la|su|sus|un|una)\s+(\w+\s+)?(toys?|juguete\w*|chupete|blanket|manta|mantita|sock|media)\b"
                      r"(\s+del? (beb[eé]|nene|nena))?", re.I)


def is_emergency(text):
    return bool(EMERGENCY.search(EVERYDAY.sub(" ", text or "")))



# Red flags said out loud. The ear (Muse Spark Open) sometimes mishears one word of an emergency: on Oct 30 it heard
# "está azul y no respira bien" as "está azulino respira bien", and the 911 line did not fire (results/glasses-speech).
# So a transcript is read a second time: no accents, the "y no" the ear glued onto a colour split off again, and a key
# word one letter away (two in a long word) read as that word. The words it fixes are the gate's own, so whatever fires
# is still a sign on the gate's list.
SPOKEN_KEYS = ("respira", "respirar", "respirando", "morado", "morada", "morados", "moradas", "convulsion", "convulsiones",
               "convulsiona", "convulsionando", "despierta", "despertar", "reacciona", "responde", "sangrando", "ahogando",
               "atraganto", "atragantando", "flojito", "flojita", "inconsciente", "desmayado", "desmayada",
               "breathing", "breathe", "purple", "seizure", "convulsing", "unresponsive", "choking", "bleeding", "gasping",
               "floppy")
# Real words one letter from a key word, never read as it: "no lo despiertes", "respiro hondo", "le respondo".
SPOKEN_NEAR = frozenset(("respiro", "respire", "respiras", "respiran", "respiren", "respirado", "despierto", "despierte",
                         "despiertes", "despiertas", "despiertan", "respondo", "responda", "respondi",
                         "responder", "reaccion", "breathes", "breathed", "bleeds", "choked", "chokes"))
SPOKEN_COLOURS = ("azul", "morado", "morada", "gris", "palido", "palida", "blue", "purple", "grey", "gray")
GLUED_NO = re.compile(r"^(\w{3,}?)(?:i|y|e)no$")


def _distance(a, b, most):
    """Edit distance between two words, or most + 1 once it is sure to be more."""
    if abs(len(a) - len(b)) > most:
        return most + 1
    row = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        prev, row[0] = row[0], i
        for j, y in enumerate(b, 1):
            prev, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, prev + (x != y))
        if min(row) > most:
            return most + 1
    return row[-1]


def _key_word(word):
    """The key word a heard word stands for, or the word itself."""
    if len(word) < 6 or word in SPOKEN_KEYS or word in SPOKEN_NEAR:
        return word
    most = 2 if len(word) >= 9 else 1
    best = min(SPOKEN_KEYS, key=lambda key: _distance(word, key, most) if key[0] == word[0] else most + 1)
    return best if best[0] == word[0] and _distance(word, best, most) <= most else word


def spoken_forms(text):
    """What a heard transcript may have been: as heard, then without accents, then with the glued "y no" split and the
    key words fixed."""
    text = text or ""
    yield text
    bare = unicodedata.normalize("NFD", text.lower().replace("\u2019", "'"))
    bare = "".join(c for c in bare if unicodedata.category(c) != "Mn")
    bare = " ".join(re.sub(r"[^a-z0-9' ]+", " ", bare).split())
    yield bare
    words = []
    for word in bare.split():
        glued = GLUED_NO.match(word)
        if glued and any(_distance(glued.group(1), colour, 1) <= (1 if len(colour) > 4 else 0) for colour in SPOKEN_COLOURS):
            words += [glued.group(1), "y", "no"]
        else:
            words.append(_key_word(word))
    yield " ".join(words)


def spoken_emergency(text):
    """The form of a heard transcript that the gate reads as a red flag (is_emergency), or None. The form is what the
    agent is told, so the 911 line fires on it the same way it fires on typed words."""
    for form in spoken_forms(text):
        if form and is_emergency(form):
            return form
    return None

# Words of a sign a log guard must never talk over, wider than the gate: labor, bleeding, shaking, a bite. A message
# with one of these still goes to the brain when the gate does not answer it, but no log honesty guard replaces the reply.
WATCH = re.compile(r"\b(water(s)? (has |have |just )?(broke|broken|burst)|(se )?(me )?rompi\w* (la )?bolsa|romp\w* (la )?bolsa|"
                   r"contractions?|contracci\w*|labou?r pains?|trabajo de parto|shak(e|es|ing)|trembl\w*|tembl\w*|jerk(s|ed|ing)|"
                   r"twitch\w*|bleed\w*|sangr\w*|seizure|convuls\w*|unresponsive|no responde|no reacciona|"
                   r"(bit|bitten|mordi[oó]|mordid[oa]))\b", re.I)
# A reply that tells the parent to get help: an emergency number, the pediatrician, a doctor, the maternity or the
# hospital. "Hospital bag" is a prep list, not one.
SAFETY_LINE = re.compile(r"911|pediatr|emergenc|m[eé]dic(o|a|os|as|al)\b|doctor|urgent|matern\w*|midwife|partera|obstetr\w*|ambulanc\w*|"
                         r"guardia|hospital(?! bag)", re.I)


def names_red_flag(text):
    """True when a message names a red flag the gate answers, or a sign on the wider watch list."""
    text = text or ""
    return bool(is_emergency(text) or newborn_red_flag(text) or WATCH.search(text))


def fixed_safety_line(text, lang="en"):
    """The gate's fixed line for a message, or None: the 911 line for a red flag, the newborn call-now line for a newborn
    sign. Used where a message would otherwise get a limit, a sign-up step or an error and never reach the agent."""
    lang = message_lang(text or "") or lang
    lang = lang if lang in ("en", "es") else "en"
    if is_emergency(text):
        return EMERGENCY_REPLY[lang]
    kind = newborn_red_flag(text)
    return URGENT_REPLY[kind][lang] if kind else None


def carries_safety_line(text):
    return bool(SAFETY_LINE.search(text or ""))


def is_safe_sleep_question(text):
    """A question on how a baby sleeps safely, with no symptom, medicine or red flag in it."""
    text = text or ""
    return (bool(SAFE_SLEEP.search(text)) and bool(SAFE_SLEEP_ASK.search(text)) and not is_emergency(text)
            and not is_medical(text) and not is_medical_es(text) and not SYMPTOM.search(text))


def is_medical_es(text):
    return bool(MEDICAL_ES.search(text or ""))


def is_health(text):
    """Any health, safety or emergency talk, in English or Spanish. Never treated as a note to log."""
    return (is_medical(text) or is_medical_es(text) or is_emergency(text) or bool(HEALTH.search(text or ""))
            or newborn_red_flag(text) is not None)


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


WOKE_SAID = re.compile(r"despert|despiert|levant|\bwoke\b|\bwakes?\b|\bawake\b|\bgot up\b", re.I)
# How long a sleep lasted, said in the message: "durmio 2 horas", "hizo una siestita de 40 min", "napped for an hour".
SLEPT_FOR = re.compile(r"(\d+(?:[.,]\d+)?|una|un|one|an?|media|half an?)\s*(horas?|hs?\b|hours?|hrs?\b|min\w*|m\b)", re.I)
SLEPT_WORDS = re.compile(r"durm|dorm|siest|slept|\bnap", re.I)


def slept_minutes(text):
    """The minutes of a finished sleep the message names ("durmio 2 horas", "siestita de 40 min"), or None."""
    text = text or ""
    if not SLEPT_WORDS.search(text):
        return None
    total = 0.0
    for amount, unit in SLEPT_FOR.findall(text):
        low = amount.lower()
        value = {"una": 1, "un": 1, "one": 1, "a": 1, "an": 1, "media": 0.5}.get(low)
        if value is None:
            value = 0.5 if low.startswith("half") else float(low.replace(",", "."))
        total += value * (60 if unit.lower().startswith("h") else 1)
    return total if 0 < total <= BOUNDS["sleep_hours"] * 60 else None


def says_woke(text):
    return bool(WOKE_SAID.search(text or ""))
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


# The only words a bare "why is he crying?" holds. Anything else in a cry message (a symptom, a colour, something
# swallowed) means it is not bare, and the agent's gates answer it instead of the cry shortcut.
CRY_BARE_WORDS = set("""why is he she it the baby my so much a lot keep keeps keeps still won wont t stop stopping been has
has for an hour hours again now all night tonight today what wrong with him her how come does do did s and just right
minutes mins min this that crying cry cries cried fussy fussing fuss screaming por porque qu que q xq le pasa tiene llora
llorando lloró llore llorar qué por no para de tanto mucho mi el la beba bebe nene nena sigue otra vez ahora toda noche hoy y
hace minutos horas hora molesto molesta está esta es""".split())


def is_bare_cry_question(text):
    """True only for a cry question with nothing else in it: "why is he crying?", "no para de llorar, ¿por qué?". A
    baby's name is allowed. Anything else, a symptom or a sign, goes to the gates."""
    text = text or ""
    if not CRY.search(text) or is_health(text) or newborn_red_flag(text) is not None:
        return False
    rest = [w for w in re.findall(r"[^\W\d_]+", text) if w.lower() not in CRY_BARE_WORDS]
    return not rest or (len(rest) == 1 and rest[0][:1].isupper() and rest[0].lower() not in ("i", "y"))


def is_cry_question(text):
    return is_bare_cry_question(text)


WET_SAID = re.compile(r"wet|pee|wee|pis|pich|mojad|orin|me[oó]\b|meado|both|ambos|los dos|y (con )?ca(c|qu)|and dirty|and poo", re.I)
# Stems, not whole words: "caquita", "cacona", "popó" and "sucito" are all a dirty diaper (round 4 blind, step 13).
SOLID_SAID = re.compile(r"dirty|poo|solid|caca|caqu|cacon|suci|pop[oó]|deposici|both|ambos|los dos", re.I)


def said_only(request, kind, details, ts=None):
    """The log call's details and time, without anything the parent did not say: no breast side, milk type, duration,
    amount, diaper color or time the brain made up. Returns (details, ts)."""
    details = dict(details or {}) if isinstance(details, dict) else {}
    request = request or ""
    timed = bool(TIME_SAID.search(request) or clock_times(request))
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
    if kind == "feeding" and "breast" in str(details.get("method") or "") and details.get("duration_min") is None \
            and not BOTTLE_WORDS.search(request) and not TIME_SAID.search(request):
        # "pecho izquierdo 15": a bare number after a breast side is minutes. Run 1 of round 3 lost the 15.
        bare = re.findall(r"(?<![\d:.])(\d{1,3})(?![\d:.])", request)
        if len(bare) == 1 and 1 <= int(bare[0]) <= 60:
            details["duration_min"] = int(bare[0])
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


# "onza", "onzas", "onzitas", "oz": any form of the word, never a fixed list (round 4 blind, step 10).
OUNCE_WORD = r"(?:onz\w*|oz|ounces?)"
OUNCES = re.compile(r"(\d+(?:[.,]\d+)?)\s*" + OUNCE_WORD + r"\b", re.I)
HALF_OUNCE = re.compile(r"\d\s*(?:y media|and a half)\s*" + OUNCE_WORD + r"\b|" + OUNCE_WORD + r"\s*(?:y media|and a half)\b", re.I)
ML_PER_OUNCE = 30


BREAST_WORDS = re.compile(r"\b(teta|tetas|pecho|pechos|breast\w*|nurs\w*|amamant\w*)\b", re.I)
BOTTLE_WORDS = re.compile(r"\b(mamadera\w*|biber[oó]n|bottle|f[oó]rmula|formula)\b|\d\s*ml\b|\bonz\w*", re.I)


def amount_said(amount, text):
    """True when the amount follows from the message's own numbers: "le di 90" is 90, "prepare 110 y sobraron 20" is
    110 minus 20, "3 onzitas" is 3 times 30. The guard used to ask for the literal number, so in the second blind set it
    threw away Muse's right 90 ml twice. An amount from no number in the message (an earlier bottle) is still not said."""
    try:
        wanted = float(amount)
    except (TypeError, ValueError):
        return False
    numbers = [float(n.replace(",", ".")) for n in re.findall(r"-?\d+(?:[.,]\d+)?", text or "")][:4]
    if re.search(OUNCE_WORD, text or "", re.I):
        numbers += [n * ML_PER_OUNCE for n in numbers]
    candidates = set(numbers) | {a - b for a in numbers for b in numbers if a > b}
    return any(abs(c - wanted) < 0.5 for c in candidates)


HALF_OF = re.compile(r"\b(la )?mitad de (la |una )?(mamadera|biber[oó]n|bottle)?\s*(de )?(\d+)|\bhalf (of )?(a |the )?(\d+)", re.I)


HALF_TAKEN = re.compile(r"(?<![\d:.])(\d{2,3})(?![\d:.])(?!\s*(?:min|hs?\b|horas?))[^\d]{0,40}?\b(?:se )?(?:tom[oó]|drank|took|had)\s+"
                        r"(?:la |the |solo la |s[oó]lo la )?(?:mitad|half)\b", re.I)


def half_ml(text):
    """"tomo la mitad de la mamadera de 120" and "le prepare 120 y tomo la mitad" are 60 ml, or None."""
    m = HALF_OF.search(text or "")
    if m:
        return float(m.group(5) or m.group(8)) / 2
    m = HALF_TAKEN.search(text or "")
    return float(m.group(1)) / 2 if m else None


def ounce_followup_ml(request, previous):
    """"en realidad tomo 3, dejo una" right after "mamadera 4 onzas": the first number in ounces, at 30 ml each."""
    if not previous or not OUNCES.search(previous) or re.search(r"\d\s*ml\b", request or "", re.I):
        return None
    numbers = re.findall(r"\d+(?:[.,]\d+)?", request or "")
    if not numbers or float(numbers[0].replace(",", ".")) > 12:
        return None
    return round(float(numbers[0].replace(",", ".")) * ML_PER_OUNCE)


NAMES_WHEN = re.compile(r"\b(de|a) las? \d{1,2}\b|\d{1,2}[:.]\d{2}|\b(at|from) \d{1,2}\b", re.I)


def names_when(text):
    """True when a message names a day or a clock time: "la de la 1 y 20 fue 80", "la de ayer"."""
    return bool(DAY_SAID.search(text or "") or NAMES_WHEN.search(text or ""))


def ounces_ml(text):
    """The ml of "tomo 3 onzas", at 30 ml an ounce as the bottle marks read, or None. One amount only."""
    text = re.sub(r"(\d)\s*(y media|and a half)\s*(" + OUNCE_WORD + r")\b", r"\1 \3 \2", text or "", flags=re.I)
    found = OUNCES.findall(text)
    if len(found) != 1:
        return None
    # "3 onzas y media" is 105 ml: run 1 of the held-out set logged 90.
    half = 0.5 if HALF_OUNCE.search(text) else 0
    return round((float(found[0].replace(",", ".")) + half) * ML_PER_OUNCE)


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


def latest_start_end(details, now, request=""):
    """A start and an end the parent named as clock times: the end is the latest such time not after now and the start
    the latest such time not after the end, so the pair keeps its order whatever the hour the message came."""
    details = dict(details)
    anchor = now
    if details.get("end"):
        details["end"] = latest_time(details["end"], now, request)
        try:
            anchor = datetime.datetime.fromisoformat(str(details["end"]))
        except ValueError:
            anchor = now
        if anchor.tzinfo is None:
            anchor = anchor.replace(tzinfo=now.tzinfo)
    if details.get("start"):
        details["start"] = latest_time(details["start"], anchor, request)
    return details


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


MINUTE_WORDS = {"media": 30, "cuarto": 15, "diez": 10, "veinte": 20, "cinco": 5, "veinticinco": 25}
RANGE_SAID = re.compile(r"\bde (las? )?\d{1,2}.{0,12}\ba (las? )?\d|\bfrom \d{1,2}.{0,12}\b(to|until|till) \d|\bdesde\b.{0,30}\bhasta\b|\bhasta\b", re.I)
# A number that is an amount or a length, never a clock time: "4 onzas", "10 min", "2 horas".
NOT_A_CLOCK = r"(?!\s*(?:min\w*|m\b|ml|cc|oz|onz\w*|hs?\b|horas?|hours?|hrs?\b|g\b|gr\b|kg|%))"
MINUTE_WORD = r"(media|cuarto|diez|veinticinco|veinte|cinco|\d{2})"
# Every form a tired parent types a clock time in, in the order they are tried. A later form never reads a part of the
# message an earlier one already read, so "a las 3:15" is 03:15 and never also 03:00. The third blind set lost
# "se desperto 4 y 55" and "wet diaper at noon": the old parser only knew "a las 3" and "at 3".
CLOCK_FORMS = [
    ("menos", re.compile(r"(?<![\d.,:])(\d{1,2}) menos (cuarto|diez|veinte|cinco|\d{1,2})\b", re.I)),
    ("las", re.compile(r"\b(?:a|desde|hasta|de) las? (\d{1,2})(?:[:.](\d{2})| y " + MINUTE_WORD + r"\b)?" + NOT_A_CLOCK, re.I)),
    ("hm", re.compile(r"(?<![\d.,:])(\d{1,2})[:.h](\d{2})(?![\d.,])" + NOT_A_CLOCK + r"(?:\s*(am|pm)\b)?", re.I)),
    ("y", re.compile(r"(?<![\d.,:])(\d{1,2}) y " + MINUTE_WORD + r"\b" + NOT_A_CLOCK, re.I)),
    ("ampm", re.compile(r"(?<![\d.,:])(\d{1,2})\s*(am|pm)\b", re.I)),
    ("at", re.compile(r"\b(?:at|since) (\d{1,2})(?![\d:.])\b" + NOT_A_CLOCK, re.I)),
    ("noon", re.compile(r"\b(noon|midday|mediod[ií]a)\b", re.I)),
    ("midnight", re.compile(r"\b(midnight|medianoche)\b", re.I)),
]


def clock_times(text):
    """The clock times a message names, as (hour, minute, fixed) in the order said, each once. fixed is True when the
    hour is not 12-hour ambiguous ("3pm", "noon", "15:20"). A bare "10 y 10" in a breast feed is minutes per side, never
    10:10, so the bare "H y MM" form needs a message with no breast side and no minutes."""
    text = text or ""
    taken, found = [], []
    bare_ok = not (BREAST_WORDS.search(text) or SIDE_SAID.search(text) or MINUTES_SAID.search(text))
    for form, pattern in CLOCK_FORMS:
        if form == "y" and not bare_ok:
            continue
        for m in pattern.finditer(text):
            if any(m.start() < end and start < m.end() for start, end in taken):
                continue
            taken.append(m.span())
            if form == "noon":
                value = (12, 0, True)
            elif form == "midnight":
                value = (0, 0, True)
            elif form == "menos":
                word = m.group(2).lower()
                minus = int(word) if word.isdigit() else MINUTE_WORDS[word]
                hour = (int(m.group(1)) - 1) % 24
                value = (hour, 60 - minus, False) if 0 < minus < 60 else None
            else:
                hour, ampm = int(m.group(1)), ""
                if form == "las":
                    word = m.group(2) or m.group(3) or ""
                elif form == "hm":
                    word, ampm = m.group(2), m.group(3) or ""
                elif form == "y":
                    word = m.group(2)
                elif form == "ampm":
                    word, ampm = "", m.group(2)
                else:
                    word = ""
                word = word.lower()
                minute = int(word) if word.isdigit() else MINUTE_WORDS.get(word, 0)
                if ampm:
                    hour = hour % 12 + (12 if ampm.lower() == "pm" else 0)
                value = (hour, minute, bool(ampm) or hour >= 13 or hour == 0) if hour <= 23 and minute <= 59 else None
            if value is not None and value not in found:
                found.append(value)
    return found


def latest_clock(hour, minute, fixed, now):
    """The latest moment not after now with that clock time: "a las 3" at 15:20 is 15:00, at 03:20 it is 03:00."""
    hours = [hour] if fixed or hour >= 12 else [hour, hour + 12]
    moments = []
    for h in hours:
        moment = now.replace(hour=h, minute=minute, second=0, microsecond=0)
        moments.append(moment if moment <= now else moment - datetime.timedelta(days=1))
    return max(moments)


def named_time(request, now):
    """The clock time a note names, "a las 3", "4 y 55", "at 3:15", "at noon", as the latest such moment not after now,
    or None when it names none or more than one, names a day, or gives a range."""
    found = clock_times(request)
    if len(found) != 1 or DAY_SAID.search(request or "") or RANGE_SAID.search(request or ""):
        return None
    return latest_clock(*found[0], now).isoformat(timespec="seconds")


# A breast feed that ended as the message was sent: "arranque 2:15 y largo recien", "from 2:15 until now".
FEED_ENDED = re.compile(r"\b(larg[oó]|solt[oó]|termin[oó]|acab[oó]|se desprendi[oó]|hasta (ahora|reci[eé]n)|finished|"
                        r"stopped|let go|unlatched|until now|just (now|finished|stopped))\b", re.I)


def feed_minutes(text, now):
    """How long a breast feed lasted when the parent gave it as times, not minutes: "de 2:15 a 2:35" is 20, and
    "arranque 2:15 y largo recien" sent at 02:35 is 20. None when the message gives no such span. The said-only guard
    dropped every length that was not "N min", so the third blind set lost this 20."""
    found = clock_times(text)
    if len(found) == 2 and RANGE_SAID.search(text or ""):
        end = latest_clock(*found[1], now)
        start = latest_clock(*found[0], end)
    elif len(found) == 1 and FEED_ENDED.search(text or ""):
        start, end = latest_clock(*found[0], now), now
    else:
        return None
    minutes = round((end - start).total_seconds() / 60)
    return minutes if 1 <= minutes <= 90 else None


def plain_numbers(text):
    """The numbers of a text that are not part of a clock time: "lo dejamos en 100 ml a las 05:50" holds 100."""
    return [float(n.replace(",", ".")) for n in re.findall(r"(?<![\d:.,])\d+(?:[.,]\d+)?(?![\d:])", re.sub(r"\d{1,2}:\d{2}", " ", text or ""))]


# A question passed on for someone else: "Mi mamá pregunta cuándo comió por última vez" (the end-to-end day, Oct 30,
# got "No pude anotarlo" because it has no question mark and names a feed).
RELAYED_QUESTION = re.compile(r"\b(?:pregunta|preguntan|quiere saber|quieren saber|asks|is asking|wants to know|"
                              r"wonders)\s+(?:si\b|if\b|whether\b|cu[aá]nd[oa]|cu[aá]nt[oa]s?|qu[eé]|c[oó]mo|"
                              r"d[oó]nde|when|how|what|where)", re.I)


# "¿Cuándo comió por última vez?", "when did he last eat?", "¿a qué hora fue la última toma?": answered from the log in one
# line by plain code. Blind round 1 (Oct 31): on the demo Muse said "Voy a revisar el registro de Theo para vos." and asked
# something else, and only a third try gave the time.
LAST_FEED = re.compile(
    r"\b(?:cu[aá]ndo|a qu[eé] hora|hace cu[aá]nto)\b[^?.!]{0,40}\b(?:comi[oó]|tom[oó]|mam[oó]|le di(?:mos)?|"
    r"(?:la )?[uú]ltima (?:toma|mamadera|teta))\b|"
    r"\b(?:cu[aá]l|cu[aá]ndo) (?:fue|es) la [uú]ltima (?:toma|mamadera)\b|"
    r"\bwhen (?:did|was|has) (?:he|she|the baby|theo|it|they)?\s*(?:last )?(?:eat|ate|feed|fed|eaten|had a bottle)\b|"
    r"\bwhen was (?:the |his |her )?last (?:feed|feeding|bottle|meal)\b|"
    r"\b(?:time of |what time was )(?:the |his |her )?last (?:feed|feeding|bottle)\b", re.I)


def asks_last_feed(text):
    """True for a question about when the baby last ate, never for a message that logs a feed."""
    text = text or ""
    return bool(LAST_FEED.search(text)) and is_question(text) and not re.search(r"\b\d+\s*(?:ml|cc|oz)\b", text, re.I)


def is_question(text):
    return "?" in text or bool(QUESTION_START.search(text.strip())) or bool(RELAYED_QUESTION.search(text))


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


# How many are left at home is stock, not a diaper change: "Tenemos 26 pañales en casa" also logged a wet diaper in
# the end-to-end day on Oct 30.
STOCK_TALK = re.compile(r"\b(?:tenemos|quedan|nos quedan|hay|compramos|compré|compre|we have|there are|we bought|"
                        r"bought|left)\b[^.?!]{0,20}\b\d+\s+(?:pa[ñn]ales|toallitas|diapers|nappies|wipes)\b|"
                        r"\b\d+\s+(?:pa[ñn]ales|diapers|wipes|toallitas)\s+(?:left|en casa|at home)\b|"
                        r"\b(?:quedan pocos|quedan pocas|se (?:est[áa]n )?(?:acaban|terminan)|running low|low on|out of)\b"
                        r"[^.?!]{0,20}\b(?:pa[ñn]ales|toallitas|diapers|nappies|wipes)\b|"
                        r"lista de (?:las )?compras|shopping list", re.I)


def is_stock_talk(text):
    return bool(STOCK_TALK.search(text or ""))


def log_kind(text):
    """The kind of log entry a parent's message reports (feeding, diaper, sleep, bath, note), in English or Spanish.
    None for questions, health questions, stock counts and anything that is not a note about the baby."""
    if is_stock_talk(text):  # what is left at home is no log, the rest of the message may still be one
        text = STOCK_TALK.sub(" ", text)
    english = note_to_english(text)
    if is_question(text) or is_question(english) or is_health(text):
        return None
    parsed = parse_note(text) or parse_note(english)
    denied = denied_kinds(text)
    if parsed and denied and (kinds_said(text) or {parsed[0]}) <= denied:
        return None
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


# A reply that says this turn wrote to the log: "Anoté", "Corregí", "ya anoté el sueño", "moví esa mamadera", "Logged".
CLAIMS_DONE = re.compile(r"\b(anot[eé]|registr[eé]|correg[ií]|borr[eé]|mov[ií]|cambi[eé]|saqu[eé]|elimin[eé]|actualic[eé])\b|"
                         r"\b(I|I've|I have)\s+(just\s+)?(logged|recorded|fixed|moved|deleted|removed|changed|updated|corrected)\b|"
                         r"(^|[.!:]\s+)(Logged|Recorded|Fixed|Moved|Deleted|Removed|Changed|Updated|Corrected)\b")


YESTERDAY = re.compile(r"\bayer\b|\byesterday\b", re.I)
SO_FAR = re.compile(r"hasta ahora|hasta hoy|y hoy|\bhoy\b|so far|until now|and today|\btoday\b", re.I)
# A reply that says the agent did something only one tool does. It goes out only when that tool ran in the turn.
CLAIM_TOOLS = [
    (re.compile(r"\b(told|messaged|texted|notified|pinged|let (?!me\b|us\b)(him|her|them|your partner|\w+) know|asked (him|her|them|your|ceci|"
                r"gonza|parent)|sent (him|her|them|ceci|gonza|your|a message|parent)|(is|are) on (his|her|their|the) way|"
                r"le avis[eé]|les avis[eé]|le dije|les dije|le escrib[ií]|le mand[eé]|le ped[ií]|va en camino|est[aá] en camino)\b", re.I),
     {"call_partner", "notify", "send_handover_to_sitter", "reply_to_visitor"}),
    (re.compile(r"\b(announced|anunci[eé])\b", re.I), {"announce", "announce_kitchen", "reply_to_visitor"}),
    (re.compile(r"\b(saved|remembered|i'?ll remember|i will remember|guard[eé]|lo recuerdo|me lo acuerdo)\b", re.I),
     {"remember", "log_baby_event", "edit_baby_event", "appointments", "prep_add", "prep_check", "set_due_date", "remind_me"}),
    (re.compile(r"\b(added|agregu[eé]|sum[eé])\b", re.I), {"prep_add", "log_baby_event", "appointments"}),
    (re.compile(r"\b(ticked|checked (it )?off|crossed (it )?off|tach[eé]|marqu[eé])\b", re.I), {"prep_check"}),
]


# "Si me decís, lo recuerdo": an offer on a condition the parent has not met is no claim that it happened. Once Muse
# answered Ceci's question that way twice and the guard replaced it with "No mandé nada, no se hizo nada".
CONDITION = re.compile(r"\b(si|if|en cuanto|apenas|as soon as|once you)\b", re.I)


def offered_on_condition(text, start):
    """True when the sentence before position start sets a condition: "Si me decís quién, lo recuerdo"."""
    sentence = re.split(r"[.!?\n]", text[:start])[-1]
    return bool(CONDITION.search(sentence))


def unmet_claims(text, ran):
    """The claimed actions in a reply whose tool did not run this turn: "I told Parent B" after only dim_lights."""
    text, out = text or "", set()
    for pattern, tools in CLAIM_TOOLS:
        for m in pattern.finditer(text):
            if NEGATED.search(text[max(0, m.start() - 40):m.start()]) or offered_on_condition(text, m.start()):
                continue
            if not (tools & set(ran)):
                out.add(m.group(0).lower())
    return out


def claims_done(text):
    """True when a reply says the log was written in this turn, and does not say the opposite ("no lo anoté")."""
    text = text or ""
    return any(not NEGATED.search(text[max(0, m.start() - 40):m.start()]) for m in CLAIMS_DONE.finditer(text))


SPANISH_WORDS = re.compile(r"\b(se|le|la|el|de|del|un|una|y|con|ya|reci[eé]n|hoy)\b", re.I)
NAME_WORD = re.compile(r"(?<![\w.!?¿¡]\s)(?<=\s)[A-ZÁÉÍÓÚÑ][\wáéíóúñ]*")


def looks_spanish(text):
    """Spanish words, or an accent or ¿¡ outside a name: "José had 90 ml" stays English."""
    text = text or ""
    if note_to_english(text) != text or SPANISH_WORDS.search(text):
        return True
    return bool(re.search(r"[ñáéíóú¿¡]", NAME_WORD.sub("", " " + text)))


# "took 75ml of formula" had none of the old words, so the third blind set answered it in Spanish.
ENGLISH = re.compile(r"\b(the|she|he|his|her|him|is|was|did|gave|had|just|when|how|what|why|it|that|bottle|diaper|"
                     r"nappy|feed|fed|nursed|breast|woke|asleep|slept|nap|crying|poop|pee|wet|dirty|bath|left|right|"
                     r"at|ago|hello|hi|thanks|please|delete|fix|sorry|took|drank|ate|finished|of|with|and|after|again)\b", re.I)


def message_lang(text):
    """The language of one parent message, "es" or "en", or None when its words say neither ("120", "ok")."""
    if looks_spanish(text):
        return "es"
    return "en" if ENGLISH.search(text or "") else None


EN_COMMON = re.compile(r"(are|a|an|to|in|on|for|my|me|you|we|not|off|up|out|be|been|have|has|having|this|there|so|but|"
                       r"or|very|all|one|two|won|can|t|don|didn|isn|wasn|doesn|s|ll|ve|m)", re.I)
ES_COMMON = re.compile(r"(lo|los|las|dos|una|uno|es|era|eran|fue|fueron|s[ií]+|mismo|misma|veces|vez|que|qu[eé]|por|para|"
                       r"pero|como|cuando|mand[eé]|sola|solo|bien|todo|nada|m[aá]s|muy|ahi|ah[ií]|ac[aá]|esta|est[aá]|"
                       r"eso|esa|ese|perd[oó]n|tranqui|dale|nomas|nom[aá]s|igual|otra|otro|recien|reci[eé]n|pa|che)", re.I)


def clearly_english(text):
    """True when a message is in English and not Spanish with an English word: "gave her a 60 ml bottle" and "his lips
    are blue" are, "sii lo mande dos veces sorry" and "ok thanks" are not."""
    if is_courtesy(text):
        return False
    words = re.findall(r"[^\W\d_]+", text or "")
    if any(ES_COMMON.fullmatch(w) for w in words):
        return False
    hits = [w for w in words if ENGLISH.fullmatch(w) or EN_COMMON.fullmatch(w)
            or (w[-1:].lower() == "s" and ENGLISH.fullmatch(w[:-1]))]
    return bool(hits) and (2 * len(hits) >= len(words) or len(hits) >= 2)


# A thanks or an ok with nothing else in it. Round 5: "ok thanks" in a Spanish family got an English reply in 3 of 3 runs,
# once with "Benja is doing great", a claim about the baby nobody made. It never flips the language, and it gets a short
# fixed reply with no brain call and nothing said about the baby.
COURTESY = re.compile(r"^\W*((ok(ay|a|i|is)?|dale|listo|genial|perfecto|buen[ií]simo|b[aá]rbaro|joya|great|cool|nice|"
                      r"thanks?( a lot| so much)?|thank you( so much)?|thx|ty|gracias|muchas gracias|mil gracias|grax|"
                      r"de una|sounds good|got it|entendido|👍|🙏|❤️?)[\s,.!]*)+$", re.I)
THANKS = re.compile(r"thank|thx|\bty\b|graci|grax|🙏", re.I)
COURTESY_REPLY = {"en": {"thanks": "You are welcome.", "ok": "OK."}, "es": {"thanks": "De nada.", "ok": "Dale."}}


def is_courtesy(text):
    return bool(text) and bool(COURTESY.match(text.strip()))


def courtesy_reply(text, lang):
    words = COURTESY_REPLY["es" if lang == "es" else "en"]
    return words["thanks"] if THANKS.search(text or "") else words["ok"]


TWO_FEEDS = re.compile(r"\b(dos|two|2|both|ambas|ambos) (mamaderas|tomas|bottles|feeds|feedings)\b|"
                       r"\b(y|and|then|despu[eé]s|luego) (otra|another)\b|"
                       r"\b(otra|another|other|second|segunda) (mamadera|toma|bottle|feed)\b", re.I)
CLOCK_SAID = re.compile(r"\b\d{1,2}[:h.]\d{2}\b|\b(?:a las?|at) \d{1,2}\b", re.I)
FEED_NUMBER = re.compile(r"(?<![\d:.])\d{1,3}(?:[.,]\d)?(?![\d:])")


def says_two_feeds(text):
    """True when one message reports more than one feed: two amounts or minutes, or "dos mamaderas". "tomo 60 y largo un
    poco" reports one, and the demo stored it twice in 1 of 2 round 5 tries."""
    text = text or ""
    numbers = {n.replace(",", ".") for n in FEED_NUMBER.findall(re.sub(r"\b\d{1,2}[:h.]\d{2}\b|\ba las? \d{1,2}\b", " ", text))}
    times = {t.lower() for t in CLOCK_SAID.findall(text)}
    return bool(TWO_FEEDS.search(text)) or len(numbers) >= 2 or len(times) >= 2


def turn_lang(text, home):
    """The language to answer one message in, for a chat whose language is home. A Spanish family's "sorry" or "ok"
    never turns the reply English: on round 4 "sii lo mande dos veces sorry" got "No worries, left it as one bottle"
    at 03:48 in 3 of 3 runs. A message clearly in the other language still gets that language."""
    lang = message_lang(text)
    if lang == "en" and home == "es" and not clearly_english(text):
        return "es"
    return lang


def answer(question, summary):
    """A short answer to a parent's question from baby_summary, or None when the rules do not know the question."""
    q = question.lower()
    feeds, diapers, sleep, baths = summary["feedings"], summary["diapers"], summary["sleep"], summary["baths"]
    if "dirty" in q or "poop" in q:
        if "how many" in q:
            return f"{diapers['dirty']} dirty diapers today."
        return f"The last dirty diaper was at {diapers['last_dirty_at']}." if diapers["last_dirty_at"] else "No dirty diaper in the log yet."
    if "diaper" in q or "wet" in q:
        return f"Today: {diapers['said']['en']}."
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


TEST_PREFIX = re.compile(r"^\s*test:\s*", re.I)


def is_test(text):
    """A message that starts with "Test:" is a test: it never counts for the KR."""
    return bool(TEST_PREFIX.match(str(text or "")))


def without_test_prefix(text):
    """The message without its "Test:" marker. The marker is for the KR scorer, the brain answers the words after it."""
    text = str(text or "")
    rest = TEST_PREFIX.sub("", text, count=1)
    return rest if rest.strip() else text


# "¿Quién está de turno esta noche?", "who is on duty tonight", "who gets up tonight": the night rota answers it.
ON_DUTY = re.compile(r"\b(de turno|on duty|le toca (levantarse|esta noche|hoy)|toca levantarse|"
                     r"who(se)? (turn|gets up|is up tonight)|a qui[eé]n le toca)\b", re.I)
# "¿Cuál es la farmacia de turno?" asks about a pharmacy or a doctor on duty, never the night rota.
NOT_ROTA = re.compile(r"\b(farmacia|pharmacy|m[eé]dic[oa]|doctor|pediatra|pediatrician|emergencia|emergency|"
                      r"sanatorio|hospital|mutualista|enfermer[oa]|nurse)\b", re.I)


def asks_on_duty(text):
    text = text or ""
    return bool(ON_DUTY.search(text)) and is_question(text) and not NOT_ROTA.search(text)


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
    brain call. "note" for a symptom the parent reports with no question: noted in their words, no brain call. "log" for
    a health message that also reports something the parent wants kept, a medicine given, a milestone, an explicit ask
    to log, or a feed told with the symptom ("tomo 70 y vomito un poco"): the entry is logged, the symptom kept as a
    note, and only an advice part is refused."""
    if not text or is_emergency(text) or not (is_medical(text) or is_medical_es(text)):
        return None
    if LOG_ASK.search(text) or GAVE.search(text) or MILESTONE.search(text):
        return "log"
    if SYMPTOM.search(text) and not is_question(text) and not ADVICE.search(text):
        # "vomito un poquito dsp de la toma" reports what the parent saw: it is kept as a note in their words, for the
        # pediatrician. "tomo 70 y vomito un poco" also reports a feed: on round 4 the 70 ml was lost from the day total
        # in 3 of 3 runs, so a message that carries a feed amount or minutes goes to the log as well.
        return "log" if symptom_feed(text) else "note"
    return "refuse"


def asks_advice(text):
    """True when the parent asked something a health line answers, or named a fever. A symptom reported with no question
    ("tomo 70 y vomito un poco") gets no "I can't give medical advice" tail: the parent asked nothing."""
    return bool(ADVICE.search(text or "")) or names_fever(text)


# A feed told together with a symptom: "tomo 70 y vomito un poco", "vomito despues de la mamadera de 120",
# "took 60 ml and spat up". Plain code reads it, so the urgent line and the note path never lose the amount.
SYMPTOM_BOTTLE = re.compile(r"\b(?:tom[oó]|tomo|le di|le dimos|se tom[oó]|mamadera(?: de)?|biber[oó]n(?: de)?|f[oó]rmula|"
                            r"took|drank|had|bottle(?: of)?|fed(?: him| her)?)\s+(?:como |unos |about |de )?(\d{2,3})"
                            r"(?:\s*(?:ml|cc))?\b(?!\s*(?:min|minutos|mins|minutes|h\b|hs|horas|hours|veces|times|grados|degrees|°))|"
                            r"\b(\d{2,3})\s*(?:ml|cc)\b", re.I)
SYMPTOM_BREAST = re.compile(r"\b(?:pecho|teta|breast|nursed)\b[^.?!]{0,30}?\b(\d{1,3})\s*(?:min|minutos|mins|minutes)\b|"
                            r"\b(\d{1,3})\s*(?:min|minutos|mins|minutes)\b[^.?!]{0,20}?\b(?:pecho|teta|breast)\b", re.I)


def symptom_feed(text):
    """The feed a symptom message also reports, as log_baby_event details, or None. Only a bottle amount of 5 to 300 ml
    or breast minutes of 1 to 120 count, so "vomito dos veces" and "38 de fiebre" are no feed."""
    text = text or ""
    if medicine_only(text) and not SYMPTOM_BOTTLE.search(text):
        return None
    bottle = SYMPTOM_BOTTLE.search(text)
    if bottle:
        ml = float(bottle.group(1) or bottle.group(2))
        if 5 <= ml <= 300 and not names_fever(text[max(0, bottle.start() - 5):bottle.end() + 12]):
            return {"method": "bottle", "amount_ml": ml}
    breast = SYMPTOM_BREAST.search(text)
    if breast:
        minutes = int(breast.group(1) or breast.group(2))
        if 1 <= minutes <= 120:
            return {"method": "breast", "duration_min": minutes}
    return None


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


ADD_START = re.compile(r"^\W*(ah,?\s+)?(y|tambi[eé]n|tmb|tb|and|also)\b|\b(tambi[eé]n|tmb|tb|too|also)\W*$", re.I)
WET_ADD = re.compile(r"\b(pis|pich[ií]|pee|wee|mojad\w*|orin\w*|wet)\b", re.I)
SOLID_ADD = re.compile(r"\b(caca|caquita|poo|poop|popo|pop[oó]|sucio|dirty)\b", re.I)
TYPE_ADD = re.compile(r"\b(f[oó]rmula|formula|leche materna|materna|breast ?milk)\b", re.I)
# Words that start a new feed rather than add to the last one: "le di formula" is a feed, "de materna" is a detail.
NEW_FEED = re.compile(r"\b(le di|le dio|le dimos|le doy|di[oó]|tom[oó]|toma|gave|fed|drank|mamadera|biber[oó]n|bottle|otra|another)\b", re.I)
SLEEP_SLANG = re.compile(r"frit[ao]|rendid[ao]|se qued[oó]|cay[oó]|planch|fundid|arriba|abri[oó] los ojos|ojitos|cuna|upa|"
                         r"\bout\b|crashed|went down|is up\b", re.I)


def addendum(text):
    """A short follow-up that only adds one detail to the entry logged just before: "como 14 min" after "teta izq",
    "y pis tmb" after a dirty diaper, "ah y era formula" after a bottle. Returns (kind, details, minutes back) or None.
    In run 1 of the held-out set each of these became a second entry or was lost."""
    text = (text or "").strip()
    if not text or "?" in text or len(text) > 60:
        return None
    numbers = re.findall(r"\d+", text)
    lowered = text.lower()
    minutes = MINUTES.search(lowered) or re.search(r"(\d+)\s*mins?\b", lowered)
    if minutes and len(numbers) == 1 and not (BREAST_WORDS.search(text) or SIDE_SAID.search(text) or BOTTLE_WORDS.search(text)
                                              or KIND_WORDS["diaper"].search(text) or KIND_WORDS["sleep"].search(text)
                                              or TIME_SAID.search(text) or ML.search(text)):
        value = int(minutes.group(1))
        return ("feeding", {"duration_min": value}, 60) if 1 <= value <= 90 else None
    if numbers:
        return None
    patch = diaper_patch(text)
    if patch:
        return "diaper", patch, 15
    m = TYPE_ADD.search(text)
    # A short message whose only detail is a milk type, in any frame: "ah y era formula", "de materna, la q sacaste
    # ayer", "la de recien fue con formula". The old rule wanted "era" or "fue" right before the type, so the second
    # blind set lost two of these to the brain.
    if m and not (BREAST_WORDS.search(text) or NEW_FEED.search(text) or KIND_WORDS["diaper"].search(text)
                  or KIND_WORDS["sleep"].search(text)):
        milk = "formula" if TYPE_SAID["formula"].search(m.group(1)) else "breast milk"
        return "feeding", {"type": milk}, 20
    return None


# A follow-up that points back at the entry just logged, wherever the word sits: "uh no, tambien tenia pis", "y pis tmb",
# "estaba con caca tambien". The old rule wanted the word first or last, so a filler ("uh no,") sent it to the brain.
REFERS_BACK = re.compile(r"\b(tambi[eé]n|tmb|tb|too|also|adem[aá]s|ten[ií]a|estaba|had|was)\b|^\W*(ah,?\s+)?(y|and)\b", re.I)
NEW_DIAPER = re.compile(r"pa[nñ]al|diaper|otro|another|cambi|chang", re.I)
NOT_BEFORE = re.compile(r"\b(sin|no|ni|without|not|no ten[ií]a|no hab[ií]a|no hizo|no had)\s+(\w+\s+)?$", re.I)


def diaper_patch(text):
    """The wet and dirty details a short follow-up adds to or takes from the diaper just logged: "uh no, tambien tenia
    pis" is wet, "no tenia caca" is not dirty. {} when the message is not such a follow-up."""
    if NEW_DIAPER.search(text) or not (REFERS_BACK.search(text) or EDIT.search(text)):
        return {}
    patch = {}
    for name, pattern in (("wet", WET_ADD), ("solid", SOLID_ADD)):
        m = pattern.search(text)
        if m:
            patch[name] = not NOT_BEFORE.search(text[max(0, m.start() - 20):m.start()])
    return patch


# A follow-up that gives the bottle just logged its real amount: "no wait, dejo un poco, ponele 100" sets it,
# "dejo como media onza igual" and "sobraron 20" take what was left from it.
SET_AMOUNT = re.compile(r"\b(ponele|pon[eé]|pone|eran?|fue|fueron|son|ser[ií]an?|make it|it was|was)\b|^\W*no\b", re.I)
LEFT_OVER = re.compile(r"\b(sobr\w*|dej[oó]|qued[oó]|left( over)?)\b", re.I)
HALF_OUNCE_ONLY = re.compile(r"\b(media|half an?) " + OUNCE_WORD + r"\b", re.I)
NEW_BOTTLE = re.compile(r"\b(took|had|another|new|nueva|prepar\w*)\b", re.I)


def amount_followup(text):
    """(ml, "set" or "left") for a short message that only gives an amount for the bottle just logged, or None. It never
    reads a message that starts a feed ("le di 100", "mamadera 90", "took 75 ml"), names a time or a breast, or asks."""
    text = (text or "").strip()
    if not text or "?" in text or len(text) > 70:
        return None
    if (NEW_FEED.search(text) or NEW_BOTTLE.search(text) or BREAST_WORDS.search(text) or SIDE_SAID.search(text)
            or KIND_WORDS["diaper"].search(text) or KIND_WORDS["sleep"].search(text) or KIND_WORDS["bath"].search(text)
            or clock_times(text) or DAY_SAID.search(text) or MINUTES_SAID.search(text) or TIME_SAID.search(text)):
        return None
    numbers = re.findall(r"\d+(?:[.,]\d+)?", text)
    if len(numbers) > 1:
        return None
    if numbers:
        ml = ounces_ml(text) or float(numbers[0].replace(",", "."))
    elif HALF_OUNCE_ONLY.search(text):
        ml = ML_PER_OUNCE / 2
    else:
        return None
    if not 5 <= ml <= BOUNDS["amount_ml"][1]:
        return None
    mode = "set" if SET_AMOUNT.search(text) or not LEFT_OVER.search(text) else "left"
    return float(ml), mode


# A message that says something did not happen: "mire el pañal y esta seco, no la cambie" is no diaper. Each match
# names the kind it denies, so "se durmio, no tomo la teta" still logs the sleep.
NOT_HAPPENED = [
    ("diaper", re.compile(r"\b(no|nunca|todav[ií]a no|a[uú]n no)\s+(la |lo |le )?(cambi[eé]|cambiamos|cambi[oó]|hizo)\b|"
                          r"\b(est[aá]|estaba|segu[ií]a|sigue)\s+(\w+\s+)?sec[oa]\b|\bpa[nñ]al sec[oa]\b|\b(still |was |is )?dry\b|"
                          r"\b(didn'?t|did not|haven'?t|hasn'?t) (change|need)", re.I)),
    ("feeding", re.compile(r"\b(no|nunca|todav[ií]a no|a[uú]n no)\s+(le )?(di|dimos|dio|tom[oó]|comi[oó])\b(?!\s+(m[aá]s|todo|toda|entera))|"
                           r"\b(didn'?t|did not|hasn'?t|has not) (eat|feed|drink|take)\b(?!\s+(more|all))", re.I)),
    ("sleep", re.compile(r"\b(no|nunca|todav[ií]a no|a[uú]n no)\s+(se )?(durmi[oó]|duerme)\b|\b(didn'?t|did not|hasn'?t|has not|won'?t) (sleep|nap)", re.I)),
    ("bath", re.compile(r"\b(no|todav[ií]a no|a[uú]n no)\s+(la |lo )?(ba[nñ][eé]|ba[nñ]amos)\b", re.I)),
]


# A feed with an amount or a length did happen: "no tomo mucho, 60 nomas" and "no le di teta, le di 90" are feeds.
FEED_AMOUNT_SAID = re.compile(r"(?<!las )(?<!la )(?<![\d:.,])\d{2,3}(?![\d:.,])|\b(mitad|half|onzas?|oz|ounces?)\b|\d+\s*min", re.I)


def denied_kinds(text):
    """The log kinds a message says did not happen."""
    denied = {kind for kind, pattern in NOT_HAPPENED if pattern.search(text or "")}
    if "feeding" in denied and FEED_AMOUNT_SAID.search(text or ""):
        denied.discard("feeding")
    return denied


def says_sleep(text):
    """True when a message speaks of sleep or waking at all, in the plain words or the slang ("se quedo frita")."""
    return bool(KIND_WORDS["sleep"].search(text or "") or SLEEP_SLANG.search(text or "") or WOKE_SAID.search(text or ""))


CHAT = re.compile(r"sonrient\w*|sonr[ií]e\b|feliz|content[ao]|divin[ao]|hermos[ao]|re lind[ao]|no para de mirar|mirando todo|"
                  r"fr[ií]o|abrigad\w*|calor(?! en)|que sue[nñ]o|q sue[nñ]o|cansad[ao]|agotad[ao]|so happy|smiley|so cute|cold today",
                  re.I)


def chat_only(text):
    """True when a message only shares a moment or a mood, "hoy esta re sonriente, no para de mirar el movil", "hoy hace
    un frio barbaro": chat, never a note (run 1 of the held-out set logged one). Health, a medicine, a milestone or a
    parent asking to log it is never chat."""
    text = text or ""
    if not CHAT.search(text):
        return False
    return not (is_health(text) or MEDICINE.search(text) or SYMPTOM.search(text) or MILESTONE.search(text)
                or LOG_ASK.search(text) or GAVE.search(text))


# What a message reports besides its question, for the fixed lines that answer it with no brain call (round b4: "le di
# 60 ml ... ¿puede dormir boca abajo?" got the safe sleep line and lost the 60 ml, "caca verde" lost the diaper).
QUESTION_PART = re.compile(r"¿[^?]*\?|[^.!?¿,;]*\?")
DIAPER_COLOR = (("green", re.compile(r"verde|green", re.I)), ("yellow", re.compile(r"amarill|yellow", re.I)),
                ("brown", re.compile(r"marr[oó]n|brown", re.I)), ("black", re.compile(r"negr|black", re.I)))


def reported_part(text):
    """The message without its questions: "le di 60 ml, ¿puede dormir boca abajo?" is "le di 60 ml"."""
    return QUESTION_PART.sub(" ", text or "")


def reported_diaper(text):
    """The diaper a message reports outside its questions, as log_baby_event details, or None. "hizo caca verde, ¿es
    normal?" is a dirty green diaper, "¿es normal la caca verde?" and "no hizo caca" are none."""
    said = reported_part(text)
    if is_stock_talk(said) or not KIND_WORDS["diaper"].search(said):
        return None
    out = {}
    for name, pattern in (("wet", WET_ADD), ("solid", SOLID_ADD)):
        m = pattern.search(said)
        out[name] = bool(m) and not NOT_BEFORE.search(said[max(0, m.start() - 20):m.start()])
    if not (out["wet"] or out["solid"]):
        if not re.search(r"\b(cambi\w*|changed)\b", said, re.I):
            return None
        out["wet"] = True
    color = next((name for name, pattern in DIAPER_COLOR if pattern.search(said)), None) if out["solid"] else None
    return {**out, "color": color} if color else out


def reported_entries(text):
    """[(kind, details)] a message reports outside its questions: a feed with its amount or minutes, a diaper."""
    said = reported_part(text)
    out = []
    feed = symptom_feed(said) if FEED_WORDS.search(said) or re.search(r"\d\s*(ml|cc)\b", said, re.I) else None
    if feed:
        out.append(("feeding", feed))
    diaper = reported_diaper(text)
    if diaper:
        out.append(("diaper", diaper))
    return out


def diaper_counts(diapers):
    """Today's diapers as numbers that add up: wet only, dirty (with or without pee) and dry, plus the line to say."""
    details = [d.get("details") or {} for d in diapers]
    dirty = sum(1 for d in details if d.get("solid"))
    wet_only = sum(1 for d in details if d.get("wet") and not d.get("solid"))
    dry = len(details) - dirty - wet_only
    return {"count": len(details), "wet_only": wet_only, "dirty": dirty, "dry": dry,
            "said": {lang: diaper_line(len(details), wet_only, dirty, dry, lang) for lang in ("en", "es")}}


def diaper_line(count, wet_only, dirty, dry, lang="en"):
    """"4 pañales: 3 solo pis, 1 con caca": the parts always add up to the count, with no diaper counted twice."""
    if lang == "es":
        head = f"{count} pañal" if count == 1 else f"{count} pañales"
        parts = [f"{wet_only} solo pis" if wet_only else "", f"{dirty} con caca" if dirty else "",
                 (f"{dry} seco" if dry == 1 else f"{dry} secos") if dry else ""]
    else:
        head = f"{count} diaper" if count == 1 else f"{count} diapers"
        parts = [f"{wet_only} wet only" if wet_only else "", f"{dirty} dirty" if dirty else "", f"{dry} dry" if dry else ""]
    parts = [p for p in parts if p]
    return head + (": " + ", ".join(parts) if parts else "")


# Blind round b5: red flags by meaning. The word list above misses new phrasings ("face in the pillow and now very
# still"), so a message that is not on it is also read by Muse for what it means (agent/danger.py). When that reading
# cannot be had (no model, an error, an unreadable answer), these signs of a baby who may not be breathing put the
# message on the 911 line anyway: the conservative fallback.
DANGER_FALLBACK = re.compile(
    r"\bface\b[^.!?]{0,20}\b(in|into|against|on|under)\b[^.!?]{0,12}\b(pillows?|mattress|cushions?|blankets?|duvet|"
    r"comforter|bumpers?|couch|sofa|bedding|sheets?|quilt)\b|"
    r"\b(pillows?|blankets?|duvet|cushions?|quilt|comforter)\b[^.!?]{0,15}\b(over|on|covering|across)\b[^.!?]{0,8}\b"
    r"(his|her|the baby'?s?|its|their) (face|head|mouth|nose)\b|"
    r"\b(very|so|too|really|completely|totally|eerily|strangely|weirdly|unusually|perfectly|dead) still\b|"
    r"\b(he|she|baby|the baby|it)('s| is| was|'s been| has been)? (not|no longer|isn'?t|stopped|hasn'?t been|won'?t|doesn'?t) "
    r"(moving|move|responding|respond|reacting|react)\b|"
    r"\bcan'?t (hear|see|feel) (him|her|the baby|them) breath\w*|\bno (lo |la )?(escucho|oigo|siento|veo) respirar|"
    r"\bcara\b[^.!?]{0,20}\b(en|contra|sobre|metida en|hundida en|apretada contra|debajo de)\b[^.!?]{0,8}\b(la |el |una |un )?"
    r"(almohad\w*|colch[oó]n|mantas?|frazadas?|acolchado|s[aá]banas?|cobijas?|sill[oó]n|sof[aá]|edred[oó]n)\b|"
    r"\b(almohad\w*|mantas?|frazadas?|cobijas?|acolchado|edred[oó]n)\b[^.!?]{0,15}\b(sobre|encima de|tap[aá]ndole|le tapa)\b"
    r"[^.!?]{0,8}\b(la )?(cara|boca|nariz|cabeza)\b|"
    r"\b(muy|re|demasiado|totalmente|completamente|rar[oa]mente) quiet[oa]\b", re.I)


def maybe_danger(text):
    """True for a sign a baby may not be breathing that the word list misses. The fallback when Muse cannot read it."""
    return bool(DANGER_FALLBACK.search(EVERYDAY.sub(" ", text or "")))


# A model's answer that sends the parent to emergency services now is itself a red flag reading: on round b5 Muse
# answered the pillow line with the 911 line and four numbered first aid steps after it. The parent gets the fixed
# emergency text only. A refusal that says "call 911 if it is urgent" is not one.
URGES_EMERGENCY = re.compile(
    r"\b(call|phone|dial|ring)\s+(911|112|999|emergency services|an ambulance|emergencies)\b(?![^.!?]{0,30}\b(if|when|should)\b)"
    r"[^.!?]{0,20}\b(now|right now|right away|immediately|at once|straight away)\b|"
    r"\b(now|right now|immediately|right away)\b,?\s+(call|phone|dial)\s+(911|112|999|emergency services|an ambulance)\b|"
    r"\bllam[aáe]\w*\s+(ya|ahora|ahora mismo|inmediatamente|ya mismo|urgente)\s+(al|a)\s+(911|112|emergencias?|una ambulancia)\b|"
    r"\bllam[aáe]\w*\s+(al|a)\s+(911|112|emergencias?|una ambulancia)\s+(ya|ahora|ahora mismo|inmediatamente|ya mismo|urgente)\b",
    re.I)


def urges_emergency(text):
    return bool(URGES_EMERGENCY.search(text or ""))


# "She is napping now", "está durmiendo la siesta": the baby is asleep now, so a sleep starts and stays open until the
# parent says he woke. Round b5: the demo logged it as a finished nap from 15:13 that overlapped two feeds.
ASLEEP_NOW = re.compile(
    r"\b(is|'s|are)\s+(now\s+)?(napping|sleeping|asleep|down for (a|his|her|the) nap|having (a|his|her) nap|out cold|"
    r"fast asleep|sound asleep)\b|\b(napping|sleeping|asleep) (now|right now|at the moment)\b|"
    r"\b(just\s+)?(fell|went|dozed off|drifted off)( back)?( to)?( sleep| asleep| off| down)?\b(?! at \d)(?=[^.!?]*$)|"
    r"\b(est[aá]|sigue|qued[oó])\s+(ahora\s+)?(durmiendo|dormid[oa]|en (la )?siesta|haciendo (la )?siesta|frit[oa])\b|"
    r"\bduerme (ahora|ya|la siesta)\b|\bse (acaba de )?(durmi[oó]|dormi[oó]|qued[oó] (dormid[oa]|frit[oa]))\b|"
    r"\bse acaba de dormir\b", re.I)


def asleep_now(text):
    """True when the newest message says the baby is asleep now and nothing that makes it a finished sleep: no
    wake-up, no length, no from-to."""
    text = text or ""
    if not ASLEEP_NOW.search(text):
        return False
    return not (says_woke(text) or slept_minutes(text) or RANGE_SAID.search(text))


# "Only took 20 ml since morning", "tomó 300 en total hoy": a total over a period, never a new feed (round b5 logged
# it as a 20 ml bottle). The agent asks instead, with what the log holds.
TOTAL_SAID = re.compile(
    r"\b(since (this |the )?morning|since (he|she) (woke|got up)|so far( today)?|all day( long)?|(in )?total|altogether|"
    r"the whole day|for the day|today in all|in all today|"
    r"en total|desde (la|esta|hoy (a|en) la) ma[ñn]ana|desde que se despert[oó]|en todo el d[ií]a|en lo que va del d[ií]a|"
    r"hasta ahora|hasta el momento|todo el d[ií]a|en el d[ií]a|sumando todo|entre todas)\b", re.I)
TOTAL_FEED = re.compile(r"\d\s*(ml|cc|oz|onzas?)\b|\b(took|drank|had|ate|eaten|fed|tom[oó]|comi[oó]|bebi[oó]|mam[oó])\b", re.I)
TOTAL_REPLY = {
    "en": ("That sounds like a total for the day, so I did not add it as a new feed. Today the log has {feeds}. "
           "If a feed is missing, tell me when it was and how much, and I will add it."),
    "es": ("Eso suena a un total del día, así que no lo anoté como una toma nueva. Hoy el registro tiene {feeds}. "
           "Si falta una toma, decime a qué hora fue y cuánto, y la agrego."),
}
TOTAL_FEEDS = {"en": ("no feeds yet", "1 feed", "{n} feeds"), "es": ("ninguna toma todavía", "1 toma", "{n} tomas")}


def reports_total(text):
    """True when a message gives a feed total over a period, not one feed."""
    text = text or ""
    return bool(TOTAL_SAID.search(text) and TOTAL_FEED.search(text)) and not is_question(text)


def total_reply(summary, lang):
    lang = lang if lang in TOTAL_REPLY else "en"
    feeds = (summary or {}).get("feedings") or {}
    count = int(feeds.get("count") or 0)
    words = TOTAL_FEEDS[lang]
    said = words[0] if count == 0 else words[1] if count == 1 else words[2].format(n=count)
    if feeds.get("total_ml"):
        said += f", {feeds['total_ml']} ml" + (" en mamaderas" if lang == "es" else " in bottles")
    if feeds.get("last_at") and count:
        said += (f", la última a las {feeds['last_at']}" if lang == "es" else f", the last at {feeds['last_at']}")
    return TOTAL_REPLY[lang].format(feeds=said)


# A fever written in the log reaches every place that speaks first (round b5: a 38.6 in a 5 week old showed nowhere
# but the chat that logged it): the panel, the night plan, the morning message and the Echo. The line is fixed, the
# same under-3-months call-now guidance as the gate, never a dose and never a judgement about this baby.
FEVER_LOGGED = {"en": "A fever was logged at {at}.", "es": "Hay una fiebre anotada a las {at}."}
FEVER_SPOKEN = {
    "en": ("A baby under 3 months with a temperature of 38 degrees or more needs a doctor right away. Call your "
           "pediatrician now, or go to the emergency room. If you cannot reach them, call 911."),
    "es": ("Un bebé de menos de 3 meses con 38 grados o más tiene que verlo un médico ya. Llamá ahora a tu pediatra o "
           "andá a emergencia. Si no los ubicás, llamá al 911."),
}
FEVER_HOURS = 24


def logged_fever(entries, now, hours=FEVER_HOURS):
    """The newest note in the last `hours` that says the baby has a fever, or None."""
    since = now - datetime.timedelta(hours=hours)
    found = None
    for entry in entries or []:
        if entry.get("kind") != "note":
            continue
        text = str((entry.get("details") or {}).get("text") or "")
        try:
            at = datetime.datetime.fromisoformat(str(entry.get("ts")))
        except ValueError:
            continue
        at = at.replace(tzinfo=now.tzinfo) if at.tzinfo is None else at.astimezone(now.tzinfo)
        if since <= at <= now + datetime.timedelta(minutes=5) and names_fever(text):
            if found is None or at >= found[0]:
                found = (at, entry)
    return found


def fever_line(found, lang, spoken=False):
    """The fixed line for a logged fever: when it was logged, then the call-now guidance (with its public source in
    text, without the link when it is spoken)."""
    lang = lang if lang in FEVER_LOGGED else "en"
    at, _ = found
    tz = at.tzinfo
    head = FEVER_LOGGED[lang].format(at=at.astimezone(tz).strftime("%H:%M"))
    return head + " " + (FEVER_SPOKEN[lang] if spoken else URGENT_REPLY["fever"][lang])


# Where the agent runs, said right. On round b5 Muse said it runs on Meta's servers: it runs on Baseten.
SELF_FACTS = ("About yourself, only if asked: you are Muse Spark Open, Meta's open-weights model, served by Baseten "
              "(inference.baseten.co) on the hackathon's free credits. You do not run on Meta's servers. The baby log "
              "stays on the family's own server (Baby Buddy). The messages, voice notes and the log lines you read are "
              "sent to Baseten, and on the free credits Meta may use them to train future Meta models.")
WRONG_HOST = re.compile(
    r"[^.!?\n]*\b(?:(?:on|in|through|by|from|via|using|uses?)\s+(?:the\s+)?meta'?s?\s+(?:own\s+)?(?:servers?|infrastructure|"
    r"cloud|data ?cent(?:er|re)s?|systems)|meta\s+(?:servers?|infrastructure|cloud|data ?cent(?:er|re)s?)|"
    r"servidores (?:propios )?de meta|(?:la )?infraestructura de meta|la nube de meta|los sistemas de meta)\b[^.!?\n]*[.!?]?",
    re.I)
RIGHT_HOST = {"en": "I run on Muse Spark Open, Meta's open model, served by Baseten, not on Meta's servers.",
              "es": "Funciono con Muse Spark Open, el modelo abierto de Meta, en los servidores de Baseten, no en los de Meta."}


def right_host(text, lang="en"):
    """Every sentence that says the agent runs on Meta's servers goes, and the fact is said once in its place."""
    if not text or not any("baseten" not in m.group(0).lower() for m in WRONG_HOST.finditer(text)):
        return text
    lang = lang if lang in RIGHT_HOST else "en"
    said = []

    def swap(match):
        if "baseten" in match.group(0).lower():
            return match.group(0)  # the fact itself, "served by Baseten, not on Meta's servers"
        first, _ = not said, said.append(True)
        return " " + RIGHT_HOST[lang] + " " if first else " "
    return " ".join(WRONG_HOST.sub(swap, text).split())


# "Where do you run?", "¿qué modelo sos?": a fixed answer with the facts, no brain call. Live on Nov 1 Muse's own answer
# ("messages are sent to Baseten") read as a claimed action to the log honesty guard and the parent got "nothing ran".
ASKS_SELF = re.compile(
    r"\b(where|on what|on which|on whose|whose)\b[^.!?]{0,30}\b(do you|are you|you)\b[^.!?]{0,20}\b(run\w*|hosted|live|servers?)\b|"
    r"\bwhat (ai|model|llm)\b[^.!?]{0,20}\b(are you|do you use|is this|runs? you|powers? you)\b|\bwho (made|built|runs) you\b|"
    r"\bare you (chatgpt|gpt|claude|gemini|meta ai|llama)\b|\byour servers?\b|"
    r"\bd[oó]nde (corr[eé]s|funcion[aá]s|est[aá]s alojad\w*|te ejecut\w*)\b|\ben (qu[eé]|cu[aá]les|los) servidores\b|"
    r"\bqu[eé] (modelo|ia|inteligencia artificial)\b[^.!?]{0,20}\b(sos|us[aá]s|es|te mueve)\b|\bqui[eé]n te (hizo|cre[oó]|program[oó])\b|"
    r"\btus servidores\b", re.I)
SELF_ANSWER = {
    "en": ("I run on Muse Spark Open, Meta's open model, served by Baseten on the hackathon's free credits, not on Meta's "
           "servers. {log} What you send me goes to Baseten, and on those free credits Meta may use it to train future "
           "Meta models."),
    "es": ("Funciono con Muse Spark Open, el modelo abierto de Meta, en los servidores de Baseten con créditos gratis de "
           "la hackathon, no en los de Meta. {log} Lo que me mandás va a Baseten, y con esos créditos Meta lo puede usar "
           "para entrenar futuros modelos de Meta."),
}
SELF_LOG = {"en": "The baby log stays on the family's own server.", "es": "El registro del bebé queda en el servidor de la familia."}


def asks_about_self(text):
    return bool(ASKS_SELF.search(text or "")) and not is_health(text)
