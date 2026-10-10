"use strict";

// Весь вывод строится через textContent/DOM API: данные внешних сервисов не попадают в innerHTML.

const ERROR_TEXT = {
  upstream_timeout: "Источник не ответил вовремя.",
  upstream_unavailable: "Источник временно недоступен.",
  upstream_bad_response: "Источник вернул неожиданный ответ.",
  api_key_missing: "Не задан API-ключ REST Countries (см. README).",
  dependency_failed: "Недоступно: нужны данные о стране назначения.",
  currency_unsupported: "Курс для этой пары валют не поддерживается.",
  country_unknown: "Не удалось определить страну.",
  internal_error: "Внутренняя ошибка сервиса.",
};

const $ = (id) => document.getElementById(id);

const form = $("trip-form");
const submit = $("submit");
const message = $("message");
const result = $("result");

let map = null;
let mapLayer = null;

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (key === "class") node.className = value;
    else node.setAttribute(key, value);
  }
  for (const child of children) {
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

function setDefaultDates() {
  const day = 24 * 3600 * 1000;
  const iso = (d) => d.toISOString().slice(0, 10);
  const start = new Date(Date.now() + 3 * day);
  $("start").value = iso(start);
  $("end").value = iso(new Date(start.getTime() + 4 * day));
}

function showMessage(text) {
  message.textContent = text;
  message.hidden = !text;
}

function errorDetail(payload, status) {
  const detail = payload && payload.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length) {
    return detail.map((d) => d.msg).join("; ");
  }
  return `Ошибка ${status}`;
}

function renderBlock(selector, block, renderData) {
  const body = document.querySelector(`${selector} .body`);
  body.replaceChildren();
  if (block.status === "error") {
    body.append(el("p", { class: "block-error" }, ERROR_TEXT[block.error] || `Ошибка: ${block.error}`));
    return;
  }
  if (block.warning) body.append(el("p", { class: "block-warning" }, block.warning));
  body.append(renderData(block.data));
}

function renderCountry(data) {
  const currencies = data.currencies.map((c) => (c.symbol ? `${c.code} (${c.symbol})` : c.code));
  const rows = [
    ["Столица", data.capital || "—"],
    ["Языки", data.languages.join(", ") || "—"],
    ["Валюта", currencies.join(", ") || "—"],
    ["Часовой пояс", data.timezones.join(", ") || "—"],
  ];
  const list = el("dl");
  for (const [label, value] of rows) list.append(el("dt", {}, label), el("dd", {}, value));
  return el(
    "div",
    {},
    el("p", {}, el("span", { class: "flag" }, data.flag_emoji || ""), el("strong", {}, data.name)),
    list,
  );
}

function renderCurrency(data) {
  const rate = data.rate.toLocaleString("ru-RU", { maximumFractionDigits: 4 });
  return el(
    "div",
    {},
    el("p", { class: "big" }, `1 ${data.base} = ${rate} ${data.quote}`),
    el("p", { class: "muted" }, `Курс на ${data.date}`),
  );
}

function renderWeather(days) {
  if (!days.length) return el("p", { class: "muted" }, "Нет данных о погоде для выбранных дат.");
  const fmt = (v, unit) => (v === null || v === undefined ? "—" : `${Math.round(v * 10) / 10}${unit}`);
  const head = el(
    "tr",
    {},
    el("th", {}, "Дата"),
    el("th", { class: "num" }, "Мин."),
    el("th", { class: "num" }, "Макс."),
    el("th", { class: "num" }, "Осадки"),
  );
  const rows = days.map((d) =>
    el(
      "tr",
      {},
      el("td", {}, new Date(`${d.date}T00:00:00`).toLocaleDateString("ru-RU", { weekday: "short", day: "numeric", month: "short" })),
      el("td", { class: "num" }, fmt(d.t_min, " °C")),
      el("td", { class: "num" }, fmt(d.t_max, " °C")),
      el("td", { class: "num" }, fmt(d.precip_mm, " мм")),
    ),
  );
  return el("table", {}, el("thead", {}, head), el("tbody", {}, ...rows));
}

function renderMap(destination, placesBlock) {
  if (!map) {
    L.Icon.Default.imagePath = "/static/vendor/leaflet/images/";
    map = L.map("map");
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(map);
  }
  if (mapLayer) mapLayer.remove();
  mapLayer = L.featureGroup().addTo(map);

  const center = [destination.lat, destination.lon];
  L.marker(center).bindPopup(el("strong", {}, destination.name)).addTo(mapLayer);

  const note = $("places-note");
  note.textContent = "";
  if (placesBlock.status === "error") {
    note.textContent = "· места недоступны: " + (ERROR_TEXT[placesBlock.error] || placesBlock.error);
  } else if (!placesBlock.data.length) {
    note.textContent = "· интересных мест рядом не найдено";
  } else {
    note.textContent = `· мест рядом: ${placesBlock.data.length}`;
    for (const place of placesBlock.data) {
      const popup = el("div", {}, el("strong", {}, place.name), el("br"), el("span", { class: "muted" }, place.category));
      L.circleMarker([place.lat, place.lon], { radius: 7, weight: 2, fillOpacity: 0.7 })
        .bindPopup(popup)
        .addTo(mapLayer);
    }
  }

  // Карта скрыта до первого результата, поэтому размер пересчитываем после показа.
  map.invalidateSize();
  if (mapLayer.getLayers().length > 1) map.fitBounds(mapLayer.getBounds().pad(0.15));
  else map.setView(center, 12);
}

function render(trip) {
  renderBlock("#card-country", trip.country, renderCountry);
  renderBlock("#card-currency", trip.currency, renderCurrency);
  renderBlock("#card-weather", trip.weather, renderWeather);
  result.hidden = false;
  renderMap(trip.destination, trip.places);
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  showMessage("");
  if (!form.reportValidity()) return;

  const params = new URLSearchParams({
    destination: $("destination").value.trim(),
    start: $("start").value,
    end: $("end").value,
    home_currency: $("home_currency").value.trim().toUpperCase(),
  });

  submit.disabled = true;
  submit.textContent = "Загружаю…";
  try {
    const response = await fetch(`/api/v1/trip?${params}`);
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
      result.hidden = true;
      showMessage(errorDetail(payload, response.status));
      return;
    }
    render(payload);
  } catch {
    result.hidden = true;
    showMessage("Не удалось связаться с сервером. Проверьте соединение.");
  } finally {
    submit.disabled = false;
    submit.textContent = "Показать";
  }
});

setDefaultDates();
