"""The prep lists the agent starts with, before Theo is born. Logistics only: what to buy, build, place and pack.

Each item has an id, a text and optionally a "by" date (ISO) or "before_due_days" (packed by that many days before the
due date). Items marked in_hand start done, they are already in the house. The parents add, tick and untick items by
message, and the lists live in the agent's own memory file from then on.

Sources: the nursery plan in the home twin (nursery.py), the car seat coach profiles (skills/carseat/), the Tesla notes
(docs/tesla.md) and the DIY white noise machine plan (gonzalomelov projects/diy-white-noise-machine.md, Oct 5 2026).
"""
from . import nursery

JOIE_MANUAL = "https://dl.joiebaby.com/Instruction_Manual/GL/i-Snug-2/Joie-carseat-i-snug-2-instruction-manual.pdf"

LISTS = {
    "nursery": {
        "title": "Nursery setup",
        "source": nursery.SOURCE,
        "items": [
            ("layout", "Pick the layout: A, desk on the inner wall, or B, desk at the window (nursery plan page)", "2026-11-08"),
            ("crib", "Crib, 130 x 70 cm, on the long wall opposite the desk wall", "2026-11-22"),
            ("dresser", "Dresser with the changing mat, 120 x 45 cm, starting 82 cm from the door wall so the door swings clear", "2026-11-22"),
            ("anchor", "Anchor the dresser and the wall shelf to the wall", "2026-11-22"),
            ("walkway", "Keep 70 cm of clear floor between the dresser and the crib", None),
            ("shelf", "Wall shelf 152 cm up, never on the wall above the crib (layout B puts it over the crib's end)", "2026-11-22"),
            ("rocker", "Alba rocker in the corner by the door wall", "2026-11-29"),
            ("rug", "Star rug, 145 x 92 cm, between the dresser and the crib", "2026-11-29"),
            ("bins", "Nappy bin, laundry basket and toy basket in their spots from the plan", "2026-11-29"),
            ("night_light", "Night feed light: the study light (light.wiz_824512_192_0_2_10) warm and low, test it once", "2026-11-29"),
            ("heater", "Decide where the plug-in heater on the Shelly plug goes, away from the crib", "2026-11-29"),
            ("noise_spot", "White noise machine in the far corner from the crib (the room allows 187 cm at most, see the noise list)", "2026-12-01"),
        ],
    },
    "hospital_bag": {
        "title": "Hospital bag",
        "source": "logistics only, ask the hospital what they provide",
        "items": [
            ("ask_hospital", "Ask the hospital what they give and what to bring, and where to park", None, 35),
            ("ids", "Both cédulas and the mutualista card", None, 28),
            ("papers", "Admission papers and any forms the hospital asked for", None, 28),
            ("chargers", "Phone chargers and a long cable", None, 28),
            ("ceci_clothes", "Clothes for Ceci for 2 or 3 days, slippers and toiletries", None, 28),
            ("gonza_clothes", "A change of clothes for Gonza", None, 28),
            ("theo_outfit", "Going home outfit for Theo in newborn and 0 to 3 month sizes, a hat and a blanket", None, 28),
            ("diapers", "Newborn diapers and wipes, if the hospital asks you to bring them", None, 28),
            ("snacks", "Snacks and water bottles", None, 28),
            ("payment", "A card and some cash for parking", None, 28),
            ("car_seat_in", "Car seat installed in the car before the bag goes in (car seat list)", None, 21),
        ],
    },
    "car_seat": {
        "title": "Car seat, Joie Litetrax with the belt install",
        "source": "car seat coach profiles skills/carseat/joie-i-snug-2.json and tesla-model-3.json, docs/tesla.md",
        "items": [
            ("model", "Check the Litetrax box carries the i-Snug 2 carrier (EU and NZ) and not the Gemm (US): the coach's profile is the i-Snug 2", "2026-11-04"),
            ("buy", "Buy the Litetrax travel system (Gonza buys, the agent never pays)", "2026-11-04"),
            ("manual", f"Read the 'Installation without base' part of the manual: {JOIE_MANUAL}", "2026-11-05"),
            ("seat_spot", "Pick the seat: rear center takes a belt installed seat only, ISOFIX is on the two outer rear seats", "2026-11-05"),
            ("no_front", "Never in the front passenger seat with the airbag on", None),
            ("first_install", "First install in the Model 3 (arrives Nov 5) with the car seat coach on the Mac: say 'car seat coach'", "2026-11-08"),
            ("hand_checks", "Movement at the belt path under 2.5 cm and the harness pinch test, the coach asks both", "2026-11-08"),
            ("technician", "Book a check by a certified child passenger safety technician", "2026-11-22"),
            ("practice", "Practice taking the carrier in and out of the car a few times", "2026-11-29"),
            ("register", "Register the seat with Joie for recall notices", "2026-11-15"),
        ],
    },
    "white_noise": {
        "title": "White noise machine, DIY",
        "source": "gonzalomelov projects/diy-white-noise-machine.md and parenting_agent/white_noise.py",
        "items": [
            ("esp32", "ESP32-S3 N16R8, board B", None, None, True),
            ("usb_power", "USB-C power supply", None, None, True),
            ("amp", "Buy a MAX98357A I2S amplifier", "2026-11-08"),
            ("speaker", "Buy a 3 W 4 ohm speaker, 40 to 50 mm", "2026-11-08"),
            ("breadboard", "Breadboard: the amplifier on board B over I2S, white, pink and brown noise", "2026-11-15"),
            ("by_ear", "Pick the sound by ear with Ceci", "2026-11-15"),
            ("esphome", "ESPHome: on and off, noise type, volume with a hard cap, sleep timer, night light", "2026-11-22"),
            ("measure", "Measure at the crib with a phone dB meter and set the cap at 50 dB there, then give the agent the numbers", "2026-11-22"),
            ("enclosure", "Print the enclosure", "2026-11-29"),
            ("automation", "Home Assistant: on at bedtime, timer down once he sleeps (the agent's white noise plan, dry until house.live)", "2026-12-01"),
        ],
    },
}
ORDER = ("car_seat", "nursery", "white_noise", "hospital_bag")

