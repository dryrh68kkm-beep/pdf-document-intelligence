const NAV_ITEMS = [
  { view: "dashboard", icon: "📊", label: "Dashboard" },
  { view: "departments", icon: "🏷️", label: "Departments" },
  { view: "products", icon: "📦", label: "Products" },
  { view: "review", icon: "⚠️", label: "Review" },
  { view: "documents", icon: "📄", label: "Documents" },
];

export function renderSidebar(store) {
  const el = document.getElementById("sidebar");
  const { view, dashboard, documents } = store.state;
  const counts = {
    departments: dashboard?.departmentCount ?? 0,
    products: dashboard?.skuCount ?? 0,
    review: dashboard?.reviewCount ?? 0,
    documents: documents.length,
  };
  el.innerHTML = "";
  NAV_ITEMS.forEach((item) => {
    const div = document.createElement("div");
    div.className = "nav-item" + (view === item.view ? " active" : "");
    const count = counts[item.view];
    div.innerHTML =
      `<span aria-hidden="true">${item.icon}</span><span>${item.label}</span>` +
      (count !== undefined ? `<span class="count">${count}</span>` : "");
    div.addEventListener("click", () => store.navigate(item.view));
    el.appendChild(div);
  });
}
