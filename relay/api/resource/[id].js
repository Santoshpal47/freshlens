// FreshLens relay: forwards a data.gov.in resource request from Vercel's Mumbai region (bom1).
// api.data.gov.in only answers Indian IP addresses; GitHub's runners are abroad, so the nightly
// workflow fetches through this function. Only data.gov.in resources can be reached, and only with
// the shared RELAY_KEY, so this is not an open proxy.
export default async function handler(req, res) {
  if (!process.env.RELAY_KEY || req.headers["x-relay-key"] !== process.env.RELAY_KEY) {
    return res.status(401).json({ error: "unauthorized" });
  }
  const { id } = req.query;
  if (!/^[0-9a-f-]{36}$/.test(String(id))) {
    return res.status(400).json({ error: "bad resource id" });
  }
  const incoming = new URL(req.url, "http://relay.local");
  const upstream = new URL(`https://api.data.gov.in/resource/${id}`);
  for (const [k, v] of incoming.searchParams) if (k !== "id") upstream.searchParams.append(k, v);
  try {
    const r = await fetch(upstream, {
      headers: { "User-Agent": "freshlens-relay/0.1 (+https://github.com/Santoshpal47/freshlens)" },
      signal: AbortSignal.timeout(25000),
    });
    res.status(r.status);
    res.setHeader("content-type", r.headers.get("content-type") || "application/json");
    res.setHeader("x-relay-region", process.env.VERCEL_REGION || "unknown");
    return res.send(await r.text());
  } catch (e) {
    return res.status(504).json({ error: `upstream ${e.name}`, region: process.env.VERCEL_REGION });
  }
}