# The same items in Uruguayan Spanish, for a Spanish morning nudge. An item a parent added or reworded keeps its own words.
ES = {
    "nursery": {
        "layout": "Elegir la distribución: A, el escritorio en la pared de adentro, o B, el escritorio en la ventana",
        "crib": "La cuna, 130 x 70 cm, en la pared larga frente a la del escritorio",
        "dresser": "La cómoda con el cambiador, 120 x 45 cm, a 82 cm de la pared de la puerta para que la puerta abra",
        "anchor": "Fijar la cómoda y el estante a la pared",
        "walkway": "Dejar 70 cm libres entre la cómoda y la cuna",
        "shelf": "El estante a 152 cm, nunca en la pared arriba de la cuna",
        "rocker": "La mecedora Alba en la esquina de la pared de la puerta",
        "rug": "La alfombra de estrellas, 145 x 92 cm, entre la cómoda y la cuna",
        "bins": "El tacho de pañales, el canasto de ropa y el de juguetes en su lugar",
        "night_light": "La luz para las tomas de noche: la del estudio, cálida y baja, probarla una vez",
        "heater": "Decidir dónde va la estufa del enchufe Shelly, lejos de la cuna",
        "noise_spot": "La máquina de ruido blanco en la esquina más lejos de la cuna",
    },
    "hospital_bag": {
        "ask_hospital": "Preguntar en el sanatorio qué dan, qué llevar y dónde estacionar",
        "ids": "Las cédulas de los dos y el carné de la mutualista",
        "papers": "Los papeles de ingreso y lo que haya pedido el sanatorio",
        "chargers": "Cargadores del celular y un cable largo",
        "ceci_clothes": "Ropa para Ceci para 2 o 3 días, pantuflas y cosas de baño",
        "gonza_clothes": "Una muda de ropa para Gonza",
        "theo_outfit": "La ropa de salida de Theo en talle recién nacido y de 0 a 3 meses, un gorro y una manta",
        "diapers": "Pañales de recién nacido y toallitas, si el sanatorio pide llevarlos",
        "snacks": "Algo para picar y botellas de agua",
        "payment": "Una tarjeta y algo de efectivo para el estacionamiento",
        "car_seat_in": "La silla del auto instalada antes de cargar el bolso (lista de la silla)",
    },
    "car_seat": {
        "model": "Revisar que la caja de la Litetrax traiga el huevito i-Snug 2 (Europa y Nueva Zelanda) y no el Gemm (EE.UU.)",
        "buy": "Comprar el sistema de viaje Litetrax (lo compra Gonza, el agente nunca paga)",
        "manual": "Leer la parte 'instalación sin base' del manual",
        "seat_spot": "Elegir el asiento: el del medio atrás solo con cinturón, ISOFIX está en los dos de los costados",
        "no_front": "Nunca adelante con el airbag prendido",
        "first_install": "Primera instalación en el Model 3 con el coach de la silla en la Mac: decí 'car seat coach'",
        "hand_checks": "Que se mueva menos de 2,5 cm en el paso del cinturón y la prueba del pellizco del arnés",
        "technician": "Reservar una revisión con un técnico certificado en sillas de auto",
        "practice": "Practicar sacar y poner el huevito del auto unas cuantas veces",
        "register": "Registrar la silla con Joie para los avisos de retiro",
    },
    "white_noise": {
        "esp32": "ESP32-S3 N16R8, placa B",
        "usb_power": "Fuente USB-C",
        "amp": "Comprar un amplificador I2S MAX98357A",
        "speaker": "Comprar un parlante de 3 W y 4 ohm, de 40 a 50 mm",
        "breadboard": "Protoboard: el amplificador en la placa B por I2S, ruido blanco, rosa y marrón",
        "by_ear": "Elegir el sonido de oído con Ceci",
        "esphome": "ESPHome: prender y apagar, tipo de ruido, volumen con tope, temporizador, luz de noche",
        "measure": "Medir en la cuna con un medidor de dB en el celular, tope de 50 dB ahí, y pasarle los números al agente",
        "enclosure": "Imprimir la caja",
        "automation": "Home Assistant: prender a la hora de dormir, bajar el temporizador cuando se duerme",
    },
}


def text_in(lang, item):
    """An item's words in the nudge's language: the Spanish ones only for an item still worded as in the plan."""
    if lang == "es":
        seeded = {row[0]: row[1] for row in LISTS.get(item["list"], {}).get("items", [])}
        if seeded.get(item.get("id") or item.get("item_id")) == item["text"]:
            return ES.get(item["list"], {}).get(item.get("id") or item.get("item_id"), item["text"])
    return item["text"]


def seed_items():
    """Every starting item as a dict, in list order."""
    out = []
    for name in ORDER:
        for position, row in enumerate(LISTS[name]["items"]):
            item_id, text, by = row[0], row[1], row[2]
            before_due = row[3] if len(row) > 3 else None
            in_hand = bool(row[4]) if len(row) > 4 else False
            out.append({"list": name, "item_id": item_id, "text": text, "by": by, "before_due_days": before_due,
                        "in_hand": in_hand, "position": position})
    return out
