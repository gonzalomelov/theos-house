"use strict";
(() => {
  const WORDS = {
    en: {title: "The first-month book", lead: "The home writes it from its own log and memory, so press it after some moments. A real family's book fills as the month goes.",
      make: "Make the book so far", making: "The home is writing…", empty: "The log is empty so far.", full: "Try again in a moment.", muse: "Written from this home's log", code: "A plain line, since the written page didn't match the log", both: "Written from this home's log, with a plain line for what it left out",
      art: "Illustration made ahead of time, not from this session", locale: "en-US"},
    es: {title: "El libro del primer mes", lead: "La casa lo escribe con su registro y su memoria, así que probalo después de algunos momentos. El libro de una familia real se va llenando con el mes.",
      make: "Hacer el libro hasta acá", making: "La casa está escribiendo…", empty: "El registro todavía está vacío.", full: "Probá de nuevo en un momento.", muse: "Escrito con el registro de esta casa", code: "Una línea simple, porque la página escrita no coincidía con el registro", both: "Escrito con el registro de esta casa, con una línea simple para lo que dejó afuera",
      art: "Ilustración hecha antes, no en esta sesión", locale: "es-UY"},
  };
  const ART = ["cover", "night", "recipe", "carseat"];
  const ART_OF = {alarm: "night", recipe: "recipe", coach: "carseat"};
  const $ = id => document.getElementById(id);
  const lang = () => (document.documentElement.lang === "es" ? "es" : "en");
  function words() {
    const t = WORDS[lang()];
    $("book-t").textContent = t.title;
    $("book-lead").textContent = t.lead;
    $("book-make").textContent = t.make;
    return t;
  }
  function page(item, i, t) {
    const fig = document.createElement("figure"), img = document.createElement("img"), cap = document.createElement("figcaption");
    const day = document.createElement("strong"), text = document.createElement("span"), by = document.createElement("small"), art = document.createElement("small");
    fig.className = "book-page";
    img.src = `/static/book/${ART_OF[item.art] || ART[i % ART.length]}.jpg`;
    img.alt = "";
    img.loading = "lazy";
    day.textContent = new Date(`${item.day}T12:00:00Z`).toLocaleDateString(t.locale, {weekday: "long", month: "long", day: "numeric", timeZone: "UTC"});
    text.textContent = item.text;
    by.textContent = t[item.by] || t.code;
    art.textContent = t.art;
    cap.append(day, text, by, art);
    fig.append(img, cap);
    return fig;
  }
  async function make() {
    const t = words(), button = $("book-make"), status = $("book-status");
    button.disabled = true;
    status.textContent = t.making;
    try {
      const reply = await fetch("/api/book", {method: "POST", headers: {"Content-Type": "application/json"}, body: "{}"});
      const book = await reply.json();
      if (!reply.ok) {
        status.textContent = book.error || t.full;
        return;
      }
      const pages = $("book-pages");
      pages.replaceChildren(...book.pages.map((item, i) => page(item, i, t)));
      status.textContent = book.pages.length ? `${book.title}. ${book.totals || ""}` : t.empty;
    } catch {
      status.textContent = t.full;
    } finally {
      button.disabled = false;
    }
  }
  $("book-make").addEventListener("click", make);
  words();
  new MutationObserver(words).observe(document.documentElement, {attributes: true, attributeFilter: ["lang"]});
})();
