// Case list (stored encrypted on this computer).
import { listCases, listLawyers } from "../store";
import { h } from "../ui";
import { startPanel } from "./help";

const STATUS: Record<string, [string, string]> = {
  ready: ["Gotowe", "status-ready"], analyzing: ["Analiza nieukończona", "status-awaiting_approval"], error: ["Błąd", "status-error"],
};

export async function renderCases(root: HTMLElement) {
  const [cases, lawyers, start] = await Promise.all([listCases(), listLawyers(), startPanel(() => void renderCases(root))]);
  const names = new Map(lawyers.map((l) => [l.id, l.fullName]));
  const body = cases.length
    ? h("table", { class: "grid" },
      h("thead", {}, h("tr", {}, ...["Sygnatura", "Sprawa", "Prawnik", "Utworzona", "Pismo", "Status"].map((t) => h("th", {}, t)))),
      h("tbody", {}, ...cases.map((c) => {
        const [label, cls] = STATUS[c.status] ?? [c.status, ""];
        return h("tr", {},
          h("td", {}, c.caseNumber || "—"),
          h("td", {}, h("a", { href: `#/case/${c.id}` }, c.title)),
          h("td", {}, names.get(c.lawyerId) ?? "—"),
          h("td", {}, new Date(c.createdAt).toLocaleString("pl-PL", { dateStyle: "short", timeStyle: "short" })),
          h("td", {}, c.letter ? c.letter.templateName : "—"),
          h("td", {}, h("span", { class: `badge ${cls}` }, label)));
      })))
    : h("p", {}, "Brak spraw. Kliknij „Nowa sprawa”, aby przeanalizować dokumenty.");
  root.replaceChildren(
    start ?? "",
    h("div", { class: "row-between" }, h("h1", {}, "Sprawy"), h("a", { class: "button", href: "#/new" }, "Nowa sprawa")),
    h("p", { class: "muted small" }, "Sprawy są zapisane zaszyfrowane tylko na tym komputerze. Rób regularnie kopię zapasową (menu „Kopia zapasowa”)."),
    body);
}
