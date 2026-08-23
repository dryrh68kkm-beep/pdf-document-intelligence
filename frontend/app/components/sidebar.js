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

// The logo mark, "SYSTEM STATUS: Operational" line, and "AD / Admin" user
// row below are all purely decorative per explicit product decision - there
// is no health-check API wired up here and no auth system in this app, so
// none of it calls any backend endpoint.
function logoMarkSvg() {
  return `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z"/><path d="M14 2v6h6"/><circle cx="12" cy="15" r="2.4"/></svg>`;
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

  el.innerHTML = `
    <div class="sidebar-logo">
      <span class="sidebar-logo-mark" aria-hidden="true">${logoMarkSvg()}</span>
      <span class="sidebar-logo-text">PDF Document<br/>Intelligence</span>
    </div>
  `;

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

  const nav = document.createElement("div");
  nav.className = "sidebar-nav";
  NAV_ITEMS.forEach((item) => {
    const div = document.createElement("div");
    div.className = "nav-item" + (view === item.view ? " active" : "");
    div.title = item.label;
    const count = counts[item.view];
    div.innerHTML =
      `<span class="nav-icon" aria-hidden="true">${item.icon}</span><span class="nav-label">${item.label}</span>` +
      (count !== undefined && count > 0 ? `<span class="count">${count}</span>` : "");
    div.addEventListener("click", () => store.navigate(item.view));
    nav.appendChild(div);
  });
  el.appendChild(nav);

  // Reuses the app shell's existing upload flow (#fileInput, wired up in
  // main.js) - this is the same "+ Add Files" action as the bottom bar
  // button, not a second upload feature.
  const cta = document.createElement("button");
  cta.type = "button";
  cta.className = "sidebar-cta";
  cta.innerHTML = `<span aria-hidden="true">${icons.upload}</span><span class="label">+ Add Files</span>`;
  cta.addEventListener("click", () => document.getElementById("fileInput")?.click());
  el.appendChild(cta);

  const footer = document.createElement("div");
  footer.className = "sidebar-footer";
  footer.innerHTML = `
    <div class="sidebar-status">
      <div class="sidebar-status-label">System Status</div>
      <div class="sidebar-status-row"><span class="sidebar-status-dot"></span>Operational</div>
      <div class="sidebar-status-sub">All systems running normally</div>
    </div>
    <div class="sidebar-user">
      <span class="sidebar-user-avatar">AD</span>
      <div>
        <div class="sidebar-user-name">Admin</div>
        <div class="sidebar-user-role">Administrator</div>
      </div>
      <span class="sidebar-user-chevron" aria-hidden="true">${icons.chevronDown}</span>
    </div>
  `;
  el.appendChild(footer);
}
