"use strict";
(() => {
  const WORDS = {
    en: {title: "The first-month book", lead: "Muse writes it from this home's own log and memory, so press it after some moments. A real family's book fills as the month goes.",
      make: "Make the book so far", making: "Muse is writing…", empty: "The log is empty so far.", full: "Try again in a moment.", muse: "Written by Muse from this log", code: "A plain line from code, Muse's page didn't match the log", both: "Written by Muse from this log, with a line from code for what it left out",
      art: "Illustration made ahead of time in Meta's Muse app, not from this session"},
    es: {title: "El libro del primer mes", lead: "Muse lo escribe con el registro y la memoria de este hogar, así que probalo después de algunos momentos. El libro de una familia real se va llenando con el mes.",
      make: "Hacer el libro hasta acá", making: "Muse está escribiendo…", empty: "El registro todavía está vacío.", full: "Probá de nuevo en un momento.", muse: "Escrito por Muse con este registro", code: "Una línea simple desde el código, la página de Muse no coincidía con el registro", both: "Escrito por Muse con este registro, con una línea del código para lo que dejó afuera",
      art: "Ilustración hecha antes en la app Muse de Meta, no en esta sesión"},
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
    day.textContent = item.day;
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
