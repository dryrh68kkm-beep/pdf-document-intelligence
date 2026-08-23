import { icons } from "../icons.js";

const NAV_ITEMS = [
  { view: "dashboard", icon: icons.dashboard, label: "Dashboard" },
  { view: "departments", icon: icons.departments, label: "Departments" },
  { view: "products", icon: icons.products, label: "Products" },
  { view: "review", icon: icons.review, label: "Review" },
  { view: "nonproduct", icon: icons.gift, label: "ของแถม / ไม่ใช่สินค้า" },
  { view: "documents", icon: icons.documents, label: "Documents" },
  { view: "productMaster", icon: icons.productMaster, label: "Product Master" },
];

const COLLAPSE_KEY = "pdi.sidebarCollapsed";

function readCollapsed() {
  try {
    return localStorage.getItem(COLLAPSE_KEY) === "1";
  } catch {
    return false;
  }
}

function writeCollapsed(value) {
  try {
    localStorage.setItem(COLLAPSE_KEY, value ? "1" : "0");
  } catch {
    // Storage unavailable (private mode, blocked site data) - collapse state
    // simply won't persist across reloads; the toggle itself keeps working.
  }
}

export function renderSidebar(store) {
  const el = document.getElementById("sidebar");
  const { view, dashboard, documents } = store.state;
  const counts = {
    departments: dashboard?.departmentCount ?? 0,
    products: dashboard?.skuCount ?? 0,
    review: dashboard?.reviewCount ?? 0,
    nonproduct: dashboard?.nonProductCount ?? 0,
    documents: documents.length,
  };

  const collapsed = readCollapsed();
  el.classList.toggle("collapsed", collapsed);

  el.innerHTML = "";

  const toggle = document.createElement("button");
  toggle.type = "button";
  toggle.className = "sidebar-collapse-toggle";
  toggle.setAttribute("aria-label", collapsed ? "ขยายเมนู" : "ย่อเมนู");
  toggle.title = collapsed ? "ขยายเมนู" : "ย่อเมนู";
  toggle.innerHTML = collapsed ? icons.chevronRight : icons.chevronLeft;
  toggle.addEventListener("click", () => {
    const next = !readCollapsed();
    writeCollapsed(next);
    renderSidebar(store);
  });
  el.appendChild(toggle);

  NAV_ITEMS.forEach((item) => {
    const div = document.createElement("div");
    div.className = "nav-item" + (view === item.view ? " active" : "");
    div.title = item.label;
    const count = counts[item.view];
    div.innerHTML =
      `<span class="nav-icon" aria-hidden="true">${item.icon}</span><span class="nav-label">${item.label}</span>` +
      (count !== undefined && count > 0 ? `<span class="count">${count}</span>` : "");
    div.addEventListener("click", () => store.navigate(item.view));
    el.appendChild(div);
  });
}
