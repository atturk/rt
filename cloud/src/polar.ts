/** Client minimo dell'API Polar: checkout e portale cliente. */
export interface Payments {
  createCheckout(args: { productId: string; userId: string; email: string; successUrl: string }): Promise<string>;
  customerPortal(userId: string): Promise<string>;
}

export function polarPayments(apiBase: string, token: string, fetchImpl: typeof fetch = fetch): Payments {
  async function post(path: string, body: unknown): Promise<any> {
    const resp = await fetchImpl(`${apiBase}${path}`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!resp.ok) throw new Error(`Polar POST ${path}: HTTP ${resp.status}`);
    return resp.json();
  }
  return {
    async createCheckout({ productId, userId, email, successUrl }) {
      const res = await post("/v1/checkouts/", {
        products: [productId],
        external_customer_id: userId,
        customer_email: email,
        success_url: successUrl,
      });
      return res.url;
    },
    async customerPortal(userId) {
      const res = await post("/v1/customer-sessions/", { external_customer_id: userId });
      return res.customer_portal_url;
    },
  };
}
