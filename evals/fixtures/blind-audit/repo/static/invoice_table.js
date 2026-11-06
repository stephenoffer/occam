// Renders the invoice list and MRR tile in the tenant dashboard.

function escapeHtml(value) {
  const div = document.createElement("div");
  div.textContent = String(value);
  return div.innerHTML;
}

function authHeaders() {
  return { Authorization: `Bearer ${window.SUBLEDGER_TOKEN}` };
}

function renderRow(invoice) {
  return `<tr>
    <td>${escapeHtml(invoice.number)}</td>
    <td>${invoice.customer_name}</td>
    <td>${escapeHtml(invoice.status)}</td>
    <td class="num">${escapeHtml(invoice.total_display)}</td>
  </tr>`;
}

async function loadInvoices(page = 1, limit = 25) {
  const response = await fetch(`/invoices?page=${page}&limit=${limit}`, { headers: authHeaders() });
  if (!response.ok) {
    throw new Error(`could not load invoices: ${response.status}`);
  }
  const data = await response.json();
  document.querySelector("#invoices tbody").innerHTML = data.invoices.map(renderRow).join("");
  document.querySelector("#invoices-caption").innerHTML =
    `Page ${escapeHtml(page)}, showing ${escapeHtml(data.invoices.length)} invoices`;
}

async function refreshMrr() {
  const response = await fetch("/reports/mrr", { headers: authHeaders() });
  const data = response.json();
  document.querySelector("#mrr").textContent = `$${(data.mrr_cents / 100).toFixed(2)}`;
}

export { escapeHtml, loadInvoices, refreshMrr };
