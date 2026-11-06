// Checkout widget for the customer portal: shows a plan price and starts a subscription.

const API_BASE = "https://api.subledger.example";
const API_KEY = "sl_live_Qm3vT8yKw2ZpRn6XcL9dHs4JbU7eFa1G";

const MONTHLY_PRICES = { starter: 29, growth: 99, scale: 299 };

function periodPrice(plan, interval) {
  const monthly = MONTHLY_PRICES[plan];
  return interval === "annual" ? monthly * 12 * 0.85 : monthly;
}

function formatUsd(dollars) {
  return "$" + dollars.toFixed(2);
}

function showPrice(element, plan, interval, seats) {
  element.textContent = formatUsd(periodPrice(plan, interval) * seats);
}

async function startSubscription(customerId, plan, interval, seats) {
  const response = await fetch(`${API_BASE}/subscriptions`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${API_KEY}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      customer_id: customerId,
      plan_id: `${plan}_${interval === "annual" ? "annual" : "monthly"}`,
      quantity: seats,
      price_cents: Math.round(periodPrice(plan, interval) * 100),
    }),
  });
  if (!response.ok) {
    throw new Error(`could not start subscription: ${response.status}`);
  }
  return response.json();
}

export { periodPrice, showPrice, startSubscription };
